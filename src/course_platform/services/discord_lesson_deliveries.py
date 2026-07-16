"""Database outbox for curator-triggered Discord lesson delivery."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    DiscordHomeworkSpace,
    DiscordLessonDelivery,
    DiscordLessonDispatch,
    DiscordParticipant,
    Enrollment,
    Lesson,
    StaffUser,
)
from course_platform.models.enums import (
    CourseAudience,
    EnrollmentStatus,
    NotificationStatus,
    VideoSource,
)


class DiscordLessonDispatchError(RuntimeError):
    """The requested lesson dispatch is not valid."""


@dataclass(frozen=True, slots=True)
class DiscordLessonDeliveryItem:
    delivery_id: UUID
    channel_id: int
    discord_user_id: int
    content: str


@dataclass(frozen=True, slots=True)
class DiscordLessonDispatchOverview:
    dispatch_id: UUID
    course_id: UUID
    course_title: str
    lesson_id: UUID
    lesson_position: int
    lesson_title: str
    custom_message: str | None
    created_by: str
    created_at: datetime
    recipient_count: int
    pending_count: int
    sent_count: int
    failed_count: int


class DiscordLessonDeliveryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_dispatch(
        self,
        *,
        guild_id: int,
        lesson_id: UUID,
        student_ids: tuple[UUID, ...],
        custom_message: str | None,
        staff_id: UUID,
    ) -> DiscordLessonDispatchOverview:
        unique_students = tuple(dict.fromkeys(student_ids))
        if not unique_students:
            raise DiscordLessonDispatchError("recipients-required")
        normalized_message = (custom_message or "").strip()[:1000] or None

        async with session_scope(self._session_factory) as session:
            lesson_row = (
                await session.execute(
                    select(Lesson, Course, Assignment)
                    .join(Course, Course.id == Lesson.course_id)
                    .outerjoin(Assignment, Assignment.lesson_id == Lesson.id)
                    .where(Lesson.id == lesson_id)
                )
            ).one_or_none()
            if lesson_row is None:
                raise DiscordLessonDispatchError("lesson-not-found")
            lesson, course, assignment = lesson_row
            if course.audience is not CourseAudience.DISCORD:
                raise DiscordLessonDispatchError("discord-course-required")
            if not course.is_active or not lesson.is_published:
                raise DiscordLessonDispatchError("published-lesson-required")
            if assignment is None:
                raise DiscordLessonDispatchError("assignment-required")

            recipients = (
                await session.execute(
                    select(DiscordParticipant, DiscordHomeworkSpace)
                    .join(
                        Enrollment,
                        Enrollment.student_id == DiscordParticipant.student_id,
                    )
                    .join(Cohort, Cohort.id == Enrollment.cohort_id)
                    .join(
                        DiscordHomeworkSpace,
                        (DiscordHomeworkSpace.guild_id == DiscordParticipant.guild_id)
                        & (
                            DiscordHomeworkSpace.discord_user_id
                            == DiscordParticipant.discord_user_id
                        ),
                    )
                    .where(
                        DiscordParticipant.guild_id == guild_id,
                        DiscordParticipant.student_id.in_(unique_students),
                        DiscordParticipant.is_guild_member.is_(True),
                        Cohort.course_id == course.id,
                        Cohort.is_active.is_(True),
                        Enrollment.status == EnrollmentStatus.ACTIVE,
                        Enrollment.current_lesson_position == lesson.position,
                    )
                )
            ).all()
            by_student = {
                participant.student_id: (participant, space) for participant, space in recipients
            }
            if set(by_student) != set(unique_students):
                raise DiscordLessonDispatchError("recipients-not-eligible")

            already_exists = set(
                await session.scalars(
                    select(DiscordLessonDelivery.participant_id).where(
                        DiscordLessonDelivery.lesson_id == lesson.id,
                        DiscordLessonDelivery.participant_id.in_(
                            participant.id for participant, _space in by_student.values()
                        ),
                    )
                )
            )
            selected = [
                (participant, space)
                for participant, space in by_student.values()
                if participant.id not in already_exists
            ]
            if not selected:
                raise DiscordLessonDispatchError("lesson-already-dispatched")

            dispatch = DiscordLessonDispatch(
                lesson_id=lesson.id,
                created_by_staff_id=staff_id,
                custom_message=normalized_message,
                recipient_count=len(selected),
            )
            session.add(dispatch)
            await session.flush()
            session.add_all(
                DiscordLessonDelivery(
                    dispatch_id=dispatch.id,
                    lesson_id=lesson.id,
                    participant_id=participant.id,
                    discord_user_id=participant.discord_user_id,
                    channel_id=space.channel_id,
                    status=NotificationStatus.PENDING,
                    attempts=0,
                )
                for participant, space in selected
            )
            await session.flush()
            return DiscordLessonDispatchOverview(
                dispatch_id=dispatch.id,
                course_id=course.id,
                course_title=course.title,
                lesson_id=lesson.id,
                lesson_position=lesson.position,
                lesson_title=lesson.title,
                custom_message=normalized_message,
                created_by=(await session.get(StaffUser, staff_id)).display_name,
                created_at=dispatch.created_at,
                recipient_count=len(selected),
                pending_count=len(selected),
                sent_count=0,
                failed_count=0,
            )

    async def list_dispatches(self, *, limit: int = 30) -> list[DiscordLessonDispatchOverview]:
        async with self._session_factory() as session:
            dispatches = list(
                await session.scalars(
                    select(DiscordLessonDispatch)
                    .order_by(DiscordLessonDispatch.created_at.desc())
                    .limit(limit)
                )
            )
            if not dispatches:
                return []
            delivery_counts = (
                await session.execute(
                    select(
                        DiscordLessonDelivery.dispatch_id,
                        DiscordLessonDelivery.status,
                        func.count(DiscordLessonDelivery.id),
                    )
                    .where(
                        DiscordLessonDelivery.dispatch_id.in_(
                            dispatch.id for dispatch in dispatches
                        )
                    )
                    .group_by(
                        DiscordLessonDelivery.dispatch_id,
                        DiscordLessonDelivery.status,
                    )
                )
            ).all()
            counts: dict[UUID, dict[NotificationStatus, int]] = {}
            for dispatch_id, status, count in delivery_counts:
                counts.setdefault(dispatch_id, {})[status] = count
            rows = (
                await session.execute(
                    select(DiscordLessonDispatch, Lesson, Course, StaffUser)
                    .join(Lesson, Lesson.id == DiscordLessonDispatch.lesson_id)
                    .join(Course, Course.id == Lesson.course_id)
                    .join(
                        StaffUser,
                        StaffUser.id == DiscordLessonDispatch.created_by_staff_id,
                    )
                    .where(DiscordLessonDispatch.id.in_(dispatch.id for dispatch in dispatches))
                    .order_by(DiscordLessonDispatch.created_at.desc())
                )
            ).all()
            return [
                DiscordLessonDispatchOverview(
                    dispatch_id=dispatch.id,
                    course_id=course.id,
                    course_title=course.title,
                    lesson_id=lesson.id,
                    lesson_position=lesson.position,
                    lesson_title=lesson.title,
                    custom_message=dispatch.custom_message,
                    created_by=staff.display_name,
                    created_at=dispatch.created_at,
                    recipient_count=dispatch.recipient_count,
                    pending_count=counts.get(dispatch.id, {}).get(NotificationStatus.PENDING, 0),
                    sent_count=counts.get(dispatch.id, {}).get(NotificationStatus.SENT, 0),
                    failed_count=counts.get(dispatch.id, {}).get(NotificationStatus.FAILED, 0),
                )
                for dispatch, lesson, course, staff in rows
            ]

    async def list_pending(self, *, limit: int = 20) -> list[DiscordLessonDeliveryItem]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        DiscordLessonDelivery,
                        DiscordLessonDispatch,
                        Lesson,
                        Course,
                        Assignment,
                    )
                    .join(
                        DiscordLessonDispatch,
                        DiscordLessonDispatch.id == DiscordLessonDelivery.dispatch_id,
                    )
                    .join(Lesson, Lesson.id == DiscordLessonDelivery.lesson_id)
                    .join(Course, Course.id == Lesson.course_id)
                    .join(Assignment, Assignment.lesson_id == Lesson.id)
                    .where(
                        DiscordLessonDelivery.status.in_(
                            (NotificationStatus.PENDING, NotificationStatus.FAILED)
                        ),
                        DiscordLessonDelivery.attempts < 5,
                    )
                    .order_by(DiscordLessonDelivery.created_at)
                    .limit(limit)
                )
            ).all()
            return [
                DiscordLessonDeliveryItem(
                    delivery_id=delivery.id,
                    channel_id=delivery.channel_id,
                    discord_user_id=delivery.discord_user_id,
                    content=self._content(
                        discord_user_id=delivery.discord_user_id,
                        course_title=course.title,
                        lesson=lesson,
                        assignment=assignment,
                        custom_message=dispatch.custom_message,
                    ),
                )
                for delivery, dispatch, lesson, course, assignment in rows
            ]

    async def mark_sent(self, delivery_id: UUID, discord_message_id: int) -> None:
        await self._mark(delivery_id, sent=True, message_id=discord_message_id, error=None)

    async def mark_failed(self, delivery_id: UUID, error: str) -> None:
        await self._mark(delivery_id, sent=False, message_id=None, error=error[:1000])

    async def _mark(
        self,
        delivery_id: UUID,
        *,
        sent: bool,
        message_id: int | None,
        error: str | None,
    ) -> None:
        async with session_scope(self._session_factory) as session:
            delivery = await session.get(DiscordLessonDelivery, delivery_id)
            if delivery is None:
                return
            delivery.attempts += 1
            delivery.error = error
            if sent:
                delivery.status = NotificationStatus.SENT
                delivery.sent_at = datetime.now(UTC)
                delivery.discord_message_id = message_id
            else:
                delivery.status = NotificationStatus.FAILED

    @staticmethod
    def _content(
        *,
        discord_user_id: int,
        course_title: str,
        lesson: Lesson,
        assignment: Assignment,
        custom_message: str | None,
    ) -> str:
        parts = [
            f"<@{discord_user_id}>",
            f"### 📘 Урок {lesson.position} · {lesson.title}\n-# {course_title} · новый урок",
        ]
        if lesson.description:
            parts.append(lesson.description.strip())
        parts.append(f"**📝 Домашнее задание**\n{_quote(assignment.instructions)}")
        if lesson.video_source is VideoSource.EXTERNAL_URL and lesson.video_reference:
            # A masked link reads as an action, not as a raw URL dump; bots may
            # use masked links in plain message content.
            parts.append(f"🎬 **[Смотреть материал →]({lesson.video_reference.strip()})**")
        if custom_message:
            parts.append(f"**💬 Комментарий куратора**\n{_quote(custom_message)}")
        submission_guide = (
            "-# Как сдать: отправь ответ сообщением в эту ветку — "
            "под ним появится кнопка «Отправить на проверку»."
        )
        content = "\n\n".join(parts)
        content_limit = 1950 - len(submission_guide) - 2
        if len(content) > content_limit:
            content = f"{content[: content_limit - 1]}…"
        return f"{content}\n\n{submission_guide}"


def _quote(text: str) -> str:
    """Render text as a Discord block quote (every line prefixed with '> ')."""
    return "\n".join(f"> {line}" if line else ">" for line in text.strip().splitlines())
