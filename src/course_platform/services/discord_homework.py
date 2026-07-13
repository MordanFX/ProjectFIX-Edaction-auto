"""Persistence for Discord personal homework spaces."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import DiscordHomeworkSpace


@dataclass(frozen=True, slots=True)
class HomeworkSpace:
    guild_id: int
    discord_user_id: int
    parent_channel_id: int
    channel_id: int
    channel_name: str | None
    kind: str
    display_name: str
    student_id: UUID | None


class DiscordHomeworkService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find(self, guild_id: int, discord_user_id: int) -> HomeworkSpace | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(DiscordHomeworkSpace).where(
                    DiscordHomeworkSpace.guild_id == guild_id,
                    DiscordHomeworkSpace.discord_user_id == discord_user_id,
                )
            )
            return self._to_domain(model) if model is not None else None

    async def remember(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        parent_channel_id: int,
        channel_id: int,
        channel_name: str,
        kind: str,
        display_name: str,
        student_id: UUID,
    ) -> HomeworkSpace:
        async with session_scope(self._session_factory) as session:
            model = DiscordHomeworkSpace(
                guild_id=guild_id,
                discord_user_id=discord_user_id,
                parent_channel_id=parent_channel_id,
                channel_id=channel_id,
                channel_name=channel_name[:100],
                kind=kind,
                display_name=display_name,
                student_id=student_id,
            )
            session.add(model)
            await session.flush()
            return self._to_domain(model)

    async def assign_student(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        student_id: UUID,
    ) -> HomeworkSpace | None:
        async with session_scope(self._session_factory) as session:
            model = await session.scalar(
                select(DiscordHomeworkSpace).where(
                    DiscordHomeworkSpace.guild_id == guild_id,
                    DiscordHomeworkSpace.discord_user_id == discord_user_id,
                )
            )
            if model is None:
                return None
            model.student_id = student_id
            await session.flush()
            return self._to_domain(model)

    async def refresh_metadata(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        display_name: str,
        channel_name: str,
    ) -> HomeworkSpace | None:
        async with session_scope(self._session_factory) as session:
            model = await session.scalar(
                select(DiscordHomeworkSpace).where(
                    DiscordHomeworkSpace.guild_id == guild_id,
                    DiscordHomeworkSpace.discord_user_id == discord_user_id,
                )
            )
            if model is None:
                return None
            model.display_name = display_name[:100]
            model.channel_name = channel_name[:100]
            await session.flush()
            return self._to_domain(model)

    @staticmethod
    def _to_domain(model: DiscordHomeworkSpace) -> HomeworkSpace:
        return HomeworkSpace(
            guild_id=model.guild_id,
            discord_user_id=model.discord_user_id,
            parent_channel_id=model.parent_channel_id,
            channel_id=model.channel_id,
            channel_name=model.channel_name,
            kind=model.kind,
            display_name=model.display_name,
            student_id=model.student_id,
        )
