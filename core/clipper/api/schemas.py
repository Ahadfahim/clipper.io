"""Response and request models. They define the OpenAPI schema the TS client is generated from."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clipper.rules.spec import ClipSpec


class M(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)


# ---------------------------------------------------------------- system


class ControlState(M):
    paused: bool
    dry_run: bool
    kill_switch: bool
    slots: int | None
    auto_approve_tier: int | None


class UsageOut(M):
    utilization: float
    resets_at: str | None
    rate_limited: bool
    max_slots: int
    pace: str


class MarketSwitch(M):
    name: str
    enabled: bool
    session_ok: bool
    mode: str


class SocialSwitch(M):
    name: str
    enabled: bool
    accounts: int


class AccountSwitch(M):
    id: int
    platform: str
    handle: str
    enabled: bool
    status: str
    paused_reason: str | None


class SwitchesOut(M):
    marketplaces: dict[str, MarketSwitch]
    socials: dict[str, SocialSwitch]
    accounts: list[AccountSwitch]


class StatusOut(M):
    version: str
    fixture_mode: bool
    control: ControlState
    usage: UsageOut
    agents_running: int
    agents_capacity: int
    jobs_running: int
    jobs_queued: int
    gpu_util: float | None
    extension_profiles: list[str]
    discord_online: bool
    earned_today: float
    needs_you: int
    review_pending: int
    campaigns_by_market: dict[str, int]
    library_count: int


class ControlIn(BaseModel):
    key: Literal["dry_run", "paused", "kill_switch", "slots", "auto_approve_tier"]
    value: Any
    via: str = "app"


class SwitchIn(BaseModel):
    level: Literal["marketplace", "social", "account"]
    name: str
    enabled: bool
    on_active: Literal["finish", "pause"] = "finish"
    on_scheduled: Literal["cancel", "keep"] = "keep"
    via: str = "app"


class SwitchResult(M):
    ok: bool
    needs_setup: str | None = None
    effects: dict[str, Any] = Field(default_factory=dict)


class SwitchPreview(M):
    active_campaigns: int | None = None
    scheduled_posts: int | None = None


class HealthItem(M):
    name: str
    status: Literal["ok", "warn", "fail", "skip"]
    detail: str
    fix: str = ""


class OkOut(M):
    ok: bool = True
    id: int | None = None
    detail: str | None = None


# ---------------------------------------------------------------- overview


class NeedsYouAction(M):
    label: str
    action: str  # client-side action key, e.g. "review", "take", "skip", "answer", "open_profile", "resume_account"
    args: dict[str, Any] = Field(default_factory=dict)


class NeedsYouItem(M):
    kind: Literal["challenge", "question", "review", "campaign", "failure"]
    urgency: int
    title: str
    detail: str
    actions: list[NeedsYouAction]


class Kpi(M):
    key: str
    label: str
    value: float
    display: str
    delta_pct: float | None = None
    spark: list[float] = Field(default_factory=list[float])
    split: dict[str, float] | None = None
    unit: str | None = None


class Stage(M):
    name: str
    state: Literal["done", "active", "todo"]


class ActiveCampaign(M):
    id: int
    title: str
    marketplace: str
    status: str
    stages: list[Stage]
    budget_left: float | None
    budget_total: float | None
    runs_out_at: datetime | None
    deadline: datetime | None


class UpcomingPost(M):
    id: int
    account_id: int
    handle: str
    platform: str
    scheduled_at: datetime
    clip_id: int
    status: str
    thumb_url: str | None


class AgendaEntry(M):
    kind: Literal["request", "wakeup", "post"]
    when: datetime | None
    text: str
    priority: int | None = None


class NoteOut(M):
    id: int
    scope: str
    scope_id: str | None
    text: str
    author: str
    pinned: bool
    response: str | None
    created_at: datetime


class OverviewOut(M):
    needs_you: list[NeedsYouItem]
    kpis: list[Kpi]
    active_campaigns: list[ActiveCampaign]
    upcoming_posts: list[UpcomingPost]
    agenda: list[AgendaEntry]
    notes: list[NoteOut]
    health: list[HealthItem]
    next_scout_in_s: int | None


# ---------------------------------------------------------------- agents


class SlotOut(M):
    slot: int
    request_id: int | None
    session_id: int | None
    role: str | None
    campaign_id: int | None
    campaign_title: str | None
    kind: str | None
    priority: int | None
    started: datetime | None
    current_tool: str | None
    dimmed: bool


class QueueItem(M):
    request_id: int
    priority: int
    role: str
    kind: str
    campaign_id: int | None
    campaign_title: str | None
    merged: int
    queued_at: datetime


class BoardOut(M):
    capacity: int
    configured_slots: int
    halted: bool
    p01_only: bool
    slots: list[SlotOut]
    queue: list[QueueItem]


class SessionOut(M):
    id: int
    role: str
    campaign_id: int | None
    campaign_title: str | None
    status: str
    turns: int
    max_turns: int
    input_tokens: int
    output_tokens: int
    started: datetime
    last_active: datetime
    summary: str | None
    sdk_session_id: str | None


class AgentEventOut(M):
    id: int
    session_id: int | None
    ts: datetime
    type: str
    tool: str | None
    subagent: str | None
    text: str | None
    input: dict[str, Any]
    output: dict[str, Any]


class SessionDetail(M):
    session: SessionOut
    requests: list[QueueItem]
    events: list[AgentEventOut]


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    via: Literal["dashboard", "discord", "ctrl+k"] = "dashboard"
    reply_to: str | None = None


class ReplayOut(M):
    tool: str
    allowed: bool
    rule: str = ""
    reason: str = ""
    executed: bool = False
    output: dict[str, Any] | None = None
    detail: str = ""


class BumpIn(BaseModel):
    priority: int = Field(ge=0, le=3)


# ---------------------------------------------------------------- campaigns


class CampaignRow(M):
    id: int
    marketplace: str
    title: str
    brand: str | None
    creator: str | None
    status: str
    score: float | None
    cpm: float
    budget_total: float | None
    budget_left: float | None
    runs_out_at: datetime | None
    deadline: datetime | None
    content_type: str
    platforms: list[str]
    matching_accounts: list[str]
    clips_posted: int
    earned: float
    disabled_reason: str | None


class SourceOut(M):
    id: int
    url: str
    title: str | None
    status: str
    duration: float | None
    heatmap: list[float]


class TimelineEntry(M):
    ts: datetime
    type: str
    text: str


class MoneyOut(M):
    views: int
    earnings: float
    posts: int
    submissions: dict[str, int]


class CampaignDetail(M):
    campaign: CampaignRow
    url: str | None
    score_reason: str | None
    payout: dict[str, Any]
    rules_raw: str
    spec: ClipSpec | None
    sources: list[SourceOut]
    session_id: int | None
    timeline: list[TimelineEntry]
    money: MoneyOut


class ManualCampaignIn(BaseModel):
    marketplace: Literal["vyro", "whop"]
    url: str
    title: str | None = None


# ---------------------------------------------------------------- clips / library / review


class ClipRow(M):
    id: int
    campaign_id: int | None
    campaign_title: str | None
    moment_id: int
    score: float
    duration: float | None
    status: str
    layout: str
    caption_style: str
    hook: str
    version: int
    variant_label: str | None
    thumb_url: str | None
    preview_url: str | None
    platforms_posted: list[str]
    views: int
    decision: str | None
    editing_live: bool


class PostOut(M):
    id: int
    clip_id: int
    account_id: int
    handle: str
    platform: str
    scheduled_at: datetime
    posted_at: datetime | None
    url: str | None
    status: str
    dry_run: bool
    views: int
    earnings: float
    error: str | None
    thumb_url: str | None


class WordOut(M):
    t: float
    end: float
    text: str


class ClipDetail(M):
    clip: ClipRow
    source_id: int
    source_title: str | None
    source_range: list[float]
    reason: str
    payoff: str
    scores: dict[str, Any]
    qa: dict[str, Any]
    review: dict[str, Any] | None
    posts: list[PostOut]
    variants: list[ClipRow]
    transcript: list[WordOut]
    signals: dict[str, Any]


class BatchRow(M):
    id: int
    campaign_id: int
    campaign_title: str
    source_title: str | None
    status: str
    total: int
    approved: int
    rejected: int
    pending: int
    created_at: datetime
    timeout_at: datetime | None


class ReviewClip(M):
    clip: ClipRow
    source_range: list[float]
    reason: str
    decision: str
    decision_reason: str | None
    via: str | None
    reviewer: str | None
    platforms_allowed: list[str]
    platforms: list[str]
    captions: dict[str, str]
    qa_ok: bool | None


class BatchDetail(M):
    batch: BatchRow
    clips: list[ReviewClip]
    approve_all_threshold: int


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected", "pending"]
    reason: str | None = None
    platforms: list[str] | None = None
    reviewer: str = "you"
    via: Literal["dashboard", "discord"] = "dashboard"


class ThresholdIn(BaseModel):
    threshold: float = 80
    reviewer: str = "you"
    via: Literal["dashboard", "discord"] = "dashboard"


class RejectRestIn(BaseModel):
    reason: str = "other"
    reviewer: str = "you"
    via: Literal["dashboard", "discord"] = "dashboard"


class ShipIn(BaseModel):
    reviewer: str = "you"
    via: Literal["dashboard", "discord"] = "dashboard"


class CaptionIn(BaseModel):
    platform: Literal["youtube", "tiktok", "instagram", "x"]
    text: str = Field(max_length=2200)
    via: Literal["dashboard", "discord"] = "dashboard"


class RecutIn(BaseModel):
    start_delta: float = Field(default=0.0, ge=-30, le=30)
    end_delta: float = Field(default=0.0, ge=-30, le=30)
    layout: Literal["crop", "split", "fit"] | None = None
    note: str | None = Field(default=None, max_length=500)
    via: Literal["dashboard", "discord"] = "dashboard"


class AutoApproveOffer(M):
    eligible: bool
    offers: list[dict[str, Any]]
    current_tier: int | None


# ---------------------------------------------------------------- edit


class EditOpOut(M):
    id: int
    version: int
    actor: str
    op: str
    reason: str
    ts: datetime
    undone: bool


class AgendaItemOut(M):
    id: int
    text: str
    status: str
    result: str | None


class EditState(M):
    clip: ClipRow
    edl: dict[str, Any]
    version: int
    locked_by: str | None
    duration: float
    history: list[EditOpOut]
    plan: list[AgendaItemOut]
    notes: list[NoteOut]
    live_status: str | None
    live_range: list[float] | None
    proxy_url: str | None
    variants: list[ClipRow]


class EditOpIn(BaseModel):
    op: str
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class UndoIn(BaseModel):
    op_id: int


class NoteIn(BaseModel):
    scope: Literal["clip", "campaign", "creator", "global"]
    scope_id: str | None = None
    text: str = Field(min_length=1, max_length=1000)
    pinned: bool = False
    campaign_id: int | None = None


# ---------------------------------------------------------------- publishing


class AccountOut(M):
    id: int
    platform: str
    handle: str
    niche_tags: list[str]
    chrome_profile: str
    enabled: bool
    status: str
    paused_reason: str | None
    posts_today: int
    cap_today: int
    min_gap_min: int
    warmup_week: int | None  # 1, 2, or None (normal)
    extension_connected: bool


class AccountIn(BaseModel):
    platform: Literal["youtube", "tiktok", "instagram", "x"]
    handle: str
    chrome_profile: str = "main"
    niche_tags: list[str] = Field(default_factory=list)
    new_account: bool = True
    daily_cap: int | None = None


class AccountPatch(BaseModel):
    enabled: bool | None = None
    niche_tags: list[str] | None = None
    daily_cap: int | None = None
    min_gap_min: int | None = None


class CalendarOut(M):
    accounts: list[AccountOut]
    posts: list[PostOut]
    platforms_enabled: dict[str, bool]


class RescheduleIn(BaseModel):
    scheduled_at: datetime


class RecipeHealth(M):
    recipe: str
    last_success: datetime | None
    last_failure: datetime | None
    last_error: str | None
    screenshot_url: str | None
    runs_7d: int
    failures_7d: int


# ---------------------------------------------------------------- earnings


class SeriesPoint(M):
    day: str
    earnings: dict[str, float]
    views: dict[str, int]


class BreakdownRow(M):
    key: str
    label: str
    earnings: float
    views: int
    posts: int
    approval_rate: float | None = None
    avg_cpm: float | None = None
    payout_delay_days: float | None = None


class EarningsOut(M):
    days: int
    total: float
    series: list[SeriesPoint]
    by_marketplace: list[BreakdownRow]
    by_campaign: list[BreakdownRow]
    by_platform: list[BreakdownRow]
    by_account: list[BreakdownRow]
    top_clips: list[ClipRow]
    units: dict[str, float | None]


# ---------------------------------------------------------------- settings, questions, memory, tools


class QuestionOut(M):
    id: int
    session_id: int | None
    campaign_id: int | None
    text: str
    options: list[str]
    status: str
    answer: str | None
    created_at: datetime
    timeout_at: datetime | None


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=500)
    by: str = "you"
    via: Literal["dashboard", "discord"] = "dashboard"


class LessonOut(M):
    id: int
    scope: str
    entity_id: str | None
    note: str
    evidence_ref: str | None
    created_by: str
    created_at: datetime
    active: bool


class LessonPatch(BaseModel):
    note: str = Field(min_length=3, max_length=600)


class ToolStat(M):
    server: str
    tools: int
    read_only: int
    calls_7d: int
    errors_7d: int
    blocked_7d: int


class ToolsOut(M):
    servers: list[ToolStat]
    access: dict[str, list[str]]
    subagents: dict[str, list[str]]


class PromptOut(M):
    name: str
    text: str
    overridden: bool


class PromptIn(BaseModel):
    text: str = Field(min_length=50, max_length=20000)


class PromptSaveOut(M):
    saved: bool
    eval_status: str


class SecretIn(BaseModel):
    value: str = Field(min_length=1, max_length=500)


class SettingsOut(M):
    settings: dict[str, Any]
    secrets_present: dict[str, bool]
    pairing_token: str | None


class SettingsPatch(BaseModel):
    values: dict[str, Any]  # dotted path -> value, e.g. {"posting.min_gap_min": 90}


class DiscordRefIn(BaseModel):
    kind: str
    entity_id: str
    channel_id: str
    message_id: str | None = None
    thread_id: str | None = None


class DiscordRefOut(M):
    kind: str
    entity_id: str
    channel_id: str
    message_id: str | None
    thread_id: str | None


class EventOut(M):
    id: int
    type: str
    entity: str | None
    entity_id: str | None
    payload: dict[str, Any]
    ts: datetime


class JobOut(M):
    id: int
    kind: str
    status: str
    progress: float
    campaign_id: int | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
