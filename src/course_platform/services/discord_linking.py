"""Secure one-time linking between Telegram students and Discord members."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Cohort,
    Course,
    DiscordHomeworkSpace,
    DiscordLinkCode,
    DiscordStudentLink,
    Enrollment,
    Student,
)
from course_platform.models.enums import EnrollmentStatus

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 12
CODE_TTL = timedelta(minutes=10)


class DiscordLinkError(ValueError):
    """Base error safe to translate into a user-facing link response."""


class DiscordAccessRequiredError(DiscordLinkError):
    """The Telegram account has no currently active course access."""


class InvalidDiscordLinkCodeError(DiscordLinkError):
    """The supplied code is unknown, expired, or already consumed."""


class DiscordAccountAlreadyLinkedError(DiscordLinkError):
    """The Discord account already belongs to another student."""


class StudentAlreadyLinkedError(DiscordLinkError):
    """The student is already linked to another Discord account."""


@dataclass(frozen=True, slots=True)
class IssuedDiscordLinkCode:
    code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class LinkedDiscordStudent:
    student_id: UUID
    first_name: str
    already_linked: bool = False


class DiscordLinkService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret: SecretStr | str,
    ) -> None:
        self._session_factory = session_factory
        value = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        if not value:
            raise ValueError("Discord link secret is empty")
        self._secret = value.encode()

    async def issue(self, telegram_user_id: int) -> IssuedDiscordLinkCode:
        now = datetime.now(UTC)
        async with session_scope(self._session_factory) as session:
            student = await self._active_student(
                session, telegram_user_id=telegram_user_id
            )
            if student is None:
                raise DiscordAccessRequiredError("active-access-required")

            await session.execute(
                update(DiscordLinkCode)
                .where(
                    DiscordLinkCode.student_id == student.id,
                    DiscordLinkCode.used_at.is_(None),
                )
                .values(used_at=now)
            )
            raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            expires_at = now + CODE_TTL
            session.add(
                DiscordLinkCode(
                    student_id=student.id,
                    code_digest=self._digest(raw),
                    expires_at=expires_at,
                )
            )
            return IssuedDiscordLinkCode(self._format(raw), expires_at)

    async def redeem(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        code: str,
    ) -> LinkedDiscordStudent:
        now = datetime.now(UTC)
        normalized = self._normalize(code)
        async with session_scope(self._session_factory) as session:
            link_code = await session.scalar(
                select(DiscordLinkCode).where(
                    DiscordLinkCode.code_digest == self._digest(normalized)
                )
            )
            if (
                link_code is None
                or link_code.used_at is not None
                or self._as_utc(link_code.expires_at) <= now
            ):
                raise InvalidDiscordLinkCodeError("invalid-link-code")

            student = await self._active_student(session, student_id=link_code.student_id)
            if student is None:
                raise DiscordAccessRequiredError("active-access-required")

            user_link = await session.scalar(
                select(DiscordStudentLink).where(
                    DiscordStudentLink.guild_id == guild_id,
                    DiscordStudentLink.discord_user_id == discord_user_id,
                )
            )
            if user_link is not None and user_link.student_id != student.id:
                raise DiscordAccountAlreadyLinkedError("discord-already-linked")

            student_link = await session.scalar(
                select(DiscordStudentLink).where(
                    DiscordStudentLink.guild_id == guild_id,
                    DiscordStudentLink.student_id == student.id,
                )
            )
            if student_link is not None and student_link.discord_user_id != discord_user_id:
                raise StudentAlreadyLinkedError("student-already-linked")

            already_linked = user_link is not None
            if user_link is None:
                session.add(
                    DiscordStudentLink(
                        guild_id=guild_id,
                        discord_user_id=discord_user_id,
                        student_id=student.id,
                    )
                )
            link_code.used_at = now
            await session.execute(
                update(DiscordHomeworkSpace)
                .where(
                    DiscordHomeworkSpace.guild_id == guild_id,
                    DiscordHomeworkSpace.discord_user_id == discord_user_id,
                )
                .values(student_id=student.id)
            )
            return LinkedDiscordStudent(student.id, student.first_name, already_linked)

    async def get_active_student(
        self, guild_id: int, discord_user_id: int
    ) -> LinkedDiscordStudent | None:
        async with self._session_factory() as session:
            student = await session.scalar(
                select(Student)
                .join(DiscordStudentLink, DiscordStudentLink.student_id == Student.id)
                .join(Enrollment, Enrollment.student_id == Student.id)
                .join(Cohort, Cohort.id == Enrollment.cohort_id)
                .join(Course, Course.id == Cohort.course_id)
                .where(
                    DiscordStudentLink.guild_id == guild_id,
                    DiscordStudentLink.discord_user_id == discord_user_id,
                    Student.is_active.is_(True),
                    Enrollment.status == EnrollmentStatus.ACTIVE,
                    Cohort.is_active.is_(True),
                    Course.is_active.is_(True),
                )
                .limit(1)
            )
            if student is None:
                return None
            return LinkedDiscordStudent(student.id, student.first_name)

    async def _active_student(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int | None = None,
        student_id: UUID | None = None,
    ) -> Student | None:
        query = (
            select(Student)
            .join(Enrollment, Enrollment.student_id == Student.id)
            .join(Cohort, Cohort.id == Enrollment.cohort_id)
            .join(Course, Course.id == Cohort.course_id)
            .where(
                Student.is_active.is_(True),
                Enrollment.status == EnrollmentStatus.ACTIVE,
                Cohort.is_active.is_(True),
                Course.is_active.is_(True),
            )
            .limit(1)
        )
        if telegram_user_id is not None:
            query = query.where(Student.telegram_user_id == telegram_user_id)
        elif student_id is not None:
            query = query.where(Student.id == student_id)
        else:
            raise ValueError("A student identity is required")
        return await session.scalar(query)

    def _digest(self, normalized_code: str) -> str:
        return hmac.new(
            self._secret,
            self._normalize(normalized_code).encode(),
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
