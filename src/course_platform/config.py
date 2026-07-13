"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Shared settings for the bot, database, and future API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str = (
        "postgresql+asyncpg://course_user:course_password@localhost:5432/course_platform"
    )
    db_echo: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_api_url: str = "https://api.telegram.org"
    discord_bot_token: SecretStr | None = None
    discord_guild_id: int | None = None
    discord_homework_channel_id: int | None = None
    discord_staff_role_id: int | None = None
    discord_message_content_enabled: bool = False
    jwt_secret: SecretStr | None = None
    jwt_access_token_expire_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings instance per process."""

    return Settings()
