"""``supervisor`` server: agents have no clock; they schedule follow-ups and read usage pacing."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clipper.clock import ensure_utc
from clipper.db.engine import WriteTx
from clipper.db.models import AgentSession
from clipper.events.types import AgentEventLogged
from clipper.tools.base import ToolContext, ToolFailure, tool


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class WakeMe(_A):
    at: str | None = Field(default=None, description="ISO-8601 time with offset")
    in_minutes: float | None = Field(default=None, alias="in", gt=0, le=20160)
    reason: str = Field(min_length=3, max_length=300, description="what to do when you wake up")

    @model_validator(mode="after")
    def _one(self) -> WakeMe:
        if (self.at is None) == (self.in_minutes is None):
            raise ValueError("give exactly one of 'at' or 'in' (minutes)")
        return self


@tool(
    "supervisor",
    "wake_me",
    "Schedule your own follow-up ('check views in 6h', 'post the next clip at 19:00').",
    WakeMe,
)
async def wake_me(ctx: ToolContext, a: WakeMe) -> dict[str, Any]:
    at = ensure_utc(datetime.fromisoformat(a.at.replace("Z", "+00:00"))) if a.at else None
    wid = ctx.core.wakeups.wake_me(
        at=at,
        in_minutes=a.in_minutes,
        reason=a.reason,
        session_id=ctx.session_id,
        campaign_id=ctx.campaign_id,
        role=ctx.role,
    )
    return {"wakeup_id": wid}


class Empty(_A):
    pass


@tool("supervisor", "list_wakeups", "Your pending follow-ups.", Empty)
async def list_wakeups(ctx: ToolContext, a: Empty) -> dict[str, Any]:
    return {"wakeups": ctx.core.wakeups.list(session_id=ctx.session_id, campaign_id=ctx.campaign_id)}


class WakeupArg(_A):
    wakeup_id: int


@tool("supervisor", "cancel_wakeup", "Cancel a pending follow-up.", WakeupArg)
async def cancel_wakeup(ctx: ToolContext, a: WakeupArg) -> dict[str, Any]:
    ctx.core.wakeups.cancel(a.wakeup_id)
    return {"cancelled": a.wakeup_id}


@tool(
    "supervisor",
    "get_usage",
    "Claude plan usage in the current window, reset time and how hard to pace yourself.",
    Empty,
)
async def get_usage(ctx: ToolContext, a: Empty) -> dict[str, Any]:
    return ctx.core.usage.as_dict()


class Status(_A):
    text: str = Field(min_length=1, max_length=500)


@tool("supervisor", "report_status", "One-line status shown on the Agents page slot board.", Status)
async def report_status(ctx: ToolContext, a: Status) -> dict[str, Any]:
    if ctx.session_id is None:
        raise ToolFailure("no session to report on")
    sid = ctx.session_id

    def job(tx: WriteTx) -> None:
        row = tx.session.get(AgentSession, sid)
        if row is not None:
            row.summary = a.text
            tx.add(row)
        tx.publish(AgentEventLogged(session_id=sid, agent_event_id=0, kind="status", summary=a.text))

    ctx.core.db.write(job)
    return {"ok": True}
