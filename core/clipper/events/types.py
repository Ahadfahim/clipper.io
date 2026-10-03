"""Typed event payloads.

Every event is persisted as an ``event`` row (type, entity, entity_id, payload) and dispatched to
in-process subscribers after commit. The supervisor turns some of them into agent resumes
(``clipper.supervisor.router``); the API streams them to the dashboard and the bot over WebSocket.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

EVENT_TYPES: dict[str, type[EventPayload]] = {}


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    TYPE: ClassVar[str] = ""
    ENTITY: ClassVar[str | None] = None
    ENTITY_FIELD: ClassVar[str | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.TYPE:
            if cls.TYPE in EVENT_TYPES:
                raise ValueError(f"duplicate event type {cls.TYPE}")
            EVENT_TYPES[cls.TYPE] = cls

    def entity_id(self) -> str | None:
        if self.ENTITY_FIELD is None:
            return None
        value = getattr(self, self.ENTITY_FIELD)
        return None if value is None else str(value)


# ---------------------------------------------------------------- campaigns


class CampaignFound(EventPayload):
    TYPE = "campaign.found"
    ENTITY = "campaign"
    ENTITY_FIELD = "campaign_id"
    campaign_id: int
    marketplace: str
    score: float | None = None


class CampaignTaken(EventPayload):
    TYPE = "campaign.taken"
    ENTITY = "campaign"
    ENTITY_FIELD = "campaign_id"
    campaign_id: int
    by: str = "user"
    via: str = "dashboard"


class CampaignSkipped(EventPayload):
    TYPE = "campaign.skipped"
    ENTITY = "campaign"
    ENTITY_FIELD = "campaign_id"
    campaign_id: int
    by: str = "user"
    via: str = "dashboard"


class CampaignUpdated(EventPayload):
    TYPE = "campaign.updated"
    ENTITY = "campaign"
    ENTITY_FIELD = "campaign_id"
    campaign_id: int
    fields: list[str] = Field(default_factory=list)


class CampaignEnding(EventPayload):
    TYPE = "campaign.ending"
    ENTITY = "campaign"
    ENTITY_FIELD = "campaign_id"
    campaign_id: int
    reason: str = "deadline"


class SpecUpdated(EventPayload):
    TYPE = "spec.updated"
    ENTITY = "campaign"
    ENTITY_FIELD = "campaign_id"
    campaign_id: int
    by: str = "user"


# ---------------------------------------------------------------- jobs


class JobQueued(EventPayload):
    TYPE = "job.queued"
    ENTITY = "job"
    ENTITY_FIELD = "job_id"
    job_id: int
    kind: str
    campaign_id: int | None = None


class JobProgress(EventPayload):
    TYPE = "job.progress"
    ENTITY = "job"
    ENTITY_FIELD = "job_id"
    job_id: int
    kind: str
    progress: float
    campaign_id: int | None = None


class JobDone(EventPayload):
    TYPE = "job.done"
    ENTITY = "job"
    ENTITY_FIELD = "job_id"
    job_id: int
    kind: str
    status: Literal["done", "failed", "cancelled"]
    campaign_id: int | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------- clips, review


class ClipUpdated(EventPayload):
    TYPE = "clip.updated"
    ENTITY = "clip"
    ENTITY_FIELD = "clip_id"
    clip_id: int
    status: str
    campaign_id: int | None = None
    version: int | None = None


class ReviewBatchPosted(EventPayload):
    TYPE = "review.batch_posted"
    ENTITY = "review_batch"
    ENTITY_FIELD = "batch_id"
    batch_id: int
    campaign_id: int
    clip_ids: list[int]


class ReviewDecided(EventPayload):
    TYPE = "review.decided"
    ENTITY = "clip"
    ENTITY_FIELD = "clip_id"
    clip_id: int
    batch_id: int | None
    decision: Literal["approved", "rejected", "pending"]
    reason: str | None = None
    via: str
    reviewer: str | None = None


class ReviewShipped(EventPayload):
    TYPE = "review.shipped"
    ENTITY = "review_batch"
    ENTITY_FIELD = "batch_id"
    batch_id: int
    campaign_id: int
    approved: list[int]
    rejected: list[int]
    via: str = "dashboard"


class RecutRequested(EventPayload):
    TYPE = "recut.requested"
    ENTITY = "clip"
    ENTITY_FIELD = "clip_id"
    clip_id: int
    campaign_id: int | None = None
    start_delta: float = 0.0
    end_delta: float = 0.0
    layout: str | None = None
    note: str | None = None
    via: str = "dashboard"


class CaptionEdited(EventPayload):
    TYPE = "caption.edited"
    ENTITY = "clip"
    ENTITY_FIELD = "clip_id"
    clip_id: int
    platform: str
    text: str
    via: str = "dashboard"


# ---------------------------------------------------------------- publishing, marketplaces


class PostScheduled(EventPayload):
    TYPE = "post.scheduled"
    ENTITY = "post"
    ENTITY_FIELD = "post_id"
    post_id: int
    clip_id: int
    account_id: int
    platform: str
    scheduled_at: str
    dry_run: bool = False


class PostStatusChanged(EventPayload):
    TYPE = "post.status"
    ENTITY = "post"
    ENTITY_FIELD = "post_id"
    post_id: int
    status: str
    error: str | None = None


class PostLive(EventPayload):
    TYPE = "post.live"
    ENTITY = "post"
    ENTITY_FIELD = "post_id"
    post_id: int
    clip_id: int
    campaign_id: int | None
    platform: str
    url: str
    dry_run: bool = False


class SubmissionStatus(EventPayload):
    TYPE = "submission.status"
    ENTITY = "post"
    ENTITY_FIELD = "post_id"
    post_id: int
    campaign_id: int
    status: str
    dry_run: bool = False


class AccountPaused(EventPayload):
    TYPE = "account.paused"
    ENTITY = "account"
    ENTITY_FIELD = "account_id"
    account_id: int
    reason: str


class TogglesChanged(EventPayload):
    TYPE = "toggles.changed"
    ENTITY = "switch"
    ENTITY_FIELD = "name"
    level: Literal["marketplace", "social", "account"]
    name: str
    enabled: bool
    by: str = "user"
    via: str = "app"  # app | ctrl+k | discord | director | settings
    effects: dict[str, Any] = Field(default_factory=dict)


class ControlChanged(EventPayload):
    TYPE = "control.changed"
    ENTITY = "control"
    ENTITY_FIELD = "key"
    key: Literal["dry_run", "paused", "kill_switch", "slots", "auto_approve_tier"]
    value: Any
    by: str = "user"
    via: str = "app"


# ---------------------------------------------------------------- humans and agents


class NoteAdded(EventPayload):
    TYPE = "note.added"
    ENTITY = "note"
    ENTITY_FIELD = "note_id"
    note_id: int
    scope: str
    scope_id: str | None
    text: str
    campaign_id: int | None = None


class UserChat(EventPayload):
    TYPE = "user.chat"
    ENTITY = "director"
    text: str
    via: str = "dashboard"  # dashboard | discord
    reply_to: str | None = None  # e.g. Discord thread id


class QuestionAsked(EventPayload):
    TYPE = "question.asked"
    ENTITY = "question"
    ENTITY_FIELD = "question_id"
    question_id: int
    session_id: int | None
    campaign_id: int | None
    text: str
    options: list[str]


class QuestionAnswered(EventPayload):
    TYPE = "question.answered"
    ENTITY = "question"
    ENTITY_FIELD = "question_id"
    question_id: int
    session_id: int | None
    campaign_id: int | None
    answer: str
    via: str


class AgentEventLogged(EventPayload):
    """Mirror of an ``agent_event`` row for the live console."""

    TYPE = "agent.event"
    ENTITY = "agent_session"
    ENTITY_FIELD = "session_id"
    session_id: int | None
    agent_event_id: int
    kind: str
    tool: str | None = None
    summary: str = ""


class AgentSessionChanged(EventPayload):
    TYPE = "agent.session"
    ENTITY = "agent_session"
    ENTITY_FIELD = "session_id"
    session_id: int
    role: str
    status: str
    campaign_id: int | None = None


class Alert(EventPayload):
    TYPE = "alert"
    ENTITY = "alert"
    level: Literal["info", "warning", "error"]
    text: str
    source: str = "system"
    campaign_id: int | None = None


class Report(EventPayload):
    TYPE = "report"
    ENTITY = "report"
    markdown: str
    source: str = "analyst"


class EditOpApplied(EventPayload):
    TYPE = "edit.op"
    ENTITY = "clip"
    ENTITY_FIELD = "clip_id"
    clip_id: int
    op_id: int
    op: str
    actor: str
    version: int
    reason: str = ""
    range: list[float] | None = None
    undone: bool = False


class EditStatus(EventPayload):
    """Live 'Claude is editing: ...' status line and violet range on the Edit page."""

    TYPE = "edit.status"
    ENTITY = "clip"
    ENTITY_FIELD = "clip_id"
    clip_id: int
    actor: str
    text: str
    range: list[float] | None = None


class AgendaUpdated(EventPayload):
    TYPE = "agenda.updated"
    ENTITY = "agenda"
    ENTITY_FIELD = "scope_id"
    scope: str
    scope_id: str | None


class WakeupDue(EventPayload):
    TYPE = "wakeup.due"
    ENTITY = "wakeup"
    ENTITY_FIELD = "wakeup_id"
    wakeup_id: int
    session_id: int | None
    campaign_id: int | None
    role: str | None
    reason: str


class WatchdogNudge(EventPayload):
    TYPE = "watchdog.nudge"
    ENTITY = "campaign"
    ENTITY_FIELD = "campaign_id"
    campaign_id: int
    idle_minutes: float


class TriggerFired(EventPayload):
    TYPE = "trigger.fired"
    ENTITY = "trigger"
    ENTITY_FIELD = "name"
    name: Literal["scout", "analyst"]


class UsageUpdated(EventPayload):
    TYPE = "usage.updated"
    ENTITY = "usage"
    utilization: float
    resets_at: str | None
    rate_limited: bool
    max_slots: int
