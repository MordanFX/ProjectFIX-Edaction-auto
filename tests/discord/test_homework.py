"""Personal Discord homework space tests."""

from typing import Any

from course_platform.discord.api import DiscordAPIError
from course_platform.discord.homework import DiscordHomeworkManager
from course_platform.discord.setup import GUILD_CATEGORY, GUILD_TEXT
from course_platform.services.discord_homework import DiscordHomeworkService
from course_platform.services.students import StudentRegistration, StudentService


class FakeDiscordAPI:
    def __init__(self, *, private_threads_supported: bool = True) -> None:
        self.channels: list[dict[str, Any]] = []
        self.private_threads_supported = private_threads_supported
        self.thread_members: list[tuple[int, int]] = []
        self.permission_updates: list[tuple[int, int, int, int]] = []

    async def guild_channels(self, guild_id: int) -> list[dict[str, Any]]:
        return list(self.channels)

    async def create_channel(
        self, guild_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        channel = {**payload, "id": str(len(self.channels) + 1)}
        self.channels.append(channel)
        return channel

    async def create_private_thread(
        self, parent_channel_id: int, name: str
    ) -> dict[str, Any]:
        if not self.private_threads_supported:
            raise DiscordAPIError("not available", status_code=403)
        return {"id": "900", "name": name, "parent_id": str(parent_channel_id)}

    async def add_thread_member(self, thread_id: int, user_id: int) -> None:
        self.thread_members.append((thread_id, user_id))

    async def set_member_channel_permissions(
        self,
        channel_id: int,
        user_id: int,
        *,
        allow: int,
        deny: int = 0,
    ) -> None:
        self.permission_updates.append((channel_id, user_id, allow, deny))


async def test_creates_private_thread_once(session_factory) -> None:
    student = await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=1, first_name="Test")
    )
    api = FakeDiscordAPI()
    service = DiscordHomeworkService(session_factory)
    manager = DiscordHomeworkManager(api, service, bot_user_id=500)  # type: ignore[arg-type]

    first = await manager.get_or_create(
        guild_id=100,
        discord_user_id=200,
        display_name="Test Student",
        student_id=student.student_id,
    )
    second = await manager.get_or_create(
        guild_id=100,
        discord_user_id=200,
        display_name="Test Student",
        student_id=student.student_id,
    )

    assert first.created is True
    assert first.space.kind == "private_thread"
    assert first.space.channel_id == 900
    assert second.created is False
    assert second.space == first.space
    assert api.thread_members == [(900, 200)]
    assert api.permission_updates[0][1] == 500
    assert len([item for item in api.channels if item["type"] == GUILD_CATEGORY]) == 3
    assert len([item for item in api.channels if item["type"] == GUILD_TEXT]) == 6


async def test_falls_back_to_private_channel(session_factory) -> None:
    student = await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=2, first_name="Fallback")
    )
    api = FakeDiscordAPI(private_threads_supported=False)
    service = DiscordHomeworkService(session_factory)
    manager = DiscordHomeworkManager(api, service, bot_user_id=500)  # type: ignore[arg-type]

    result = await manager.get_or_create(
        guild_id=100,
        discord_user_id=201,
        display_name="Fallback Student",
        student_id=student.student_id,
    )

    assert result.created is True
    assert result.space.kind == "private_channel"
    channel = next(
        item for item in api.channels if item["id"] == str(result.space.channel_id)
    )
    overwrites = channel["permission_overwrites"]
    assert overwrites[0]["id"] == "100"
    assert overwrites[1]["id"] == "201"
    assert overwrites[2]["id"] == "500"
