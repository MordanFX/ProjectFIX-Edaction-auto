"""Discord slash-command identity gate tests."""

from dataclasses import dataclass, field
from uuid import UUID

from course_platform.discord.application import DiscordApplication
from course_platform.services.discord_lesson_deliveries import DiscordLessonDeliveryItem
from course_platform.services.submissions import SubmissionReceipt


class FakeAPI:
    def __init__(self) -> None:
        self.responses: list[str] = []
        self.followups: list[str] = []
        self.channel_messages: list[tuple[int, dict[str, object]]] = []
        self.deferred_updates: list[tuple[str, str]] = []
        self.edited_messages: list[tuple[int, int, dict[str, object]]] = []

    async def respond_interaction(self, interaction_id, token, content) -> None:
        self.responses.append(content)

    async def followup(self, application_id, token, content) -> None:
        self.followups.append(content)

    async def defer_message_update(self, interaction_id, token) -> None:
        self.deferred_updates.append((interaction_id, token))

    async def channel_message(self, channel_id, message_id):
        return {
            "id": str(message_id),
            "author": {"id": "200"},
            "content": "My homework",
            "attachments": [],
        }

    async def edit_channel_message(self, channel_id, message_id, payload):
        self.edited_messages.append((channel_id, message_id, payload))
        return {"id": str(message_id), **payload}

    async def send_channel_message(self, channel_id, payload):
        self.channel_messages.append((channel_id, payload))
        return {"id": "300"}


@dataclass
class FakeParticipantService:
    activities: list[dict[str, object]] = field(default_factory=list)
    departures: list[dict[str, object]] = field(default_factory=list)
    activity_result: bool = True

    async def get_or_create(self, **kwargs):
        return object()

    async def record_activity(self, **kwargs):
        self.activities.append(kwargs)
        return self.activity_result

    async def mark_left(self, **kwargs):
        self.departures.append(kwargs)
        return True


class FakeSubmissionService:
    async def can_offer(self, *, guild_id: int, discord_user_id: int, channel_id: int):
        return guild_id == 100 and discord_user_id == 200 and channel_id == 300

    async def submit_message(self, **kwargs):
        return SubmissionReceipt(
            lesson_position=1,
            lesson_title="First lesson",
            attempt_number=1,
        )


class FakeQuestionService:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.resolved_from_replies: list[dict[str, object]] = []

    async def create_from_message(self, **kwargs):
        self.created.append(kwargs)
        return object()

    async def resolve_latest_open_in_channel(self, **kwargs):
        self.resolved_from_replies.append(kwargs)
        return object()


class FakeLessonDeliveryService:
    def __init__(self) -> None:
        self.sent: list[tuple[UUID, int]] = []

    async def list_pending(self):
        return [
            DiscordLessonDeliveryItem(
                delivery_id=UUID("00000000-0000-0000-0000-000000000001"),
                channel_id=300,
                discord_user_id=200,
                content="New homework",
            )
        ]

    async def mark_sent(self, delivery_id, message_id):
        self.sent.append((delivery_id, message_id))

    async def mark_failed(self, delivery_id, error):
        raise AssertionError(error)


def interaction(name: str, options: list[dict[str, object]] | None = None):
    return {
        "id": "1",
        "token": "token",
        "application_id": "app",
        "member": {"user": {"id": "200", "username": "alex"}},
        "data": {"name": name, "options": options or []},
    }


async def test_student_message_gets_explicit_submission_button() -> None:
    api = FakeAPI()
    participants = FakeParticipantService()
    app = DiscordApplication(
        api,  # type: ignore[arg-type]
        "token",
        100,
        object(),  # type: ignore[arg-type]
        participants,  # type: ignore[arg-type]
        FakeSubmissionService(),  # type: ignore[arg-type]
        message_content_enabled=True,
    )

    await app._handle_message_create(  # noqa: SLF001
        {
            "id": "400",
            "guild_id": "100",
            "channel_id": "300",
            "author": {"id": "200", "bot": False},
            "member": {"nick": "Alex", "joined_at": "2026-01-02T03:04:05Z"},
            "content": "My homework",
            "attachments": [],
        }
    )

    assert api.channel_messages[0][0] == 300
    buttons = api.channel_messages[0][1]["components"][0]["components"]  # type: ignore[index]
    assert buttons[0]["custom_id"] == "submit_discord:400"
    assert buttons[0]["label"] == "Отправить на проверку"
    assert buttons[1]["custom_id"] == "ask_curator:400"
    assert buttons[1]["label"] == "Уточнить вопрос"
    assert participants.activities[0]["display_name"] == "Alex"
    assert participants.activities[0]["channel_id"] == 300


async def test_member_events_refresh_profile_and_mark_departure() -> None:
    participants = FakeParticipantService()
    app = DiscordApplication(
        FakeAPI(),  # type: ignore[arg-type]
        "token",
        100,
        object(),  # type: ignore[arg-type]
        participants,  # type: ignore[arg-type]
    )

    member = {
        "guild_id": "100",
        "nick": "Alex",
        "joined_at": "2026-01-02T03:04:05Z",
        "user": {
            "id": "200",
            "username": "alex.user",
            "global_name": "Alex Global",
            "avatar": "avatar",
        },
    }
    await app._handle_member_update(member)  # noqa: SLF001
    await app._handle_member_remove(  # noqa: SLF001
        {"guild_id": "100", "user": {"id": "200"}}
    )

    assert participants.activities[0]["username"] == "alex.user"
    assert participants.activities[0]["touch_activity"] is False
    assert participants.departures == [
        {"guild_id": 100, "discord_user_id": 200}
    ]


