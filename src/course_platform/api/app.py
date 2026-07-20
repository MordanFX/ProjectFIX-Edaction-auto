"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.api.routers import (
    auth,
    courses,
    dashboard,
    discord,
    health,
    reviews,
    staff,
    students,
    telegram_questions,
)
from course_platform.config import Settings, get_settings
from course_platform.db.session import create_engine, create_session_factory


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    telegram_transport: httpx.AsyncBaseTransport | None = None,
    vimeo_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if session_factory is not None:
            yield
            return

        engine = create_engine(resolved_settings)
        application.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    application = FastAPI(
        title="Mordan | Project FIX API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.telegram_transport = telegram_transport
    application.state.vimeo_transport = vimeo_transport
    if session_factory is not None:
        application.state.session_factory = session_factory

    application.include_router(health.router, prefix="/api")
    application.include_router(auth.router, prefix="/api")
    application.include_router(reviews.router, prefix="/api")
    application.include_router(dashboard.router, prefix="/api")
    application.include_router(students.router, prefix="/api")
    application.include_router(courses.router, prefix="/api")
    application.include_router(discord.router, prefix="/api")
    application.include_router(staff.router, prefix="/api")
    application.include_router(telegram_questions.router, prefix="/api")
    return application


app = create_app()
