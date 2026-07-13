"""Small asynchronous Vimeo oEmbed metadata client."""

from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class VimeoMetadata:
    thumbnail_url: str


class VimeoOEmbedClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://vimeo.com/",
            timeout=httpx.Timeout(8.0),
            transport=transport,
        )
        self._cache: dict[str, VimeoMetadata | None] = {}

    async def __aenter__(self) -> "VimeoOEmbedClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def get_metadata(self, video_url: str) -> VimeoMetadata | None:
        if video_url in self._cache:
            return self._cache[video_url]
        try:
            response = await self._client.get(
                "api/oembed.json",
                params={"url": video_url, "width": 1280},
            )
            response.raise_for_status()
            payload = response.json()
            thumbnail_url = payload.get("thumbnail_url_with_play_button") or payload.get(
                "thumbnail_url"
            )
            metadata = (
                VimeoMetadata(thumbnail_url=thumbnail_url)
                if isinstance(thumbnail_url, str) and thumbnail_url.startswith("https://")
                else None
            )
        except (httpx.HTTPError, ValueError, TypeError):
            metadata = None
        self._cache[video_url] = metadata
        return metadata
