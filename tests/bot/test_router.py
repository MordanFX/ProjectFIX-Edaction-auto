"""Student command routing tests."""

import json

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.bot.api import TelegramBotClient
from course_platform.bot.notifications import TelegramFeedbackDispatcher
from course_platform.bot.router import MessageRouter
from course_platform.bot.types import TelegramUpdate
from course_platform.bot.ui import curator_keyboard, stage_keyboard
from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import (
    Enrollment,
    Feedback,
    FeedbackAttachment,
    Lesson,
    LessonMaterial,
    StaffUser,
    Student,
    Submission,
    SubmissionAttachment,
    TelegramQuestion,
)
from course_platform.models.enums import (
    AttachmentKind,
    EnrollmentStatus,
    FeedbackVerdict,
    SubmissionStatus,
    VideoSource,
)
from course_platform.services.admin_dashboard import AdminDashboardService
from course_platform.services.learning import LearningService
from course_platform.services.notifications import FeedbackNotificationService
from course_platform.services.progression import ProgressionService
from course_platform.services.reviews import ReviewService
from course_platform.services.students import (
    StudentRegistration,
    StudentService,
    StudentStage,
)
from course_platform.services.submissions import HomeworkAttachment, SubmissionService


def message_update(
    text: str = "/start payload",
    *,
    chat_type: str = "private",
) -> TelegramUpdate:
    return TelegramUpdate.model_validate(
        {
            "update_id": 10,
            "message": {
                "message_id": 2,
                "date": 1_700_000_000,
                "chat": {"id": 555, "type": chat_type},
                "from": {
                    "id": 555,
                    "is_bot": False,
                    "first_name": "Alex",
                    "username": "alex_student",
                },
                "text": text,
            },
        }
    )


def photo_update() -> TelegramUpdate:
    return TelegramUpdate.model_validate(
        {
            "update_id": 11,
            "message": {
                "message_id": 4,
                "date": 1_700_000_002,
                "chat": {"id": 555, "type": "private"},
                "from": {
                    "id": 555,
                    "is_bot": False,
                    "first_name": "Alex",
                },
                "caption": "Photo result",
                "photo": [
                    {
                        "file_id": "small-photo",
                        "file_unique_id": "photo-unique",
                        "width": 90,
                        "height": 90,
                        "file_size": 100,
                    },
                    {
                        "file_id": "large-photo",
                        "file_unique_id": "photo-unique",
                        "width": 1280,
                        "height": 720,
                        "file_size": 5000,
                    },
                ],
            },
        }
    )


def video_update() -> TelegramUpdate:
    return TelegramUpdate.model_validate(
        {
            "update_id": 12,
            "message": {
                "message_id": 6,
                "date": 1_700_000_004,
                "chat": {"id": 555, "type": "private"},
                "from": {
                    "id": 555,
                    "is_bot": False,
                    "first_name": "Alex",
                },
                "caption": "OBS screen recording",
                "video": {
                    "file_id": "obs-video-id",
                    "file_unique_id": "obs-video-unique-id",
                    "width": 1920,
                    "height": 1080,
                    "duration": 125,
                    "file_name": "recording.mp4",
                    "mime_type": "video/mp4",
                    "file_size": 25_000_000,
                },
            },
        }
    )


def review_callback_update(callback_data: str) -> TelegramUpdate:
    return TelegramUpdate.model_validate(
        {
            "update_id": 13,
            "callback_query": {
                "id": "callback-1",
                "from": {
                    "id": 555,
                    "is_bot": False,
                    "first_name": "Alex",
                },
                "message": {
                    "message_id": 20,
                    "date": 1_700_000_006,
                    "chat": {"id": 555, "type": "private"},
                    "text": "Review card",
                },
                "data": callback_data,
            },
        }
    )


