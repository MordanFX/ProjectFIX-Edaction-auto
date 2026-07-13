"""Durable lesson reminder scheduling, quiet hours, and delivery state."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Course,
    CourseReminderStep,
    Enrollment,
    Lesson,
    LessonReminder,
    StaffUser,
    Student,
)
from course_platform.models.enums import ReminderKind, ReminderStatus


@dataclass(frozen=True, slots=True)
class ReminderDelivery:
    reminder_id: UUID
    kind: ReminderKind
    recipient_telegram_ids: tuple[int, ...]
    message_text: str
    student_name: str
    student_username: str | None
    course_title: str
    lesson_position: int
    lesson_title: str
    last_activity_at: datetime


class LessonReminderService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    async def ensure_scheduled(
        session: AsyncSession,
        *,
        enrollment: Enrollment,
        lesson: Lesson,
        available_at: datetime,
    ) -> None:
        steps = list(
            await session.scalars(
                select(CourseReminderStep)
                .where(
                    CourseReminderStep.course_id == lesson.course_id,
                    CourseReminderStep.is_active.is_(True),
                )
                .order_by(CourseReminderStep.sequence)
            )
        )
        if not steps:
            return

        existing_step_ids = set(
            await session.scalars(
                select(LessonReminder.step_id).where(
                    LessonReminder.enrollment_id == enrollment.id,
                    LessonReminder.lesson_id == lesson.id,
                )
            )
        )
        for step in steps:
            if step.id in existing_step_ids:
                continue
            session.add(
                LessonReminder(
                    enrollment_id=enrollment.id,
                    lesson_id=lesson.id,
                    step_id=step.id,
                    scheduled_at=available_at + timedelta(hours=step.delay_hours),
                    status=ReminderStatus.PENDING,
                )
            )

    @staticmethod
    async def cancel_pending(
        session: AsyncSession,
        *,
        enrollment_id: UUID,
        lesson_id: UUID,
    ) -> None:
        reminders = list(
            await session.scalars(
                select(LessonReminder).where(
                    LessonReminder.enrollment_id == enrollment_id,
                    LessonReminder.lesson_id == lesson_id,
                    LessonReminder.status.in_([ReminderStatus.PENDING, ReminderStatus.FAILED]),
                )
            )
        )
        for reminder in reminders:
            reminder.status = ReminderStatus.CANCELLED
            reminder.last_error = None

    async def list_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> list[ReminderDelivery]:
        current_time = now or datetime.now(UTC)
        async with session_scope(self._session_factory) as session:
            rows = await session.execute(
                select(LessonReminder, CourseReminderStep, Student, Lesson, Course)
                .join(CourseReminderStep, CourseReminderStep.id == LessonReminder.step_id)
                .join(Enrollment, Enrollment.id == LessonReminder.enrollment_id)
                .join(Student, Student.id == Enrollment.student_id)
                .join(Lesson, Lesson.id == LessonReminder.lesson_id)
                .join(Course, Course.id == Lesson.course_id)
                .where(
                    LessonReminder.status.in_([ReminderStatus.PENDING, ReminderStatus.FAILED]),
                    LessonReminder.attempts < 5,
                    LessonReminder.scheduled_at <= current_time,
                )
                .order_by(LessonReminder.scheduled_at)
                .limit(limit)
            )
            curator_ids: tuple[int, ...] | None = None
            deliveries: list[ReminderDelivery] = []
            for reminder, step, student, lesson, course in rows:
                if not student.reminders_enabled or not student.is_active:
                    reminder.status = ReminderStatus.CANCELLED
                    continue

                if step.kind is ReminderKind.CURATOR_ALERT:
                    if curator_ids is None:
                        curator_ids = tuple(
                            await session.scalars(
                                select(StaffUser.telegram_user_id).where(
                                    StaffUser.is_active.is_(True),
                                    StaffUser.telegram_user_id.is_not(None),
                                )
                            )
                        )
                    recipients = curator_ids
                else:
                    allowed_at = next_allowed_delivery_time(
                        current_time,
                        timezone_name=student.timezone,
                        quiet_start=student.quiet_hours_start,
                        quiet_end=student.quiet_hours_end,
                    )
                    comparable_now = _coerce_for_reference(current_time, allowed_at)
                    if allowed_at > comparable_now:
                        reminder.scheduled_at = allowed_at
                        continue
                    recipients = (student.telegram_user_id,)

                if not recipients:
                    reminder.status = ReminderStatus.FAILED
                    reminder.attempts += 1
                    reminder.last_error = "No Telegram recipient configured"
                    continue

                deliveries.append(
                    ReminderDelivery(
                        reminder_id=reminder.id,
                        kind=step.kind,
                        recipient_telegram_ids=recipients,
                        message_text=step.message_text,
                        student_name=" ".join(
                            part for part in [student.first_name, student.last_name] if part
                        ),
                        student_username=student.username,
                        course_title=course.title,
                        lesson_position=lesson.position,
                        lesson_title=lesson.title,
                        last_activity_at=student.last_activity_at,
                    )
                )
            return deliveries

    async def mark_sent(self, reminder_id: UUID) -> None:
        async with session_scope(self._session_factory) as session:
            reminder = await session.get(LessonReminder, reminder_id)
            if reminder is None:
                return
            reminder.status = ReminderStatus.SENT
            reminder.attempts += 1
            reminder.sent_at = datetime.now(UTC)
            reminder.last_error = None

    async def mark_failed(self, reminder_id: UUID, error: str) -> None:
        async with session_scope(self._session_factory) as session:
            reminder = await session.get(LessonReminder, reminder_id)
            if reminder is None:
                return
            reminder.status = ReminderStatus.FAILED
            reminder.attempts += 1
            reminder.last_error = error[:1000]
            reminder.scheduled_at = datetime.now(UTC) + timedelta(
                minutes=min(60, 5 * 2 ** max(0, reminder.attempts - 1))
            )


def next_allowed_delivery_time(
    now: datetime,
    *,
    timezone_name: str,
    quiet_start: int,
    quiet_end: int,
) -> datetime:
    if quiet_start == quiet_end:
        return now
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")

    aware_now = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    local_now = aware_now.astimezone(timezone)
    hour = local_now.hour
    overnight = quiet_start > quiet_end
    in_quiet_hours = (
        hour >= quiet_start or hour < quiet_end
        if overnight
        else quiet_start <= hour < quiet_end
    )
    if not in_quiet_hours:
        return now

    target_date: date = local_now.date()
    if overnight and hour >= quiet_start:
        target_date += timedelta(days=1)
    local_target = datetime.combine(
        target_date,
        time(hour=quiet_end),
        tzinfo=timezone,
    )
    target_utc = local_target.astimezone(UTC)
    return target_utc.replace(tzinfo=None) if now.tzinfo is None else target_utc


def _coerce_for_reference(value: datetime, reference: datetime) -> datetime:
    if reference.tzinfo is None and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    if reference.tzinfo is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
