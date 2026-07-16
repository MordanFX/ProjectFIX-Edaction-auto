"""Minimal Discord Gateway application for Project FIX commands."""

import asyncio
import json
import logging
import platform
from datetime import datetime
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect

from course_platform.discord.api import DiscordAPIClient
from course_platform.discord.homework import DiscordHomeworkManager
from course_platform.discord.setup import ProjectFixServerSetup
from course_platform.services.discord_homework import DiscordHomeworkService
from course_platform.services.discord_invites import (
    DiscordInviteService,
    InvalidDiscordAccessCodeError,
)
from course_platform.services.discord_lesson_deliveries import DiscordLessonDeliveryService
from course_platform.services.discord_notifications import DiscordFeedbackNotificationService
from course_platform.services.discord_participants import DiscordParticipantService
from course_platform.services.discord_questions import (
    DiscordQuestionAccessError,
    DiscordQuestionService,
)
from course_platform.services.discord_submissions import (
    DiscordIncomingAttachment,
    DiscordMessageAlreadySubmittedError,
    DiscordSubmissionAccessError,
    DiscordSubmissionService,
)
from course_platform.services.students import StudentAccessError, StudentAccessService
from course_platform.services.submissions import (
    AssignmentAcceptedError,
    EmptySubmissionError,
    NoActiveAssignmentError,
    SubmissionPendingError,
    UnsupportedSubmissionKindError,
)

logger = logging.getLogger(__name__)

OPEN_HOMEWORK_BUTTON = "open_homework"
HOMEWORK_CODE_MODAL = "homework_code_modal"
ACCESS_CODE_INPUT = "access_code"
ACCESS_CODE_OPTION = "code"
HOMEWORK_BUTTON_LABEL = "Получить доступ"
ACCESS_CODE_REQUIRED = (
    "Для первого входа нужен код доступа — его выдаёт куратор вместе со ссылкой.\n"
    "Нажми кнопку «Получить доступ» и введи код из сообщения куратора."
)
ACCESS_CODE_INVALID = (
    "Этот код не подошёл — возможно, он уже использован или истёк.\n"
    "Напиши куратору, он выдаст новый."
)
WELCOME_MESSAGE = (
    "**Добро пожаловать в Project FIX!**\n\n"
    "Куратор выдал тебе персональный код доступа. Нажми кнопку ниже, "
    "введи код — и я открою твоё личное пространство для домашних работ. "
    "Его видишь только ты и кураторы.\n\n"
    "Уже занимаешься? Жми ту же кнопку — открою твою ветку."
)


