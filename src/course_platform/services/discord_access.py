"""Manual Discord access period management for the curator panel."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Cohort,
    Course,
    DiscordHomeworkSpace,
    DiscordParticipant,
    Enrollment,
    Student,
)
from course_platform.models.enums import CourseAudience, EnrollmentStatus

DiscordAccessStatus = Literal[
    "active",
    "expiring",
    "expired",
    "revoked",
    "no_course",
    "no_expiry",
]


class DiscordAccessError(LookupError):
    """Raised when a Discord access operation cannot be applied."""


@dataclass(frozen=True, slots=True)
class DiscordAccessOverview:
    student_id: UUID
    guild_id: int
    discord_user_id: int
    discord_display_name: str
    discord_username: str | None
    avatar_url: str | None
    course_id: UUID | None
    course_title: str | None
    enrollment_status: EnrollmentStatus | None
    access_started_at: datetime | None
    access_expires_at: datetime | None
    access_source: str | None
    access_plan: str | None
    status: DiscordAccessStatus
    days_left: int | None
    channel_id: int | None
    thread_name: str | None
    last_activity_at: datetime | None


class DiscordAccessService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_accesses(self, guild_id: int | None = None) -> list[DiscordAccessOverview]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    self._base_query(guild_id).order_by(
                        DiscordParticipant.created_at.desc(),
                        Enrollment.created_at.desc(),
                    )
                )
            ).all()
            result: list[DiscordAccessOverview] = []
            seen: set[UUID] = set()
            for participant, student, space, enrollment, course in rows:
                if participant.id in seen:
                    continue
                seen.add(participant.id)
                result.append(self._overview(participant, student, space, enrollment, course))
            return result

    async def extend_access(self, *, student_id: UUID, months: int) -> DiscordAccessOverview:
        if months not in {1, 3}:
            raise DiscordAccessError("unsupported-access-period")
        async with session_scope(self._session_factory) as session:
            row = await self._access_context(session, student_id)
            participant, student, space, enrollment, course = row
            now = datetime.now(UTC)
            current_expires_at = _aware(enrollment.access_expires_at)
            base = (
                current_expires_at
                if current_expires_at and current_expires_at > now
                else now
            )
            enrollment.status = EnrollmentStatus.ACTIVE
            enrollment.access_started_at = enrollment.access_started_at or now
            enrollment.access_expires_at = _add_months(base, months)
            enrollment.access_source = "manual"
            enrollment.access_plan = f"{months}_month"
            student.is_active = True
            await session.flush()
            return self._overview(participant, student, space, enrollment, course)

    async def close_access(self, *, student_id: UUID) -> DiscordAccessOverview:
        async with session_scope(self._session_factory) as session:
            row = await self._access_context(session, student_id)
            participant, student, space, enrollment, course = row
            now = datetime.now(UTC)
            enrollment.status = EnrollmentStatus.REVOKED
            enrollment.access_expires_at = now
            enrollment.access_source = enrollment.access_source or "manual"
            await session.flush()
            return self._overview(participant, student, space, enrollment, course)

    async def set_expiry(
        self,
        *,
        student_id: UUID,
        expires_at: datetime,
    ) -> DiscordAccessOverview:
        async with session_scope(self._session_factory) as session:
            row = await self._access_context(session, student_id)
            participant, student, space, enrollment, course = row
            now = datetime.now(UTC)
            normalized_expires_at = _aware(expires_at)
            if normalized_expires_at is None:
                raise DiscordAccessError("access-expiry-required")
            enrollment.status = EnrollmentStatus.ACTIVE
            enrollment.access_started_at = enrollment.access_started_at or now
            enrollment.access_expires_at = normalized_expires_at
            enrollment.access_source = "manual"
            enrollment.access_plan = "custom"
            student.is_active = True
            await session.flush()
            return self._overview(participant, student, space, enrollment, course)

    def _base_query(self, guild_id: int | None = None):
        query = (
            select(
                DiscordParticipant,
                Student,
                DiscordHomeworkSpace,
                Enrollment,
                Course,
            )
            .join(Student, Student.id == DiscordParticipant.student_id)
            .outerjoin(
                DiscordHomeworkSpace,
                (DiscordHomeworkSpace.guild_id == DiscordParticipant.guild_id)
                & (
                    DiscordHomeworkSpace.discord_user_id
                    == DiscordParticipant.discord_user_id
                ),
            )
            .outerjoin(Enrollment, Enrollment.student_id == Student.id)
            .outerjoin(Cohort, Cohort.id == Enrollment.cohort_id)
            .outerjoin(
                Course,
                and_(
                    Course.id == Cohort.course_id,
                    Course.audience == CourseAudience.DISCORD,
                ),
            )
        )
        if guild_id is not None:
            query = query.where(DiscordParticipant.guild_id == guild_id)
        return query

    async def _access_context(
        self,
        session: AsyncSession,
        student_id: UUID,
    ) -> tuple[DiscordParticipant, Student, DiscordHomeworkSpace | None, Enrollment, Course]:
        row = (
            await session.execute(
                self._base_query()
                .where(Student.id == student_id, Course.id.is_not(None))
                .order_by(Enrollment.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            raise DiscordAccessError("discord-course-access-not-found")
        participant, student, space, enrollment, course = row
        if enrollment is None or course is None:
            raise DiscordAccessError("discord-course-access-not-found")
        return participant, student, space, enrollment, course

    def _overview(
        self,
        participant: DiscordParticipant,
        student: Student,
        space: DiscordHomeworkSpace | None,
        enrollment: Enrollment | None,
        course: Course | None,
    ) -> DiscordAccessOverview:
        status, days_left = _access_status(enrollment, course)
        return DiscordAccessOverview(
            student_id=student.id,
            guild_id=participant.guild_id,
            discord_user_id=participant.discord_user_id,
            discord_display_name=participant.display_name,
            discord_username=participant.username,
            avatar_url=_avatar_url(participant),
            course_id=course.id if course else None,
            course_title=course.title if course else None,
            enrollment_status=enrollment.status if enrollment else None,
            access_started_at=enrollment.access_started_at if enrollment else None,
            access_expires_at=enrollment.access_expires_at if enrollment else None,
            access_source=enrollment.access_source if enrollment else None,
            access_plan=enrollment.access_plan if enrollment else None,
            status=status,
            days_left=days_left,
            channel_id=space.channel_id if space else None,
            thread_name=space.channel_name if space else None,
            last_activity_at=participant.last_activity_at,
        )


def _access_status(
    enrollment: Enrollment | None,
    course: Course | None,
) -> tuple[DiscordAccessStatus, int | None]:
    if enrollment is None or course is None:
        return "no_course", None
    if enrollment.status is EnrollmentStatus.REVOKED:
        return "revoked", None
    expires_at = enrollment.access_expires_at
    if expires_at is None:
        return "no_expiry", None
    expires_at = _aware(expires_at)
    now = datetime.now(UTC)
    seconds_left = (expires_at - now).total_seconds()
    days_left = max(0, int(seconds_left // 86400))
    if seconds_left < 0:
        return "expired", 0
    if days_left <= 7:
        return "expiring", days_left
    return "active", days_left


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _avatar_url(participant: DiscordParticipant) -> str:
    if participant.avatar_hash:
        return (
            "https://cdn.discordapp.com/avatars/"
            f"{participant.discord_user_id}/{participant.avatar_hash}.png?size=128"
        )
    index = (participant.discord_user_id >> 22) % 6
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"
