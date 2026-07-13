"""Telegram delivery tests for lesson reminders and curator escalation."""

import json
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.bot.api import TelegramBotClient
from course_platform.bot.reminders import TelegramLessonReminderDispatcher
from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import LessonReminder, Student
from course_platform.models.enums import ReminderStatus
from course_platform.services.learning import LearningService
from course_platform.services.reminders import LessonReminderService
from course_platform.services.students import StudentRegistration, StudentService


async def test_dispatcher_sends_student_chain_and_curator_alert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(
        StudentRegistration(telegram_user_id=701, first_name="Reminder")
    )
    await seed_demo_data(session_factory)
    assert await LearningService(session_factory).get_current_lesson(701) is not None

    now = datetime.now(UTC)
    async with session_factory() as session:
        student = await session.scalar(
            select(Student).where(Student.telegram_user_id == 701)
        )
        reminders = list(await session.scalars(select(LessonReminder)))
        assert student is not None
        student.quiet_hours_start = 0
        student.quiet_hours_end = 0
        for reminder in reminders:
            reminder.scheduled_at = now - timedelta(minutes=1)
        await session.commit()

    sent: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        sent.append(payload)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": len(sent),
                    "date": 1_700_000_001,
                    "chat": {"id": payload["chat_id"], "type": "private"},
                    "text": payload["text"],
                },
            },
        )

    reminders = LessonReminderService(session_factory)
    async with TelegramBotClient(
        "token",
        transport=httpx.MockTransport(handler),
    ) as api:
        delivered = await TelegramLessonReminderDispatcher(
            api,
            reminders,
        ).dispatch_due()

    assert delivered == 3
    student_messages = [
        item for item in sent if "УЧЕНИКУ НУЖНО ВНИМАНИЕ" not in str(item["text"])
    ]
    curator_message = next(
        item for item in sent if "УЧЕНИКУ НУЖНО ВНИМАНИЕ" in str(item["text"])
    )
    assert len(student_messages) == 2
    assert all(
        any(
                    button["text"] == "▶ Продолжить"
            for row in message["reply_markup"]["keyboard"]
            for button in row
        )
        for message in student_messages
    )
    curator_buttons = {
        button["text"]
        for row in curator_message["reply_markup"]["keyboard"]
        for button in row
    }
    assert "📥 Очередь проверки" in curator_buttons
    assert "🗂 Проверенные" in curator_buttons

    async with session_factory() as session:
        statuses = list(await session.scalars(select(LessonReminder.status)))
    assert statuses == [ReminderStatus.SENT] * 3
