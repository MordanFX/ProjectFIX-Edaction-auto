"""Curator-created Discord onboarding invites.

Path 1 onboarding: a curator hands a plain Discord invite to a new student, the
student joins and opens ``/homework`` to create their private thread. We store
the link only so the curator can review what they handed out; there is no usage
tracking, because reading invite usage would require ``Manage Server`` for the
bot.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import DiscordInvite


class DiscordInviteError(RuntimeError):
    """Invite creation or lookup failed."""


@dataclass(frozen=True, slots=True)
class DiscordInviteOverview:
    invite_id: UUID
    guild_id: int
    channel_id: int
    code: str
    invite_url: str
    course_id: UUID | None
    max_age_seconds: int
    expires_at: datetime
    created_by_staff_id: UUID | None
    created_at: datetime
    status: str


class DiscordInviteService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def remember_invite(
        self,
        *,
        guild_id: int,
        channel_id: int,
        code: str,
        invite_url: str,
        course_id: UUID | None,
        created_by_staff_id: UUID | None,
        max_age_seconds: int = 86400,
    ) -> DiscordInviteOverview:
        now = datetime.now(UTC)
        async with session_scope(self._session_factory) as session:
            model = DiscordInvite(
                guild_id=guild_id,
                channel_id=channel_id,
                code=code[:64],
                invite_url=invite_url[:255],
                course_id=course_id,
                max_age_seconds=max_age_seconds,
                expires_at=now + timedelta(seconds=max_age_seconds),
                created_by_staff_id=created_by_staff_id,
            )
            session.add(model)
            await session.flush()
            return self._to_domain(model)

    async def list_invites(self, *, guild_id: int) -> list[DiscordInviteOverview]:
        async with self._session_factory() as session:
            models = (
                await session.scalars(
                    select(DiscordInvite)
                    .where(DiscordInvite.guild_id == guild_id)
                    .order_by(DiscordInvite.created_at.desc())
                )
            ).all()
            return [self._to_domain(model) for model in models]

    @staticmethod
    def _to_domain(model: DiscordInvite) -> DiscordInviteOverview:
        now = datetime.now(UTC)
        expires_at = model.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        status = "expired" if expires_at <= now else "active"
        return DiscordInviteOverview(
            invite_id=model.id,
            guild_id=model.guild_id,
            channel_id=model.channel_id,
            code=model.code,
            invite_url=model.invite_url,
            course_id=model.course_id,
            max_age_seconds=model.max_age_seconds,
            expires_at=model.expires_at,
            created_by_staff_id=model.created_by_staff_id,
            created_at=model.created_at,
            status=status,
        )
