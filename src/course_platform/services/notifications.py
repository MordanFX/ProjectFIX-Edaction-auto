"""Database-backed delivery queue for Telegram feedback notifications."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import Assignment, Enrollment, Feedback, Lesson, Student, Submission
from course_platform.models.enums import (
    EnrollmentStatus,
    FeedbackVerdict,
    NotificationStatus,
)


@dataclass(frozen=True, slots=True)
class FeedbackNotification:
    feedback_id: UUID
    student_telegram_user_id: int
    verdict: FeedbackVerdict
    message: str
    current_lesson_position: int
    course_completed: bool


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
            return [
                FeedbackNotification(
                    feedback_id=row.id,
                    student_telegram_user_id=row.telegram_user_id,
                    verdict=row.verdict,
                    message=row.message,
                    current_lesson_position=row.current_lesson_position,
                    course_completed=(
                        row.status is EnrollmentStatus.COMPLETED
                        and row.reviewed_lesson_position == row.current_lesson_position
                    ),
                )
                for row in rows
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