async def test_start_registers_student_and_replies(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sent_messages: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        sent_messages.append(payload)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 3,
                    "date": 1_700_000_001,
                    "chat": {"id": 555, "type": "private"},
                    "text": payload["text"],
                },
            },
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            StudentService(session_factory),
            LearningService(session_factory),
            SubmissionService(session_factory),
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        handled = await router.handle(message_update())

    async with session_factory() as session:
        student = await session.scalar(select(Student))

    assert handled is True
    assert student is not None
    assert student.telegram_user_id == 555
    assert sent_messages[0]["chat_id"] == 555
    assert sent_messages[0]["parse_mode"] == "HTML"
    assert sent_messages[0]["reply_markup"] == {
        "keyboard": [
            [{"text": "📘 Текущий урок"}, {"text": "📊 Мой прогресс"}],
            [{"text": "📚 Программа курса"}, {"text": "🗂 Мои разборы"}],
            [{"text": "⚙️ Настройки"}, {"text": "ℹ️ Помощь"}],
        ],
        "resize_keyboard": True,
        "input_field_placeholder": "PROJECT FIX · выбери действие",
    }
    assert "PROJECT FIX / ACCESS" in str(sent_messages[0]["text"])


async def test_student_edits_settings_from_inline_menu(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
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
                        "message_id": 20,
                        "date": 1_700_000_001,
                        "chat": {"id": 555, "type": "private"},
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
        )
        await router.handle(message_update("⚙️ Настройки"))
        await router.handle(review_callback_update("settings:timezone"))
        await router.handle(review_callback_update("settings:timezone:Europe/Warsaw"))
        await router.handle(review_callback_update("settings:quiet:23:8"))
        await router.handle(review_callback_update("settings:reminders:0"))

    journey = await students.get_journey(555)
    settings_message = next(payload for method, payload in api_calls if method == "sendMessage")

    assert "Изменение этих параметров добавим" not in str(settings_message["text"])
    assert "с 22:00 до 09:00" in str(settings_message["text"])
    assert settings_message["reply_markup"]["inline_keyboard"][0][0]["text"] == (
        "🌍 Часовой пояс"
    )
    assert journey is not None
    assert journey.timezone == "Europe/Warsaw"
    assert (journey.quiet_hours_start, journey.quiet_hours_end) == (23, 8)
    assert journey.reminders_enabled is False
    assert any(
        method == "editMessageText" and "Выбери свой часовой пояс" in str(payload["text"])
        for method, payload in api_calls
    )
    assert any(method == "answerCallbackQuery" for method, _ in api_calls)


