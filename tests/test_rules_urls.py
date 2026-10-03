from __future__ import annotations

import pytest

from clipper.rules.urls import canonical_source, domain_allowed, source_whitelisted, youtube_id


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=xyz", "dQw4w9WgXcQ"),
        ("https://youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/@MrBeast", None),
        ("https://notyoutube.com/watch?v=dQw4w9WgXcQ", None),
    ],
)
def test_youtube_id(url: str, expected: str | None) -> None:
    assert youtube_id(url) == expected


def test_canonical_source_strips_tracking() -> None:
    assert canonical_source("https://www.tiktok.com/@a/video/123?lang=en") == "tiktok:123"
    assert canonical_source("https://Example.com/v/1/?utm_source=x&b=2&a=1") == "example.com/v/1?a=1&b=2"


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://studio.youtube.com/channel/x", True),
        ("https://www.tiktok.com/upload", True),
        ("https://tiktok.com.evil.io/", False),
        ("https://eviltiktok.com/", False),
        ("javascript:alert(1)", False),
        ("chrome://settings", False),
        ("https://whop.com/discover", True),
    ],
)
def test_domain_allowed(url: str, ok: bool) -> None:
    assert domain_allowed(url, ["studio.youtube.com", "tiktok.com", "whop.com"]) is ok


def test_source_whitelisted_rejects_non_http() -> None:
    assert not source_whitelisted("file:///etc/passwd", ["file:///etc/passwd"])
    assert source_whitelisted("http://youtu.be/dQw4w9WgXcQ", ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
