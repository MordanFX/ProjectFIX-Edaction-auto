"""Idempotent Project FIX server structure setup."""

from dataclasses import dataclass
from typing import Any

from course_platform.discord.api import DiscordAPIClient

GUILD_CATEGORY = 4
GUILD_TEXT = 0

VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
READ_MESSAGE_HISTORY = 1 << 16
CREATE_PUBLIC_THREADS = 1 << 35
CREATE_PRIVATE_THREADS = 1 << 36
SEND_MESSAGES_IN_THREADS = 1 << 38
ATTACH_FILES = 1 << 15
MANAGE_CHANNELS = 1 << 4
MANAGE_ROLES = 1 << 28
MANAGE_THREADS = 1 << 34


@dataclass(frozen=True, slots=True)
class SetupResult:
    created: tuple[str, ...]
    existing: tuple[str, ...]


class ProjectFixServerSetup:
    def __init__(self, api: DiscordAPIClient) -> None:
        self._api = api

    async def run(self, guild_id: int) -> SetupResult:
        channels = await self._api.guild_channels(guild_id)
        created: list[str] = []
        existing: list[str] = []

        categories: dict[str, dict[str, Any]] = {}
        for category_name in ("START", "PRACTICE", "HOMEWORK"):
            category = next(
                (
                    item
                    for item in channels
                    if item.get("type") == GUILD_CATEGORY
                    and item.get("name") == category_name
                ),
                None,
            )
            if category is None:
                category = await self._api.create_channel(
                    guild_id, {"name": category_name, "type": GUILD_CATEGORY}
                )
                channels.append(category)
                created.append(category_name)
            else:
                existing.append(category_name)
            categories[category_name] = category

        specs = {
            "START": ("welcome", "announcements"),
            "PRACTICE": ("questions", "market", "trading-systems"),
            "HOMEWORK": ("homework-desk",),
        }
        for category_name, names in specs.items():
            parent_id = categories[category_name]["id"]
            for name in names:
                channel = next(
                    (
                        item
                        for item in channels
                        if item.get("type") == GUILD_TEXT
                        and item.get("name") == name
                        and item.get("parent_id") == parent_id
                    ),
                    None,
                )
                if channel is not None:
                    existing.append(f"#{name}")
                    continue
                payload: dict[str, Any] = {
                    "name": name,
                    "type": GUILD_TEXT,
                    "parent_id": parent_id,
                }
                if name == "homework-desk":
                    payload["topic"] = (
                        "Project FIX: приватные пространства учеников "
                        "для домашних работ"
                    )
                    payload["permission_overwrites"] = [
                        {
                            "id": str(guild_id),
                            "type": 0,
                            "allow": str(
                                VIEW_CHANNEL
                                | READ_MESSAGE_HISTORY
                                | SEND_MESSAGES_IN_THREADS
                            ),
                            "deny": str(
                                SEND_MESSAGES
                                | CREATE_PUBLIC_THREADS
                                | CREATE_PRIVATE_THREADS
                            ),
                        }
                    ]
                channel = await self._api.create_channel(guild_id, payload)
                channels.append(channel)
                created.append(f"#{name}")

        return SetupResult(tuple(created), tuple(existing))

    async def homework_container(self, guild_id: int) -> tuple[int, int]:
        """Return HOMEWORK category and homework-desk channel IDs."""

        channels = await self._api.guild_channels(guild_id)
        category = next(
            (
                item
                for item in channels
                if item.get("type") == GUILD_CATEGORY
                and item.get("name") == "HOMEWORK"
            ),
            None,
        )
        if category is None:
            await self.run(guild_id)
            channels = await self._api.guild_channels(guild_id)
            category = next(
                item
                for item in channels
                if item.get("type") == GUILD_CATEGORY
                and item.get("name") == "HOMEWORK"
            )
        desk = next(
            item
            for item in channels
            if item.get("type") == GUILD_TEXT
            and item.get("name") == "homework-desk"
            and item.get("parent_id") == category["id"]
        )
        return int(category["id"]), int(desk["id"])
