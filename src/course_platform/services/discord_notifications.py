"""Database outbox delivery of curator feedback to Discord homework threads."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import Feedback, FeedbackAttachment, Submission
from course_platform.models.enums import FeedbackVerdict, NotificationStatus, SubmissionSource


@dataclass(frozen=True, slots=True)
class DiscordFeedbackAttachment:
    external_url: str | None
    local_path: str | None
    file_name: str | None
    mime_type: str | None


@dataclass(frozen=True, slots=True)
class DiscordFeedbackNotification:
    feedback_id: UUID
    channel_id: int
    verdict: FeedbackVerdict
    message: str
    attachments: tuple[DiscordFeedbackAttachment, ...]


class DiscordFeedbackNotificationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_pending(self, *, limit: int = 20) -> list[DiscordFeedbackNotification]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    Feedback.id,
                    Submission.source_channel_id,
                    Feedback.verdict,
                    Feedback.message,
                )
                .join(Submission, Submission.id == Feedback.submission_id)
                .where(
                    Submission.source == SubmissionSource.DISCORD,
                    Submission.source_channel_id.is_not(None),
                    Feedback.notification_status.in_(
                        [NotificationStatus.PENDING, NotificationStatus.FAILED]
                    ),
                    Feedback.notification_attempts < 5,
                )
                .order_by(Feedback.created_at)
                .limit(limit)
            )
            items = [
                DiscordFeedbackNotification(
                    feedback_id=row.id,
                    channel_id=row.source_channel_id,
                    verdict=row.verdict,
                    message=row.message,
                    attachments=(),
                )
                for row in rows
                if row.source_channel_id is not None
            ]
            if not items:
                return []
            attachments = await session.execute(
                select(
                    FeedbackAttachment.feedback_id,
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
            by_feedback: dict[UUID, list[DiscordFeedbackAttachment]] = {
                item.feedback_id: [] for item in items
            }
            for row in attachments:
                by_feedback[row.feedback_id].append(
                    DiscordFeedbackAttachment(
                        external_url=row.external_url,
                        local_path=row.local_path,
                        file_name=row.file_name,
                        mime_type=row.mime_type,
                    )
                )
            return [
                DiscordFeedbackNotification(
                    feedback_id=item.feedback_id,
                    channel_id=item.channel_id,
                    verdict=item.verdict,
                    message=item.message,
                    attachments=tuple(by_feedback[item.feedback_id]),
                )
                for item in items
            ]

    async def mark_sent(self, feedback_id: UUID) -> None:
        await self._mark(feedback_id, sent=True, error=None)

    async def mark_failed(self, feedback_id: UUID, error: str) -> None:
        await self._mark(feedback_id, sent=False, error=error[:1000])

    async def _mark(self, feedback_id: UUID, *, sent: bool, error: str | None) -> None:
        async with session_scope(self._session_factory) as session:
            feedback = await session.get(Feedback, feedback_id)
            if feedback is None:
                return
            feedback.notification_attempts += 1
            feedback.notification_error = error
            if sent:
                feedback.notification_status = NotificationStatus.SENT
                feedback.notified_at = datetime.now(UTC)
            else:
                feedback.notification_status = NotificationStatus.FAILED
