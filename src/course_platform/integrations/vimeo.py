"""Small asynchronous Vimeo oEmbed metadata client."""

import re
from dataclasses import dataclass

import httpx

_WATCH_URL = re.compile(
    r"^https?://(?:www\.)?vimeo\.com/(\d+)(?:/([0-9a-fA-F]+))?/?(?:[?#].*)?$"
)


def vimeo_watch_url(video_reference: str) -> str:
    """Return a link that plays even for embed-only («Hide from Vimeo») videos.

    The vimeo.com page of such videos answers 404 to everyone but the account
    owner, while the player page stays reachable, so students get the player.
    """
    match = _WATCH_URL.match(video_reference.strip())
    if match is None:
        return video_reference
    video_id, unlisted_hash = match.groups()
    if unlisted_hash:
        return f"https://player.vimeo.com/video/{video_id}?h={unlisted_hash}"
    return f"https://player.vimeo.com/video/{video_id}"


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
