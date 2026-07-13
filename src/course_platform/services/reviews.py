"""Homework review use cases shared by Telegram and the future web API."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Course,
    Enrollment,
    Feedback,
    Lesson,
    StaffBotState,
    StaffUser,
    Student,
    Submission,
    SubmissionAttachment,
)
from course_platform.models.enums import (
    AttachmentKind,
    FeedbackVerdict,
    SubmissionSource,
    SubmissionStatus,
)
from course_platform.services.progression import ProgressionService


class ReviewWorkflowError(RuntimeError):
    """Base class for expected review workflow outcomes."""


class UnauthorizedReviewerError(ReviewWorkflowError):
    pass


class SubmissionNotFoundError(ReviewWorkflowError):
    pass


class AttachmentNotFoundError(ReviewWorkflowError):
    pass


class SubmissionAlreadyReviewedError(ReviewWorkflowError):
    pass


class EmptyFeedbackError(ReviewWorkflowError):
    pass


class NoPendingFeedbackError(ReviewWorkflowError):
    pass


@dataclass(frozen=True, slots=True)
class ReviewQueueItem:
    submission_id: UUID
    student_id: UUID
    student_name: str
    student_username: str | None
    course_title: str
    lesson_position: int
    lesson_title: str
    attempt_number: int
    submitted_at: datetime
    text_body: str | None
    attachment_count: int
    attachment_kind: AttachmentKind | None
    attachment_file_name: str | None
    attachment_mime_type: str | None
    status: SubmissionStatus
    source: SubmissionSource
    source_guild_id: int | None
    source_channel_id: int | None
    source_message_id: int | None


@dataclass(frozen=True, slots=True)
class ReviewAttachment:
    id: UUID
    kind: AttachmentKind
    file_name: str | None
    mime_type: str | None
    file_size: int | None
    duration_seconds: int | None
    width: int | None
    height: int | None
    source_available: bool


def _review_attachment(attachment: SubmissionAttachment) -> ReviewAttachment:
    return ReviewAttachment(
        id=attachment.id,
        kind=attachment.kind,
        file_name=attachment.file_name,
        mime_type=attachment.mime_type,
        file_size=attachment.file_size,
        duration_seconds=attachment.duration_seconds,
        width=attachment.width,
        height=attachment.height,
        source_available=(
            (
                attachment.source_chat_id is not None
                and attachment.source_message_id is not None
            )
            or attachment.external_url is not None
        ),
    )


@dataclass(frozen=True, slots=True)
class AttachmentMediaSource:
    id: UUID
    submission_id: UUID
    kind: AttachmentKind
    telegram_file_id: str | None
    external_url: str | None
    file_name: str | None
    mime_type: str | None
    file_size: int | None


@dataclass(frozen=True, slots=True)
class TelegramAttachmentCopy:
    source_chat_id: int
    source_message_id: int
    kind: AttachmentKind


@dataclass(frozen=True, slots=True)
class PendingReviewFeedback:
    submission_id: UUID
    reviewer_id: UUID
    verdict: FeedbackVerdict
    source_chat_id: int
    source_message_id: int


@dataclass(frozen=True, slots=True)
class TelegramReviewCompletion:
    result: "ReviewResult"
    source_chat_id: int
    source_message_id: int


@dataclass(frozen=True, slots=True)
class ReviewDetail(ReviewQueueItem):
    reviewed_at: datetime | None
    feedback_verdict: FeedbackVerdict | None
    feedback_message: str | None
    reviewer_name: str | None
    attachments: tuple[ReviewAttachment, ...]
    previous_attempts: tuple["ReviewAttempt", ...]


@dataclass(frozen=True, slots=True)
class ReviewAttempt:
    submission_id: UUID
    attempt_number: int
    submitted_at: datetime
    text_body: str | None
    status: SubmissionStatus
    source: SubmissionSource
    reviewed_at: datetime | None
    feedback_verdict: FeedbackVerdict | None
    feedback_message: str | None
    reviewer_name: str | None
    attachments: tuple[ReviewAttachment, ...]


@dataclass(frozen=True, slots=True)
class ReviewResult:
    submission_id: UUID
    student_telegram_user_id: int | None
    verdict: FeedbackVerdict
    feedback_message: str
    current_lesson_position: int
    course_completed: bool


class ReviewService:
    """List pending work and apply curator decisions transactionally."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def is_reviewer(self, telegram_user_id: int) -> bool:
        async with self._session_factory() as session:
            reviewer_id = await session.scalar(
                select(StaffUser.id).where(
                    StaffUser.telegram_user_id == telegram_user_id,
                    StaffUser.is_active.is_(True),
                )
            )
            return reviewer_id is not None

    async def list_pending(
        self,
        *,
        limit: int = 50,
        include_reviewed: bool = False,
        source: SubmissionSource | None = None,
    ) -> list[ReviewQueueItem]:
        statuses = [SubmissionStatus.SUBMITTED, SubmissionStatus.IN_REVIEW]
        if include_reviewed:
            statuses.extend(
                [SubmissionStatus.ACCEPTED, SubmissionStatus.REVISION_REQUESTED]
            )
        attachment_count = (
            select(func.count(SubmissionAttachment.id))
            .where(SubmissionAttachment.submission_id == Submission.id)
            .correlate(Submission)
            .scalar_subquery()
        )
        attachment_kind = (
            select(SubmissionAttachment.kind)
            .where(SubmissionAttachment.submission_id == Submission.id)
            .order_by(SubmissionAttachment.created_at.asc())
            .limit(1)
            .correlate(Submission)
            .scalar_subquery()
        )
        attachment_file_name = (
            select(SubmissionAttachment.file_name)
            .where(SubmissionAttachment.submission_id == Submission.id)
            .order_by(SubmissionAttachment.created_at.asc())
            .limit(1)
            .correlate(Submission)
            .scalar_subquery()
        )
        attachment_mime_type = (
            select(SubmissionAttachment.mime_type)
            .where(SubmissionAttachment.submission_id == Submission.id)
            .order_by(SubmissionAttachment.created_at.asc())
            .limit(1)
            .correlate(Submission)
            .scalar_subquery()
        )

        async with self._session_factory() as session:
            query = (
                select(
                    Submission.id,
                    Student.id.label("student_id"),
                    Student.first_name,
                    Student.last_name,
                    Student.username,
                    Course.title.label("course_title"),
                    Lesson.position,
                    Lesson.title.label("lesson_title"),
                    Submission.attempt_number,
                    Submission.submitted_at,
                    Submission.text_body,
                    attachment_count.label("attachment_count"),
                    attachment_kind.label("attachment_kind"),
                    attachment_file_name.label("attachment_file_name"),
                    attachment_mime_type.label("attachment_mime_type"),
                    Submission.status,
                    Submission.source,
                    Submission.source_guild_id,
                    Submission.source_channel_id,
                    Submission.source_message_id,
                )
                .join(Enrollment, Enrollment.id == Submission.enrollment_id)
                .join(Student, Student.id == Enrollment.student_id)
                .join(Assignment, Assignment.id == Submission.assignment_id)
                .join(Lesson, Lesson.id == Assignment.lesson_id)
                .join(Course, Course.id == Lesson.course_id)
                .where(Submission.status.in_(statuses))
                .order_by(
                    Submission.submitted_at.desc()
                    if include_reviewed
                    else Submission.submitted_at.asc()
                )
                .limit(limit)
            )
            if source is not None:
                query = query.where(Submission.source == source)
            rows = await session.execute(query)

            return [
                ReviewQueueItem(
                    submission_id=row.id,
                    student_id=row.student_id,
                    student_name=" ".join(part for part in [row.first_name, row.last_name] if part),
                    student_username=row.username,
                    course_title=row.course_title,
                    lesson_position=row.position,
                    lesson_title=row.lesson_title,
                    attempt_number=row.attempt_number,
                    submitted_at=row.submitted_at,
                    text_body=row.text_body,
                    attachment_count=row.attachment_count,
                    attachment_kind=row.attachment_kind,
                    attachment_file_name=row.attachment_file_name,
                    attachment_mime_type=row.attachment_mime_type,
                    status=row.status,
                    source=row.source,
                    source_guild_id=row.source_guild_id,
                    source_channel_id=row.source_channel_id,
                    source_message_id=row.source_message_id,
                )
                for row in rows
            ]

    async def list_attachment_copies(
        self,
        submission_id: UUID,
    ) -> tuple[TelegramAttachmentCopy, ...]:
        async with self._session_factory() as session:
            attachments = list(
                await session.scalars(
                    select(SubmissionAttachment)
                    .where(
                        SubmissionAttachment.submission_id == submission_id,
                        SubmissionAttachment.source_chat_id.is_not(None),
                        SubmissionAttachment.source_message_id.is_not(None),
                    )
                    .order_by(SubmissionAttachment.created_at)
                )
            )
            return tuple(
                TelegramAttachmentCopy(
                    source_chat_id=attachment.source_chat_id,
                    source_message_id=attachment.source_message_id,
                    kind=attachment.kind,
                )
                for attachment in attachments
                if attachment.source_chat_id is not None
                and attachment.source_message_id is not None
            )

    async def begin_telegram_feedback(
        self,
        *,
        submission_id: UUID,
        reviewer_telegram_user_id: int,
        verdict: FeedbackVerdict,
        source_chat_id: int,
        source_message_id: int,
    ) -> PendingReviewFeedback:
        async with session_scope(self._session_factory) as session:
            reviewer = await session.scalar(
                select(StaffUser).where(
                    StaffUser.telegram_user_id == reviewer_telegram_user_id,
                    StaffUser.is_active.is_(True),
                )
            )
            if reviewer is None:
                raise UnauthorizedReviewerError
            submission = await session.get(Submission, submission_id)
            if submission is None:
                raise SubmissionNotFoundError
            if submission.status not in {
                SubmissionStatus.SUBMITTED,
                SubmissionStatus.IN_REVIEW,
            }:
                raise SubmissionAlreadyReviewedError

            state = await session.get(StaffBotState, reviewer.id)
            if state is None:
                state = StaffBotState(staff_id=reviewer.id, submission_id=submission_id)
                session.add(state)
            state.submission_id = submission_id
            state.verdict = verdict
            state.source_chat_id = source_chat_id
            state.source_message_id = source_message_id

            return PendingReviewFeedback(
                submission_id=submission_id,
                reviewer_id=reviewer.id,
                verdict=verdict,
                source_chat_id=source_chat_id,
                source_message_id=source_message_id,
            )

    async def get_pending_telegram_feedback(
        self,
        reviewer_telegram_user_id: int,
    ) -> PendingReviewFeedback | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(StaffBotState, StaffUser)
                    .join(StaffUser, StaffUser.id == StaffBotState.staff_id)
                    .where(
                        StaffUser.telegram_user_id == reviewer_telegram_user_id,
                        StaffUser.is_active.is_(True),
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            state, reviewer = row
            return PendingReviewFeedback(
                submission_id=state.submission_id,
                reviewer_id=reviewer.id,
                verdict=state.verdict,
                source_chat_id=state.source_chat_id,
                source_message_id=state.source_message_id,
            )

    async def cancel_telegram_feedback(self, reviewer_telegram_user_id: int) -> bool:
        async with session_scope(self._session_factory) as session:
            state = await session.scalar(
                select(StaffBotState)
                .join(StaffUser, StaffUser.id == StaffBotState.staff_id)
                .where(StaffUser.telegram_user_id == reviewer_telegram_user_id)
            )
            if state is None:
                return False
            await session.delete(state)
            return True

    async def complete_telegram_feedback(
        self,
        *,
        reviewer_telegram_user_id: int,
        message: str,
    ) -> TelegramReviewCompletion:
        pending = await self.get_pending_telegram_feedback(reviewer_telegram_user_id)
        if pending is None:
            raise NoPendingFeedbackError
        result = await self.review_by_staff_id(
            submission_id=pending.submission_id,
            reviewer_id=pending.reviewer_id,
            verdict=pending.verdict,
            message=message,
        )
        async with session_scope(self._session_factory) as session:
            state = await session.get(StaffBotState, pending.reviewer_id)
            if state is not None:
                await session.delete(state)
        return TelegramReviewCompletion(
            result=result,
            source_chat_id=pending.source_chat_id,
            source_message_id=pending.source_message_id,
        )

    async def get_detail(self, submission_id: UUID) -> ReviewDetail:
        attachment_count = (
            select(func.count(SubmissionAttachment.id))
            .where(SubmissionAttachment.submission_id == Submission.id)
            .correlate(Submission)
            .scalar_subquery()
        )
        attachment_kind = (
            select(SubmissionAttachment.kind)
            .where(SubmissionAttachment.submission_id == Submission.id)
            .order_by(SubmissionAttachment.created_at.asc())
            .limit(1)
            .correlate(Submission)
            .scalar_subquery()
        )
        attachment_file_name = (
            select(SubmissionAttachment.file_name)
            .where(SubmissionAttachment.submission_id == Submission.id)
            .order_by(SubmissionAttachment.created_at.asc())
            .limit(1)
            .correlate(Submission)
            .scalar_subquery()
        )
        attachment_mime_type = (
            select(SubmissionAttachment.mime_type)
            .where(SubmissionAttachment.submission_id == Submission.id)
            .order_by(SubmissionAttachment.created_at.asc())
            .limit(1)
            .correlate(Submission)
            .scalar_subquery()
        )
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        Submission.id,
                        Submission.enrollment_id,
                        Submission.assignment_id,
                        Student.id.label("student_id"),
                        Student.first_name,
                        Student.last_name,
                        Student.username,
                        Course.title.label("course_title"),
                        Lesson.position,
                        Lesson.title.label("lesson_title"),
                        Submission.attempt_number,
                        Submission.submitted_at,
                        Submission.text_body,
                        attachment_count.label("attachment_count"),
                        attachment_kind.label("attachment_kind"),
                        attachment_file_name.label("attachment_file_name"),
                        attachment_mime_type.label("attachment_mime_type"),
                        Submission.status,
                        Submission.source,
                        Submission.source_guild_id,
                        Submission.source_channel_id,
                        Submission.source_message_id,
                        Submission.reviewed_at,
                        Feedback.verdict.label("feedback_verdict"),
                        Feedback.message.label("feedback_message"),
                        StaffUser.display_name.label("reviewer_name"),
                    )
                    .join(Enrollment, Enrollment.id == Submission.enrollment_id)
                    .join(Student, Student.id == Enrollment.student_id)
                    .join(Assignment, Assignment.id == Submission.assignment_id)
                    .join(Lesson, Lesson.id == Assignment.lesson_id)
                    .join(Course, Course.id == Lesson.course_id)
                    .outerjoin(Feedback, Feedback.submission_id == Submission.id)
                    .outerjoin(StaffUser, StaffUser.id == Feedback.reviewer_id)
                    .where(Submission.id == submission_id)
                )
            ).one_or_none()
            if row is None:
                raise SubmissionNotFoundError

            attachments = (
                await session.scalars(
                    select(SubmissionAttachment)
                    .where(SubmissionAttachment.submission_id == submission_id)
                    .order_by(SubmissionAttachment.created_at.asc())
                )
            ).all()

            previous_rows = (
                await session.execute(
                    select(
                        Submission.id,
                        Submission.attempt_number,
                        Submission.submitted_at,
                        Submission.text_body,
                        Submission.status,
                        Submission.source,
                        Submission.reviewed_at,
                        Feedback.verdict.label("feedback_verdict"),
                        Feedback.message.label("feedback_message"),
                        StaffUser.display_name.label("reviewer_name"),
                    )
                    .outerjoin(Feedback, Feedback.submission_id == Submission.id)
                    .outerjoin(StaffUser, StaffUser.id == Feedback.reviewer_id)
                    .where(
                        Submission.enrollment_id == row.enrollment_id,
                        Submission.assignment_id == row.assignment_id,
                        Submission.attempt_number < row.attempt_number,
                    )
                    .order_by(Submission.attempt_number.desc())
                )
            ).all()
            previous_ids = [previous.id for previous in previous_rows]
            previous_attachment_rows = []
            if previous_ids:
                previous_attachment_rows = list(
                    (
                        await session.scalars(
                            select(SubmissionAttachment)
                            .where(SubmissionAttachment.submission_id.in_(previous_ids))
                            .order_by(SubmissionAttachment.created_at.asc())
                        )
                    ).all()
                )
            attachments_by_submission: dict[UUID, list[ReviewAttachment]] = {
                submission_id: [] for submission_id in previous_ids
            }
            for attachment in previous_attachment_rows:
                attachments_by_submission[attachment.submission_id].append(
                    _review_attachment(attachment)
                )

            return ReviewDetail(
                submission_id=row.id,
                student_id=row.student_id,
                student_name=" ".join(
                    part for part in [row.first_name, row.last_name] if part
                ),
                student_username=row.username,
                course_title=row.course_title,
                lesson_position=row.position,
                lesson_title=row.lesson_title,
                attempt_number=row.attempt_number,
                submitted_at=row.submitted_at,
                text_body=row.text_body,
                attachment_count=row.attachment_count,
                attachment_kind=row.attachment_kind,
                attachment_file_name=row.attachment_file_name,
                attachment_mime_type=row.attachment_mime_type,
                status=row.status,
                source=row.source,
                source_guild_id=row.source_guild_id,
                source_channel_id=row.source_channel_id,
                source_message_id=row.source_message_id,
                reviewed_at=row.reviewed_at,
                feedback_verdict=row.feedback_verdict,
                feedback_message=row.feedback_message,
                reviewer_name=row.reviewer_name,
                attachments=tuple(
                    _review_attachment(attachment)
                    for attachment in attachments
                ),
                previous_attempts=tuple(
                    ReviewAttempt(
                        submission_id=previous.id,
                        attempt_number=previous.attempt_number,
                        submitted_at=previous.submitted_at,
                        text_body=previous.text_body,
                        status=previous.status,
                        source=previous.source,
                        reviewed_at=previous.reviewed_at,
                        feedback_verdict=previous.feedback_verdict,
                        feedback_message=previous.feedback_message,
                        reviewer_name=previous.reviewer_name,
                        attachments=tuple(attachments_by_submission[previous.id]),
                    )
                    for previous in previous_rows
                ),
            )

    async def get_attachment_media_source(
        self,
        *,
        submission_id: UUID,
        attachment_id: UUID,
    ) -> AttachmentMediaSource:
        async with self._session_factory() as session:
            attachment = await session.scalar(
                select(SubmissionAttachment).where(
                    SubmissionAttachment.id == attachment_id,
                    SubmissionAttachment.submission_id == submission_id,
                )
            )
            if attachment is None:
                raise AttachmentNotFoundError

            return AttachmentMediaSource(
                id=attachment.id,
                submission_id=attachment.submission_id,
                kind=attachment.kind,
                telegram_file_id=attachment.telegram_file_id,
                external_url=attachment.external_url,
                file_name=attachment.file_name,
                mime_type=attachment.mime_type,
                file_size=attachment.file_size,
            )

    async def review(
        self,
        *,
        submission_id: UUID,
        reviewer_telegram_user_id: int,
        verdict: FeedbackVerdict,
        message: str,
    ) -> ReviewResult:
        async with self._session_factory() as session:
            reviewer_id = await session.scalar(
                select(StaffUser.id).where(
                    StaffUser.telegram_user_id == reviewer_telegram_user_id,
                    StaffUser.is_active.is_(True),
                )
            )
        if reviewer_id is None:
            raise UnauthorizedReviewerError

        return await self.review_by_staff_id(
            submission_id=submission_id,
            reviewer_id=reviewer_id,
            verdict=verdict,
            message=message,
        )

    async def review_by_staff_id(
        self,
        *,
        submission_id: UUID,
        reviewer_id: UUID,
        verdict: FeedbackVerdict,
        message: str,
    ) -> ReviewResult:
        normalized_message = message.strip()
        if not normalized_message:
            raise EmptyFeedbackError

        async with session_scope(self._session_factory) as session:
            reviewer = await session.scalar(
                select(StaffUser).where(
                    StaffUser.id == reviewer_id,
                    StaffUser.is_active.is_(True),
                )
            )
            if reviewer is None:
                raise UnauthorizedReviewerError

            row = (
                await session.execute(
                    select(Submission, Enrollment, Lesson, Course, Student)
                    .join(Enrollment, Enrollment.id == Submission.enrollment_id)
                    .join(Student, Student.id == Enrollment.student_id)
                    .join(Assignment, Assignment.id == Submission.assignment_id)
                    .join(Lesson, Lesson.id == Assignment.lesson_id)
                    .join(Course, Course.id == Lesson.course_id)
                    .where(Submission.id == submission_id)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                raise SubmissionNotFoundError

            submission, enrollment, lesson, course, student = row
            if submission.status not in {
                SubmissionStatus.SUBMITTED,
                SubmissionStatus.IN_REVIEW,
            }:
                raise SubmissionAlreadyReviewedError

            existing_feedback = await session.scalar(
                select(Feedback.id).where(Feedback.submission_id == submission.id)
            )
            if existing_feedback is not None:
                raise SubmissionAlreadyReviewedError

            submission.status = (
                SubmissionStatus.ACCEPTED
                if verdict is FeedbackVerdict.ACCEPTED
                else SubmissionStatus.REVISION_REQUESTED
            )
            submission.reviewed_at = datetime.now(UTC)
            session.add(
                Feedback(
                    submission_id=submission.id,
                    reviewer_id=reviewer.id,
                    verdict=verdict,
                    message=normalized_message,
                )
            )

            progression = await ProgressionService.record_review(
                session,
                enrollment_id=enrollment.id,
                lesson_id=lesson.id,
                accepted=verdict is FeedbackVerdict.ACCEPTED,
                occurred_at=submission.reviewed_at,
            )

            return ReviewResult(
                submission_id=submission.id,
                student_telegram_user_id=student.telegram_user_id,
                verdict=verdict,
                feedback_message=normalized_message,
                current_lesson_position=progression.current_lesson_position,
                course_completed=progression.course_completed,
            )
