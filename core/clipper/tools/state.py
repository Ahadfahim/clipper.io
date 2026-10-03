"""``state`` server: the only way agents read and change campaign state (PLAN §16.1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import col, select

from clipper.db.models import Campaign, Clip, Event, Moment, Review
from clipper.events.types import AgentLog
from clipper.rules.spec import ClipSpec
from clipper.tools.base import ToolContext, ToolFailure, tool


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CampaignRef(_A):
    campaign_id: int
    clips_offset: int = Field(default=0, ge=0, description="page through clips 30 at a time")


@tool(
    "state",
    "get_campaign",
    "Campaign summary: payout, spec, sources, moments, a page of clips, open jobs, plan, recent log notes.",
    CampaignRef,
)
async def get_campaign(ctx: ToolContext, a: CampaignRef) -> dict[str, Any]:
    out = ctx.core.campaigns.summary(a.campaign_id, clips_offset=a.clips_offset)
    with ctx.core.db.read() as s:
        logs = s.exec(
            select(Event)
            .where(Event.type == "agent.log", Event.entity_id == str(a.campaign_id))
            .order_by(col(Event.id).desc())
            .limit(5)
        ).all()
    out["log_notes"] = [e.payload.get("text") for e in reversed(logs)]
    return out


class ListCampaigns(_A):
    status: str | None = Field(
        default=None, description="suggested | active | paused | ending | ended | skipped | needs_user"
    )
    market: Literal["vyro", "whop"] | None = None
    limit: int = Field(default=30, ge=1, le=100)


@tool(
    "state",
    "list_campaigns",
    "Campaigns in the database (not the live marketplace), newest first.",
    ListCampaigns,
)
async def list_campaigns(ctx: ToolContext, a: ListCampaigns) -> dict[str, Any]:
    return {"campaigns": ctx.core.campaigns.list(status=a.status, market=a.market, limit=a.limit)}


class UpdateCampaign(_A):
    campaign_id: int
    status: Literal["suggested", "active", "paused", "ending", "ended", "needs_user"] | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    score_reason: str | None = Field(default=None, max_length=600)


@tool("state", "update_campaign", "Set a campaign's status, score or score reason.", UpdateCampaign)
async def update_campaign(ctx: ToolContext, a: UpdateCampaign) -> dict[str, Any]:
    fields = {k: v for k, v in a.model_dump().items() if k != "campaign_id" and v is not None}
    if not fields:
        raise ToolFailure("nothing to update")
    return {"campaign_id": a.campaign_id, "updated": ctx.core.campaigns.update(a.campaign_id, fields)}


class SaveSpec(_A):
    campaign_id: int
    spec: ClipSpec


@tool(
    "state",
    "save_spec",
    "Save the ClipSpec produced by the brief-reader (platforms are limited to the campaign's).",
    SaveSpec,
)
async def save_spec(ctx: ToolContext, a: SaveSpec) -> dict[str, Any]:
    spec = ctx.core.campaigns.save_spec(a.campaign_id, a.spec, by=ctx.actor)
    return {
        "campaign_id": a.campaign_id,
        "platforms": spec.platforms,
        "sources": len(spec.source_whitelist),
        "unclear": spec.unclear,
    }


class MomentIn(_A):
    start: float = Field(description="source seconds")
    end: float = Field(description="source seconds")
    hook: str = Field(default="", max_length=300)
    payoff: str = Field(default="", max_length=300)
    final_score: float = Field(ge=0, le=100)
    reason: str = Field(default="", max_length=600)
    scores: dict[str, float] = Field(default_factory=dict, description="e.g. {'hook': 80, 'heatmap': 70}")


class SaveMoments(_A):
    campaign_id: int
    source_id: int
    moments: list[MomentIn] = Field(min_length=1, max_length=30)


@tool(
    "state",
    "save_moments",
    "Save ranked moments the editor picked from a source. Returns moment ids.",
    SaveMoments,
)
async def save_moments(ctx: ToolContext, a: SaveMoments) -> dict[str, Any]:
    ids = ctx.core.media.save_moments(a.campaign_id, a.source_id, [m.model_dump() for m in a.moments])
    return {"moment_ids": ids}


class ClipRef(_A):
    clip_id: int


@tool("state", "get_clip", "Clip status, moment, QA results, review decision and captions.", ClipRef)
async def get_clip(ctx: ToolContext, a: ClipRef) -> dict[str, Any]:
    with ctx.core.db.read() as s:
        clip = s.get(Clip, a.clip_id)
        if clip is None:
            raise ToolFailure(f"clip {a.clip_id} not found")
        moment = s.get(Moment, clip.moment_id)
        review = s.get(Review, a.clip_id)
    qa = clip.qa_json or {}
    failed = [c["name"] for c in qa.get("checks", []) if not c.get("ok")]
    return {
        "id": clip.id,
        "campaign_id": clip.campaign_id,
        "status": clip.status,
        "version": clip.version,
        "variant_of": clip.variant_of,
        "variant_label": clip.variant_label,
        "duration": clip.duration,
        "layout": clip.layout,
        "caption_style": clip.caption_style,
        "qa_ok": qa.get("ok"),
        "qa_failed": failed,
        "has_final": bool(clip.path),
        "moment": {
            "id": moment.id,
            "source_id": moment.source_id,
            "start": moment.start,
            "end": moment.end,
            "hook": moment.hook,
            "payoff": moment.payoff,
            "score": moment.final_score,
            "reason": moment.reason,
        }
        if moment
        else None,
        "review": {
            "decision": review.decision,
            "reason": review.reason,
            "platforms": review.platforms,
            "captions": review.captions_json,
            "via": review.via,
        }
        if review
        else None,
    }


class LogNote(_A):
    text: str = Field(min_length=1, max_length=1000)
    campaign_id: int | None = None


@tool(
    "state",
    "log_note",
    "Append to the campaign's running log so a fresh session can pick up where you left off.",
    LogNote,
)
async def log_note(ctx: ToolContext, a: LogNote) -> dict[str, Any]:
    cid = a.campaign_id if a.campaign_id is not None else ctx.campaign_id
    env = await ctx.core.bus.apublish(AgentLog(campaign_id=cid, session_id=ctx.session_id, text=a.text))
    return {"logged": env.id}


class LearningExamples(_A):
    campaign_id: int | None = None
    creator: str | None = None
    n: int = Field(default=6, ge=1, le=20)


@tool(
    "state",
    "get_learning_examples",
    "Recent approved and rejected clips (hook, score, reviewer reason) to calibrate picks.",
    LearningExamples,
)
async def get_learning_examples(ctx: ToolContext, a: LearningExamples) -> dict[str, Any]:
    with ctx.core.db.read() as s:
        q = (
            select(Review, Moment, Campaign)
            .join(Clip, col(Clip.id) == col(Review.clip_id))
            .join(Moment, col(Moment.id) == col(Clip.moment_id))
            .join(Campaign, col(Campaign.id) == col(Clip.campaign_id))
            .where(col(Review.decision).in_(["approved", "rejected"]))
            .order_by(col(Review.decided_at).desc())
            .limit(a.n * 3)
        )
        if a.campaign_id is not None:
            q = q.where(Campaign.id == a.campaign_id)
        if a.creator:
            q = q.where(Campaign.creator == a.creator)
        rows = s.exec(q).all()

    def pack(decision: str) -> list[dict[str, Any]]:
        return [
            {
                "hook": m.hook,
                "length": round(m.end - m.start, 1),
                "score": m.final_score,
                "reason": r.reason,
                "campaign": c.title,
            }
            for r, m, c in rows
            if r.decision == decision
        ][: a.n]

    tuning = ctx.core.memory.tuning()
    return {"approved": pack("approved"), "rejected": pack("rejected"), "tuning": tuning}


class SetTuning(_A):
    key: Literal["editor_min_score", "scout_min_score", "approve_all_threshold", "max_clips_per_source"]
    value: float
    reason: str = Field(min_length=3, max_length=300, description="the evidence behind the change")


@tool(
    "state",
    "set_tuning",
    "Analyst: adjust a learning weight/threshold (logged with its evidence).",
    SetTuning,
)
async def set_tuning(ctx: ToolContext, a: SetTuning) -> dict[str, Any]:
    lesson_id = ctx.core.memory.set_tuning(a.key, a.value, a.reason, by=ctx.actor)
    return {"key": a.key, "value": a.value, "lesson_id": lesson_id}
