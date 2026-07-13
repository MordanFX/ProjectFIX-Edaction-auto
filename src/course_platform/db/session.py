"""Async SQLAlchemy engine and session helpers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from course_platform.config import Settings, get_settings


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    """Build an engine without creating module-level network connections."""

    resolved_settings = settings or get_settings()
    engine = create_async_engine(
        resolved_settings.database_url,
        echo=resolved_settings.db_echo,
        pool_pre_ping=True,
    )
    if resolved_settings.database_url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the shared async session factory for an engine."""

    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Commit successful units of work and roll back failed ones."""

    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
