"""Safe live check for the configured Telegram bot token."""

import asyncio

from course_platform.bot.api import TelegramBotClient
from course_platform.config import get_settings


async def check_bot() -> None:
    settings = get_settings()
    if settings.telegram_bot_token is None:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not configured")

    async with TelegramBotClient(settings.telegram_bot_token) as client:
        bot = await client.get_me()

    username = f"@{bot.username}" if bot.username else bot.first_name
    print(f"Telegram bot connected: {username} (id={bot.id})")


if __name__ == "__main__":
    asyncio.run(check_bot())
