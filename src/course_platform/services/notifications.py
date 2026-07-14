"""Database-backed delivery queue for Telegram feedback notifications."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    Enrollment,
    Feedback,
    FeedbackAttachment,
    Lesson,
    Student,
    Submission,
)
from course_platform.models.enums import (
    AttachmentKind,
    EnrollmentStatus,
    FeedbackVerdict,
    NotificationStatus,
)


@dataclass(frozen=True, slots=True)
class FeedbackNotificationAttachment:
    kind: AttachmentKind
    source_chat_id: int | None
    source_message_id: int | None
    external_url: str | None
    local_path: str | None
    file_name: str | None
    mime_type: str | None


@dataclass(frozen=True, slots=True)
class FeedbackNotification:
    feedback_id: UUID
    student_telegram_user_id: int
    verdict: FeedbackVerdict
    message: str
    attachments: tuple[FeedbackNotificationAttachment, ...]
    current_lesson_position: int
    course_completed: bool


@dataclass(frozen=True, slots=True)
class AccessNotification:
    enrollment_id: UUID
    student_telegram_user_id: int
    course_title: str
    current_lesson_position: int


class FeedbackNotificationService:
    """Read and acknowledge review notifications using the shared database."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_pending(self, *, limit: int = 50) -> list[FeedbackNotification]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    Feedback.id,
                    Student.telegram_user_id,
                    Feedback.verdict,
                    Feedback.message,
                    Enrollment.current_lesson_position,
                    Enrollment.status,
                    Lesson.position.label("reviewed_lesson_position"),
                )
                .join(Submission, Submission.id == Feedback.submission_id)
                .join(Enrollment, Enrollment.id == Submission.enrollment_id)
                .join(Assignment, Assignment.id == Submission.assignment_id)
                .join(Lesson, Lesson.id == Assignment.lesson_id)
                .join(Student, Student.id == Enrollment.student_id)
                .where(
                    Student.telegram_user_id.is_not(None),
                    Feedback.notification_status.in_(
                        [NotificationStatus.PENDING, NotificationStatus.FAILED]
                    ),
                    Feedback.notification_attempts < 5,
                )
                .order_by(Feedback.created_at.asc())
                .limit(limit)
            )
            items = [
                FeedbackNotification(
                    feedback_id=row.id,
                    student_telegram_user_id=row.telegram_user_id,
                    verdict=row.verdict,
                    message=row.message,
                    attachments=(),
                    current_lesson_position=row.current_lesson_position,
                    course_completed=(
                        row.status is EnrollmentStatus.COMPLETED
                        and row.reviewed_lesson_position == row.current_lesson_position
                    ),
                )
                for row in rows
            ]
            if not items:
                return []
            attachments = await session.execute(
                select(
                    FeedbackAttachment.feedback_id,
                    FeedbackAttachment.kind,
                    FeedbackAttachment.source_chat_id,
                    FeedbackAttachment.source_message_id,
                    FeedbackAttachment.external_url,
                    FeedbackAttachment.local_path,
                    FeedbackAttachment.file_name,
                    FeedbackAttachment.mime_type,
                )
                .where(
                    FeedbackAttachment.feedback_id.in_(
                        [item.feedback_id for item in items]
                    )
                )
                .order_by(FeedbackAttachment.created_at.asc())
            )
            by_feedback: dict[UUID, list[FeedbackNotificationAttachment]] = {
                item.feedback_id: [] for item in items
            }
            for row in attachments:
                by_feedback[row.feedback_id].append(
                    FeedbackNotificationAttachment(
                        kind=row.kind,
                        source_chat_id=row.source_chat_id,
                        source_message_id=row.source_message_id,
                        external_url=row.external_url,
                        local_path=row.local_path,
                        file_name=row.file_name,
                        mime_type=row.mime_type,
                    )
                )
            return [
                FeedbackNotification(
                    feedback_id=item.feedback_id,
                    student_telegram_user_id=item.student_telegram_user_id,
                    verdict=item.verdict,
                    message=item.message,
                    attachments=tuple(by_feedback[item.feedback_id]),
                    current_lesson_position=item.current_lesson_position,
                    course_completed=item.course_completed,
                )
                for item in items
            ]

    async def mark_sent(self, feedback_id: UUID) -> None:
        async with session_scope(self._session_factory) as session:
            feedback = await session.get(Feedback, feedback_id)
            if feedback is None:
                return
            feedback.notification_status = NotificationStatus.SENT
            feedback.notification_attempts += 1
            feedback.notified_at = datetime.now(UTC)
            feedback.notification_error = None

    async def mark_failed(self, feedback_id: UUID, error: str) -> None:
        async with session_scope(self._session_factory) as session:
            feedback = await session.get(Feedback, feedback_id)
            if feedback is None:
                return
            feedback.notification_status = NotificationStatus.FAILED
            feedback.notification_attempts += 1
            feedback.notification_error = error[:1000]


class AccessNotificationService:
    """Notify Telegram students when a curator/admin opens course access."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_pending(self, *, limit: int = 50) -> list[AccessNotification]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    Enrollment.id,
                    Student.telegram_user_id,
                    Course.title,
                    Enrollment.current_lesson_position,
                )
                .join(Student, Student.id == Enrollment.student_id)
                .join(Cohort, Cohort.id == Enrollment.cohort_id)
                .join(Course, Course.id == Cohort.course_id)
                .where(
                    Student.telegram_user_id.is_not(None),
                    Student.is_active.is_(True),
                    Course.is_active.is_(True),
                    Enrollment.status == EnrollmentStatus.ACTIVE,
                    Enrollment.access_notified_at.is_(None),
                )
                .order_by(Enrollment.created_at.asc())
                .limit(limit)
            )
            return [
                AccessNotification(
                    enrollment_id=row.id,
                    student_telegram_user_id=row.telegram_user_id,
                    course_title=row.title,
                    current_lesson_position=row.current_lesson_position,
                )
                for row in rows
            ]

    async def mark_sent(self, enrollment_id: UUID) -> None:
        async with session_scope(self._session_factory) as session:
            enrollment = await session.get(Enrollment, enrollment_id)
            if enrollment is None:
                return
            enrollment.access_notified_at = datetime.now(UTC)
