"""Uploads through the Companion extension's recipes; metrics from public pages via yt-dlp. LOCAL-VERIFY."""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

from clipper.browser.bridge import BrowserBridge
from clipper.publishing.base import RECIPES, AccountHealth, PostMetrics, UploadRequest, UploadResult
from clipper.settings import Settings


class BrowserPublisher:
    def __init__(self, bridge: BrowserBridge, settings: Settings, file_url: str) -> None:
        self.bridge = bridge
        self.settings = settings
        self.file_url = file_url  # e.g. http://127.0.0.1:8765/api/files/clip/{clip_id}/final

    async def upload(self, req: UploadRequest) -> UploadResult:  # LOCAL-VERIFY
        recipe = RECIPES[req.platform]
        params: dict[str, Any] = {
            "file_url": self.file_url,
            "file_name": req.video.name,
            "title": req.title,
            "caption": req.caption,
            "hashtags": req.hashtags,
            "schedule_at": req.schedule_at.isoformat() if req.schedule_at else None,
            "handle": req.handle,
        }
        res = await self.bridge.run_recipe(req.chrome_profile, recipe, params, dry_run=req.dry_run)
        if res.ok:
            url = res.data.get("post_url")
            if not url:
                return UploadResult(
                    ok=False,
                    error="upload finished but the post URL was not found",
                    screenshot=res.screenshot,
                )
            return UploadResult(ok=True, url=str(url))
        return UploadResult(
            ok=False,
            challenge=res.challenge,
            error=res.error,
            screenshot=res.screenshot,
            failed_step=res.step,
        )

    async def metrics(self, url: str) -> PostMetrics:  # LOCAL-VERIFY (network)
        def run() -> dict[str, Any]:
            proc = subprocess.run(
                [self.settings.paths.yt_dlp, "--skip-download", "--dump-single-json", "--no-warnings", url],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip()[-300:])
            return json.loads(proc.stdout or "{}")

        info = await asyncio.to_thread(run)
        return PostMetrics(
            views=int(info.get("view_count") or 0),
            likes=int(info.get("like_count") or 0),
            comments=int(info.get("comment_count") or 0),
            shares=int(info.get("repost_count") or 0),
        )

    async def account_health(self, platform: str, handle: str) -> AccountHealth:  # LOCAL-VERIFY
        res = await self.bridge.run_recipe("main", f"{platform}.account_health", {"handle": handle})
        if not res.ok:
            return AccountHealth(None, None, [f"health check failed: {res.error}"])
        return AccountHealth(
            res.data.get("followers"), res.data.get("recent_views"), list(res.data.get("warnings", []))
        )