async def test_lesson_returns_only_the_current_demo_lesson(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    sent_messages: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        sent_messages.append(payload)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 3,
                    "date": 1_700_000_001,
                    "chat": {"id": 555, "type": "private"},
                    "text": payload["text"],
                },
            },
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            SubmissionService(session_factory),
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        handled = await router.handle(message_update("/lesson"))

    assert handled is True
    assert "УРОК 1 ИЗ 3" in str(sent_messages[0]["text"])
    assert "Знакомство с курсом" in str(sent_messages[0]["text"])
    assert "Домашнее задание" in str(sent_messages[0]["text"])
    callback_data = sent_messages[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    assert callback_data.startswith("lesson:viewed:")


async def test_student_can_reopen_an_already_reached_lesson(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    async with session_factory() as session:
        enrollment = await session.scalar(select(Enrollment))
        first_lesson = await session.scalar(select(Lesson).order_by(Lesson.position))
        assert enrollment is not None
        assert first_lesson is not None
        enrollment.current_lesson_position = 2
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
                        "date": 1_700_000_001,
                        "chat": {"id": 555, "type": "private"},
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
        )
        await router.handle(message_update("📖 Все уроки"))
        await router.handle(review_callback_update(f"lesson:open:{first_lesson.id}"))

    catalog = next(
        payload
        for method, payload in api_calls
        if method == "sendMessage" and "Выбери текущий" in str(payload["text"])
    )
    buttons = catalog["reply_markup"]["inline_keyboard"]
    assert buttons[0][0]["callback_data"] == f"lesson:open:{first_lesson.id}"
    assert buttons[2][0]["callback_data"].startswith("lesson:locked:")
    assert any(
        method == "sendMessage" and "УРОК 1 ИЗ 3" in str(payload["text"])
        for method, payload in api_calls
    )


async def test_telegram_channel_lesson_copies_video_before_card(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    async with session_factory() as session:
        lesson = await session.scalar(select(Lesson).order_by(Lesson.position))
        assert lesson is not None
        lesson.video_source = VideoSource.TELEGRAM_CHANNEL
        lesson.video_reference = "-1001234567890:42"
        await session.commit()

    api_calls: list[tuple[str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", maxsplit=1)[-1]
        payload = json.loads(request.content)
        api_calls.append((method, payload))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": len(api_calls),
                    "date": 1_700_000_001,
                    "chat": {"id": 555, "type": "private"},
                    "text": payload.get("text"),
                },
            },
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            SubmissionService(session_factory),
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        await router.handle(message_update("/lesson"))

    copied = next(payload for method, payload in api_calls if method == "copyMessage")
    assert copied["from_chat_id"] == -1001234567890
    assert copied["message_id"] == 42
    assert any(method == "sendMessage" for method, _ in api_calls)


async def test_multi_video_lesson_opens_workspace_then_selected_material(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    async with session_factory() as session:
        lesson = await session.scalar(select(Lesson).order_by(Lesson.position))
        assert lesson is not None
        session.add_all(
            [
                LessonMaterial(
                    lesson_id=lesson.id,
                    position=1,
                    title="Market Logic",
                    video_source=VideoSource.EXTERNAL_URL,
                    video_reference="https://vimeo.com/1",
                ),
                LessonMaterial(
                    lesson_id=lesson.id,
                    position=2,
                    title="QnA",
                    video_source=VideoSource.EXTERNAL_URL,
                    video_reference="https://vimeo.com/2",
                ),
            ]
        )
        lesson_id = lesson.id
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
                        "date": 1_700_000_001,
                        "chat": {"id": 555, "type": "private"},
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
        )
        await router.handle(message_update("/lesson"))
        await router.handle(review_callback_update(f"lesson:viewed:{lesson_id}"))
        await router.handle(review_callback_update(f"material:{lesson_id}:2"))
        await router.handle(review_callback_update(f"matview:{lesson_id}:2"))
        await router.handle(review_callback_update(f"template:{lesson_id}"))

    workspace = next(
        payload
        for method, payload in api_calls
        if method == "sendMessage" and "Урок 1 из" in str(payload["text"])
    )
    assert workspace["reply_markup"]["inline_keyboard"][1][0]["callback_data"] == (
        f"material:{lesson_id}:2"
    )
    assert any(
        method == "answerCallbackQuery"
        and payload.get("show_alert") is True
        and "0/2" in str(payload.get("text"))
        for method, payload in api_calls
    )
    assert any(
        method == "sendMessage" and "Материал 2 из 2" in str(payload.get("text"))
        for method, payload in api_calls
    )
    assert any(
        method == "sendMessage" and "1/2" in str(payload.get("text"))
        for method, payload in api_calls
    )
    assert any(
        method == "sendMessage" and "ANSWER TEMPLATE" in str(payload.get("text"))
        for method, payload in api_calls
    )


async def test_viewed_callback_updates_lesson_and_unlocks_homework(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
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
                        "date": 1_700_000_001,
                        "chat": {"id": 555, "type": "private"},
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
        )
        await router.handle(message_update("/lesson"))
        lesson_message = next(payload for method, payload in api_calls if method == "sendMessage")
        callback_data = lesson_message["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        await router.handle(review_callback_update(callback_data))
        await router.handle(message_update("📤 Сдать ДЗ"))

    assert any(method == "answerCallbackQuery" for method, _ in api_calls)
    edited_markup = next(
        payload
        for method, payload in api_calls
        if method == "editMessageReplyMarkup"
    )
    edited_labels = {
        button["text"]
        for row in edited_markup["reply_markup"]["inline_keyboard"]
        for button in row
    }
    assert "📝 Домашнее задание" in edited_labels
    assert any(
        method == "sendMessage" and "МАТЕРИАЛЫ ОТМЕЧЕНЫ" in str(payload["text"])
        for method, payload in api_calls
    )
    viewed_message = next(
        payload
        for method, payload in api_calls
        if method == "sendMessage" and "МАТЕРИАЛЫ ОТМЕЧЕНЫ" in str(payload["text"])
    )
    inline_buttons = [
        button
        for row in viewed_message["reply_markup"]["inline_keyboard"]
        for button in row
    ]
    assert inline_buttons[0]["text"] == "📝 Открыть домашнее задание"
    assert inline_buttons[0]["callback_data"].startswith("homework:")
    assert "СДАЧА ДОМАШНЕГО ЗАДАНИЯ" in str(api_calls[-1][1]["text"])


async def test_submit_button_and_next_text_create_submission(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(555)
    sent_messages: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        sent_messages.append(payload)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": len(sent_messages),
                    "date": 1_700_000_001,
                    "chat": {"id": 555, "type": "private"},
                    "text": payload["text"],
                },
            },
        )

    submissions = SubmissionService(session_factory)
    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            submissions,
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        await router.handle(message_update("📤 Сдать ДЗ"))
        await router.handle(message_update("Мой ответ на первое задание"))

    async with session_factory() as session:
        submission = await session.scalar(select(Submission))

    assert "СДАЧА ДОМАШНЕГО ЗАДАНИЯ" in str(sent_messages[0]["text"])
    assert "ДОМАШНЕЕ ЗАДАНИЕ ОТПРАВЛЕНО" in str(sent_messages[1]["text"])
    assert submission is not None
    assert submission.text_body == "Мой ответ на первое задание"


async def test_student_can_ask_curator_from_homework_card(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    async with session_factory() as session:
        lesson = await session.scalar(select(Lesson).order_by(Lesson.position))
        reviewer = await session.scalar(select(StaffUser))
        assert lesson is not None
        assert reviewer is not None
        lesson_id = lesson.id
        reviewer.telegram_user_id = 777
        await session.commit()
    await ProgressionService(session_factory).mark_current_viewed(555)

    api_calls: list[tuple[str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", maxsplit=1)[-1]
        payload = json.loads(request.content)
        api_calls.append((method, payload))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": len(api_calls),
                    "date": 1_700_000_001,
                    "chat": {"id": payload.get("chat_id", 555), "type": "private"},
                    "text": payload.get("text", ""),
                },
            },
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            SubmissionService(session_factory),
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        await router.handle(review_callback_update(f"ask_curator:{lesson_id}"))
        await router.handle(message_update("Не понимаю, как оформить схему в Notion."))

    assert any(
        method == "sendMessage"
        and payload.get("chat_id") == 555
        and "ВОПРОС КУРАТОРУ" in str(payload.get("text"))
        for method, payload in api_calls
    )
    assert any(
        method == "sendMessage"
        and payload.get("chat_id") == 777
        and "ВОПРОС ОТ УЧЕНИКА" in str(payload.get("text"))
        and "Notion" in str(payload.get("text"))
        for method, payload in api_calls
    )


async def test_photo_while_awaiting_question_is_saved_as_question_not_homework(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    async with session_factory() as session:
        lesson = await session.scalar(select(Lesson).order_by(Lesson.position))
        reviewer = await session.scalar(select(StaffUser))
        assert lesson is not None
        assert reviewer is not None
        lesson_id = lesson.id
        reviewer.telegram_user_id = 777
        await session.commit()
    await ProgressionService(session_factory).mark_current_viewed(555)

    api_calls: list[tuple[str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", maxsplit=1)[-1]
        payload = json.loads(request.content)
        api_calls.append((method, payload))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": len(api_calls),
                    "date": 1_700_000_001,
                    "chat": {"id": payload.get("chat_id", 555), "type": "private"},
                    "text": payload.get("text", ""),
                },
            },
        )

    submissions = SubmissionService(session_factory)
    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            submissions,
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        await router.handle(review_callback_update(f"ask_curator:{lesson_id}"))
        await router.handle(photo_update())

    async with session_factory() as session:
        submission = await session.scalar(select(Submission))
        question = await session.scalar(select(TelegramQuestion))

    assert submission is None
    assert question is not None
    assert question.attachment_kind is not None
    assert question.text_body == "Photo result"

    assert any(
        method == "sendMessage"
        and payload.get("chat_id") == 555
        and "Вопрос отправлен куратору" in str(payload.get("text"))
        for method, payload in api_calls
    )
    assert any(
        method == "sendMessage"
        and payload.get("chat_id") == 777
        and "ВОПРОС ОТ УЧЕНИКА" in str(payload.get("text"))
        for method, payload in api_calls
    )
    assert any(
        method == "copyMessage" and payload.get("chat_id") == 777
        for method, payload in api_calls
    )


async def test_photo_submission_uses_largest_telegram_size(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(555)

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 5,
                    "date": 1_700_000_003,
                    "chat": {"id": 555, "type": "private"},
                    "text": payload["text"],
                },
            },
        )

    submissions = SubmissionService(session_factory)
    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            submissions,
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        await router.handle(message_update("📤 Сдать ДЗ"))
        await router.handle(photo_update())

    async with session_factory() as session:
        attachment = await session.scalar(select(SubmissionAttachment))

    assert attachment is not None
    assert attachment.telegram_file_id == "large-photo"
    assert attachment.mime_type == "image/jpeg"


