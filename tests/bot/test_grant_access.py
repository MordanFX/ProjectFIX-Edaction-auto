"""Curator Telegram course grant flow tests."""

import json

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.bot.api import TelegramBotClient
from course_platform.bot.router import MessageRouter
from course_platform.bot.types import TelegramUpdate
from course_platform.models import Course, Enrollment, StaffUser
from course_platform.models.enums import CourseAudience, EnrollmentStatus
from course_platform.services.admin_dashboard import AdminDashboardService
from course_platform.services.learning import LearningService
from course_platform.services.progression import ProgressionService
from course_platform.services.reviews import ReviewService
from course_platform.services.students import (
    StudentAccessService,
    StudentRegistration,
    StudentService,
)
from course_platform.services.submissions import SubmissionService


def curator_message(text: str) -> TelegramUpdate:
    return TelegramUpdate.model_validate(
        {
            "update_id": 100,
            "message": {
                "message_id": 10,
                "date": 1_700_000_000,
                "chat": {"id": 555, "type": "private"},
                "from": {
                    "id": 555,
                    "is_bot": False,
                    "first_name": "Curator",
                    "username": "curator",
                },
                "text": text,
            },
        }
    )


def grant_callback(data: str) -> TelegramUpdate:
    return TelegramUpdate.model_validate(
        {
            "update_id": 101,
            "callback_query": {
                "id": f"callback-{data}",
                "from": {
                    "id": 555,
                    "is_bot": False,
                    "first_name": "Curator",
                    "username": "curator",
                },
                "message": {
                    "message_id": 20,
                    "date": 1_700_000_001,
                    "chat": {"id": 555, "type": "private"},
                    "text": "Grant access",
                },
                "data": data,
            },
        }
    )


async def test_curator_grants_telegram_course_from_bot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    registration = await students.register(
        StudentRegistration(
            telegram_user_id=888,
            first_name="Student",
            username="student",
        )
    )
    async with session_factory() as session:
        session.add(
            StaffUser(
                login="curator",
                display_name="Curator",
                telegram_user_id=555,
                is_active=True,
            )
        )
        session.add(
            Course(
                slug="practice",
                title="PRACTICE 2026",
                description=None,
                audience=CourseAudience.TELEGRAM,
                is_active=True,
            )
        )
        await session.commit()

    api_calls: list[tuple[str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", maxsplit=1)[-1]
        payload = json.loads(request.content)
        api_calls.append((method, payload))
        if method == "sendMessage":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "message_id": len(api_calls),
                        "date": 1_700_000_002,
                        "chat": {"id": payload["chat_id"], "type": "private"},
                        "text": payload["text"],
                    },
                },
            )
        return httpx.Response(200, json={"ok": True, "result": True})

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            SubmissionService(session_factory),
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
            StudentAccessService(session_factory),
        )
        assert await router.handle(curator_message("🎓 Выдать доступ")) is True
        student_picker = next(
            payload for method, payload in api_calls if method == "sendMessage"
        )
        student_callback = student_picker["reply_markup"]["inline_keyboard"][0][0][
            "callback_data"
        ]

        assert await router.handle(grant_callback(student_callback)) is True
        course_picker = [
            payload for method, payload in api_calls if method == "sendMessage"
        ][1]
        course_callback = course_picker["reply_markup"]["inline_keyboard"][0][0][
            "callback_data"
        ]

        assert await router.handle(grant_callback(course_callback)) is True
        assert await router.handle(grant_callback("grant:confirm")) is True

    async with session_factory() as session:
        enrollment = await session.scalar(
            select(Enrollment).where(Enrollment.student_id == registration.student_id)
        )

    assert enrollment is not None
    assert enrollment.status is EnrollmentStatus.ACTIVE
    assert enrollment.current_lesson_position == 1
    assert enrollment.access_notified_at is None
    assert any(method == "answerCallbackQuery" for method, _ in api_calls)
    assert any(
        method == "sendMessage" and "Доступ выдан" in str(payload["text"])
        for method, payload in api_calls
    )
