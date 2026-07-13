"""Small asynchronous client for the official Telegram Bot API."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from course_platform.bot.types import TelegramFile, TelegramMessage, TelegramUpdate, TelegramUser

TELEGRAM_API_URL = "https://api.telegram.org"


class TelegramAPIError(RuntimeError):
    """A sanitized error returned by Telegram."""

    def __init__(self, description: str, error_code: int | None = None) -> None:
        super().__init__(description)
        self.description = description
        self.error_code = error_code


class TelegramTransportError(RuntimeError):
    """A network or malformed-response error without the secret request URL."""


class TelegramBotClient:
    """Direct async access to the small Bot API surface currently required."""

    def __init__(
        self,
        token: SecretStr | str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        api_url: str = TELEGRAM_API_URL,
    ) -> None:
        token_value = token.get_secret_value() if isinstance(token, SecretStr) else token
        if not token_value:
            raise ValueError("Telegram bot token is empty")

        normalized_api_url = api_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=f"{normalized_api_url}/bot{token_value}/",
            timeout=httpx.Timeout(40.0),
            transport=transport,
        )
        self._file_client = httpx.AsyncClient(
            base_url=f"{normalized_api_url}/file/bot{token_value}/",
            timeout=httpx.Timeout(60.0),
            transport=transport,
        )

    async def __aenter__(self) -> TelegramBotClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()
        await self._file_client.aclose()

    async def _call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        request_timeout: float | None = None,
    ) -> Any:
        request_options: dict[str, Any] = {}
        if request_timeout is not None:
            request_options["timeout"] = request_timeout

        try:
            response = await self._client.post(
                method,
                json=payload or {},
                **request_options,
            )
        except httpx.HTTPError:
            raise TelegramTransportError("Telegram API request failed") from None

        try:
            response_data = response.json()
        except ValueError:
            raise TelegramTransportError("Telegram API returned invalid JSON") from None

        if not isinstance(response_data, dict):
            raise TelegramTransportError("Telegram API returned an invalid response")

        if not response_data.get("ok"):
            description = response_data.get("description")
            error_code = response_data.get("error_code")
            raise TelegramAPIError(
                description if isinstance(description, str) else "Telegram API request failed",
                error_code if isinstance(error_code, int) else None,
            )

        return response_data.get("result")

    async def get_me(self) -> TelegramUser:
        """Validate the token and return the bot account."""

        result = await self._call("getMe")
        try:
            return TelegramUser.model_validate(result)
        except ValidationError:
            raise TelegramTransportError("Telegram API returned invalid bot data") from None

    async def get_file(self, file_id: str) -> TelegramFile:
        """Resolve a reusable Telegram file id to its current download path."""

        result = await self._call("getFile", {"file_id": file_id})
        try:
            return TelegramFile.model_validate(result)
        except ValidationError:
            raise TelegramTransportError("Telegram API returned invalid file data") from None

    async def open_file(
        self,
        file_path: str,
        *,
        range_header: str | None = None,
    ) -> httpx.Response:
        """Open a Telegram file response without buffering it in application memory."""

        headers = {"Range": range_header} if range_header else None
        try:
            request = self._file_client.build_request(
                "GET",
                file_path.lstrip("/"),
                headers=headers,
            )
            return await self._file_client.send(request, stream=True)
        except httpx.HTTPError:
            raise TelegramTransportError("Telegram file download failed") from None

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        poll_timeout: int = 30,
    ) -> list[TelegramUpdate]:
        """Fetch message updates using long polling."""

        payload: dict[str, Any] = {
            "timeout": poll_timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset

        result = await self._call(
            "getUpdates",
            payload,
            request_timeout=poll_timeout + 10,
        )
        try:
            return [TelegramUpdate.model_validate(item) for item in result]
        except (TypeError, ValidationError):
            raise TelegramTransportError("Telegram API returned invalid updates") from None

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
        link_preview_options: dict[str, Any] | None = None,
    ) -> TelegramMessage:
        """Send a plain text message."""

        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if link_preview_options is not None:
            payload["link_preview_options"] = link_preview_options

        result = await self._call("sendMessage", payload)
        try:
            return TelegramMessage.model_validate(result)
        except ValidationError:
            raise TelegramTransportError("Telegram API returned invalid message data") from None

    async def send_photo(
        self,
        chat_id: int,
        photo: str,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> TelegramMessage:
        """Send a photo by an HTTPS URL."""

        payload: dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption is not None:
            payload["caption"] = caption
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = await self._call("sendPhoto", payload)
        try:
            return TelegramMessage.model_validate(result)
        except ValidationError:
            raise TelegramTransportError("Telegram API returned invalid message data") from None

    async def send_photo_file(
        self,
        chat_id: int,
        path: Path,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> TelegramMessage:
        """Upload a local image to Telegram using multipart form data."""

        try:
            content = await asyncio.to_thread(path.read_bytes)
            data: dict[str, str] = {"chat_id": str(chat_id)}
            if caption is not None:
                data["caption"] = caption
            if parse_mode is not None:
                data["parse_mode"] = parse_mode
            if reply_markup is not None:
                data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
            response = await self._client.post(
                "sendPhoto",
                data=data,
                files={"photo": (path.name, content, "image/png")},
            )
        except (OSError, httpx.HTTPError):
            raise TelegramTransportError("Telegram photo upload failed") from None
        try:
            response_data = response.json()
        except ValueError:
            raise TelegramTransportError("Telegram API returned invalid JSON") from None
        if not isinstance(response_data, dict) or not response_data.get("ok"):
            description = (
                response_data.get("description")
                if isinstance(response_data, dict)
                else None
            )
            raise TelegramAPIError(
                description if isinstance(description, str) else "Telegram API request failed"
            )
        try:
            return TelegramMessage.model_validate(response_data.get("result"))
        except ValidationError:
            raise TelegramTransportError("Telegram API returned invalid message data") from None

    async def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text is not None:
            payload["text"] = text
        await self._call("answerCallbackQuery", payload)

    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict[str, Any],
    ) -> None:
        await self._call(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
            },
        )

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        """Edit an existing bot message and its inline keyboard."""

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        await self._call("editMessageText", payload)

    async def copy_message(
        self,
        chat_id: int,
        from_chat_id: int,
        message_id: int,
    ) -> None:
        """Copy an existing Telegram message without downloading its media."""

        await self._call(
            "copyMessage",
            {
                "chat_id": chat_id,
                "from_chat_id": from_chat_id,
                "message_id": message_id,
            },
        )