async def test_obs_mp4_submission_preserves_video_and_source_message_metadata(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(555)

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 7,
                    "date": 1_700_000_005,
                    "chat": {"id": 555, "type": "private"},
                    "text": payload["text"],
                },
            },
        )

    submissions = SubmissionService(session_factory)
    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            submissions,
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        await router.handle(message_update("📤 Сдать ДЗ"))
        await router.handle(video_update())

    async with session_factory() as session:
        attachment = await session.scalar(select(SubmissionAttachment))

    assert attachment is not None
    assert attachment.kind.value == "video"
    assert attachment.telegram_file_id == "obs-video-id"
    assert attachment.source_chat_id == 555
    assert attachment.source_message_id == 6
    assert attachment.duration_seconds == 125
    assert (attachment.width, attachment.height) == (1920, 1080)


async def test_curator_queue_and_accept_callback_open_next_lesson(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(555)
    submissions = SubmissionService(session_factory)
    await submissions.begin(555)
    await submissions.submit_attachment(
        555,
        HomeworkAttachment(
            kind=AttachmentKind.VIDEO,
            telegram_file_id="curator-video",
            telegram_file_unique_id="curator-video-unique",
            source_chat_id=555,
            source_message_id=66,
            mime_type="video/mp4",
        ),
    )
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
                        "date": 1_700_000_007,
                        "chat": {"id": payload["chat_id"], "type": "private"},
                        "text": payload["text"],
                    },
                },
            )
        return httpx.Response(200, json={"ok": True, "result": True})

    reviews = ReviewService(session_factory)
    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            submissions,
            reviews,
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        await router.handle(message_update("/reviews"))
        review_card = next(payload for method, payload in api_calls if method == "sendMessage")
        callback_data = review_card["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        await router.handle(review_callback_update(callback_data))
        await router.handle(message_update("Отличная работа, всё выполнено правильно."))
        await TelegramFeedbackDispatcher(
            api,
            FeedbackNotificationService(session_factory),
        ).dispatch_pending()
        await router.handle(message_update("🗂 Проверенные"))
        await router.handle(message_update("📊 Сводка куратора"))
        await router.handle(message_update("👥 Ученики"))

    async with session_factory() as session:
        submission = await session.scalar(select(Submission))
        enrollment = await session.scalar(select(Enrollment))

    assert submission is not None
    assert submission.status is SubmissionStatus.ACCEPTED
    assert enrollment is not None
    assert enrollment.current_lesson_position == 2
    assert any(method == "answerCallbackQuery" for method, _ in api_calls)
    assert any(method == "editMessageReplyMarkup" for method, _ in api_calls)
    assert any(
        method == "copyMessage"
        and payload["from_chat_id"] == 555
        and payload["message_id"] == 66
        for method, payload in api_calls
    )
    assert any(
        method == "sendMessage" and "КОММЕНТАРИЙ УЧЕНИКУ" in str(payload["text"])
        for method, payload in api_calls
    )
    assert any(
        method == "sendMessage" and "ДЗ принято" in str(payload["text"])
        for method, payload in api_calls
    )
    assert any(
        method == "sendMessage"
        and "ПОСЛЕДНИЕ ПРОВЕРЕННЫЕ РАБОТЫ" in str(payload["text"])
        for method, payload in api_calls
    )
    assert any(
        method == "sendMessage" and "✅ принято" in str(payload["text"])
        for method, payload in api_calls
    )
    assert any(
        method == "sendMessage" and "СВОДКА КУРАТОРА" in str(payload["text"])
        for method, payload in api_calls
    )
    assert any(
        method == "sendMessage" and "УЧЕНИКИ" in str(payload["text"])
        for method, payload in api_calls
    )


async def test_group_message_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with TelegramBotClient("token", transport=httpx.MockTransport(lambda _: None)) as api:
        router = MessageRouter(
            api,
            StudentService(session_factory),
            LearningService(session_factory),
            SubmissionService(session_factory),
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        handled = await router.handle(message_update(chat_type="group"))

    assert handled is False


def test_help_and_next_step_placeholders_are_clear() -> None:
    help_text = MessageRouter._help_text(None, is_reviewer=False)
    next_text = MessageRouter._next_step_text(None)

    assert "КАК РАБОТАЕТ ОБУЧЕНИЕ" in help_text
    assert "/lesson" in help_text
    assert "после назначения курса" in next_text
    curator_buttons = {
        button["text"]
        for row in curator_keyboard()["keyboard"]
        for button in row
    }
    assert curator_buttons == {
        "📥 Очередь проверки",
        "🗂 Проверенные",
        "📊 Сводка куратора",
        "👥 Ученики",
        "🎓 Выдать доступ",
        "🎓 Режим ученика",
        "🎬 Видео уроков",
    }
    assert MessageRouter._extract_command("🧑‍💼 Режим куратора") == "/curator_mode"
    assert MessageRouter._extract_command("🎓 Режим ученика") == "/student_mode"
    assert MessageRouter._extract_command("📚 О курсе") == "/course"
    assert MessageRouter._extract_command("📖 Все уроки") == "/lessons"


async def test_external_vimeo_lesson_links_use_player_urls(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    async with session_factory() as session:
        lesson = await session.scalar(select(Lesson).order_by(Lesson.position))
        assert lesson is not None
        lesson.video_source = VideoSource.EXTERNAL_URL
        lesson.video_reference = "https://vimeo.com/1196958528?share=copy&fl=sv&fe=ci"
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
                        "date": 1_700_000_001,
                        "chat": {"id": 555, "type": "private"},
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
        )
        await router.handle(message_update("/lesson"))
        lesson_message = next(
            payload for method, payload in api_calls if method == "sendMessage"
        )
        viewed_callback = next(
            button["callback_data"]
            for row in lesson_message["reply_markup"]["inline_keyboard"]
            for button in row
            if "callback_data" in button
        )
        await router.handle(review_callback_update(viewed_callback))

    payload = lesson_message
    assert 'href="https://player.vimeo.com/video/1196958528"' in str(payload["text"])
    assert "vimeo.com/1196958528?share=copy" not in str(payload["text"])
    url_buttons = [
        button["url"]
        for row in payload["reply_markup"]["inline_keyboard"]
        for button in row
        if "url" in button
    ]
    assert url_buttons == ["https://player.vimeo.com/video/1196958528"]
    assert (
        payload["link_preview_options"]["url"]
        == "https://player.vimeo.com/video/1196958528"
    )

    # После подтверждения просмотра карточка сохраняет кнопку пересмотра.
    edited_markup = next(
        payload
        for method, payload in api_calls
        if method == "editMessageReplyMarkup"
    )
    edited_buttons = [
        button
        for row in edited_markup["reply_markup"]["inline_keyboard"]
        for button in row
    ]
    assert {
        "text": "▶ Смотреть урок повторно",
        "url": "https://player.vimeo.com/video/1196958528",
    } in edited_buttons


async def test_lesson_command_reports_completed_lesson_waiting_for_next(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)

    progression = ProgressionService(session_factory)
    submissions = SubmissionService(session_factory)
    reviews = ReviewService(session_factory)
    await progression.mark_current_viewed(555)
    await submissions.begin(555)
    await submissions.submit_text(555, "Ответ на первый урок")
    async with session_factory() as session:
        submission_id = await session.scalar(select(Submission.id).limit(1))
    assert submission_id is not None
    await reviews.review(
        submission_id=submission_id,
        reviewer_telegram_user_id=555,
        verdict=FeedbackVerdict.ACCEPTED,
        message="Принято",
    )
    async with session_factory() as session:
        enrollment = await session.scalar(select(Enrollment))
        assert enrollment is not None
        enrollment.current_lesson_position = 1
        await session.commit()

    sent_messages: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        sent_messages.append(payload)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 3,
                    "date": 1_700_000_001,
                    "chat": {"id": 555, "type": "private"},
                    "text": payload.get("text", ""),
                },
            },
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            SubmissionService(session_factory),
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        await router.handle(message_update("/lesson"))

    text = str(sent_messages[0]["text"])
    assert "Текущий урок пройден" in text
    assert "зарегистрируйся" not in text


