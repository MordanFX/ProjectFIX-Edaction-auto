"""Database construction and transaction boundary tests."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.config import Settings
from course_platform.db.session import create_engine, create_session_factory, session_scope
from course_platform.models import Student


async def test_engine_and_session_factory_are_built_from_settings() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", _env_file=None)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    assert engine.dialect.name == "sqlite"
    assert session_factory.class_ is AsyncSession

    await engine.dispose()


async def test_session_scope_commits(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory) as session:
        session.add(Student(telegram_user_id=42, first_name="Test"))

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Student))

    assert count == 1


async def test_session_scope_rolls_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RuntimeError, match="force rollback"):
        async with session_scope(session_factory) as session:
            session.add(Student(telegram_user_id=99, first_name="Rollback"))
            await session.flush()
            raise RuntimeError("force rollback")

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Student))

    assert count == 0
