"""Trend sources. ``YtDlpTrends`` searches YouTube via yt-dlp (network, LOCAL-VERIFY); ``FakeTrends`` for tests."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Protocol

from clipper.settings import Settings


@dataclass(frozen=True)
class TrendItem:
    title: str
    url: str
    views: int | None
    channel: str | None = None


@dataclass(frozen=True)
class Saturation:
    existing_clips: int
    covered_ranges: list[tuple[float, float]] = field(
        default_factory=lambda: []
    )  # source seconds already clipped
    examples: list[TrendItem] = field(default_factory=lambda: [])


class TrendsSource(Protocol):
    def search(self, query: str, limit: int = 20) -> list[TrendItem]: ...
    def saturation(self, source_title: str, source_url: str) -> Saturation: ...


_HASHTAG = re.compile(r"#(\w{2,30})")


def hashtags_from(items: list[TrendItem], top: int = 12) -> list[str]:
    counts: dict[str, int] = {}
    for it in items:
        for tag in _HASHTAG.findall(it.title):
            counts[tag.lower()] = counts.get(tag.lower(), 0) + 1 + (it.views or 0) // 1_000_000
    return ["#" + t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:top]]


class FakeTrends:
    def __init__(self, items: list[TrendItem] | None = None, saturation: Saturation | None = None) -> None:
        self.items = items or [
            TrendItem("He did WHAT? #mrbeast #shorts", "https://youtube.com/shorts/a", 2_400_000, "clips"),
            TrendItem("Best moment #podcast #shorts #viral", "https://youtube.com/shorts/b", 800_000, "pods"),
            TrendItem("Wait for it #mrbeast", "https://youtube.com/shorts/c", 1_100_000, "clips2"),
        ]
        self._saturation = saturation or Saturation(2, [(12.0, 40.0)], self.items[:2])

    def search(self, query: str, limit: int = 20) -> list[TrendItem]:
        return self.items[:limit]

    def saturation(self, source_title: str, source_url: str) -> Saturation:
        return self._saturation


class YtDlpTrends:
    """``ytsearchN:<query>`` with --flat-playlist (titles, views, urls). LOCAL-VERIFY (network)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search(self, query: str, limit: int = 20) -> list[TrendItem]:  # LOCAL-VERIFY
        proc = subprocess.run(
            [
                self.settings.paths.yt_dlp,
                "--flat-playlist",
                "--dump-single-json",
                "--no-warnings",
                f"ytsearch{limit}:{query}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip()[-300:])
        data: dict[str, Any] = json.loads(proc.stdout or "{}")
        entries: list[dict[str, Any]] = list(data.get("entries") or [])
        return [
            TrendItem(
                str(e.get("title", "")),
                str(e.get("url") or e.get("webpage_url") or ""),
                e.get("view_count"),
                e.get("channel"),
            )
            for e in entries
        ]

    def saturation(self, source_title: str, source_url: str) -> Saturation:  # LOCAL-VERIFY
        items = self.search(f"{source_title} shorts", 30)
        words = {w for w in re.findall(r"\w{4,}", source_title.lower())}
        related = [it for it in items if len(words & set(re.findall(r"\w{4,}", it.title.lower()))) >= 2]
        return Saturation(len(related), [], related[:5])
