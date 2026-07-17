"""Vimeo oEmbed client tests."""

import httpx
import pytest

from course_platform.integrations.vimeo import VimeoOEmbedClient, vimeo_watch_url


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (
            "https://vimeo.com/1196958528?share=copy&fl=sv&fe=ci",
            "https://player.vimeo.com/video/1196958528",
        ),
        ("https://vimeo.com/1196958528", "https://player.vimeo.com/video/1196958528"),
        ("http://www.vimeo.com/42", "https://player.vimeo.com/video/42"),
        (
            "https://vimeo.com/1196958528/abc123DEF0",
            "https://player.vimeo.com/video/1196958528?h=abc123DEF0",
        ),
        (
            "https://vimeo.com/1196958528/abc123DEF0?share=copy",
            "https://player.vimeo.com/video/1196958528?h=abc123DEF0",
        ),
        (" https://vimeo.com/77/ ", "https://player.vimeo.com/video/77"),
    ],
)
def test_watch_url_rewrites_video_pages_to_player(reference: str, expected: str) -> None:
    assert vimeo_watch_url(reference) == expected


@pytest.mark.parametrize(
    "reference",
    [
        "https://youtu.be/xyz",
        "https://vimeo.com/channels/staffpicks/123",
        "https://player.vimeo.com/video/1196958528",
        "not a url",
    ],
)
def test_watch_url_leaves_other_references_untouched(reference: str) -> None:
    assert vimeo_watch_url(reference) == reference


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
