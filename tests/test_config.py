"""Configuration behavior and secret handling."""

from course_platform.config import Settings


def test_settings_have_safe_development_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.telegram_bot_token is None


def test_settings_read_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DB_ECHO", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "not-a-real-token")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.db_echo is True
    assert settings.telegram_bot_token is not None
    assert settings.telegram_bot_token.get_secret_value() == "not-a-real-token"
    assert "not-a-real-token" not in repr(settings)
