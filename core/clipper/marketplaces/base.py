"""The marketplace interface every adapter implements (PLAN §15.1). Agents never see marketplace specifics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

Deliverable = Literal["link", "upload"]
ContentType = Literal["clipping", "ugc", "other"]
JoinKind = Literal["free", "paid", "joined", "none"]


@dataclass(frozen=True)
class CampaignCard:
    marketplace: str
    external_id: str
    title: str
    cpm_usd: float
    brand: str | None = None
    creator: str | None = None
    url: str | None = None
    budget_total: float | None = None
    budget_left: float | None = None
    cap_per_post: float | None = None
    min_views_to_pay: int | None = None
    allowed_platforms: list[str] = field(default_factory=lambda: [])
    deliverable: Deliverable = "link"
    content_type: ContentType = "clipping"
    tracking_window_days: int | None = None
    deadline: datetime | None = None
    join: JoinKind = "none"
    payouts_ended: bool = False  # the marketplace says no more payouts: nothing posted now can earn


@dataclass(frozen=True)
class CampaignDetail:
    card: CampaignCard
    rules_raw: str  # third-party text: untrusted
    sources: list[str] = field(default_factory=lambda: [])


@dataclass(frozen=True)
class JoinResult:
    status: Literal["joined", "already", "needs_user"]
    detail: str = ""


@dataclass(frozen=True)
class SubmitResult:
    submission_id: str
    status: str = "pending"


@dataclass(frozen=True)
class SubmissionState:
    status: Literal["pending", "approved", "rejected", "paid"]
    reason: str | None = None


@dataclass(frozen=True)
class PayoutRow:
    external_campaign_id: str
    post_url: str | None
    amount_usd: float
    views: int | None
    ts: datetime


SessionState = Literal["ok", "needs_login"]


class MarketplaceError(RuntimeError):
    def __init__(self, message: str, *, challenge: str | None = None, screenshot: str | None = None) -> None:
        super().__init__(message)
        self.challenge = challenge
        self.screenshot = screenshot


class MarketplaceAdapter(Protocol):
    name: str

    async def session_check(self) -> SessionState: ...
    async def list_campaigns(self) -> list[CampaignCard]: ...
    async def get_campaign(self, external_id: str) -> CampaignDetail: ...
    async def join_campaign(self, external_id: str) -> JoinResult: ...
    async def submit_post(self, external_id: str, post_url: str) -> SubmitResult: ...
    async def submission_status(self, submission_id: str) -> SubmissionState: ...
    async def earnings(self, since: datetime) -> list[PayoutRow]: ...
