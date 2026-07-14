"""Telegram dispatcher for database-backed feedback notifications."""

import logging
from pathlib import Path

from course_platform.bot.api import TelegramBotClient
from course_platform.bot.ui import (
    access_notification_text,
    feedback_notification_text,
    stage_keyboard,
)
from course_platform.models.enums import AttachmentKind, FeedbackVerdict
from course_platform.services.notifications import (
    AccessNotificationService,
    FeedbackNotificationService,
)
from course_platform.services.students import StudentStage

logger = logging.getLogger(__name__)


class TelegramFeedbackDispatcher:
    def __init__(
        self,
        api: TelegramBotClient,
        notifications: FeedbackNotificationService,
    ) -> None:
        self._api = api
        self._notifications = notifications

    async def dispatch_pending(self) -> int:
        pending = await self._notifications.list_pending()
        sent_count = 0
        for notification in pending:
            try:
                if notification.verdict is FeedbackVerdict.REVISION_REQUESTED:
                    keyboard = stage_keyboard(StudentStage.REVISION_REQUESTED)
                elif notification.course_completed:
                    keyboard = stage_keyboard(StudentStage.COURSE_COMPLETED)
                else:
                    keyboard = stage_keyboard(StudentStage.NEEDS_VIEW)
                await self._api.send_message(
                    notification.student_telegram_user_id,
                    feedback_notification_text(notification),
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
                for attachment in notification.attachments:
                    if (
                        attachment.source_chat_id is not None
                        and attachment.source_message_id is not None
                    ):
                        await self._api.copy_message(
                            notification.student_telegram_user_id,
                            attachment.source_chat_id,
                            attachment.source_message_id,
                        )
                    elif attachment.external_url is not None:
                        await self._api.send_message(
                            notification.student_telegram_user_id,
                            attachment.external_url,
                        )
                    elif attachment.local_path is not None:
                        local_path = Path(attachment.local_path)
                        if attachment.kind is AttachmentKind.PHOTO:
                            await self._api.send_photo_file(
                                notification.student_telegram_user_id,
                                local_path,
                                mime_type=attachment.mime_type or "image/jpeg",
                            )
                        else:
                            await self._api.send_document_file(
                                notification.student_telegram_user_id,
                                local_path,
                                mime_type=attachment.mime_type or "application/octet-stream",
                            )
            except Exception as error:
                logger.exception(
                    "Failed to deliver feedback notification %s",
                    notification.feedback_id,
                )
                await self._notifications.mark_failed(
                    notification.feedback_id,
                    type(error).__name__,
                )
                continue

            await self._notifications.mark_sent(notification.feedback_id)
            sent_count += 1
        return sent_count


class TelegramAccessDispatcher:
    def __init__(
        self,
        api: TelegramBotClient,
        notifications: AccessNotificationService,
    ) -> None:
        self._api = api
        self._notifications = notifications

    async def dispatch_pending(self) -> int:
        pending = await self._notifications.list_pending()
        sent_count = 0
        for notification in pending:
            try:
                await self._api.send_message(
                    notification.student_telegram_user_id,
                    access_notification_text(notification),
                    parse_mode="HTML",
                    reply_markup=stage_keyboard(StudentStage.NEEDS_VIEW),
                )
            except Exception:
                logger.exception(
                    "Failed to deliver access notification %s",
                    notification.enrollment_id,
                )
                continue

            await self._notifications.mark_sent(notification.enrollment_id)
            sent_count += 1
        return sent_count
