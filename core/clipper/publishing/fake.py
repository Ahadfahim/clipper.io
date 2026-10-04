"""Fake publisher: records uploads, returns plausible URLs, can be told to hit a challenge."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from clipper.publishing.base import AccountHealth, PostMetrics, UploadRequest, UploadResult


@dataclass
class FakePublisher:
    uploads: list[UploadRequest] = field(default_factory=lambda: [])
    challenge_for: set[str] = field(default_factory=lambda: set[str]())  # handles that hit a challenge
    fail_for: set[str] = field(default_factory=lambda: set[str]())
    views: dict[str, int] = field(default_factory=lambda: {})
    _ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    async def upload(self, req: UploadRequest) -> UploadResult:
        self.uploads.append(req)
        if req.handle in self.challenge_for:
            return UploadResult(
                ok=False,
                challenge="verification",
                error="verify it's you",
                screenshot="data:image/png;base64,",
            )
        if req.handle in self.fail_for:
            return UploadResult(
                ok=False, error="upload button not found", failed_step=3, screenshot="data:image/png;base64,"
            )
        n = next(self._ids)
        url = {
            "youtube": f"https://youtube.com/shorts/fake{n:07d}",
            "tiktok": f"https://www.tiktok.com/@{req.handle.lstrip('@')}/video/7{n:018d}",
            "instagram": f"https://www.instagram.com/reel/FAKE{n:07d}/",
            "x": f"https://x.com/{req.handle.lstrip('@')}/status/1{n:018d}",
        }[req.platform]
        return UploadResult(ok=True, url=url)

    async def metrics(self, url: str) -> PostMetrics:
        return PostMetrics(views=self.views.get(url, 1234), likes=56, comments=7, shares=3)

    async def account_health(self, platform: str, handle: str) -> AccountHealth:
        return AccountHealth(followers=1200, recent_views=45_000)
