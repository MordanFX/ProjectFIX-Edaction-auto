"""Independent Discord participant identities backed by shared learning primitives."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import DiscordHomeworkSpace, DiscordParticipant, Student
from course_platform.models.enums import StudentOrigin


@dataclass(frozen=True, slots=True)
class DiscordParticipantIdentity:
    participant_id: UUID
    student_id: UUID
    guild_id: int
    discord_user_id: int
    display_name: str


class DiscordParticipantService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_or_create(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        display_name: str,
        username: str | None = None,
        global_name: str | None = None,
        avatar_hash: str | None = None,
        guild_joined_at: datetime | None = None,
    ) -> DiscordParticipantIdentity:
        normalized_name = display_name.strip()[:100] or f"Discord {discord_user_id}"
        now = datetime.now(UTC)
        async with session_scope(self._session_factory) as session:
            participant = await session.scalar(
                select(DiscordParticipant).where(
                    DiscordParticipant.guild_id == guild_id,
                    DiscordParticipant.discord_user_id == discord_user_id,
                )
            )
            if participant is None:
                student = Student(
                    telegram_user_id=None,
                    origin=StudentOrigin.DISCORD,
                    first_name=normalized_name,
                    username=None,
                    is_active=True,
                )
                session.add(student)
                await session.flush()
                participant = DiscordParticipant(
                    guild_id=guild_id,
                    discord_user_id=discord_user_id,
                    student_id=student.id,
                    display_name=normalized_name,
                    username=self._normalized(username, 64),
                    global_name=self._normalized(global_name, 100),
                    avatar_hash=avatar_hash,
                    guild_joined_at=guild_joined_at,
                    last_activity_at=now,
                    is_guild_member=True,
                )
                session.add(participant)
                await session.flush()
            else:
                student = await session.get(Student, participant.student_id)
                if student is None:
                    raise RuntimeError("Discord participant has no learning profile")
                student.first_name = normalized_name
                student.origin = StudentOrigin.DISCORD
                participant.display_name = normalized_name
                participant.username = self._normalized(username, 64)
                participant.global_name = self._normalized(global_name, 100)
                participant.avatar_hash = avatar_hash
                participant.guild_joined_at = guild_joined_at or participant.guild_joined_at
                participant.last_activity_at = now
                participant.is_guild_member = True
                participant.left_at = None

            return DiscordParticipantIdentity(
                participant_id=participant.id,
                student_id=participant.student_id,
                guild_id=participant.guild_id,
                discord_user_id=participant.discord_user_id,
                display_name=normalized_name,
            )

    async def record_activity(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        display_name: str,
        username: str | None,
        global_name: str | None,
        avatar_hash: str | None,
        guild_joined_at: datetime | None,
        channel_id: int | None = None,
        touch_activity: bool = True,
    ) -> bool:
        """Refresh an existing profile from a Discord member activity event."""
        async with session_scope(self._session_factory) as session:
            query = select(DiscordParticipant).where(
                    DiscordParticipant.guild_id == guild_id,
                    DiscordParticipant.discord_user_id == discord_user_id,
                )
            if channel_id is not None:
                query = query.join(
                    DiscordHomeworkSpace,
                    (DiscordHomeworkSpace.guild_id == DiscordParticipant.guild_id)
                    & (
                        DiscordHomeworkSpace.discord_user_id
                        == DiscordParticipant.discord_user_id
                    ),
                ).where(DiscordHomeworkSpace.channel_id == channel_id)
            participant = await session.scalar(query)
            if participant is None:
                return False
            normalized_name = display_name.strip()[:100] or participant.display_name
            participant.display_name = normalized_name
            participant.username = self._normalized(username, 64)
            participant.global_name = self._normalized(global_name, 100)
            participant.avatar_hash = avatar_hash
            participant.guild_joined_at = guild_joined_at or participant.guild_joined_at
            if touch_activity:
                participant.last_activity_at = datetime.now(UTC)
            participant.is_guild_member = True
            participant.left_at = None
            student = await session.get(Student, participant.student_id)
            if student is not None:
                student.first_name = normalized_name
            return True

    async def mark_left(self, *, guild_id: int, discord_user_id: int) -> bool:
        """Mark a known participant as no longer present on the configured server."""
        async with session_scope(self._session_factory) as session:
            participant = await session.scalar(
                select(DiscordParticipant).where(
                    DiscordParticipant.guild_id == guild_id,
                    DiscordParticipant.discord_user_id == discord_user_id,
                )
            )
            if participant is None:
                return False
            participant.is_guild_member = False
            participant.left_at = datetime.now(UTC)
            return True

    @staticmethod
    def _normalized(value: str | None, limit: int) -> str | None:
        normalized = (value or "").strip()
        return normalized[:limit] or None
