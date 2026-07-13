"""Vimeo oEmbed client tests."""

import httpx

from course_platform.integrations.vimeo import VimeoOEmbedClient


async def test_oembed_returns_and_caches_thumbnail() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/api/oembed.json"
        assert request.url.params["url"] == "https://vimeo.com/1196958528"
        return httpx.Response(
            200,
            json={
                "thumbnail_url": "https://i.vimeocdn.com/video/plain.jpg",
                "thumbnail_url_with_play_button": (
                    "https://i.vimeocdn.com/video/with-play.jpg"
                ),
            },
        )

    async with VimeoOEmbedClient(transport=httpx.MockTransport(handler)) as client:
        first = await client.get_metadata("https://vimeo.com/1196958528")
        second = await client.get_metadata("https://vimeo.com/1196958528")

    assert first is not None
    assert first.thumbnail_url == "https://i.vimeocdn.com/video/with-play.jpg"
    assert second == first
    assert calls == 1


async def test_oembed_failure_returns_none() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with VimeoOEmbedClient(transport=httpx.MockTransport(handler)) as client:
        assert await client.get_metadata("https://vimeo.com/missing") is None
