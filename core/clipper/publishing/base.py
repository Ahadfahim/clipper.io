"""The publishing interface (YouTube Shorts, TikTok, Instagram Reels, X)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class UploadRequest:
    platform: str
    account_id: int
    handle: str
    chrome_profile: str
    video: Path
    title: str = ""
    caption: str = ""
    hashtags: list[str] = field(default_factory=lambda: [])
    schedule_at: datetime | None = None  # None = publish now
    dry_run: bool = False


@dataclass(frozen=True)
class UploadResult:
    ok: bool
    url: str | None = None
    challenge: str | None = None  # login | captcha | verification -> pause the account
    error: str | None = None
    screenshot: str | None = None
    failed_step: int | None = None


@dataclass(frozen=True)
class PostMetrics:
    views: int
    likes: int = 0
    comments: int = 0
    shares: int = 0


@dataclass(frozen=True)
class AccountHealth:
    followers: int | None
    recent_views: int | None
    warnings: list[str] = field(default_factory=lambda: [])


class PublishAdapter(Protocol):
    async def upload(self, req: UploadRequest) -> UploadResult: ...
    async def metrics(self, url: str) -> PostMetrics: ...
    async def account_health(self, platform: str, handle: str) -> AccountHealth: ...


RECIPES: dict[str, str] = {
    "youtube": "youtube.upload_short",
    "tiktok": "tiktok.upload",
    "instagram": "instagram.upload_reel",
    "x": "x.post_video",
}
