"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    discord_invite_channel_id: int | None = None
    discord_staff_role_id: int | None = None
    discord_staff_role_ids: Annotated[tuple[int, ...], NoDecode] = ()
    discord_message_content_enabled: bool = False
    jwt_secret: SecretStr | None = None
    jwt_access_token_expire_minutes: int = 60
    feedback_upload_dir: str = "data/feedback_uploads"

    @field_validator("discord_staff_role_ids", mode="before")
    @classmethod
    def parse_discord_staff_role_ids(cls, value: object) -> tuple[int, ...]:
        if value in (None, ""):
            return ()
        if isinstance(value, str):
            return tuple(
                int(item.strip())
                for item in value.split(",")
                if item.strip()
            )
        if isinstance(value, (list, tuple, set)):
            return tuple(int(item) for item in value)
        return (int(value),)


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings instance per process."""

    return Settings()
