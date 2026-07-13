"""Durable lesson reminder scheduling and quiet-hour tests."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import CourseReminderStep, LessonReminder, Student
from course_platform.models.enums import ReminderKind, ReminderStatus
from course_platform.services.learning import LearningService
from course_platform.services.progression import ProgressionService
from course_platform.services.reminders import (
    LessonReminderService,
    next_allowed_delivery_time,
)
from course_platform.services.students import StudentRegistration, StudentService


async def prepare_reminders(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=701, first_name="Reminder")
    )
    await seed_demo_data(session_factory)
    lesson = await LearningService(session_factory).get_current_lesson(701)
    assert lesson is not None


async def test_opening_lesson_schedules_steps_and_view_cancels_them(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await prepare_reminders(session_factory)

    async with session_factory() as session:
        reminders = list(
            await session.scalars(
                select(LessonReminder)
                .join(CourseReminderStep, CourseReminderStep.id == LessonReminder.step_id)
                .order_by(CourseReminderStep.sequence)
            )
        )

    assert len(reminders) == 3
    assert all(item.status is ReminderStatus.PENDING for item in reminders)
    assert reminders[1].scheduled_at - reminders[0].scheduled_at == timedelta(hours=24)

    await ProgressionService(session_factory).mark_current_viewed(701)
    async with session_factory() as session:
        statuses = list(await session.scalars(select(LessonReminder.status)))

    assert statuses == [ReminderStatus.CANCELLED] * 3


async def test_due_reminders_target_student_then_curator(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await prepare_reminders(session_factory)
    now = datetime.now(UTC)
    async with session_factory() as session:
        student = await session.scalar(select(Student))
        reminders = list(await session.scalars(select(LessonReminder)))
        assert student is not None
        student.quiet_hours_start = 0
        student.quiet_hours_end = 0
        for reminder in reminders:
            reminder.scheduled_at = now - timedelta(minutes=1)
        await session.commit()

    due = await LessonReminderService(session_factory).list_due(now=now)

    assert {item.kind for item in due} == {
        ReminderKind.STUDENT_GENTLE,
        ReminderKind.STUDENT_FOLLOW_UP,
        ReminderKind.CURATOR_ALERT,
    }
    student_reminder = next(item for item in due if item.kind is ReminderKind.STUDENT_GENTLE)
    assert student_reminder.recipient_telegram_ids == (701,)
    assert "Знакомство с курсом" in student_reminder.lesson_title


async def test_student_can_disable_and_reenable_current_lesson_reminders(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await prepare_reminders(session_factory)
    students = StudentService(session_factory)

    await students.update_settings(701, reminders_enabled=False)
    async with session_factory() as session:
        disabled = list(await session.scalars(select(LessonReminder)))

    assert disabled
    assert all(reminder.status is ReminderStatus.CANCELLED for reminder in disabled)

    reenabled_at = datetime.now(UTC)
    await students.update_settings(701, reminders_enabled=True)
    async with session_factory() as session:
        reenabled = list(await session.scalars(select(LessonReminder)))

    assert all(reminder.status is ReminderStatus.PENDING for reminder in reenabled)
    assert all(
        (
            reminder.scheduled_at
            if reminder.scheduled_at.tzinfo is not None
            else reminder.scheduled_at.replace(tzinfo=UTC)
        )
        >= reenabled_at
        for reminder in reenabled
    )
    assert all(reminder.attempts == 0 for reminder in reenabled)


def test_quiet_hours_move_delivery_to_morning() -> None:
    now = datetime(2026, 6, 30, 20, 30, tzinfo=UTC)

    allowed = next_allowed_delivery_time(
        now,
        timezone_name="Europe/Kyiv",
        quiet_start=22,
        quiet_end=9,
    )

    assert allowed == datetime(2026, 7, 1, 6, 0, tzinfo=UTC)