class DiscordApplication:
    def __init__(
        self,
        api: DiscordAPIClient,
        token: str,
        guild_id: int,
        homework_service: DiscordHomeworkService,
        participant_service: DiscordParticipantService,
        submission_service: DiscordSubmissionService | None = None,
        *,
        invite_service: DiscordInviteService | None = None,
        student_access_service: StudentAccessService | None = None,
        message_content_enabled: bool = False,
        feedback_service: DiscordFeedbackNotificationService | None = None,
        lesson_delivery_service: DiscordLessonDeliveryService | None = None,
        question_service: DiscordQuestionService | None = None,
        homework_channel_id: int | None = None,
        welcome_channel_id: int | None = None,
        staff_role_id: int | None = None,
        staff_role_ids: tuple[int, ...] = (),
    ) -> None:
        self._api = api
        self._token = token
        self._guild_id = guild_id
        self._homework_service = homework_service
        self._participant_service = participant_service
        self._submission_service = submission_service
        self._invite_service = invite_service
        self._student_access_service = student_access_service
        self._message_content_enabled = message_content_enabled
        self._feedback_service = feedback_service
        self._lesson_delivery_service = lesson_delivery_service
        self._question_service = question_service
        self._homework_channel_id = homework_channel_id
        self._welcome_channel_id = welcome_channel_id
        self._staff_role_ids = tuple(
            dict.fromkeys(
                role_id
                for role_id in (
                    *((staff_role_id,) if staff_role_id is not None else ()),
                    *staff_role_ids,
                )
                if role_id is not None
            )
        )
        self._homework_manager: DiscordHomeworkManager | None = None
        self._bot_user_id: int | None = None
        self._sequence: int | None = None

    async def run(self) -> None:
        bot = await self._api.current_user()
        application_id = int(bot["id"])
        self._bot_user_id = application_id
        self._homework_manager = DiscordHomeworkManager(
            self._api,
            self._homework_service,
            bot_user_id=application_id,
            homework_channel_id=self._homework_channel_id,
            staff_role_ids=self._staff_role_ids,
        )
        await self._api.guild(self._guild_id)
        await self._api.register_guild_commands(
            application_id,
            self._guild_id,
            [
                {
                    "name": "setup_project_fix",
                    "description": "Создать базовую структуру сервера Project FIX",
                    "type": 1,
                    "default_member_permissions": str(1 << 5),
                },
                {
                    "name": "setup_welcome",
                    "description": "Опубликовать приветствие с кнопкой в канале входа",
                    "type": 1,
                    "default_member_permissions": str(1 << 5),
                },
                {
                    "name": "homework",
                    "description": "Открыть личное пространство для домашних работ",
                    "type": 1,
                    "options": [
                        {
                            "name": ACCESS_CODE_OPTION,
                            "description": "Код доступа от куратора (нужен только в первый раз)",
                            "type": 3,
                            "required": False,
                        }
                    ],
                },
            ],
        )
        gateway = await self._api.gateway_url()
        logger.info("Discord bot @%s connected to configured guild", bot["username"])
        async with connect(f"{gateway}?v=10&encoding=json") as websocket:
            hello = json.loads(await websocket.recv())
            heartbeat_interval = hello["d"]["heartbeat_interval"] / 1000
            heartbeat = asyncio.create_task(self._heartbeat(websocket, heartbeat_interval))
            feedback_dispatcher = asyncio.create_task(self._dispatch_feedback_forever())
            lesson_dispatcher = asyncio.create_task(self._dispatch_lessons_forever())
            try:
                await websocket.send(
                    json.dumps(
                        {
                            "op": 2,
                            "d": {
                                "token": self._token,
                                "intents": (
                                    1 | (1 << 9) | (1 << 15) if self._message_content_enabled else 1
                                ),
                                "properties": {
                                    "os": platform.system().lower(),
                                    "browser": "course-platform",
                                    "device": "course-platform",
                                },
                            },
                        }
                    )
                )
                async for raw in websocket:
                    payload = json.loads(raw)
                    if payload.get("s") is not None:
                        self._sequence = payload["s"]
                    if payload.get("op") == 7:
                        raise RuntimeError("Discord requested reconnect")
                    if payload.get("op") == 0 and payload.get("t") == "READY":
                        logger.info("Discord Gateway ready")
                    if payload.get("op") == 0 and payload.get("t") == "INTERACTION_CREATE":
                        await self._handle_interaction(payload["d"])
                    if (
                        self._message_content_enabled
                        and payload.get("op") == 0
                        and payload.get("t") == "MESSAGE_CREATE"
                    ):
                        await self._handle_message_create(payload["d"])
                    if payload.get("op") == 0 and payload.get("t") == "GUILD_MEMBER_UPDATE":
                        await self._handle_member_update(payload["d"])
                    if payload.get("op") == 0 and payload.get("t") == "GUILD_MEMBER_REMOVE":
                        await self._handle_member_remove(payload["d"])
            finally:
                heartbeat.cancel()
                feedback_dispatcher.cancel()
                lesson_dispatcher.cancel()
                await asyncio.gather(
                    heartbeat,
                    feedback_dispatcher,
                    lesson_dispatcher,
                    return_exceptions=True,
                )

    async def _heartbeat(self, websocket: Any, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await websocket.send(json.dumps({"op": 1, "d": self._sequence}))

    async def _dispatch_feedback_forever(self) -> None:
        while True:
            if self._feedback_service is not None:
                for item in await self._feedback_service.list_pending():
                    verdict = (
                        "✅ Принято! Отличная работа"
                        if item.verdict.value == "accepted"
                        else "🔄 Нужно доработать — смотри комментарий ниже"
                    )
                    try:
                        local_attachments = [
                            attachment
                            for attachment in item.attachments
                            if attachment.local_path is not None
                        ]
                        attachment_lines = [
                            f"- {attachment.file_name or 'attachment'}: {attachment.external_url}"
                            for attachment in item.attachments
                            if attachment.external_url is not None
                        ]
                        attachments_text = (
                            "\n\n**Вложения куратора:**\n"
                            + "\n".join(attachment_lines)
                            if attachment_lines
                            else ""
                        )
                        payload = {
                            "content": f"**{verdict}**\n\n{item.message}{attachments_text}",
                            "allowed_mentions": {"parse": []},
                        }
                        if local_attachments:
                            first_attachment = local_attachments[0]
                            await self._api.send_channel_message_file(
                                item.channel_id,
                                payload,
                                Path(first_attachment.local_path or ""),
                                file_name=first_attachment.file_name,
                                mime_type=first_attachment.mime_type,
                            )
                            for attachment in local_attachments[1:]:
                                await self._api.send_channel_message_file(
                                    item.channel_id,
                                    {"content": "", "allowed_mentions": {"parse": []}},
                                    Path(attachment.local_path or ""),
                                    file_name=attachment.file_name,
                                    mime_type=attachment.mime_type,
                                )
                        else:
                            await self._api.send_channel_message(
                                item.channel_id,
                                payload,
                            )
                        await self._feedback_service.mark_sent(item.feedback_id)
                    except Exception as error:
                        logger.exception("Discord feedback delivery failed")
                        await self._feedback_service.mark_failed(item.feedback_id, str(error))
            await asyncio.sleep(5)

    async def _dispatch_lessons_forever(self) -> None:
        while True:
            await self._dispatch_lessons_once()
            await asyncio.sleep(5)

    async def _dispatch_lessons_once(self) -> None:
        if self._lesson_delivery_service is None:
            return
        for item in await self._lesson_delivery_service.list_pending():
            try:
                message = await self._api.send_channel_message(
                    item.channel_id,
                    {
                        "content": item.content,
                        "allowed_mentions": {
                            "parse": [],
                            "users": [str(item.discord_user_id)],
                        },
                    },
                )
                await self._lesson_delivery_service.mark_sent(
                    item.delivery_id,
                    int(message["id"]),
                )
            except Exception as error:
                logger.exception("Discord lesson delivery failed")
                await self._lesson_delivery_service.mark_failed(
                    item.delivery_id,
                    str(error),
                )

    async def _handle_interaction(self, interaction: dict[str, Any]) -> None:
        if int(interaction.get("guild_id", 0)) != self._guild_id:
            # One bot token can sit in several guilds (e.g. a staging server), and the
            # Gateway delivers every interaction to every session. Without this guard a
            # click in another guild would be served against the configured guild.
            return
        data = interaction.get("data") or {}
        custom_id = str(data.get("custom_id", ""))
        if interaction.get("type") == 5:  # MODAL_SUBMIT
            if custom_id == HOMEWORK_CODE_MODAL:
                await self._handle_homework_modal(interaction)
            return
        if custom_id.startswith("submit_discord:"):
            await self._handle_submission_confirmation(interaction)
            return
        if custom_id.startswith("ask_curator:"):
            await self._handle_question_confirmation(interaction)
            return
        if custom_id == OPEN_HOMEWORK_BUTTON:
            # The welcome channel is read-only for students, so /homework cannot be
            # typed there. A button click is not a message, so it works regardless.
            await self._handle_homework_button(interaction)
            return
        if data.get("name") == "setup_project_fix":
            await self._handle_setup(interaction)
        elif data.get("name") == "setup_welcome":
            await self._handle_setup_welcome(interaction)
        elif data.get("name") == "homework":
            await self._handle_homework(interaction)

    async def _handle_message_create(self, message: dict[str, Any]) -> None:
        if self._submission_service is None and self._question_service is None:
            return
        author = message.get("author") or {}
        if author.get("bot") or int(author.get("id", 0)) == self._bot_user_id:
            return
        if int(message.get("guild_id", 0)) != self._guild_id:
            return
        content = str(message.get("content") or "").strip()
        attachments = message.get("attachments") or []
        if not content and not attachments:
            return
        channel_id = int(message["channel_id"])
        user_id = int(author["id"])
        member = message.get("member") or {}
        is_thread_owner = await self._participant_service.record_activity(
            guild_id=self._guild_id,
            discord_user_id=user_id,
            display_name=self._display_name(member, author, user_id),
            username=author.get("username"),
            global_name=author.get("global_name"),
            avatar_hash=author.get("avatar"),
            guild_joined_at=self._discord_datetime(member.get("joined_at")),
            channel_id=channel_id,
        )
        if not is_thread_owner:
            await self._resolve_question_from_curator_reply(
                channel_id=channel_id,
                responder_discord_user_id=user_id,
            )
            return
        if self._submission_service is None or not await self._submission_service.can_offer(
            guild_id=self._guild_id,
            discord_user_id=user_id,
            channel_id=channel_id,
        ):
            return
        await self._api.send_channel_message(
            channel_id,
            {
                "content": "Отправить эту работу на проверку?",
                "message_reference": {
                    "message_id": str(message["id"]),
                    "channel_id": str(channel_id),
                    "guild_id": str(self._guild_id),
                    "fail_if_not_exists": False,
                },
                "allowed_mentions": {"parse": []},
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 2,
                                "style": 1,
                                "label": "Отправить на проверку",
                                "custom_id": f"submit_discord:{message['id']}",
                            },
                            {
                                "type": 2,
                                "style": 2,
                                "label": "Уточнить вопрос",
                                "custom_id": f"ask_curator:{message['id']}",
                            },
                        ],
                    }
                ],
            },
        )

    async def _resolve_question_from_curator_reply(
        self,
        *,
        channel_id: int,
        responder_discord_user_id: int,
    ) -> None:
        if self._question_service is None:
            return
        try:
            await self._question_service.resolve_latest_open_in_channel(
                guild_id=self._guild_id,
                channel_id=channel_id,
                responder_discord_user_id=responder_discord_user_id,
            )
        except Exception:
            logger.exception("Discord question auto-resolve failed")

    async def _handle_member_update(self, member: dict[str, Any]) -> None:
        if int(member.get("guild_id", 0)) != self._guild_id:
            return
        user = member.get("user") or {}
        user_id = int(user.get("id", 0))
        if not user_id or user.get("bot"):
            return
        await self._participant_service.record_activity(
            guild_id=self._guild_id,
            discord_user_id=user_id,
            display_name=self._display_name(member, user, user_id),
            username=user.get("username"),
            global_name=user.get("global_name"),
            avatar_hash=user.get("avatar"),
            guild_joined_at=self._discord_datetime(member.get("joined_at")),
            touch_activity=False,
        )

    async def _handle_member_remove(self, member: dict[str, Any]) -> None:
        if int(member.get("guild_id", 0)) != self._guild_id:
            return
        user = member.get("user") or {}
        user_id = int(user.get("id", 0))
        if user_id:
            await self._participant_service.mark_left(
                guild_id=self._guild_id,
                discord_user_id=user_id,
            )

    async def _handle_submission_confirmation(self, interaction: dict[str, Any]) -> None:
        interaction_id = str(interaction["id"])
        interaction_token = str(interaction["token"])
        application_id = str(interaction["application_id"])
        await self._api.defer_message_update(interaction_id, interaction_token)
        data = interaction.get("data") or {}
        message_id = int(str(data["custom_id"]).split(":", 1)[1])
        channel_id = int(interaction["channel_id"])
        member = interaction.get("member") or {}
        user = member.get("user") or interaction.get("user") or {}
        user_id = int(user["id"])
        prompt_message = interaction.get("message") or {}
        try:
            if self._submission_service is None or not self._message_content_enabled:
                raise DiscordSubmissionAccessError
            original = await self._api.channel_message(channel_id, message_id)
            if int((original.get("author") or {}).get("id", 0)) != user_id:
                raise DiscordSubmissionAccessError
            attachments = tuple(
                DiscordIncomingAttachment(
                    attachment_id=int(item["id"]),
                    url=str(item["url"]),
                    file_name=str(item.get("filename") or "discord-file"),
                    mime_type=item.get("content_type"),
                    file_size=item.get("size"),
                    width=item.get("width"),
                    height=item.get("height"),
                    duration_seconds=(
                        int(item["duration_secs"])
                        if item.get("duration_secs") is not None
                        else None
                    ),
                )
                for item in (original.get("attachments") or [])
            )
            receipt = await self._submission_service.submit_message(
                guild_id=self._guild_id,
                discord_user_id=user_id,
                channel_id=channel_id,
                message_id=message_id,
                text=str(original.get("content") or ""),
                attachments=attachments,
            )
            content = (
                f"✅ Работа ушла на проверку: урок {receipt.lesson_position} · "
                f"{receipt.lesson_title}, попытка {receipt.attempt_number}. "
                "Как куратор посмотрит — напишу сюда."
            )
        except DiscordMessageAlreadySubmittedError:
            content = "Эта работа уже на проверке."
        except SubmissionPendingError:
            content = "Твоя предыдущая работа ещё на проверке — сначала дождись ответа."
        except AssignmentAcceptedError:
            content = "Это задание уже принято — ждём следующий урок."
        except UnsupportedSubmissionKindError:
            content = "Для этого задания нужен другой формат — глянь условие ещё раз."
        except (NoActiveAssignmentError, DiscordSubmissionAccessError):
            content = "Не нашёл активного задания — или это не твоя ветка."
        except EmptySubmissionError:
            content = "В сообщении пусто — добавь текст или файл и попробуй снова."
        if prompt_message.get("id"):
            await self._api.edit_channel_message(
                channel_id,
                int(prompt_message["id"]),
                {"content": content, "components": []},
            )
        else:
            await self._api.followup(application_id, interaction_token, content)

    async def _handle_question_confirmation(self, interaction: dict[str, Any]) -> None:
        interaction_id = str(interaction["id"])
        interaction_token = str(interaction["token"])
        application_id = str(interaction["application_id"])
        await self._api.defer_message_update(interaction_id, interaction_token)
        data = interaction.get("data") or {}
        message_id = int(str(data["custom_id"]).split(":", 1)[1])
        channel_id = int(interaction["channel_id"])
        member = interaction.get("member") or {}
        user = member.get("user") or interaction.get("user") or {}
        user_id = int(user["id"])
        prompt_message = interaction.get("message") or {}
        try:
            if self._question_service is None or not self._message_content_enabled:
                raise DiscordQuestionAccessError
            original = await self._api.channel_message(channel_id, message_id)
            if int((original.get("author") or {}).get("id", 0)) != user_id:
                raise DiscordQuestionAccessError
            await self._question_service.create_from_message(
                guild_id=self._guild_id,
                discord_user_id=user_id,
                channel_id=channel_id,
                message_id=message_id,
                text=str(original.get("content") or ""),
                attachment_count=len(original.get("attachments") or []),
            )
            await self._notify_staff_about_question(
                channel_id=channel_id,
                message_id=message_id,
            )
            content = "Передал вопрос куратору — ответ придёт сюда, в твою ветку."
        except DiscordQuestionAccessError:
            content = "Не получилось передать вопрос — похоже, это не твоя ветка."
        if prompt_message.get("id"):
            await self._api.edit_channel_message(
                channel_id,
                int(prompt_message["id"]),
                {"content": content, "components": []},
            )
        else:
            await self._api.followup(application_id, interaction_token, content)

    async def _notify_staff_about_question(self, *, channel_id: int, message_id: int) -> None:
        if not self._staff_role_ids:
            return
        try:
            role_mentions = " ".join(f"<@&{role_id}>" for role_id in self._staff_role_ids)
            await self._api.send_channel_message(
                channel_id,
                {
                    "content": (
                        f"{role_mentions} нужен ответ в приватной ветке."
                    ),
                    "message_reference": {
                        "message_id": str(message_id),
                        "channel_id": str(channel_id),
                        "guild_id": str(self._guild_id),
                        "fail_if_not_exists": False,
                    },
                    "allowed_mentions": {
                        "parse": [],
                        "roles": [str(role_id) for role_id in self._staff_role_ids],
                    },
                },
            )
        except Exception:
            logger.exception("Discord staff question notification failed")

    async def _handle_setup(self, interaction: dict[str, Any]) -> None:
        interaction_id = str(interaction["id"])
        interaction_token = str(interaction["token"])
        application_id = str(interaction["application_id"])
        await self._api.respond_interaction(
            interaction_id,
            interaction_token,
            "Настройка Project FIX запущена…",
        )
        try:
            result = await ProjectFixServerSetup(self._api).run(self._guild_id)
            created = ", ".join(result.created) or "ничего"
            existing = ", ".join(result.existing) or "ничего"
            content = f"Готово. Создано: {created}. Уже существовало: {existing}."
        except Exception:
            logger.exception("Discord server setup failed")
            content = "Настройка не завершена. Проверь права приложения и журнал."
        await self._api.followup(application_id, interaction_token, content)

    async def _handle_setup_welcome(self, interaction: dict[str, Any]) -> None:
        interaction_id = str(interaction["id"])
        interaction_token = str(interaction["token"])
        application_id = str(interaction["application_id"])
        await self._api.respond_interaction(
            interaction_id,
            interaction_token,
            "Публикую приветствие…",
        )
        if self._welcome_channel_id is None:
            await self._api.followup(
                application_id,
                interaction_token,
                "Канал входа не настроен. Задай DISCORD_INVITE_CHANNEL_ID.",
            )
            return
        try:
            await self._api.send_channel_message(
                self._welcome_channel_id,
                {
                    "content": WELCOME_MESSAGE,
                    "allowed_mentions": {"parse": []},
                    "components": [
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 2,
                                    "style": 1,
                                    "label": HOMEWORK_BUTTON_LABEL,
                                    "custom_id": OPEN_HOMEWORK_BUTTON,
                                }
                            ],
                        }
                    ],
                },
            )
            content = "Готово. Приветствие с кнопкой опубликовано в канале входа."
        except Exception:
            logger.exception("Discord welcome message publish failed")
            content = (
                "Не удалось опубликовать приветствие. Проверь, что боту разрешено "
                "отправлять сообщения в канале входа."
            )
        await self._api.followup(application_id, interaction_token, content)

    async def _handle_homework(self, interaction: dict[str, Any]) -> None:
        """Slash-command entry — a fallback for staff/testing.

        In the closed setup students never type this (channels are read-only);
        they come through the button + code modal instead.
        """
        interaction_id = str(interaction["id"])
        interaction_token = str(interaction["token"])
        application_id = str(interaction["application_id"])
        await self._api.respond_interaction(
            interaction_id,
            interaction_token,
            "Секунду, открываю твоё пространство…",
        )
        await self._provision_homework(
            interaction,
            application_id=application_id,
            interaction_token=interaction_token,
            code=self._string_option(interaction, ACCESS_CODE_OPTION),
        )

    async def _handle_homework_button(self, interaction: dict[str, Any]) -> None:
        interaction_id = str(interaction["id"])
        interaction_token = str(interaction["token"])
        application_id = str(interaction["application_id"])
        member = interaction.get("member") or {}
        user = member.get("user") or interaction.get("user") or {}
        user_id = int(user["id"])
        # Returning students already have a space — reopen it, no code needed.
        # A new student must prove a paid seat: pop a modal to type the one-time
        # code. The modal must be this interaction's first (and only) response,
        # so the find() check has to happen before we acknowledge anything.
        if await self._homework_service.find(self._guild_id, user_id) is not None:
            await self._api.respond_interaction(
                interaction_id,
                interaction_token,
                "Секунду, открываю твоё пространство…",
            )
            await self._provision_homework(
                interaction,
                application_id=application_id,
                interaction_token=interaction_token,
                code=None,
            )
            return
        await self._api.respond_with_modal(
            interaction_id,
            interaction_token,
            custom_id=HOMEWORK_CODE_MODAL,
            title="Код доступа",
            components=[
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 4,  # text input
                            "custom_id": ACCESS_CODE_INPUT,
                            "style": 1,  # short, single line
                            "label": "Введи код от куратора",
                            "min_length": 4,
                            "max_length": 32,
                            "placeholder": "ABCD-EFGH-JKLM",
                            "required": True,
                        }
                    ],
                }
            ],
        )

    async def _handle_homework_modal(self, interaction: dict[str, Any]) -> None:
        interaction_id = str(interaction["id"])
        interaction_token = str(interaction["token"])
        application_id = str(interaction["application_id"])
        await self._api.respond_interaction(
            interaction_id,
            interaction_token,
            "Секунду, проверяю код…",
        )
        await self._provision_homework(
            interaction,
            application_id=application_id,
            interaction_token=interaction_token,
            code=self._modal_value(interaction, ACCESS_CODE_INPUT),
        )

    async def _provision_homework(
        self,
        interaction: dict[str, Any],
        *,
        application_id: str,
        interaction_token: str,
        code: str | None,
    ) -> None:
        """Gate on the access code, then open (or reopen) the private space.

        Callers must have already acknowledged the interaction; this method only
        posts the ephemeral follow-up with the result.
        """
        member = interaction.get("member") or {}
        user = member.get("user") or interaction.get("user") or {}
        user_id = int(user["id"])
        display_name = self._display_name(member, user, user_id)
        try:
            # A student who already has a space just reopens it. Opening a *new*
            # one costs a one-time access code: the desk is hidden from
            # @everyone, and the code is what proves this member paid for a seat.
            invite = None
            if await self._homework_service.find(self._guild_id, user_id) is None:
                if not code:
                    await self._api.followup(
                        application_id, interaction_token, ACCESS_CODE_REQUIRED
                    )
                    return
                if self._invite_service is None:
                    raise RuntimeError("Discord invite service is not initialized")
                try:
                    invite = await self._invite_service.redeem_access_code(
                        guild_id=self._guild_id,
                        code=code,
                        discord_user_id=user_id,
                    )
                except InvalidDiscordAccessCodeError:
                    await self._api.followup(
                        application_id, interaction_token, ACCESS_CODE_INVALID
                    )
                    return

            participant = await self._participant_service.get_or_create(
                guild_id=self._guild_id,
                discord_user_id=user_id,
                display_name=display_name,
                username=user.get("username"),
                global_name=user.get("global_name"),
                avatar_hash=user.get("avatar"),
                guild_joined_at=self._discord_datetime(member.get("joined_at")),
            )
            if self._homework_manager is None:
                raise RuntimeError("Discord homework manager is not initialized")
            result = await self._homework_manager.get_or_create(
                guild_id=self._guild_id,
                discord_user_id=user_id,
                display_name=display_name,
                student_id=participant.student_id,
            )
            if (
                invite is not None
                and invite.course_id is not None
                and self._student_access_service is not None
            ):
                try:
                    await self._student_access_service.assign_discord_course(
                        student_id=participant.student_id,
                        course_id=invite.course_id,
                    )
                except StudentAccessError:
                    logger.exception("Discord access code course assignment failed")
            assignment = (
                await self._submission_service.current_assignment(
                    guild_id=self._guild_id,
                    discord_user_id=user_id,
                )
                if self._submission_service is not None
                else None
            )
            content = (
                f"Готово! Твоё личное пространство: <#{result.space.channel_id}>. "
                "Здесь будем разбирать твои работы — видишь его только ты и кураторы."
                if result.created
                else (
                    f"С возвращением! Твоё пространство: <#{result.space.channel_id}> "
                    "— заходи, продолжаем."
                )
            )
            if assignment is None:
                content += (
                    "\n\nАктивного задания сейчас нет — "
                    "как появится, оно придёт прямо в твою ветку."
                )
            else:
                instructions = assignment.instructions.strip()
                if len(instructions) > 1200:
                    instructions = f"{instructions[:1197]}…"
                content += (
                    f"\n\n**Текущее ДЗ · {assignment.course_title}**"
                    f"\nУрок {assignment.lesson_position}: {assignment.lesson_title}"
                    f"\n{instructions}"
                )
        except Exception:
            logger.exception("Discord homework space creation failed")
            if invite is not None and self._invite_service is not None:
                # The code was consumed but the seat wasn't delivered — hand it
                # back so the student can retry once the cause is fixed, instead
                # of burning a code on a failure they can't do anything about.
                try:
                    await self._invite_service.release_access_code(
                        invite_id=invite.invite_id
                    )
                except Exception:
                    logger.exception("Discord access code release failed")
            content = (
                "Не удалось открыть пространство — что-то пошло не так. "
                "Напиши куратору, разберёмся."
            )
        await self._api.followup(application_id, interaction_token, content)

    @staticmethod
    def _string_option(interaction: dict[str, Any], name: str) -> str | None:
        data = interaction.get("data") or {}
        for option in data.get("options") or []:
            if option.get("name") == name:
                return str(option.get("value") or "").strip() or None
        return None

    @staticmethod
    def _modal_value(interaction: dict[str, Any], custom_id: str) -> str | None:
        data = interaction.get("data") or {}
        for row in data.get("components") or []:
            for component in row.get("components") or []:
                if component.get("custom_id") == custom_id:
                    return str(component.get("value") or "").strip() or None
        return None

    @staticmethod
    def _display_name(member: dict[str, Any], user: dict[str, Any], user_id: int) -> str:
        return str(
            member.get("nick")
            or user.get("global_name")
            or user.get("username")
            or f"student-{user_id}"
        )

    @staticmethod
    def _discord_datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
