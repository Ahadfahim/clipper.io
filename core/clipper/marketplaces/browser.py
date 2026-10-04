"""Vyro and Whop through the Companion extension's recipes (PLAN §15.1). LOCAL-VERIFY.

Every recipe's selectors are UNVERIFIED (written without access to the real sites); the recipe files
live in ``apps/extension/recipes``. Pages are untrusted: this adapter only extracts structured fields;
rules text goes to the brief-reader subagent, never straight into an agent with write tools.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

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
from clipper.marketplaces.docs import fetch_doc_text


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


# dates as sites display them, in the browser's (this PC's) time zone: Vyro's "October 17, 2026, 09:10:00"
_SHOWN_DATES = ("%B %d, %Y, %H:%M:%S", "%B %d, %Y, %H:%M", "%B %d, %Y", "%b %d, %Y")


def _date(v: Any) -> datetime | None:
    if not v:
        return None
    s = str(v).strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        for fmt in _SHOWN_DATES:
            try:
                return datetime.strptime(s, fmt).astimezone(UTC)  # naive = local time
            except ValueError:
                continue
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _join(v: Any) -> Literal["free", "paid", "joined", "none"]:
    """Join state from the join button's label: "Joined"/"Submit post" (already in), "Join free" and
    Vyro's "Join campaign" (free), "Join · $29" (paid)."""
    s = str(v or "").strip().lower()
    if s.startswith("joined") or s.startswith(("submit", "add post")):
        return "joined"
    if "$" in s or "paid" in s:
        return "paid"
    if "free" in s or s.startswith("join"):
        return "free"
    return "none"


def card_from_row(market: str, row: dict[str, Any]) -> CampaignCard:
    """Normalize one scraped campaign row (keys produced by the *.list_campaigns recipes)."""
    raw: Any = row.get("platforms") or []
    # scraped as text ("YouTube, TikTok / Reels") or already a list
    raw_platforms: list[Any] = re.split(r"[,/|·\s]+", raw) if isinstance(raw, str) else list(raw)
    aliases = {
        "yt": "youtube",
        "shorts": "youtube",
        "reels": "instagram",
        "ig": "instagram",
        "tt": "tiktok",
        "twitter": "x",
    }
    platforms = [
        aliases.get(p.strip().lower(), p.strip().lower())
        for p in raw_platforms
        if isinstance(p, str) and p.strip()
    ]
    content = str(row.get("content_type") or "clipping").lower()
    total = _num(row.get("budget_total"))
    left = _num(row.get("budget_left"))
    used = _num(row.get("budget_used"))  # Whop's cards show "$2.3k / $10.5k" (paid out / total)
    if left is None and total is not None and used is not None:
        left = max(total - used, 0.0)
    # Vyro shows "% paid out" instead of a dollar budget; at 100% (or "Payouts ended") nothing can earn
    pct = _num(row.get("paid_out_pct"))
    ended = (pct is not None and pct >= 100) or "ended" in str(row.get("state") or "").lower()
    if ended:
        left = 0.0
    return CampaignCard(
        marketplace=market,
        external_id=str(row["id"]),
        title=str(row.get("title") or row.get("card_title") or row["id"])[:200],
        cpm_usd=_num(row.get("cpm")) or 0.0,
        brand=row.get("brand"),
        creator=row.get("creator") or row.get("brand"),
        url=row.get("url") or row.get("opened_url"),
        budget_total=total,
        budget_left=left,
        cap_per_post=_num(row.get("cap_per_post")),
        min_views_to_pay=int(_num(row.get("min_views")) or 0) or None,
        allowed_platforms=[p for p in platforms if p in ("youtube", "tiktok", "instagram", "x")],
        deliverable="upload" if str(row.get("deliverable", "")).lower() == "upload" else "link",
        content_type=content if content in ("clipping", "ugc") else "other",  # type: ignore[arg-type]
        tracking_window_days=int(_num(row.get("tracking_days")) or 0) or None,
        deadline=_date(row.get("deadline")),
        join=_join(row.get("join")),
        payouts_ended=ended,
    )


class RecipeMarketplace:
    """Generic recipe-backed adapter; Vyro and Whop differ only in recipe names and profile."""

    def __init__(
        self,
        name: str,
        bridge: BrowserBridge,
        profile: str = "main",
        fetch_text: Callable[[str], Awaitable[str | None]] = fetch_doc_text,
    ) -> None:
        self.name = name
        self.bridge = bridge
        self.profile = profile
        self.fetch_text = fetch_text  # linked rule documents (Whop's Google Docs)

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
        row.setdefault("url", res.data.get("page_url"))
        rules = str(res.data.get("rules_text", ""))[:20_000]
        doc = res.data.get("rules_doc")
        if isinstance(doc, str) and doc.startswith("https://"):
            text = await self.fetch_text(doc)
            rules += f"\n\n--- Linked requirements ({doc}) ---\n" + (
                text or "(couldn't be read here: it may be private. Open it to check the rules.)"
            )
        links: list[Any] = list(res.data.get("sources") or [])
        return CampaignDetail(
            card_from_row(self.name, row),
            rules,
            [u for u in links if isinstance(u, str) and u != doc and not self._own_page(u)],
        )

    def _own_page(self, url: str) -> bool:
        """The marketplace's own help/support links aren't campaign sources."""
        host = (urlsplit(url).hostname or "").lower()
        return host == f"{self.name}.com" or host.endswith(f".{self.name}.com")

    async def join_campaign(self, external_id: str) -> JoinResult:  # LOCAL-VERIFY
        if self.name == "whop":
            # Content Rewards has no join step: every campaign page offers "Submit clip" directly
            return JoinResult("already", "Whop Content Rewards has no join step; submit clips directly")
        res = await self.bridge.run_recipe(self.profile, f"{self.name}.join_campaign", {"id": external_id})
        if not res.ok and (res.error or "").startswith("unknown recipe"):
            return JoinResult(
                "needs_user",
                f"Clipper can't join on {self.name} yet: the user joins this campaign on the site",
            )
        if not res.ok:
            raise MarketplaceError(
                f"{self.name}.join_campaign failed: {res.error}",
                challenge=res.challenge,
                screenshot=res.screenshot,
            )
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
