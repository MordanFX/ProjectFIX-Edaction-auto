"""Create course submissions from confirmed Discord thread messages."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    DiscordHomeworkSpace,
    DiscordParticipant,
    Enrollment,
    Lesson,
    Student,
    Submission,
    SubmissionAttachment,
)
from course_platform.models.enums import (
    AttachmentKind,
    CourseAudience,
    EnrollmentStatus,
    SubmissionKind,
    SubmissionSource,
    SubmissionStatus,
)
from course_platform.services.progression import ProgressionService
from course_platform.services.submissions import (
    AssignmentAcceptedError,
    EmptySubmissionError,
    NoActiveAssignmentError,
    SubmissionPendingError,
    SubmissionReceipt,
    UnsupportedSubmissionKindError,
)


class DiscordSubmissionAccessError(PermissionError):
    """The member or channel does not belong to an active linked student."""


class DiscordMessageAlreadySubmittedError(RuntimeError):
    """The same Discord message was already confirmed as homework."""


@dataclass(frozen=True, slots=True)
class DiscordCurrentAssignment:
    course_title: str
    lesson_position: int
    lesson_title: str
    instructions: str


@dataclass(frozen=True, slots=True)
class DiscordIncomingAttachment:
    attachment_id: int
    url: str
    file_name: str
    mime_type: str | None = None
    file_size: int | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: int | None = None

    @property
    def kind(self) -> AttachmentKind:
        if self.mime_type and self.mime_type.startswith("image/"):
            return AttachmentKind.PHOTO
        if self.mime_type and self.mime_type.startswith("video/"):
            return AttachmentKind.VIDEO
        return AttachmentKind.DOCUMENT


class DiscordSubmissionService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def can_offer(
        self, *, guild_id: int, discord_user_id: int, channel_id: int
    ) -> bool:
        async with self._session_factory() as session:
            student_id = await session.scalar(
                select(DiscordParticipant.student_id)
                .join(
                    DiscordHomeworkSpace,
                    (DiscordHomeworkSpace.guild_id == DiscordParticipant.guild_id)
                    & (
                        DiscordHomeworkSpace.discord_user_id
                        == DiscordParticipant.discord_user_id
                    ),
                )
                .join(Student, Student.id == DiscordParticipant.student_id)
                .join(Enrollment, Enrollment.student_id == Student.id)
                .join(Cohort, Cohort.id == Enrollment.cohort_id)
                .join(Course, Course.id == Cohort.course_id)
                .where(
                    DiscordParticipant.guild_id == guild_id,
                    DiscordParticipant.discord_user_id == discord_user_id,
                    DiscordHomeworkSpace.channel_id == channel_id,
                    Student.is_active.is_(True),
                    Enrollment.status == EnrollmentStatus.ACTIVE,
                    Cohort.is_active.is_(True),
                    Course.is_active.is_(True),
                    Course.audience == CourseAudience.DISCORD,
                )
                .limit(1)
            )
            return student_id is not None

    async def current_assignment(
        self, *, guild_id: int, discord_user_id: int
    ) -> DiscordCurrentAssignment | None:
        """Return the published assignment currently available to a Discord member."""
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        Course.title.label("course_title"),
                        Lesson.position,
                        Lesson.title.label("lesson_title"),
                        Assignment.instructions,
                    )
                    .select_from(DiscordParticipant)
                    .join(Student, Student.id == DiscordParticipant.student_id)
                    .join(Enrollment, Enrollment.student_id == Student.id)
                    .join(Cohort, Cohort.id == Enrollment.cohort_id)
                    .join(Course, Course.id == Cohort.course_id)
                    .join(
                        Lesson,
                        (Lesson.course_id == Course.id)
                        & (Lesson.position == Enrollment.current_lesson_position),
                    )
                    .join(Assignment, Assignment.lesson_id == Lesson.id)
                    .where(
                        DiscordParticipant.guild_id == guild_id,
                        DiscordParticipant.discord_user_id == discord_user_id,
                        Student.is_active.is_(True),
                        Enrollment.status == EnrollmentStatus.ACTIVE,
                        Cohort.is_active.is_(True),
                        Course.is_active.is_(True),
                        Course.audience == CourseAudience.DISCORD,
                        Lesson.is_published.is_(True),
                    )
                    .order_by(Enrollment.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()
        if row is None:
            return None
        return DiscordCurrentAssignment(
            course_title=row.course_title,
            lesson_position=row.position,
            lesson_title=row.lesson_title,
            instructions=row.instructions,
        )

    async def submit_message(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        channel_id: int,
        message_id: int,
        text: str,
        attachments: tuple[DiscordIncomingAttachment, ...],
    ) -> SubmissionReceipt:
        normalized_text = text.strip() or None
        if normalized_text is None and not attachments:
            raise EmptySubmissionError

        async with session_scope(self._session_factory) as session:
            row = await self._submission_context(
                session,
                guild_id=guild_id,
                discord_user_id=discord_user_id,
                channel_id=channel_id,
            )
            latest_status = await session.scalar(
                select(Submission.status)
                .where(
                    Submission.enrollment_id == row.enrollment_id,
                    Submission.assignment_id == row.assignment_id,
                )
                .order_by(Submission.attempt_number.desc())
                .limit(1)
            )
            if latest_status is SubmissionStatus.ACCEPTED:
                raise AssignmentAcceptedError
            if latest_status in {SubmissionStatus.SUBMITTED, SubmissionStatus.IN_REVIEW}:
                raise SubmissionPendingError
            self._validate_kind(row.submission_kind, normalized_text, attachments)
            previous_attempt = await session.scalar(
                select(func.max(Submission.attempt_number)).where(
                    Submission.enrollment_id == row.enrollment_id,
                    Submission.assignment_id == row.assignment_id,
                )
            )
            attempt_number = (previous_attempt or 0) + 1
            submission = Submission(
                enrollment_id=row.enrollment_id,
                assignment_id=row.assignment_id,
                attempt_number=attempt_number,
                text_body=normalized_text,
                status=SubmissionStatus.SUBMITTED,
                source=SubmissionSource.DISCORD,
                source_guild_id=guild_id,
                source_channel_id=channel_id,
                source_message_id=message_id,
            )
            submission.attachments.extend(
                SubmissionAttachment(
                    kind=attachment.kind,
                    discord_attachment_id=attachment.attachment_id,
                    external_url=attachment.url,
                    file_name=attachment.file_name,
                    mime_type=attachment.mime_type,
                    file_size=attachment.file_size,
                    width=attachment.width,
                    height=attachment.height,
                    duration_seconds=attachment.duration_seconds,
                )
                for attachment in attachments
            )
            session.add(submission)
            try:
                await session.flush()
            except IntegrityError:
                raise DiscordMessageAlreadySubmittedError from None
            await ProgressionService.record_submission(
                session,
                enrollment_id=row.enrollment_id,
                lesson_id=row.lesson_id,
            )
            return SubmissionReceipt(
                lesson_position=row.position,
                lesson_title=row.title,
                attempt_number=attempt_number,
            )

    @staticmethod
    async def _submission_context(
        session: AsyncSession,
        *,
        guild_id: int,
        discord_user_id: int,
        channel_id: int,
    ):
        row = (
            await session.execute(
                select(
                    Enrollment.id.label("enrollment_id"),
                    Lesson.id.label("lesson_id"),
                    Lesson.position,
                    Lesson.title,
                    Lesson.requires_view_confirmation,
                    Assignment.id.label("assignment_id"),
                    Assignment.submission_kind,
                )
                .select_from(DiscordParticipant)
                .join(Student, Student.id == DiscordParticipant.student_id)
                .join(Enrollment, Enrollment.student_id == Student.id)
                .join(Cohort, Cohort.id == Enrollment.cohort_id)
                .join(Course, Course.id == Cohort.course_id)
                .join(
                    Lesson,
                    (Lesson.course_id == Course.id)
                    & (Lesson.position == Enrollment.current_lesson_position),
                )
                .join(Assignment, Assignment.lesson_id == Lesson.id)
                .join(
                    DiscordHomeworkSpace,
                    (DiscordHomeworkSpace.guild_id == DiscordParticipant.guild_id)
                    & (
                        DiscordHomeworkSpace.discord_user_id
                        == DiscordParticipant.discord_user_id
                    ),
                )
                .where(
                    DiscordParticipant.guild_id == guild_id,
                    DiscordParticipant.discord_user_id == discord_user_id,
                    DiscordHomeworkSpace.channel_id == channel_id,
                    Student.is_active.is_(True),
                    Enrollment.status == EnrollmentStatus.ACTIVE,
                    Cohort.is_active.is_(True),
                    Course.is_active.is_(True),
                    Course.audience == CourseAudience.DISCORD,
                    Lesson.is_published.is_(True),
                )
                .order_by(Enrollment.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            raise NoActiveAssignmentError
        return row

    @staticmethod
    def _validate_kind(
        submission_kind: SubmissionKind,
        text: str | None,
        attachments: tuple[DiscordIncomingAttachment, ...],
    ) -> None:
        if submission_kind is SubmissionKind.ANY:
            return
        if text is not None and not attachments and submission_kind is SubmissionKind.TEXT:
            return
        allowed = {
            SubmissionKind.FILE: {AttachmentKind.DOCUMENT},
            SubmissionKind.PHOTO: {AttachmentKind.PHOTO},
            SubmissionKind.VIDEO: {AttachmentKind.VIDEO},
        }
        if attachments and all(
            attachment.kind in allowed.get(submission_kind, set())
            for attachment in attachments
        ):
            return
        raise UnsupportedSubmissionKindError
