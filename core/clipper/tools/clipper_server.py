"""``clipper`` umbrella server: a read-only view of the whole system + pause/toggle controls.

Served over stdio for Claude Desktop / Claude Code (``clipper mcp clipper``); the Director also gets
``set_switch`` and ``set_paused`` from it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import col, select

from clipper.db.models import Event, ReviewBatch
from clipper.services.control import read_control, set_control
from clipper.tools.base import ToolContext, tool


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Empty(_A):
    pass


@tool("clipper", "status", "Pause/dry-run/kill switch, switches, usage and what needs the user.", Empty)
async def status(ctx: ToolContext, a: Empty) -> dict[str, Any]:
    ctl = read_control(ctx.core.db)
    return {
        "paused": ctl.paused,
        "dry_run": ctl.dry_run,
        "kill_switch": ctl.kill_switch,
        "switches": ctx.core.toggles.state(),
        "usage": ctx.core.usage.as_dict(),
        "open_questions": len(ctx.core.notify.open_questions()),
    }


@tool("clipper", "review_queue", "Review batches waiting on the user.", Empty)
async def review_queue(ctx: ToolContext, a: Empty) -> dict[str, Any]:
    with ctx.core.db.read() as s:
        batches = s.exec(
            select(ReviewBatch).where(ReviewBatch.status != "shipped").order_by(col(ReviewBatch.id))
        ).all()
    return {"batches": [ctx.core.review.batch_status(b.id) for b in batches if b.id is not None]}


class ListArgs(_A):
    status: str | None = None


@tool("clipper", "list_campaigns", "Campaigns by status.", ListArgs)
async def list_campaigns(ctx: ToolContext, a: ListArgs) -> dict[str, Any]:
    return {"campaigns": ctx.core.campaigns.list(status=a.status)}


class CampaignArg(_A):
    campaign_id: int


@tool("clipper", "campaign_report", "Clips, decisions, posts and money for one campaign.", CampaignArg)
async def campaign_report(ctx: ToolContext, a: CampaignArg) -> dict[str, Any]:
    return ctx.core.insights.campaign_report(a.campaign_id)


class Recent(_A):
    limit: int = Field(default=30, ge=1, le=100)


@tool("clipper", "recent_activity", "The latest events (what happened, newest first).", Recent)
async def recent_activity(ctx: ToolContext, a: Recent) -> dict[str, Any]:
    with ctx.core.db.read() as s:
        rows = s.exec(
            select(Event)
            .where(col(Event.type).not_in(["job.progress", "agent.event"]))
            .order_by(col(Event.id).desc())
            .limit(a.limit)
        ).all()
    return {
        "events": [
            {"id": e.id, "type": e.type, "entity": f"{e.entity}:{e.entity_id}", "ts": e.ts.isoformat()}
            for e in rows
        ]
    }


@tool("clipper", "get_usage", "Claude plan usage window and pacing.", Empty)
async def get_usage(ctx: ToolContext, a: Empty) -> dict[str, Any]:
    return ctx.core.usage.as_dict()


class Switch(_A):
    level: Literal["marketplace", "social", "account"]
    name: str = Field(description="vyro|whop, youtube|tiktok|instagram|x, or an account id")
    enabled: bool
    on_active: Literal["finish", "pause"] = Field(
        default="finish", description="marketplace off: finish or pause active campaigns"
    )
    on_scheduled: Literal["cancel", "keep"] = Field(
        default="keep", description="social/account off: cancel or keep scheduled posts"
    )


@tool(
    "clipper",
    "set_switch",
    "Turn a marketplace, social or account on/off (same effects as the app's dialog).",
    Switch,
)
async def set_switch(ctx: ToolContext, a: Switch) -> dict[str, Any]:
    return ctx.core.toggles.set(
        a.level,
        a.name,
        a.enabled,
        by=ctx.actor,
        via="director" if ctx.role == "director" else "mcp",
        on_active=a.on_active,
        on_scheduled=a.on_scheduled,
    )


class Paused(_A):
    paused: bool


@tool("clipper", "set_paused", "Pause or resume all agent work.", Paused)
async def set_paused(ctx: ToolContext, a: Paused) -> dict[str, Any]:
    set_control(ctx.core.db, "paused", a.paused, by=ctx.actor, via="mcp")
    return {"paused": a.paused}


class DryRun(_A):
    dry_run: bool


@tool("clipper", "set_dry_run", "Turn dry-run mode on or off.", DryRun)
async def set_dry_run(ctx: ToolContext, a: DryRun) -> dict[str, Any]:
    set_control(ctx.core.db, "dry_run", a.dry_run, by=ctx.actor, via="mcp")
    return {"dry_run": a.dry_run}
