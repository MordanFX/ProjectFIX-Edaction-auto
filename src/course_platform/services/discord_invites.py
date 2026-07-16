"""Curator-issued Discord seats: an invite link plus a personal access code.

A Discord invite only gets someone onto the guild — it carries no identity, so it
cannot gate anything by itself. The gate is the access code: the student presents
it to ``/homework`` and the bot then grants that one member access to the homework
channel. Because the student hands us the code, we never read Discord's own invite
usage, which would require ``Manage Server``.

Codes are single-use, unique per seat, and stored only as an HMAC digest.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import DiscordInvite

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 12


class DiscordInviteError(RuntimeError):
    """Invite creation or lookup failed."""


class InvalidDiscordAccessCodeError(DiscordInviteError):
    """The supplied access code is unknown, expired, or already consumed."""


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
    used_at: datetime | None
    used_by_discord_user_id: int | None
    status: str


@dataclass(frozen=True, slots=True)
class IssuedDiscordInvite:
    """A freshly created seat. ``access_code`` is plaintext and shown only once."""

    invite: DiscordInviteOverview
    access_code: str


class DiscordInviteService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret: SecretStr | str,
    ) -> None:
        self._session_factory = session_factory
        value = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        if not value:
            raise ValueError("Discord invite secret is empty")
        self._secret = value.encode()

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
    ) -> IssuedDiscordInvite:
        now = datetime.now(UTC)
        raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        async with session_scope(self._session_factory) as session:
            model = DiscordInvite(
                guild_id=guild_id,
                channel_id=channel_id,
                code=code[:64],
                invite_url=invite_url[:255],
                access_code_digest=self._digest(raw),
                course_id=course_id,
                max_age_seconds=max_age_seconds,
                expires_at=now + timedelta(seconds=max_age_seconds),
                created_by_staff_id=created_by_staff_id,
            )
            session.add(model)
            await session.flush()
            return IssuedDiscordInvite(self._to_domain(model), self._format(raw))

    async def redeem_access_code(
        self,
        *,
        guild_id: int,
        code: str,
        discord_user_id: int,
    ) -> DiscordInviteOverview:
        """Consume a code and return the seat it unlocks.

        Raises InvalidDiscordAccessCodeError for unknown, expired, used, or
        wrong-guild codes — the caller must not tell the student which it was.
        """

        now = datetime.now(UTC)
        async with session_scope(self._session_factory) as session:
            model = await session.scalar(
                select(DiscordInvite).where(
                    DiscordInvite.access_code_digest == self._digest(code)
                )
            )
            if (
                model is None
                or model.guild_id != guild_id
                or model.used_at is not None
                or self._as_utc(model.expires_at) <= now
            ):
                raise InvalidDiscordAccessCodeError("invalid-access-code")
            model.used_at = now
            model.used_by_discord_user_id = discord_user_id
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

    def _digest(self, code: str) -> str:
        return hmac.new(
            self._secret,
            self._normalize(code).encode(),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _normalize(code: str) -> str:
        return "".join(character for character in code.upper() if character.isalnum())

    @staticmethod
    def _format(code: str) -> str:
        return "-".join(code[index : index + 4] for index in range(0, len(code), 4))

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @classmethod
    def _to_domain(cls, model: DiscordInvite) -> DiscordInviteOverview:
        now = datetime.now(UTC)
        if model.used_at is not None:
            status = "used"
        elif cls._as_utc(model.expires_at) <= now:
            status = "expired"
        else:
            status = "active"
        return DiscordInviteOverview(
            invite_id=model.id,
            guild_id=model.guild_id,
            channel_id=model.channel_id,
            code=model.code,
            invite_url=model.invite_url,
            course_id=model.course_id,
            max_age_seconds=model.max_age_seconds,
            expires_at=cls._as_utc(model.expires_at),
            created_by_staff_id=model.created_by_staff_id,
            created_at=model.created_at,
            used_at=model.used_at,
            used_by_discord_user_id=model.used_by_discord_user_id,
            status=status,
        )
