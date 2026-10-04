"""SQLModel tables. One class per table in PLAN §9, plus the additions listed in HANDOFF §6.

Conventions:
- Datetimes are timezone-aware UTC in Python (``UTCDateTime`` column type).
- JSON columns hold plain dicts/lists; reassign them to persist changes.
- Status columns are plain strings; the allowed values live in ``clipper.db.types``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from clipper.clock import utcnow
from clipper.db.types import UTCDateTime


def _dt(*, nullable: bool = True, index: bool = False) -> Any:
    return Field(default=None, sa_type=UTCDateTime, nullable=nullable, index=index)


def _now_dt(*, index: bool = False) -> Any:
    return Field(default_factory=utcnow, sa_type=UTCDateTime, nullable=False, index=index)


def _json_dict() -> Any:
    return Field(default_factory=dict, sa_type=JSON, nullable=False)


def _json_list() -> Any:
    return Field(default_factory=list, sa_type=JSON, nullable=False)


# ---------------------------------------------------------------- marketplaces and campaigns


class Marketplace(SQLModel, table=True):
    id: str = Field(primary_key=True)  # "vyro" | "whop"
    name: str
    enabled: bool = True
    mode: str = "suggest"  # scout mode for this marketplace: suggest | auto
    session_ok: bool = False
    last_scout: datetime | None = _dt()
    settings_json: dict[str, Any] = _json_dict()


class Platform(SQLModel, table=True):
    id: str = Field(primary_key=True)  # "youtube" | "tiktok" | "instagram" | "x"
    name: str
    enabled: bool = True
    settings_json: dict[str, Any] = _json_dict()


class Campaign(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("marketplace", "external_id", name="uq_campaign_market_ext"),)

    id: int | None = Field(default=None, primary_key=True)
    marketplace: str = Field(foreign_key="marketplace.id", index=True)
    external_id: str
    url: str | None = None
    title: str
    brand: str | None = None
    creator: str | None = Field(default=None, index=True)  # groups the same creator across marketplaces
    cpm: float = 0.0
    budget_total: float | None = None
    budget_left: float | None = None
    cap_per_clip: float | None = None
    min_views_to_pay: int | None = None
    platforms: list[str] = _json_list()  # allowed platforms per the campaign
    deliverable: str = "link"  # link | upload
    content_type: str = "clipping"  # clipping | ugc | other
    tracking_window_days: int | None = None
    deadline: datetime | None = _dt()
    rules_raw: str = ""  # untrusted third-party text
    score: float | None = None
    score_reason: str | None = None
    status: str = Field(default="suggested", index=True)
    spec_json: dict[str, Any] = _json_dict()  # ClipSpec
    session_id: int | None = None  # agent_session.id of the Campaign agent
    agent_turns: int = 0
    budget_runs_out_at: datetime | None = _dt()
    found_at: datetime = _now_dt()
    taken_at: datetime | None = _dt()
    updated_at: datetime = _now_dt()


class Source(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    url: str
    title: str | None = None
    path: str | None = None
    proxy_path: str | None = None
    hash: str | None = Field(default=None, index=True)
    duration: float | None = None
    heatmap_json: list[Any] = _json_list()
    status: str = "listed"
    created_at: datetime = _now_dt()


class Analysis(SQLModel, table=True):
    source_id: int = Field(foreign_key="source.id", primary_key=True)
    transcript_path: str | None = None
    scenes_json: list[Any] = _json_list()
    energy_path: str | None = None
    faces_path: str | None = None
    signals_json: dict[str, Any] = _json_dict()
    created_at: datetime = _now_dt()


class Moment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    campaign_id: int | None = Field(default=None, foreign_key="campaign.id", index=True)
    start: float
    end: float
    hook: str = ""
    payoff: str = ""
    scores_json: dict[str, Any] = _json_dict()
    final_score: float = 0.0
    reason: str = ""
    created_at: datetime = _now_dt()


class Clip(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    moment_id: int = Field(foreign_key="moment.id", index=True)
    campaign_id: int | None = Field(default=None, foreign_key="campaign.id", index=True)
    version: int = 1
    variant_of: int | None = Field(default=None, foreign_key="clip.id")
    variant_label: str | None = None
    starred: bool = False  # the chosen hook variant
    path: str | None = None  # final render
    preview_path: str | None = None  # proxy / Discord preview
    thumb_path: str | None = None
    duration: float | None = None
    layout: str = "crop"
    caption_style: str = "bold-pop"
    qa_json: dict[str, Any] = _json_dict()
    status: str = Field(default="draft", index=True)
    created_at: datetime = _now_dt()
    updated_at: datetime = _now_dt()


class ReviewBatch(SQLModel, table=True):
    """Added: one review batch per campaign x source (a Discord forum post)."""

    __tablename__ = "review_batch"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    source_id: int | None = Field(default=None, foreign_key="source.id")
    status: str = "pending"
    created_at: datetime = _now_dt()
    shipped_at: datetime | None = _dt()
    timeout_at: datetime | None = _dt()


class Review(SQLModel, table=True):
    clip_id: int = Field(foreign_key="clip.id", primary_key=True)
    batch_id: int | None = Field(default=None, foreign_key="review_batch.id", index=True)
    decision: str = "pending"
    reason: str | None = None
    platforms: list[str] = _json_list()
    captions_json: dict[str, Any] = _json_dict()
    reviewer: str | None = None
    decided_at: datetime | None = _dt()
    via: str | None = None  # discord | dashboard | auto
    score_at_decision: float | None = None


class Account(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    platform: str = Field(foreign_key="platform.id", index=True)
    handle: str
    chrome_profile: str
    niche_tags: list[str] = _json_list()
    warmup_started: datetime | None = _dt()
    daily_cap: int | None = None  # None = settings.posting.default_daily_cap
    min_gap_min: int | None = None
    enabled: bool = True  # per-account switch (PLAN §15.2)
    status: str = "active"  # active | paused (challenge)
    paused_reason: str | None = None


class Post(SQLModel, table=True):
    __table_args__ = (Index("ix_post_account_sched", "account_id", "scheduled_at"),)

    id: int | None = Field(default=None, primary_key=True)
    clip_id: int = Field(foreign_key="clip.id", index=True)
    account_id: int = Field(foreign_key="account.id")
    campaign_id: int | None = Field(default=None, foreign_key="campaign.id", index=True)
    platform: str = Field(foreign_key="platform.id")
    scheduled_at: datetime = Field(sa_type=UTCDateTime, nullable=False)
    posted_at: datetime | None = _dt()
    url: str | None = None
    status: str = Field(default="scheduled", index=True)
    copy_json: dict[str, Any] = _json_dict()
    dry_run: bool = False
    error: str | None = None
    created_by: str | None = None


class Submission(SQLModel, table=True):
    post_id: int = Field(foreign_key="post.id", primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id", primary_key=True)
    marketplace: str = Field(foreign_key="marketplace.id")
    external_id: str | None = None
    submitted_at: datetime = _now_dt()
    external_status: str = "pending"
    tracking_ends: datetime | None = _dt()
    dry_run: bool = False


class Metric(SQLModel, table=True):
    post_id: int = Field(foreign_key="post.id", primary_key=True)
    ts: datetime = Field(sa_type=UTCDateTime, primary_key=True)
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    earnings: float = 0.0


class Job(SQLModel, table=True):
    __table_args__ = (Index("ix_job_status_kind", "status", "kind"),)

    id: int | None = Field(default=None, primary_key=True)
    kind: str  # download | analyze | render_proxy | render_final | preview | frames | ...
    input_json: dict[str, Any] = _json_dict()
    status: str = "queued"
    progress: float = 0.0
    result_json: dict[str, Any] = _json_dict()
    error: str | None = None
    campaign_id: int | None = Field(default=None, foreign_key="campaign.id", index=True)
    created_at: datetime = _now_dt()
    started_at: datetime | None = _dt()
    finished_at: datetime | None = _dt()


# ---------------------------------------------------------------- agents


class AgentSession(SQLModel, table=True):
    __tablename__ = "agent_session"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    sdk_session_id: str | None = Field(default=None, index=True)
    role: str = Field(index=True)
    campaign_id: int | None = Field(default=None, foreign_key="campaign.id", index=True)
    status: str = "running"
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    started: datetime = _now_dt()
    last_active: datetime = _now_dt()
    summary: str | None = None
    model: str | None = None  # the model that last ran (as Claude Code reported it)


class AgentEvent(SQLModel, table=True):
    __tablename__ = "agent_event"  # type: ignore[assignment]
    __table_args__ = (Index("ix_agent_event_session_ts", "session_id", "ts"),)

    id: int | None = Field(default=None, primary_key=True)
    session_id: int | None = Field(default=None, foreign_key="agent_session.id")
    ts: datetime = _now_dt()
    type: str  # message | tool_call | tool_result | subagent | blocked | thinking | result | error
    tool: str | None = None
    input_json: dict[str, Any] = _json_dict()
    output_json: dict[str, Any] = _json_dict()
    tokens: int = 0


class UsageWindow(SQLModel, table=True):
    __tablename__ = "usage_window"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    started: datetime = _now_dt()
    resets_at: datetime | None = _dt()
    tokens: int = 0
    sessions: int = 0
    rate_limited: bool = False
    utilization: float = 0.0
    window_type: str = "five_hour"


class Wakeup(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int | None = Field(default=None, foreign_key="agent_session.id", index=True)
    campaign_id: int | None = Field(default=None, foreign_key="campaign.id")
    role: str | None = None
    due_at: datetime = Field(sa_type=UTCDateTime, nullable=False, index=True)
    reason: str
    status: str = "pending"


class Question(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int | None = Field(default=None, foreign_key="agent_session.id", index=True)
    campaign_id: int | None = Field(default=None, foreign_key="campaign.id")
    text: str
    options_json: list[str] = _json_list()
    answer: str | None = None
    answered_by: str | None = None
    via: str | None = None
    status: str = "open"
    created_at: datetime = _now_dt()
    timeout_at: datetime | None = _dt()
    answered_at: datetime | None = _dt()


class Lesson(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scope: str = Field(index=True)  # creator | marketplace | platform | account | recipe | global | tuning
    entity_id: str | None = Field(default=None, index=True)
    note: str
    evidence_ref: str | None = None
    created_by: str = "agent"
    created_at: datetime = _now_dt()
    active: bool = True


# ---------------------------------------------------------------- editing (PLAN §18)


class Edl(SQLModel, table=True):
    clip_id: int = Field(foreign_key="clip.id", primary_key=True)
    version: int = 0
    data: dict[str, Any] = Field(
        default_factory=dict, sa_type=JSON, nullable=False, sa_column_kwargs={"name": "json"}
    )
    locked_by: str | None = None  # "user" | "session:<id>" | None
    updated_at: datetime = _now_dt()


class EditOp(SQLModel, table=True):
    __tablename__ = "edit_op"  # type: ignore[assignment]
    __table_args__ = (Index("ix_edit_op_clip_version", "clip_id", "version"),)

    id: int | None = Field(default=None, primary_key=True)
    clip_id: int = Field(foreign_key="clip.id")
    version: int
    actor: str  # "user" | "session:<id>" | "system"
    op: str
    args_json: dict[str, Any] = _json_dict()
    reason: str = ""
    ts: datetime = _now_dt()
    undone: bool = False


class AgendaItem(SQLModel, table=True):
    __tablename__ = "agenda_item"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    scope: str  # clip | campaign | global
    scope_id: str | None = Field(default=None, index=True)
    session_id: int | None = Field(default=None, foreign_key="agent_session.id")
    text: str
    status: str = "queued"
    result: str | None = None
    ord: int = 0


class Note(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scope: str  # clip | campaign | creator | global
    scope_id: str | None = Field(default=None, index=True)
    text: str
    author: str = "user"
    created_at: datetime = _now_dt()
    acked_by_session: int | None = None
    response: str | None = None
    pinned: bool = False


# ---------------------------------------------------------------- supervisor plumbing


class AgentRequest(SQLModel, table=True):
    __tablename__ = "agent_request"  # type: ignore[assignment]
    __table_args__ = (Index("ix_agent_request_status_prio", "status", "priority"),)

    id: int | None = Field(default=None, primary_key=True)
    priority: int = 2  # 0..3 (PLAN §17.1)
    kind: str  # event type or trigger name
    role: str = "campaign"
    campaign_id: int | None = Field(default=None, foreign_key="campaign.id", index=True)
    payload: dict[str, Any] = _json_dict()
    status: str = "queued"
    slot: int | None = None
    merged_count: int = 0
    queued_at: datetime = _now_dt()
    started_at: datetime | None = _dt()
    finished_at: datetime | None = _dt()
    error: str | None = None


class Lease(SQLModel, table=True):
    resource: str = Field(primary_key=True)  # campaign:<id> | clip:<id> | profile:<name>
    holder_session: str
    expires_at: datetime = Field(sa_type=UTCDateTime, nullable=False)


class Event(SQLModel, table=True):
    __table_args__ = (Index("ix_event_type_ts", "type", "ts"),)

    id: int | None = Field(default=None, primary_key=True)
    type: str
    entity: str | None = None
    entity_id: str | None = None
    payload: dict[str, Any] = _json_dict()
    ts: datetime = _now_dt()
    handled_by_session: int | None = None


# ---------------------------------------------------------------- additions (see HANDOFF §6)


class KV(SQLModel, table=True):
    """Small app-wide control state: dry_run, paused, kill_switch, slot override, auto-approve tier."""

    key: str = Field(primary_key=True)
    value_json: Any = Field(default=None, sa_type=JSON)
    updated_at: datetime = _now_dt()


class DiscordRef(SQLModel, table=True):
    """Where the bot posted something, so it can edit it later (batch summary, previews, cards)."""

    __tablename__ = "discord_ref"  # type: ignore[assignment]
    __table_args__ = (UniqueConstraint("kind", "entity_id", name="uq_discord_ref"),)

    id: int | None = Field(default=None, primary_key=True)
    kind: str  # campaign_card | batch_thread | batch_summary | clip_message | question
    entity_id: str
    channel_id: str
    message_id: str | None = None
    thread_id: str | None = None


class RecipeRun(SQLModel, table=True):
    """Upload/marketplace recipe outcomes for the Publishing -> Recipes tab."""

    __tablename__ = "recipe_run"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    recipe: str = Field(index=True)
    account_id: int | None = Field(default=None, foreign_key="account.id")
    ok: bool
    dry_run: bool = False
    error: str | None = None
    screenshot_path: str | None = None
    ts: datetime = _now_dt()


# Re-exported for Alembic.
metadata = SQLModel.metadata
