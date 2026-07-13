"""Discord server setup tests."""

from typing import Any

from course_platform.discord.setup import GUILD_CATEGORY, GUILD_TEXT, ProjectFixServerSetup


class FakeDiscordAPI:
    def __init__(self) -> None:
        self.channels: list[dict[str, Any]] = []

    async def guild_channels(self, guild_id: int) -> list[dict[str, Any]]:
        return list(self.channels)

    async def create_channel(self, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        channel = {**payload, "id": str(len(self.channels) + 1)}
        self.channels.append(channel)
        return channel


async def test_setup_is_idempotent_and_secures_homework_parent() -> None:
    api = FakeDiscordAPI()
    setup = ProjectFixServerSetup(api)  # type: ignore[arg-type]

    first = await setup.run(123)
    second = await setup.run(123)

    assert len(first.created) == 9
    assert second.created == ()
    assert len([item for item in api.channels if item["type"] == GUILD_CATEGORY]) == 3
    assert len([item for item in api.channels if item["type"] == GUILD_TEXT]) == 6
    homework = next(item for item in api.channels if item["name"] == "homework-desk")
    overwrite = homework["permission_overwrites"][0]
    assert overwrite["id"] == "123"
    assert int(overwrite["deny"]) > 0
