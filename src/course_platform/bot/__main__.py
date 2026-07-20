"""Run the student bot locally with long polling."""

import asyncio
import logging

from course_platform.bot.api import TelegramBotClient
from course_platform.bot.application import BotApplication
from course_platform.bot.notifications import TelegramAccessDispatcher, TelegramFeedbackDispatcher
from course_platform.bot.reminders import TelegramLessonReminderDispatcher
from course_platform.bot.router import MessageRouter
from course_platform.config import get_settings
from course_platform.db.session import create_engine, create_session_factory
from course_platform.integrations.vimeo import VimeoOEmbedClient
from course_platform.services.admin_dashboard import AdminDashboardService
from course_platform.services.learning import LearningService
from course_platform.services.notifications import (
    AccessNotificationService,
    FeedbackNotificationService,
)
from course_platform.services.progression import ProgressionService
from course_platform.services.reminders import LessonReminderService
from course_platform.services.reviews import ReviewService
from course_platform.services.students import StudentAccessService, StudentService
from course_platform.services.submissions import SubmissionService
from course_platform.services.telegram_questions import TelegramQuestionService


def configure_logging(level: str) -> None:
    """Configure application logs without exposing token-bearing HTTP URLs."""

    logging.basicConfig(level=level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def run_bot() -> None:
    settings = get_settings()
    if settings.telegram_bot_token is None:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not configured")

    configure_logging(settings.log_level)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with (
            TelegramBotClient(settings.telegram_bot_token) as api,
            VimeoOEmbedClient() as vimeo,
        ):
            bot = await api.get_me()
            logging.getLogger(__name__).info("Starting @%s", bot.username or bot.first_name)
            router = MessageRouter(
                api,
                StudentService(session_factory),
                LearningService(session_factory),
                SubmissionService(session_factory),
                ReviewService(session_factory),
                ProgressionService(session_factory),
                AdminDashboardService(session_factory),
                StudentAccessService(session_factory),
                vimeo,
                TelegramQuestionService(session_factory),
            )
            feedback_dispatcher = TelegramFeedbackDispatcher(
                api,
                FeedbackNotificationService(session_factory),
            )
            access_dispatcher = TelegramAccessDispatcher(
                api,
                AccessNotificationService(session_factory),
            )
            reminder_dispatcher = TelegramLessonReminderDispatcher(
                api,
                LessonReminderService(session_factory),
            )
            await BotApplication(
                api,
                router,
                access_dispatcher=access_dispatcher,
                feedback_dispatcher=feedback_dispatcher,
                reminder_dispatcher=reminder_dispatcher,
            ).run_forever()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass
