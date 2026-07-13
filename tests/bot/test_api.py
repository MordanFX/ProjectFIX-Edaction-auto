"""Contract tests for the direct Telegram Bot API client."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from course_platform.bot.api import (
    TelegramAPIError,
    TelegramBotClient,
    TelegramTransportError,
)

BOT_USER = {
    "id": 1001,
    "is_bot": True,
    "first_name": "Course Bot",
    "username": "course_test_bot",
}
STUDENT_USER = {
    "id": 2002,
    "is_bot": False,
    "first_name": "Student",
    "language_code": "uk",
}
CHAT = {"id": 2002, "type": "private", "first_name": "Student"}


def response(payload: object) -> httpx.Response:
    return httpx.Response(200, json=payload)


async def test_get_me_parses_bot_without_exposing_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/getMe")
        return response({"ok": True, "result": BOT_USER})

    secret = SecretStr("123456:very-secret-token")
    async with TelegramBotClient(secret, transport=httpx.MockTransport(handler)) as client:
        bot = await client.get_me()

    assert bot.username == "course_test_bot"
    assert "very-secret-token" not in repr(client)


async def test_get_file_and_stream_range_without_buffering() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            assert json.loads(request.content) == {"file_id": "video-file-id"}
            return response(
                {
                    "ok": True,
                    "result": {
                        "file_id": "video-file-id",
                        "file_unique_id": "stable-video-id",
                        "file_size": 8,
                        "file_path": "videos/homework.mp4",
                    },
                }
            )

        assert request.url.path.endswith("/file/bottoken/videos/homework.mp4")
        assert request.headers["range"] == "bytes=0-3"
        return httpx.Response(
            206,
            content=b"test",
            headers={
                "content-type": "video/mp4",
                "content-range": "bytes 0-3/8",
                "accept-ranges": "bytes",
            },
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as client:
        telegram_file = await client.get_file("video-file-id")
        download = await client.open_file(telegram_file.file_path or "", range_header="bytes=0-3")
        content = await download.aread()
        await download.aclose()

    assert telegram_file.file_size == 8
    assert content == b"test"


async def test_get_updates_sends_offset_and_parses_messages() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload == {
            "offset": 51,
            "timeout": 25,
            "allowed_updates": ["message", "callback_query"],
        }
        return response(
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 51,
                        "message": {
                            "message_id": 8,
                            "date": 1_700_000_000,
                            "chat": CHAT,
                            "from": STUDENT_USER,
                            "text": "/start",
                        },
                    }
                ],
            }
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as client:
        updates = await client.get_updates(offset=51, poll_timeout=25)

    assert updates[0].message is not None
    assert updates[0].message.sender is not None
    assert updates[0].message.sender.id == 2002


async def test_send_message_parses_result() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"chat_id": 2002, "text": "Hello"}
        return response(
            {
                "ok": True,
                "result": {
                    "message_id": 9,
                    "date": 1_700_000_001,
                    "chat": CHAT,
                    "from": BOT_USER,
                    "text": "Hello",
                },
            }
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as client:
        message = await client.send_message(2002, "Hello")

    assert message.text == "Hello"


async def test_send_message_includes_optional_formatting() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["parse_mode"] == "HTML"
        assert payload["reply_markup"]["resize_keyboard"] is True
        assert payload["link_preview_options"] == {
            "url": "https://vimeo.com/123456789",
            "prefer_large_media": True,
        }
        return response(
            {
                "ok": True,
                "result": {
                    "message_id": 10,
                    "date": 1_700_000_002,
                    "chat": CHAT,
                    "text": "<b>Hello</b>",
                },
            }
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as client:
        message = await client.send_message(
            2002,
            "<b>Hello</b>",
            parse_mode="HTML",
            reply_markup={"resize_keyboard": True},
            link_preview_options={
                "url": "https://vimeo.com/123456789",
                "prefer_large_media": True,
            },
        )

    assert message.text == "<b>Hello</b>"


async def test_send_photo_uses_https_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sendPhoto")
        assert json.loads(request.content) == {
            "chat_id": 2002,
            "photo": "https://i.vimeocdn.com/video/cover.jpg",
            "caption": "<b>Lesson</b>",
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": []},
        }
        return response(
            {
                "ok": True,
                "result": {
                    "message_id": 11,
                    "date": 1_700_000_003,
                    "chat": CHAT,
                    "photo": [
                        {
                            "file_id": "cover-id",
                            "file_unique_id": "cover-unique",
                            "width": 1280,
                            "height": 720,
                        }
                    ],
                },
            }
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as client:
        message = await client.send_photo(
            2002,
            "https://i.vimeocdn.com/video/cover.jpg",
            caption="<b>Lesson</b>",
            parse_mode="HTML",
            reply_markup={"inline_keyboard": []},
        )

    assert message.photo[0].width == 1280


async def test_send_photo_file_uploads_multipart(tmp_path: Path) -> None:
    image_path = tmp_path / "1.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nmock-image")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sendPhoto")
        assert "multipart/form-data" in request.headers["content-type"]
        assert b"1.png" in request.content
        assert b"\x89PNG" in request.content
        return response(
            {
                "ok": True,
                "result": {
                    "message_id": 12,
                    "date": 1_700_000_004,
                    "chat": CHAT,
                    "photo": [
                        {
                            "file_id": "chart-id",
                            "file_unique_id": "chart-unique",
                            "width": 2048,
                            "height": 1080,
                        }
                    ],
                },
            }
        )

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as client:
        message = await client.send_photo_file(2002, image_path, caption="Chart")

    assert message.photo[0].width == 2048


async def test_edit_message_text_includes_inline_keyboard() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/editMessageText")
        payload = json.loads(request.content)
        assert payload == {
            "chat_id": 2002,
            "message_id": 10,
            "text": "Updated",
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": []},
        }
        return response({"ok": True, "result": True})

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as client:
        await client.edit_message_text(
            2002,
            10,
            "Updated",
            parse_mode="HTML",
            reply_markup={"inline_keyboard": []},
        )


async def test_copy_message_keeps_media_inside_telegram() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/copyMessage")
        assert json.loads(request.content) == {
            "chat_id": 2002,
            "from_chat_id": 3003,
            "message_id": 44,
        }
        return response({"ok": True, "result": {"message_id": 45}})

    async with TelegramBotClient("token", transport=httpx.MockTransport(handler)) as client:
        await client.copy_message(2002, 3003, 44)


async def test_api_error_is_sanitized() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return response({"ok": False, "error_code": 401, "description": "Unauthorized"})

    token = "123456:must-not-leak"
    async with TelegramBotClient(token, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TelegramAPIError) as error:
            await client.get_me()

    assert error.value.error_code == 401
    assert token not in str(error.value)


async def test_transport_error_is_sanitized() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    token = "123456:must-not-leak"
    async with TelegramBotClient(token, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TelegramTransportError) as error:
            await client.get_me()

    assert token not in str(error.value)
