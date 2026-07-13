"""Small direct async Discord REST client."""

from typing import Any

import httpx
from pydantic import SecretStr


class DiscordAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DiscordAPIClient:
    def __init__(self, token: SecretStr | str) -> None:
        value = token.get_secret_value() if isinstance(token, SecretStr) else token
        if not value:
            raise ValueError("Discord bot token is empty")
        self._client = httpx.AsyncClient(
            base_url="https://discord.com/api/v10/",
            headers={"Authorization": f"Bot {value}"},
            timeout=30,
        )

    async def __aenter__(self) -> "DiscordAPIClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def request(
        self, method: str, path: str, *, json: Any | None = None
    ) -> Any:
        try:
            response = await self._client.request(method, path.lstrip("/"), json=json)
        except httpx.HTTPError:
            raise DiscordAPIError("Discord API request failed") from None
        if response.status_code >= 400:
            raise DiscordAPIError(
                f"Discord API returned {response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
            )
        if response.status_code == 204:
            return None
        return response.json()

    async def current_user(self) -> dict[str, Any]:
        return await self.request("GET", "users/@me")

    async def gateway_url(self) -> str:
        payload = await self.request("GET", "gateway/bot")
        return str(payload["url"])

    async def guild(self, guild_id: int) -> dict[str, Any]:
        return await self.request("GET", f"guilds/{guild_id}")

    async def guild_channels(self, guild_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"guilds/{guild_id}/channels")

    async def create_channel(self, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"guilds/{guild_id}/channels", json=payload)

    async def channel_message(self, channel_id: int, message_id: int) -> dict[str, Any]:
        return await self.request("GET", f"channels/{channel_id}/messages/{message_id}")

    async def send_channel_message(
        self, channel_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.request("POST", f"channels/{channel_id}/messages", json=payload)

    async def edit_channel_message(
        self, channel_id: int, message_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.request(
            "PATCH", f"channels/{channel_id}/messages/{message_id}", json=payload
        )

    async def create_private_thread(
        self, parent_channel_id: int, name: str
    ) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"channels/{parent_channel_id}/threads",
            json={
                "name": name,
                "type": 12,
                "auto_archive_duration": 1440,
                "invitable": False,
            },
        )

    async def add_thread_member(self, thread_id: int, user_id: int) -> None:
        await self.request(
            "PUT", f"channels/{thread_id}/thread-members/{user_id}"
        )

    async def set_member_channel_permissions(
        self,
        channel_id: int,
        user_id: int,
        *,
        allow: int,
        deny: int = 0,
    ) -> None:
        await self.request(
            "PUT",
            f"channels/{channel_id}/permissions/{user_id}",
            json={"type": 1, "allow": str(allow), "deny": str(deny)},
        )

    async def register_guild_commands(
        self, application_id: int, guild_id: int, commands: list[dict[str, Any]]
    ) -> None:
        await self.request(
            "PUT",
            f"applications/{application_id}/guilds/{guild_id}/commands",
            json=commands,
        )

    async def respond_interaction(
        self, interaction_id: str, token: str, content: str
    ) -> None:
        await self.request(
            "POST",
            f"interactions/{interaction_id}/{token}/callback",
            json={
                "type": 4,
                "data": {"content": content, "flags": 64},
            },
        )

    async def defer_message_update(self, interaction_id: str, token: str) -> None:
        """Acknowledge a component click without creating a visible message."""
        await self.request(
            "POST",
            f"interactions/{interaction_id}/{token}/callback",
            json={"type": 6},
        )

    async def followup(self, application_id: str, token: str, content: str) -> None:
        await self.request(
            "POST",
            f"webhooks/{application_id}/{token}",
            json={"content": content, "flags": 64},
        )
