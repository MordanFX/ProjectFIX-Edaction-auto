"""Homework review use cases shared by Telegram and the future web API."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Course,
    Enrollment,
    Feedback,
    FeedbackAttachment,
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


class SubmissionAlreadyAssignedError(ReviewWorkflowError):
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
    assigned_reviewer_id: UUID | None
    assigned_reviewer_name: str | None
    assigned_at: datetime | None


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
            or attachment.local_path is not None
        ),
    )


def _feedback_review_attachment(attachment: FeedbackAttachment) -> ReviewAttachment:
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
class FeedbackAttachmentInput:
    kind: AttachmentKind
    telegram_file_id: str | None = None
    telegram_file_unique_id: str | None = None
    discord_attachment_id: int | None = None
    external_url: str | None = None
    local_path: str | None = None
    source_chat_id: int | None = None
    source_message_id: int | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    duration_seconds: int | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class AttachmentMediaSource:
    id: UUID
    submission_id: UUID
    kind: AttachmentKind
    telegram_file_id: str | None
    external_url: str | None
    local_path: str | None
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
    feedback_attachments: tuple[ReviewAttachment, ...]
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
    feedback_attachments: tuple[ReviewAttachment, ...]


@dataclass(frozen=True, slots=True)
class ReviewResult:
    submission_id: UUID
    student_telegram_user_id: int | None
    verdict: FeedbackVerdict
    feedback_message: str
    feedback_attachment_count: int
    current_lesson_position: int
    course_completed: bool


@dataclass(frozen=True, slots=True)
class CuratorReviewStats:
    pending_assigned: int
    reviewed_total: int
    accepted_total: int
    revision_total: int
    telegram_reviewed: int
    discord_reviewed: int


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
                    Submission.assigned_reviewer_id,
                    Submission.assigned_at,
                    StaffUser.display_name.label("assigned_reviewer_name"),
                )
                .join(Enrollment, Enrollment.id == Submission.enrollment_id)
                .join(Student, Student.id == Enrollment.student_id)
                .join(Assignment, Assignment.id == Submission.assignment_id)
                .join(Lesson, Lesson.id == Assignment.lesson_id)
                .join(Course, Course.id == Lesson.course_id)
                .outerjoin(StaffUser, StaffUser.id == Submission.assigned_reviewer_id)
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
                    assigned_reviewer_id=row.assigned_reviewer_id,
                    assigned_reviewer_name=row.assigned_reviewer_name,
                    assigned_at=row.assigned_at,
                )
                for row in rows
            ]

    async def assign_to_reviewer(
        self,
        *,
        submission_id: UUID,
        reviewer_id: UUID,
    ) -> ReviewQueueItem:
        async with session_scope(self._session_factory) as session:
            submission = await session.get(Submission, submission_id, with_for_update=True)
            if submission is None:
                raise SubmissionNotFoundError
            if submission.status not in {SubmissionStatus.SUBMITTED, SubmissionStatus.IN_REVIEW}:
                raise SubmissionAlreadyReviewedError
            if (
                submission.assigned_reviewer_id is not None
                and submission.assigned_reviewer_id != reviewer_id
            ):
                raise SubmissionAlreadyAssignedError
            submission.status = SubmissionStatus.IN_REVIEW
            submission.assigned_reviewer_id = reviewer_id
            submission.assigned_at = datetime.now(UTC)

        detail = await self.get_detail(submission_id)
        return ReviewQueueItem(
            submission_id=detail.submission_id,
            student_id=detail.student_id,
            student_name=detail.student_name,
            student_username=detail.student_username,
            course_title=detail.course_title,
            lesson_position=detail.lesson_position,
            lesson_title=detail.lesson_title,
            attempt_number=detail.attempt_number,
            submitted_at=detail.submitted_at,
            text_body=detail.text_body,
            attachment_count=detail.attachment_count,
            attachment_kind=detail.attachment_kind,
            attachment_file_name=detail.attachment_file_name,
            attachment_mime_type=detail.attachment_mime_type,
            status=detail.status,
            source=detail.source,
            source_guild_id=detail.source_guild_id,
            source_channel_id=detail.source_channel_id,
            source_message_id=detail.source_message_id,
            assigned_reviewer_id=detail.assigned_reviewer_id,
            assigned_reviewer_name=detail.assigned_reviewer_name,
            assigned_at=detail.assigned_at,
        )

    async def release_assignment(
        self,
        *,
        submission_id: UUID,
        reviewer_id: UUID,
    ) -> ReviewQueueItem:
        async with session_scope(self._session_factory) as session:
            submission = await session.get(Submission, submission_id, with_for_update=True)
            if submission is None:
                raise SubmissionNotFoundError
            if submission.status not in {SubmissionStatus.SUBMITTED, SubmissionStatus.IN_REVIEW}:
                raise SubmissionAlreadyReviewedError
            if (
                submission.assigned_reviewer_id is not None
                and submission.assigned_reviewer_id != reviewer_id
            ):
                raise SubmissionAlreadyAssignedError
            submission.status = SubmissionStatus.SUBMITTED
            submission.assigned_reviewer_id = None
            submission.assigned_at = None

        detail = await self.get_detail(submission_id)
        return ReviewQueueItem(
            submission_id=detail.submission_id,
            student_id=detail.student_id,
            student_name=detail.student_name,
            student_username=detail.student_username,
            course_title=detail.course_title,
            lesson_position=detail.lesson_position,
            lesson_title=detail.lesson_title,
            attempt_number=detail.attempt_number,
            submitted_at=detail.submitted_at,
            text_body=detail.text_body,
            attachment_count=detail.attachment_count,
            attachment_kind=detail.attachment_kind,
            attachment_file_name=detail.attachment_file_name,
            attachment_mime_type=detail.attachment_mime_type,
            status=detail.status,
            source=detail.source,
            source_guild_id=detail.source_guild_id,
            source_channel_id=detail.source_channel_id,
            source_message_id=detail.source_message_id,
            assigned_reviewer_id=detail.assigned_reviewer_id,
            assigned_reviewer_name=detail.assigned_reviewer_name,
            assigned_at=detail.assigned_at,
        )

    async def curator_stats(self, reviewer_id: UUID) -> CuratorReviewStats:
        async with self._session_factory() as session:
            pending_assigned = await session.scalar(
                select(func.count(Submission.id)).where(
                    Submission.assigned_reviewer_id == reviewer_id,
                    Submission.status.in_(
                        [SubmissionStatus.SUBMITTED, SubmissionStatus.IN_REVIEW]
                    ),
                )
            )
            reviewed_total = await session.scalar(
                select(func.count(Feedback.id)).where(Feedback.reviewer_id == reviewer_id)
            )
            accepted_total = await session.scalar(
                select(func.count(Feedback.id)).where(
                    Feedback.reviewer_id == reviewer_id,
                    Feedback.verdict == FeedbackVerdict.ACCEPTED,
                )
            )
            revision_total = await session.scalar(
                select(func.count(Feedback.id)).where(
                    Feedback.reviewer_id == reviewer_id,
                    Feedback.verdict == FeedbackVerdict.REVISION_REQUESTED,
                )
            )
            telegram_reviewed = await session.scalar(
                select(func.count(Feedback.id))
                .join(Submission, Submission.id == Feedback.submission_id)
                .where(
                    Feedback.reviewer_id == reviewer_id,
                    Submission.source == SubmissionSource.TELEGRAM,
                )
            )
            discord_reviewed = await session.scalar(
                select(func.count(Feedback.id))
                .join(Submission, Submission.id == Feedback.submission_id)
                .where(
                    Feedback.reviewer_id == reviewer_id,
                    Submission.source == SubmissionSource.DISCORD,
                )
            )
            return CuratorReviewStats(
                pending_assigned=pending_assigned or 0,
                reviewed_total=reviewed_total or 0,
                accepted_total=accepted_total or 0,
                revision_total=revision_total or 0,
                telegram_reviewed=telegram_reviewed or 0,
                discord_reviewed=discord_reviewed or 0,
            )

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
            state.question_id = None

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
                        StaffBotState.submission_id.is_not(None),
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
        attachments: tuple[FeedbackAttachmentInput, ...] = (),
    ) -> TelegramReviewCompletion:
        pending = await self.get_pending_telegram_feedback(reviewer_telegram_user_id)
        if pending is None:
            raise NoPendingFeedbackError
        result = await self.review_by_staff_id(
            submission_id=pending.submission_id,
            reviewer_id=pending.reviewer_id,
            verdict=pending.verdict,
            message=message,
            attachments=attachments,
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
            assigned_reviewer = aliased(StaffUser)
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
                        Submission.assigned_reviewer_id,
                        Submission.assigned_at,
                        assigned_reviewer.display_name.label("assigned_reviewer_name"),
                        Submission.reviewed_at,
                        Feedback.id.label("feedback_id"),
                        Feedback.verdict.label("feedback_verdict"),
                        Feedback.message.label("feedback_message"),
                        StaffUser.display_name.label("reviewer_name"),
                    )
                    .join(Enrollment, Enrollment.id == Submission.enrollment_id)
                    .join(Student, Student.id == Enrollment.student_id)
                    .join(Assignment, Assignment.id == Submission.assignment_id)
                    .join(Lesson, Lesson.id == Assignment.lesson_id)
                    .join(Course, Course.id == Lesson.course_id)
                    .outerjoin(
                        assigned_reviewer,
                        assigned_reviewer.id == Submission.assigned_reviewer_id,
                    )
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
            feedback_attachments = []
            if row.feedback_id is not None:
                feedback_attachments = list(
                    (
                        await session.scalars(
                            select(FeedbackAttachment)
                            .where(FeedbackAttachment.feedback_id == row.feedback_id)
                            .order_by(FeedbackAttachment.created_at.asc())
                        )
                    ).all()
                )

            previous_rows = (
                await session.execute(
                    select(
                        Submission.id,
                        Feedback.id.label("feedback_id"),
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
            previous_feedback_ids = [
                previous.feedback_id
                for previous in previous_rows
                if previous.feedback_id is not None
            ]
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
            previous_feedback_attachment_rows = []
            if previous_feedback_ids:
                previous_feedback_attachment_rows = list(
                    (
                        await session.scalars(
                            select(FeedbackAttachment)
                            .where(FeedbackAttachment.feedback_id.in_(previous_feedback_ids))
                            .order_by(FeedbackAttachment.created_at.asc())
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
            feedback_attachments_by_feedback: dict[UUID, list[ReviewAttachment]] = {
                feedback_id: [] for feedback_id in previous_feedback_ids
            }
            for attachment in previous_feedback_attachment_rows:
                feedback_attachments_by_feedback[attachment.feedback_id].append(
                    _feedback_review_attachment(attachment)
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
                assigned_reviewer_id=row.assigned_reviewer_id,
                assigned_reviewer_name=row.assigned_reviewer_name,
                assigned_at=row.assigned_at,
                reviewed_at=row.reviewed_at,
                feedback_verdict=row.feedback_verdict,
                feedback_message=row.feedback_message,
                reviewer_name=row.reviewer_name,
                attachments=tuple(
                    _review_attachment(attachment)
                    for attachment in attachments
                ),
                feedback_attachments=tuple(
                    _feedback_review_attachment(attachment)
                    for attachment in feedback_attachments
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
                        feedback_attachments=tuple(
                            feedback_attachments_by_feedback.get(
                                previous.feedback_id,
                                [],
                            )
                            if previous.feedback_id is not None
                            else []
                        ),
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
                local_path=None,
                file_name=attachment.file_name,
                mime_type=attachment.mime_type,
                file_size=attachment.file_size,
            )

    async def get_feedback_attachment_media_source(
        self,
        *,
        submission_id: UUID,
        attachment_id: UUID,
    ) -> AttachmentMediaSource:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(FeedbackAttachment, Feedback)
                    .join(Feedback, Feedback.id == FeedbackAttachment.feedback_id)
                    .where(
                        FeedbackAttachment.id == attachment_id,
                        Feedback.submission_id == submission_id,
                    )
                )
            ).one_or_none()
            if row is None:
                raise AttachmentNotFoundError
            attachment, feedback = row

            return AttachmentMediaSource(
                id=attachment.id,
                submission_id=feedback.submission_id,
                kind=attachment.kind,
                telegram_file_id=attachment.telegram_file_id,
                external_url=attachment.external_url,
                local_path=attachment.local_path,
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
        attachments: tuple[FeedbackAttachmentInput, ...] = (),
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
            attachments=attachments,
        )

    async def review_by_staff_id(
        self,
        *,
        submission_id: UUID,
        reviewer_id: UUID,
        verdict: FeedbackVerdict,
        message: str,
        attachments: tuple[FeedbackAttachmentInput, ...] = (),
    ) -> ReviewResult:
        normalized_message = message.strip()
        if not normalized_message and not attachments:
            raise EmptyFeedbackError
        if not normalized_message:
            normalized_message = "См. вложение куратора."

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
            if (
                submission.assigned_reviewer_id is not None
                and submission.assigned_reviewer_id != reviewer.id
            ):
                raise SubmissionAlreadyAssignedError

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
            submission.assigned_reviewer_id = reviewer.id
            submission.assigned_at = submission.assigned_at or datetime.now(UTC)
            submission.reviewed_at = datetime.now(UTC)
            feedback = Feedback(
                submission_id=submission.id,
                reviewer_id=reviewer.id,
                verdict=verdict,
                message=normalized_message,
            )
            for attachment in attachments:
                feedback.attachments.append(
                    FeedbackAttachment(
                        kind=attachment.kind,
                        telegram_file_id=attachment.telegram_file_id,
                        telegram_file_unique_id=attachment.telegram_file_unique_id,
                        discord_attachment_id=attachment.discord_attachment_id,
                        external_url=attachment.external_url,
                        local_path=attachment.local_path,
                        source_chat_id=attachment.source_chat_id,
                        source_message_id=attachment.source_message_id,
                        file_name=attachment.file_name,
                        mime_type=attachment.mime_type,
                        file_size=attachment.file_size,
                        duration_seconds=attachment.duration_seconds,
                        width=attachment.width,
                        height=attachment.height,
                    )
                )
            session.add(feedback)

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
                feedback_attachment_count=len(attachments),
                current_lesson_position=progression.current_lesson_position,
                course_completed=progression.course_completed,
            )
