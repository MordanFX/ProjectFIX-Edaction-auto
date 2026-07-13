"""Long-polling application loop used during local development."""

import asyncio
import logging

from course_platform.bot.api import TelegramAPIError, TelegramBotClient, TelegramTransportError
from course_platform.bot.notifications import TelegramFeedbackDispatcher
from course_platform.bot.reminders import TelegramLessonReminderDispatcher
from course_platform.bot.router import MessageRouter

logger = logging.getLogger(__name__)


class BotApplication:
    """Fetch updates in order and hand each one to the message router."""

    def __init__(
        self,
        api: TelegramBotClient,
        router: MessageRouter,
        *,
        poll_timeout: int = 30,
        retry_delay: float = 2.0,
        feedback_dispatcher: TelegramFeedbackDispatcher | None = None,
        reminder_dispatcher: TelegramLessonReminderDispatcher | None = None,
    ) -> None:
        self._api = api
        self._router = router
        self._poll_timeout = poll_timeout
        self._retry_delay = retry_delay
        self._feedback_dispatcher = feedback_dispatcher
        self._reminder_dispatcher = reminder_dispatcher
        self._next_offset: int | None = None

    async def poll_once(self) -> int:
        updates = await self._api.get_updates(
            offset=self._next_offset,
            poll_timeout=self._poll_timeout,
        )
        for update in updates:
            try:
                await self._router.handle(update)
            except Exception:
                logger.exception("Failed to handle Telegram update %s", update.update_id)
            finally:
                self._next_offset = update.update_id + 1

        if self._feedback_dispatcher is not None:
            try:
                await self._feedback_dispatcher.dispatch_pending()
            except Exception:
                logger.exception("Failed to dispatch pending feedback notifications")

        if self._reminder_dispatcher is not None:
            try:
                await self._reminder_dispatcher.dispatch_due()
            except Exception:
                logger.exception("Failed to dispatch lesson reminders")

        return len(updates)

    async def run_forever(self) -> None:
        while True:
            try:
                await self.poll_once()
            except (TelegramAPIError, TelegramTransportError) as error:
                logger.warning("Telegram polling error: %s", error)
                await asyncio.sleep(self._retry_delay)