async def test_marking_last_material_finishes_lesson_without_extra_button(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    async with session_factory() as session:
        lesson = await session.scalar(select(Lesson).order_by(Lesson.position))
        assert lesson is not None
        session.add_all(
            [
                LessonMaterial(
                    lesson_id=lesson.id,
                    position=1,
                    title="Market Logic",
                    video_source=VideoSource.EXTERNAL_URL,
                    video_reference="https://vimeo.com/1",
                ),
                LessonMaterial(
                    lesson_id=lesson.id,
                    position=2,
                    title="QnA",
                    video_source=VideoSource.EXTERNAL_URL,
                    video_reference="https://vimeo.com/2",
                ),
            ]
        )
        lesson_id = lesson.id
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
                        "date": 1_700_000_001,
                        "chat": {"id": 555, "type": "private"},
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
        )
        await router.handle(message_update("/lesson"))
        await router.handle(review_callback_update(f"matview:{lesson_id}:1"))
        await router.handle(review_callback_update(f"matview:{lesson_id}:2"))

    # Первая карточка (0/2) больше не показывает кнопку подтверждения.
    first_workspace = next(
        payload
        for method, payload in api_calls
        if method == "sendMessage" and "0/2" in str(payload["text"])
    )
    first_labels = {
        button["text"]
        for row in first_workspace["reply_markup"]["inline_keyboard"]
        for button in row
    }
    assert "✅ Я посмотрел все материалы" not in first_labels

    # После отметки последнего материала урок завершается сам: карточка
    # показывает шаг сдачи ДЗ и без кнопки подтверждения.
    final_workspace = next(
        payload
        for method, payload in api_calls
        if method == "sendMessage" and "Шаг 3" in str(payload["text"])
    )
    final_labels = {
        button["text"]
        for row in final_workspace["reply_markup"]["inline_keyboard"]
        for button in row
    }
    assert "✅ Я посмотрел все материалы" not in final_labels
    assert "📝 Домашнее задание" in final_labels


