"""Run the Discord integration."""

import asyncio
import logging

from course_platform.config import get_settings
from course_platform.db.session import create_engine, create_session_factory
from course_platform.discord.api import DiscordAPIClient
from course_platform.discord.application import DiscordApplication
from course_platform.services.discord_homework import DiscordHomeworkService
from course_platform.services.discord_lesson_deliveries import DiscordLessonDeliveryService
from course_platform.services.discord_notifications import DiscordFeedbackNotificationService
from course_platform.services.discord_participants import DiscordParticipantService
from course_platform.services.discord_questions import DiscordQuestionService
from course_platform.services.discord_submissions import DiscordSubmissionService


async def main() -> None:
    settings = get_settings()
    if settings.discord_bot_token is None or settings.discord_guild_id is None:
        raise SystemExit("DISCORD_BOT_TOKEN and DISCORD_GUILD_ID are required")
    token = settings.discord_bot_token.get_secret_value()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with DiscordAPIClient(token) as api:
            await DiscordApplication(
                api,
                token,
                settings.discord_guild_id,
                DiscordHomeworkService(session_factory),
                DiscordParticipantService(session_factory),
                DiscordSubmissionService(session_factory),
                message_content_enabled=settings.discord_message_content_enabled,
                feedback_service=DiscordFeedbackNotificationService(session_factory),
                lesson_delivery_service=DiscordLessonDeliveryService(session_factory),
                question_service=DiscordQuestionService(session_factory),
                homework_channel_id=settings.discord_homework_channel_id,
                staff_role_id=settings.discord_staff_role_id,
            ).run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=getattr(logging, get_settings().log_level.upper(), logging.INFO))
    asyncio.run(main())
