"""Creation of isolated Discord homework spaces."""

import logging
import re
from dataclasses import dataclass
from uuid import UUID

from course_platform.discord.api import DiscordAPIClient, DiscordAPIError
from course_platform.discord.setup import (
    ATTACH_FILES,
    CREATE_PRIVATE_THREADS,
    MANAGE_CHANNELS,
    MANAGE_ROLES,
    MANAGE_THREADS,
    READ_MESSAGE_HISTORY,
    SEND_MESSAGES,
    SEND_MESSAGES_IN_THREADS,
    VIEW_CHANNEL,
    ProjectFixServerSetup,
)
from course_platform.services.discord_homework import (
    DiscordHomeworkService,
    HomeworkSpace,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HomeworkSpaceResult:
    space: HomeworkSpace
    created: bool


class DiscordHomeworkManager:
    def __init__(
        self,
        api: DiscordAPIClient,
        service: DiscordHomeworkService,
        *,
        bot_user_id: int,
        homework_channel_id: int | None = None,
        staff_role_ids: tuple[int, ...] = (),
    ) -> None:
        self._api = api
        self._service = service
        self._bot_user_id = bot_user_id
        self._homework_channel_id = homework_channel_id
        self._staff_role_ids = staff_role_ids

    async def get_or_create(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        display_name: str,
        student_id: UUID,
    ) -> HomeworkSpaceResult:
        existing = await self._service.find(guild_id, discord_user_id)
        if existing is not None:
            if existing.student_id != student_id:
                existing = await self._service.assign_student(
                    guild_id=guild_id,
                    discord_user_id=discord_user_id,
                    student_id=student_id,
                )
                if existing is None:
                    raise RuntimeError("Discord homework space disappeared")
            refreshed = await self._service.refresh_metadata(
                guild_id=guild_id,
                discord_user_id=discord_user_id,
                display_name=display_name,
                channel_name=self._space_name(display_name, discord_user_id),
            )
            if refreshed is not None:
                existing = refreshed
            return HomeworkSpaceResult(existing, created=False)

        category_id, desk_id = await self._homework_container(guild_id)
        name = self._space_name(display_name, discord_user_id)

        try:
            staff_thread_access = (
                VIEW_CHANNEL
                | READ_MESSAGE_HISTORY
                | SEND_MESSAGES_IN_THREADS
                | MANAGE_THREADS
            )
            # PUT replaces the bot's own overwrite wholesale, so this set must
            # contain EVERY permission the bot relies on. Omitting MANAGE_ROLES
            # here once made the bot strip its own "manage permissions" right on
            # each run, breaking the student grant below with a 403 — and every
            # manual re-grant was silently erased again on the next attempt.
            await self._api.set_member_channel_permissions(
                desk_id,
                self._bot_user_id,
                allow=(
                    VIEW_CHANNEL
                    | SEND_MESSAGES
                    | READ_MESSAGE_HISTORY
                    | ATTACH_FILES
                    | CREATE_PRIVATE_THREADS
                    | SEND_MESSAGES_IN_THREADS
                    | MANAGE_THREADS
                    | MANAGE_ROLES
                ),
            )
            for role_id in self._staff_role_ids:
                # Best-effort: a staff role positioned above the bot cannot be
                # edited by it (Discord role hierarchy → 403). Curator access to
                # the desk is a one-time channel setting, so a failure here must
                # not abort the student's thread creation.
                try:
                    await self._api.set_role_channel_permissions(
                        desk_id,
                        role_id,
                        allow=staff_thread_access,
                    )
                except DiscordAPIError as error:
                    if error.status_code != 403:
                        raise
                    logger.warning(
                        "Skipping staff role %s on desk %s (above bot in hierarchy): %s",
                        role_id,
                        desk_id,
                        error,
                    )
            # The desk is hidden from @everyone, so the student is let in one by
            # one. This must land before add_thread_member: a member who cannot
            # see the parent channel cannot be added to a thread under it. No
            # Send Messages — the student talks in their own thread, not the desk.
            await self._api.set_member_channel_permissions(
                desk_id,
                discord_user_id,
                allow=(
                    VIEW_CHANNEL
                    | READ_MESSAGE_HISTORY
                    | SEND_MESSAGES_IN_THREADS
                    | ATTACH_FILES
                ),
            )
            channel = await self._api.create_private_thread(desk_id, name)
            await self._api.add_thread_member(int(channel["id"]), discord_user_id)
            parent_channel_id = desk_id
            kind = "private_thread"
        except DiscordAPIError as error:
            if error.status_code not in {400, 403}:
                raise
            channel = await self._create_private_channel(
                guild_id=guild_id,
                category_id=category_id,
                discord_user_id=discord_user_id,
                name=name,
            )
            parent_channel_id = category_id
            kind = "private_channel"

        space = await self._service.remember(
            guild_id=guild_id,
            discord_user_id=discord_user_id,
            parent_channel_id=parent_channel_id,
            channel_id=int(channel["id"]),
            channel_name=str(channel.get("name") or name),
            kind=kind,
            display_name=display_name[:100],
            student_id=student_id,
        )
        return HomeworkSpaceResult(space, created=True)

    async def _homework_container(self, guild_id: int) -> tuple[int, int]:
        if self._homework_channel_id is None:
            setup = ProjectFixServerSetup(self._api)
            return await setup.homework_container(guild_id)

        channels = await self._api.guild_channels(guild_id)
        channel = next(
            (
                item
                for item in channels
                if int(item.get("id", 0)) == self._homework_channel_id
            ),
            None,
        )
        if channel is None:
            raise RuntimeError(
                f"Configured DISCORD_HOMEWORK_CHANNEL_ID={self._homework_channel_id} was not found"
            )
        parent_id = channel.get("parent_id")
        category_id = int(parent_id) if parent_id is not None else int(channel["id"])
        return category_id, self._homework_channel_id

    async def _create_private_channel(
        self,
        *,
        guild_id: int,
        category_id: int,
        discord_user_id: int,
        name: str,
    ) -> dict[str, object]:
        access = VIEW_CHANNEL | SEND_MESSAGES | READ_MESSAGE_HISTORY | ATTACH_FILES
        bot_access = access | MANAGE_CHANNELS
        staff_access = access
        return await self._api.create_channel(
            guild_id,
            {
                "name": name,
                "type": 0,
                "parent_id": str(category_id),
                "topic": "Личное пространство ученика для домашних работ",
                "permission_overwrites": [
                    {
                        "id": str(guild_id),
                        "type": 0,
                        "allow": "0",
                        "deny": str(VIEW_CHANNEL),
                    },
                    {
                        "id": str(discord_user_id),
                        "type": 1,
                        "allow": str(access),
                        "deny": "0",
                    },
                    {
                        "id": str(self._bot_user_id),
                        "type": 1,
                        "allow": str(bot_access),
                        "deny": "0",
                    },
                    *[
                        {
                            "id": str(role_id),
                            "type": 0,
                            "allow": str(staff_access),
                            "deny": "0",
                        }
                        for role_id in self._staff_role_ids
                    ],
                ],
            },
        )

    @staticmethod
    def _space_name(display_name: str, discord_user_id: int) -> str:
        normalized = re.sub(r"[^a-z0-9а-яё]+", "-", display_name.lower())
        normalized = normalized.strip("-")[:60] or "student"
        return f"dz-{normalized}-{str(discord_user_id)[-4:]}"