async def test_album_second_photo_joins_submitted_homework(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(555)

    api_calls: list[tuple[str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", maxsplit=1)[-1]
        payload = json.loads(request.content)
        api_calls.append((method, payload))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": len(api_calls),
                    "date": 1_700_000_003,
                    "chat": {"id": 555, "type": "private"},
                    "text": payload.get("text", ""),
                },
            },
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            SubmissionService(session_factory),
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        await router.handle(message_update("📤 Сдать ДЗ"))
        await router.handle(photo_update())
        await router.handle(photo_update())

    async with session_factory() as session:
        attachments = (await session.scalars(select(SubmissionAttachment))).all()
        submissions_count = len((await session.scalars(select(Submission))).all())

    assert submissions_count == 1
    assert len(attachments) == 2
    assert any(
        method == "sendMessage"
        and "Файл добавлен к отправленной работе" in str(payload.get("text"))
        for method, payload in api_calls
    )
    assert not any(
        method == "sendMessage" and "Не понял сообщение" in str(payload.get("text"))
        for method, payload in api_calls
    )


async def test_revision_answer_is_accepted_without_pressing_the_button(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(555)
    submissions = SubmissionService(session_factory)
    reviews = ReviewService(session_factory)
    await submissions.begin(555)
    await submissions.submit_text(555, "Первая версия")
    async with session_factory() as session:
        first_id = await session.scalar(select(Submission.id))
    assert first_id is not None
    await reviews.review(
        submission_id=first_id,
        reviewer_telegram_user_id=555,
        verdict=FeedbackVerdict.REVISION_REQUESTED,
        message="Доработай",
    )

    api_calls: list[tuple[str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", maxsplit=1)[-1]
        payload = json.loads(request.content)
        api_calls.append((method, payload))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": len(api_calls),
                    "date": 1_700_000_003,
                    "chat": {"id": 555, "type": "private"},
                    "text": payload.get("text", ""),
                },
            },
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            submissions,
            reviews,
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        # Текст доработки без кнопки «Отправить доработку».
        await router.handle(message_update("готово линк на ноушен"))

        async with session_factory() as session:
            second_id = await session.scalar(
                select(Submission.id).where(Submission.attempt_number == 2)
            )
        assert second_id is not None
        await reviews.review(
            submission_id=second_id,
            reviewer_telegram_user_id=555,
            verdict=FeedbackVerdict.REVISION_REQUESTED,
            message="Ещё раз",
        )
        # Фото доработки тоже без кнопки.
        await router.handle(photo_update())

    async with session_factory() as session:
        attempts = sorted(
            (await session.scalars(select(Submission.attempt_number))).all()
        )

    assert attempts == [1, 2, 3]
    receipts = [
        payload
        for method, payload in api_calls
        if method == "sendMessage"
        and "ДОМАШНЕЕ ЗАДАНИЕ ОТПРАВЛЕНО" in str(payload.get("text"))
    ]
    assert len(receipts) == 2
    assert not any(
        method == "sendMessage" and "Не понял сообщение" in str(payload.get("text"))
        for method, payload in api_calls
    )


async def test_journal_delivers_curator_feedback_attachments(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(555)
    submissions = SubmissionService(session_factory)
    reviews = ReviewService(session_factory)
    await submissions.begin(555)
    await submissions.submit_text(555, "Моя работа")
    async with session_factory() as session:
        submission_id = await session.scalar(select(Submission.id))
    assert submission_id is not None
    await reviews.review(
        submission_id=submission_id,
        reviewer_telegram_user_id=555,
        verdict=FeedbackVerdict.ACCEPTED,
        message="Смотри разметку на фото",
    )
    async with session_factory() as session:
        feedback_id = await session.scalar(select(Feedback.id))
        assert feedback_id is not None
        session.add(
            FeedbackAttachment(
                feedback_id=feedback_id,
                kind=AttachmentKind.PHOTO,
                source_chat_id=999,
                source_message_id=42,
            )
        )
        await session.commit()

    api_calls: list[tuple[str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", maxsplit=1)[-1]
        payload = json.loads(request.content)
        api_calls.append((method, payload))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": len(api_calls),
                    "date": 1_700_000_003,
                    "chat": {"id": 555, "type": "private"},
                    "text": payload.get("text", ""),
                },
            },
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            submissions,
            reviews,
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        await router.handle(message_update("🗂 Мои разборы"))

    assert any(
        method == "sendMessage"
        and "Смотри разметку на фото" in str(payload.get("text"))
        for method, payload in api_calls
    )
    assert any(
        method == "copyMessage"
        and payload.get("from_chat_id") == 999
        and payload.get("message_id") == 42
        for method, payload in api_calls
    )


def test_completed_stage_keyboard_offers_post_course_section() -> None:
    labels = {
        button["text"]
        for row in stage_keyboard(StudentStage.COURSE_COMPLETED)["keyboard"]
        for button in row
    }
    assert "🎯 Pre session + Backtest" in labels


async def test_post_course_section_unlocks_after_completion(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    students = StudentService(session_factory)
    await students.register(StudentRegistration(telegram_user_id=555, first_name="Alex"))
    await seed_demo_data(session_factory)

    api_calls: list[tuple[str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", maxsplit=1)[-1]
        payload = json.loads(request.content)
        api_calls.append((method, payload))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": len(api_calls),
                    "date": 1_700_000_003,
                    "chat": {"id": 555, "type": "private"},
                    "text": payload.get("text", ""),
                },
            },
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as api:
        router = MessageRouter(
            api,
            students,
            LearningService(session_factory),
            SubmissionService(session_factory),
            ReviewService(session_factory),
            ProgressionService(session_factory),
            AdminDashboardService(session_factory),
        )
        # Курс не завершён — раздел закрыт.
        await router.handle(message_update("🎯 Pre session + Backtest"))

        async with session_factory() as session:
            enrollment = await session.scalar(select(Enrollment))
            assert enrollment is not None
            enrollment.status = EnrollmentStatus.COMPLETED
            await session.commit()

        await router.handle(message_update("🎯 Pre session + Backtest"))

    locked = [
        payload
        for method, payload in api_calls
        if method == "sendMessage" and "Раздел откроется" in str(payload.get("text"))
    ]
    assert len(locked) == 1
    opened = next(
        payload
        for method, payload in api_calls
        if method == "sendMessage"
        and "PRE SESSION + BACKTEST" in str(payload.get("text"))
    )
    urls = [
        button["url"]
        for row in opened["reply_markup"]["inline_keyboard"]
        for button in row
    ]
    assert urls == [
        "https://player.vimeo.com/video/1209755707",
        "https://player.vimeo.com/video/1210090244",
        "https://player.vimeo.com/video/1208160612",
    ]
