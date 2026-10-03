"""Trends service: niche trends, hashtags, saturation of a source, best post times (PLAN §16.1 trends)."""

from __future__ import annotations

from typing import Any

from clipper.services.base import Service, ServiceError
from clipper.trends.source import hashtags_from

DEFAULT_TIMES = {
    "youtube": ["12:00", "15:00", "19:00"],
    "tiktok": ["11:00", "19:00", "21:00"],
    "instagram": ["11:00", "13:00", "19:00"],
    "x": ["09:00", "12:00", "17:00"],
}


class TrendsService(Service):
    def niche_trends(self, niche: str, limit: int = 10) -> list[dict[str, Any]]:
        items = self.core.adapters.trends.search(f"{niche} shorts", limit)
        return [{"title": i.title[:120], "url": i.url, "views": i.views, "channel": i.channel} for i in items]

    def hashtags(self, niche: str, platform: str) -> list[str]:
        items = self.core.adapters.trends.search(f"{niche} {platform}", 30)
        return hashtags_from(items)

    def saturation(self, source_id: int) -> dict[str, Any]:
        src = self.core.media.source(source_id)
        sat = self.core.adapters.trends.saturation(src.title or src.url, src.url)
        return {
            "source_id": source_id,
            "existing_clips": sat.existing_clips,
            "covered_ranges": [list(r) for r in sat.covered_ranges],
            "examples": [{"title": e.title[:100], "views": e.views} for e in sat.examples[:5]],
        }

    def best_post_times(self, account_id: int) -> dict[str, Any]:
        accounts = {a["id"]: a for a in self.core.publishing.list_accounts()}
        account = accounts.get(account_id)
        if account is None:
            raise ServiceError(f"account {account_id} not found")
        rows = self.core.insights.performance_by("hour", days=60)
        own = [r for r in rows if r["key"] is not None and r["posts"] >= 2]
        if len(own) >= 3:
            best = sorted(own, key=lambda r: -(r["views"] / max(r["posts"], 1)))[:3]
            return {
                "account_id": account_id,
                "source": "own history",
                "times": [f"{int(r['key']):02d}:00" for r in best],
            }
        return {
            "account_id": account_id,
            "source": "platform defaults",
            "times": DEFAULT_TIMES.get(account["platform"], ["12:00", "19:00"]),
        }
