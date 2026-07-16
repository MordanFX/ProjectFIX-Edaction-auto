"""Discord slash-command identity gate tests."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID

from course_platform.discord.application import DiscordApplication
from course_platform.services.discord_invites import InvalidDiscordAccessCodeError
from course_platform.services.discord_lesson_deliveries import DiscordLessonDeliveryItem
from course_platform.services.submissions import SubmissionReceipt


class FakeAPI:
    def __init__(self) -> None:
        self.responses: list[str] = []
        self.followups: list[str] = []
        self.channel_messages: list[tuple[int, dict[str, object]]] = []
        self.deferred_updates: list[tuple[str, str]] = []
        self.edited_messages: list[tuple[int, int, dict[str, object]]] = []
        self.modals: list[dict[str, object]] = []

    async def respond_interaction(self, interaction_id, token, content) -> None:
        self.responses.append(content)

    async def respond_with_modal(
        self, interaction_id, token, *, custom_id, title, components
    ) -> None:
        self.modals.append(
            {"custom_id": custom_id, "title": title, "components": components}
        )

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


STUDENT_ID = UUID("00000000-0000-0000-0000-0000000000aa")
COURSE_ID = UUID("00000000-0000-0000-0000-0000000000bb")


@dataclass
class FakeParticipantService:
    activities: list[dict[str, object]] = field(default_factory=list)
    departures: list[dict[str, object]] = field(default_factory=list)
    creations: list[dict[str, object]] = field(default_factory=list)
    activity_result: bool = True

    async def get_or_create(self, **kwargs):
        self.creations.append(kwargs)
        return SimpleNamespace(student_id=STUDENT_ID)

    async def record_activity(self, **kwargs):
        self.activities.append(kwargs)
        return self.activity_result

    async def mark_left(self, **kwargs):
        self.departures.append(kwargs)
        return True


class FakeHomeworkService:
    """Only ``find`` matters here: it decides whether a seat already exists."""

    def __init__(self, existing: object | None = None) -> None:
        self.existing = existing

    async def find(self, guild_id: int, discord_user_id: int):
        return self.existing


INVITE_ID = UUID("00000000-0000-0000-0000-0000000000cc")


class FakeInviteService:
    def __init__(self, *, course_id: UUID | None = None, valid: bool = True) -> None:
        self.course_id = course_id
        self.valid = valid
        self.redeemed: list[dict[str, object]] = []
        self.released: list[UUID] = []

    async def redeem_access_code(self, *, guild_id: int, code: str, discord_user_id: int):
        if not self.valid:
            raise InvalidDiscordAccessCodeError("invalid-access-code")
        self.redeemed.append(
            {"guild_id": guild_id, "code": code, "discord_user_id": discord_user_id}
        )
        return SimpleNamespace(invite_id=INVITE_ID, course_id=self.course_id)

    async def release_access_code(self, *, invite_id: UUID) -> None:
        self.released.append(invite_id)


class FakeHomeworkManager:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    async def get_or_create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(space=SimpleNamespace(channel_id=300), created=True)


class FakeStudentAccessService:
    def __init__(self) -> None:
        self.assigned: list[dict[str, object]] = []

    async def assign_discord_course(self, *, student_id: UUID, course_id: UUID) -> None:
        self.assigned.append({"student_id": student_id, "course_id": course_id})


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
        "guild_id": "100",
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
                "content": (
                    "✅ Работа ушла на проверку: урок 1 · First lesson, "
                    "попытка 1. Как куратор посмотрит — напишу сюда."
                ),
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
                "content": "Передал вопрос куратору — ответ придёт сюда, в твою ветку.",
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


async def test_question_confirmation_mentions_multiple_staff_roles_when_configured() -> None:
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
        staff_role_ids=(900, 901, 902),
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
                "content": (
                    "<@&900> <@&901> <@&902> "
                    "\u043d\u0443\u0436\u0435\u043d \u043e\u0442\u0432\u0435\u0442 "
                    "\u0432 \u043f\u0440\u0438\u0432\u0430\u0442\u043d\u043e\u0439 "
                    "\u0432\u0435\u0442\u043a\u0435."
                ),
                "message_reference": {
                    "message_id": "400",
                    "channel_id": "300",
                    "guild_id": "100",
                    "fail_if_not_exists": False,
                },
                "allowed_mentions": {"parse": [], "roles": ["900", "901", "902"]},
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


async def test_setup_welcome_publishes_button_into_welcome_channel() -> None:
    api = FakeAPI()
    app = DiscordApplication(
        api,  # type: ignore[arg-type]
        "token",
        100,
        object(),  # type: ignore[arg-type]
        FakeParticipantService(),  # type: ignore[arg-type]
        welcome_channel_id=777,
    )

    await app._handle_interaction(interaction("setup_welcome"))  # noqa: SLF001

    assert len(api.channel_messages) == 1
    channel_id, payload = api.channel_messages[0]
    assert channel_id == 777
    button = payload["components"][0]["components"][0]  # type: ignore[index]
    assert button["custom_id"] == "open_homework"
    assert button["label"] == "Получить доступ"


async def test_setup_welcome_reports_unconfigured_channel() -> None:
    api = FakeAPI()
    app = DiscordApplication(
        api,  # type: ignore[arg-type]
        "token",
        100,
        object(),  # type: ignore[arg-type]
        FakeParticipantService(),  # type: ignore[arg-type]
    )

    await app._handle_interaction(interaction("setup_welcome"))  # noqa: SLF001

    assert api.channel_messages == []
    assert "DISCORD_INVITE_CHANNEL_ID" in api.followups[0]


async def test_welcome_button_new_student_opens_code_modal() -> None:
    api = FakeAPI()
    participants = FakeParticipantService()
    invites = FakeInviteService()
    app = build_homework_app(
        api, participants=participants, homework_service=FakeHomeworkService(), invites=invites
    )

    await app._handle_interaction(button_interaction())  # noqa: SLF001

    # New student: the click must pop the code modal — read-only channel, so the
    # code is typed into the popup — and create nothing until the code is checked.
    assert len(api.modals) == 1
    assert api.modals[0]["custom_id"] == "homework_code_modal"
    field = api.modals[0]["components"][0]["components"][0]  # type: ignore[index]
    assert field["custom_id"] == "access_code"
    assert invites.redeemed == []
    assert app._homework_manager.created == []  # noqa: SLF001


async def test_welcome_button_returning_student_reopens_space_without_modal() -> None:
    api = FakeAPI()
    participants = FakeParticipantService()
    invites = FakeInviteService()
    app = build_homework_app(
        api,
        participants=participants,
        homework_service=FakeHomeworkService(existing=SimpleNamespace(channel_id=300)),
        invites=invites,
    )

    await app._handle_interaction(button_interaction())  # noqa: SLF001

    # Already has a seat: reopen straight away, no modal, no code demanded.
    assert api.modals == []
    assert invites.redeemed == []
    assert len(app._homework_manager.created) == 1  # noqa: SLF001
    assert "<#300>" in api.followups[0]


async def test_code_modal_with_valid_code_opens_space_and_assigns_course() -> None:
    api = FakeAPI()
    participants = FakeParticipantService()
    invites = FakeInviteService(course_id=COURSE_ID)
    access = FakeStudentAccessService()
    app = build_homework_app(
        api,
        participants=participants,
        homework_service=FakeHomeworkService(),
        invites=invites,
        access=access,
    )

    await app._handle_interaction(modal_interaction("GOOD-CODE-HERE"))  # noqa: SLF001

    assert invites.redeemed == [
        {"guild_id": 100, "code": "GOOD-CODE-HERE", "discord_user_id": 200}
    ]
    assert len(app._homework_manager.created) == 1  # noqa: SLF001
    assert access.assigned == [{"student_id": STUDENT_ID, "course_id": COURSE_ID}]
    assert "<#300>" in api.followups[0]


async def test_code_modal_with_invalid_code_gets_no_space() -> None:
    api = FakeAPI()
    participants = FakeParticipantService()
    invites = FakeInviteService(valid=False)
    app = build_homework_app(
        api, participants=participants, homework_service=FakeHomeworkService(), invites=invites
    )

    await app._handle_interaction(modal_interaction("WRON-GCOD-EXXX"))  # noqa: SLF001

    assert participants.creations == []
    assert app._homework_manager.created == []  # noqa: SLF001
    assert "не подошёл" in api.followups[0]


async def test_interaction_from_another_guild_is_ignored() -> None:
    api = FakeAPI()
    app = DiscordApplication(
        api,  # type: ignore[arg-type]
        "token",
        100,
        object(),  # type: ignore[arg-type]
        FakeParticipantService(),  # type: ignore[arg-type]
        welcome_channel_id=777,
    )
    opened: list[dict[str, object]] = []

    async def fake_button(payload: dict[str, object]) -> None:
        opened.append(payload)

    app._handle_homework_button = fake_button  # type: ignore[method-assign]  # noqa: SLF001

    # Same bot token can be connected to a staging guild; its clicks must not be
    # served against the configured guild.
    await app._handle_interaction(  # noqa: SLF001
        {
            "id": "1",
            "token": "token",
            "application_id": "app",
            "guild_id": "999",
            "type": 3,
            "member": {"user": {"id": "200", "username": "alex"}},
            "data": {"custom_id": "open_homework", "component_type": 2},
        }
    )

    assert opened == []
    assert api.channel_messages == []


def homework_interaction(code: str | None = None):
    options = [{"name": "code", "type": 3, "value": code}] if code is not None else []
    return interaction("homework", options)


def button_interaction():
    return {
        "id": "1",
        "token": "token",
        "application_id": "app",
        "guild_id": "100",
        "type": 3,  # MESSAGE_COMPONENT
        "member": {"user": {"id": "200", "username": "alex"}},
        "data": {"custom_id": "open_homework", "component_type": 2},
    }


def modal_interaction(code: str):
    return {
        "id": "1",
        "token": "token",
        "application_id": "app",
        "guild_id": "100",
        "type": 5,  # MODAL_SUBMIT
        "member": {"user": {"id": "200", "username": "alex"}},
        "data": {
            "custom_id": "homework_code_modal",
            "components": [
                {
                    "type": 1,
                    "components": [
                        {"type": 4, "custom_id": "access_code", "value": code}
                    ],
                }
            ],
        },
    }


def build_homework_app(api, *, participants, homework_service, invites, access=None):
    app = DiscordApplication(
        api,  # type: ignore[arg-type]
        "token",
        100,
        homework_service,  # type: ignore[arg-type]
        participants,  # type: ignore[arg-type]
        invite_service=invites,  # type: ignore[arg-type]
        student_access_service=access,  # type: ignore[arg-type]
    )
    app._homework_manager = FakeHomeworkManager()  # noqa: SLF001
    return app


async def test_new_student_without_access_code_gets_no_space() -> None:
    api = FakeAPI()
    participants = FakeParticipantService()
    invites = FakeInviteService()
    app = build_homework_app(
        api, participants=participants, homework_service=FakeHomeworkService(), invites=invites
    )

    await app._handle_interaction(homework_interaction())  # noqa: SLF001

    # The desk is hidden from @everyone, so a codeless member must get nothing:
    # no redeem, no student record, no thread.
    assert invites.redeemed == []
    assert participants.creations == []
    assert app._homework_manager.created == []  # noqa: SLF001
    assert "код доступа" in api.followups[0].lower()


async def test_new_student_with_invalid_access_code_gets_no_space() -> None:
    api = FakeAPI()
    participants = FakeParticipantService()
    invites = FakeInviteService(valid=False)
    app = build_homework_app(
        api, participants=participants, homework_service=FakeHomeworkService(), invites=invites
    )

    await app._handle_interaction(homework_interaction("WRON-GCOD-EXXX"))  # noqa: SLF001

    assert participants.creations == []
    assert app._homework_manager.created == []  # noqa: SLF001
    assert "не подошёл" in api.followups[0]


async def test_valid_access_code_opens_space_and_assigns_course() -> None:
    api = FakeAPI()
    participants = FakeParticipantService()
    invites = FakeInviteService(course_id=COURSE_ID)
    access = FakeStudentAccessService()
    app = build_homework_app(
        api,
        participants=participants,
        homework_service=FakeHomeworkService(),
        invites=invites,
        access=access,
    )

    await app._handle_interaction(homework_interaction("GOOD-CODE-HERE"))  # noqa: SLF001

    assert invites.redeemed == [
        {"guild_id": 100, "code": "GOOD-CODE-HERE", "discord_user_id": 200}
    ]
    assert len(app._homework_manager.created) == 1  # noqa: SLF001
    # The course rides along with the code, so the student lands already enrolled.
    assert access.assigned == [{"student_id": STUDENT_ID, "course_id": COURSE_ID}]
    assert "<#300>" in api.followups[0]


async def test_returning_student_reopens_space_without_a_code() -> None:
    api = FakeAPI()
    participants = FakeParticipantService()
    invites = FakeInviteService()
    app = build_homework_app(
        api,
        participants=participants,
        homework_service=FakeHomeworkService(existing=SimpleNamespace(channel_id=300)),
        invites=invites,
    )

    await app._handle_interaction(homework_interaction())  # noqa: SLF001

    # Already paid for their seat: no code is demanded a second time.
    assert invites.redeemed == []
    assert len(app._homework_manager.created) == 1  # noqa: SLF001
    assert "<#300>" in api.followups[0]


async def test_failed_space_creation_hands_the_access_code_back() -> None:
    api = FakeAPI()
    participants = FakeParticipantService()
    invites = FakeInviteService(course_id=COURSE_ID)
    app = build_homework_app(
        api, participants=participants, homework_service=FakeHomeworkService(), invites=invites
    )

    class BoomManager:
        async def get_or_create(self, **kwargs):
            raise RuntimeError("discord permissions missing")

    app._homework_manager = BoomManager()  # type: ignore[assignment]  # noqa: SLF001

    await app._handle_interaction(modal_interaction("GOOD-CODE-HERE"))  # noqa: SLF001

    # Code was consumed, but the thread failed — it must be released, not burned,
    # so the student can retry once the permission gap is fixed.
    assert invites.redeemed
    assert invites.released == [INVITE_ID]
    assert "Не удалось" in api.followups[-1]