async def test_submission_confirmation_edits_prompt_without_duplicate_messages() -> None:
    api = FakeAPI()
    app = DiscordApplication(
        api,  # type: ignore[arg-type]
        "token",
        100,
        object(),  # type: ignore[arg-type]
        FakeParticipantService(),  # type: ignore[arg-type]
        FakeSubmissionService(),  # type: ignore[arg-type]
        message_content_enabled=True,
    )

    await app._handle_submission_confirmation(  # noqa: SLF001
        {
            "id": "500",
            "token": "interaction-token",
            "application_id": "600",
            "channel_id": "300",
            "member": {"user": {"id": "200"}},
            "data": {"custom_id": "submit_discord:400"},
            "message": {"id": "700"},
        }
    )

    assert api.deferred_updates == [("500", "interaction-token")]
    assert api.responses == []
    assert api.followups == []
    assert api.edited_messages == [
        (
            300,
            700,
            {
                "content": "✅ ДЗ отправлено: урок 1 · First lesson, попытка 1.",
                "components": [],
            },
        )
    ]


async def test_question_confirmation_creates_curator_question() -> None:
    api = FakeAPI()
    questions = FakeQuestionService()
    app = DiscordApplication(
        api,  # type: ignore[arg-type]
        "token",
        100,
        object(),  # type: ignore[arg-type]
        FakeParticipantService(),  # type: ignore[arg-type]
        FakeSubmissionService(),  # type: ignore[arg-type]
        message_content_enabled=True,
        question_service=questions,  # type: ignore[arg-type]
    )

    await app._handle_question_confirmation(  # noqa: SLF001
        {
            "id": "500",
            "token": "interaction-token",
            "application_id": "600",
            "channel_id": "300",
            "member": {"user": {"id": "200"}},
            "data": {"custom_id": "ask_curator:400"},
            "message": {"id": "700"},
        }
    )

    assert questions.created == [
        {
            "guild_id": 100,
            "discord_user_id": 200,
            "channel_id": 300,
            "message_id": 400,
            "text": "My homework",
            "attachment_count": 0,
        }
    ]
    assert api.edited_messages == [
        (
            300,
            700,
            {
                "content": "Вопрос передан команде. Ответ появится здесь, в этой ветке.",
                "components": [],
            },
        )
    ]
    assert api.channel_messages == []


async def test_question_confirmation_mentions_staff_role_when_configured() -> None:
    api = FakeAPI()
    app = DiscordApplication(
        api,  # type: ignore[arg-type]
        "token",
        100,
        object(),  # type: ignore[arg-type]
        FakeParticipantService(),  # type: ignore[arg-type]
        FakeSubmissionService(),  # type: ignore[arg-type]
        message_content_enabled=True,
        question_service=FakeQuestionService(),  # type: ignore[arg-type]
        staff_role_id=900,
    )

    await app._handle_question_confirmation(  # noqa: SLF001
        {
            "id": "500",
            "token": "interaction-token",
            "application_id": "600",
            "channel_id": "300",
            "member": {"user": {"id": "200"}},
            "data": {"custom_id": "ask_curator:400"},
            "message": {"id": "700"},
        }
    )

    assert api.channel_messages == [
        (
            300,
            {
                "content": "<@&900> нужен ответ в приватной ветке.",
                "message_reference": {
                    "message_id": "400",
                    "channel_id": "300",
                    "guild_id": "100",
                    "fail_if_not_exists": False,
                },
                "allowed_mentions": {"parse": [], "roles": ["900"]},
            },
        )
    ]


async def test_curator_reply_resolves_question_without_submission_prompt() -> None:
    api = FakeAPI()
    questions = FakeQuestionService()
    app = DiscordApplication(
        api,  # type: ignore[arg-type]
        "token",
        100,
        object(),  # type: ignore[arg-type]
        FakeParticipantService(activity_result=False),  # type: ignore[arg-type]
        FakeSubmissionService(),  # type: ignore[arg-type]
        message_content_enabled=True,
        question_service=questions,  # type: ignore[arg-type]
    )

    await app._handle_message_create(  # noqa: SLF001
        {
            "id": "401",
            "guild_id": "100",
            "channel_id": "300",
            "author": {"id": "999", "bot": False},
            "member": {"nick": "Curator", "joined_at": "2026-01-02T03:04:05Z"},
            "content": "Ответ куратора",
            "attachments": [],
        }
    )

    assert questions.resolved_from_replies == [
        {
            "guild_id": 100,
            "channel_id": 300,
            "responder_discord_user_id": 999,
        }
    ]
    assert api.channel_messages == []


async def test_lesson_delivery_is_sent_to_private_thread() -> None:
    api = FakeAPI()
    deliveries = FakeLessonDeliveryService()
    app = DiscordApplication(
        api,  # type: ignore[arg-type]
        "token",
        100,
        object(),  # type: ignore[arg-type]
        FakeParticipantService(),  # type: ignore[arg-type]
        lesson_delivery_service=deliveries,  # type: ignore[arg-type]
    )

    await app._dispatch_lessons_once()  # noqa: SLF001

    assert api.channel_messages == [
        (
            300,
            {
                "content": "New homework",
                "allowed_mentions": {"parse": [], "users": ["200"]},
            },
        )
    ]
    assert deliveries.sent == [
        (UUID("00000000-0000-0000-0000-000000000001"), 300)
    ]
