"""Shared isolated database fixtures."""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import course_platform.models  # noqa: F401 - registers all model tables
from course_platform.db.base import Base


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield test_engine

    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
