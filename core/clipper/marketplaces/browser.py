"""Vyro and Whop through the Companion extension's recipes (PLAN §15.1). LOCAL-VERIFY.

Every recipe's selectors are UNVERIFIED (written without access to the real sites); the recipe files
live in ``apps/extension/recipes``. Pages are untrusted: this adapter only extracts structured fields;
rules text goes to the brief-reader subagent, never straight into an agent with write tools.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from clipper.browser.bridge import BrowserBridge
from clipper.browser.protocol import RecipeResult
from clipper.marketplaces.base import (
    CampaignCard,
    CampaignDetail,
    JoinResult,
    MarketplaceError,
    PayoutRow,
    SessionState,
    SubmissionState,
    SubmitResult,
)


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, int | float):
        return float(v)
    s = str(v).replace("$", "").replace(",", "").strip().lower()
    mult = 1.0
    if s.endswith("k"):
        mult, s = 1000.0, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _date(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def card_from_row(market: str, row: dict[str, Any]) -> CampaignCard:
    """Normalize one scraped campaign row (keys produced by the *.list_campaigns recipes)."""
    platforms = [p.strip().lower() for p in row.get("platforms", []) if isinstance(p, str)]
    content = str(row.get("content_type") or "clipping").lower()
    return CampaignCard(
        marketplace=market,
        external_id=str(row["id"]),
        title=str(row.get("title") or row["id"])[:200],
        cpm_usd=_num(row.get("cpm")) or 0.0,
        brand=row.get("brand"),
        creator=row.get("creator") or row.get("brand"),
        url=row.get("url"),
        budget_total=_num(row.get("budget_total")),
        budget_left=_num(row.get("budget_left")),
        cap_per_post=_num(row.get("cap_per_post")),
        min_views_to_pay=int(_num(row.get("min_views")) or 0) or None,
        allowed_platforms=[p for p in platforms if p in ("youtube", "tiktok", "instagram", "x")],
        deliverable="upload" if str(row.get("deliverable", "")).lower() == "upload" else "link",
        content_type=content if content in ("clipping", "ugc") else "other",  # type: ignore[arg-type]
        tracking_window_days=int(_num(row.get("tracking_days")) or 0) or None,
        deadline=_date(row.get("deadline")),
        join=row.get("join", "none") if row.get("join") in ("free", "paid", "joined") else "none",
    )


class RecipeMarketplace:
    """Generic recipe-backed adapter; Vyro and Whop differ only in recipe names and profile."""

    def __init__(self, name: str, bridge: BrowserBridge, profile: str = "main") -> None:
        self.name = name
        self.bridge = bridge
        self.profile = profile

    async def _run(self, recipe: str, params: dict[str, Any] | None = None) -> RecipeResult:
        res = await self.bridge.run_recipe(self.profile, f"{self.name}.{recipe}", params or {})
        if not res.ok:
            raise MarketplaceError(
                f"{self.name}.{recipe} failed: {res.error}",
                challenge=res.challenge,
                screenshot=res.screenshot,
            )
        return res

    async def session_check(self) -> SessionState:  # LOCAL-VERIFY
        res = await self.bridge.run_recipe(self.profile, f"{self.name}.session_check", {})
        return "ok" if res.ok and res.data.get("logged_in") else "needs_login"

    async def list_campaigns(self) -> list[CampaignCard]:  # LOCAL-VERIFY
        res = await self._run("list_campaigns")
        rows: list[dict[str, Any]] = [r for r in res.data.get("campaigns", []) if isinstance(r, dict)]
        return [card_from_row(self.name, r) for r in rows if r.get("id")]

    async def get_campaign(self, external_id: str) -> CampaignDetail:  # LOCAL-VERIFY
        res = await self._run("get_campaign", {"id": external_id})
        row = dict(res.data.get("campaign") or {})
        row.setdefault("id", external_id)
        return CampaignDetail(
            card_from_row(self.name, row),
            str(res.data.get("rules_text", ""))[:20_000],
            list(res.data.get("sources", [])),
        )

    async def join_campaign(self, external_id: str) -> JoinResult:  # LOCAL-VERIFY
        res = await self._run("join_campaign", {"id": external_id})
        status = str(res.data.get("status", "needs_user"))
        if status in ("joined", "already"):
            return JoinResult(status)  # type: ignore[arg-type]
        return JoinResult("needs_user", str(res.data.get("detail", "")))

    async def submit_post(self, external_id: str, post_url: str) -> SubmitResult:  # LOCAL-VERIFY
        res = await self._run("submit_url", {"id": external_id, "url": post_url})
        return SubmitResult(
            str(res.data.get("submission_id") or f"{external_id}:{post_url}"),
            str(res.data.get("status", "pending")),
        )

    async def submission_status(self, submission_id: str) -> SubmissionState:  # LOCAL-VERIFY
        res = await self._run("submission_status", {"submission_id": submission_id})
        status = str(res.data.get("status", "pending"))
        if status not in ("pending", "approved", "rejected", "paid"):
            status = "pending"
        return SubmissionState(status, res.data.get("reason"))  # type: ignore[arg-type]

    async def earnings(self, since: datetime) -> list[PayoutRow]:  # LOCAL-VERIFY
        res = await self._run("earnings", {"since": since.isoformat()})
        rows: list[PayoutRow] = []
        payouts: list[dict[str, Any]] = list(res.data.get("payouts", []))
        for r in payouts:
            ts = _date(r.get("date")) or datetime.now(UTC)
            rows.append(
                PayoutRow(
                    str(r.get("campaign_id", "")),
                    r.get("post_url"),
                    _num(r.get("amount")) or 0.0,
                    r.get("views"),
                    ts,
                )
            )
        return rows
