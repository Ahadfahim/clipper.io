"""``agenda`` server: the agent's visible plan and the user's notes (PLAN §18.5)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clipper.tools.base import ToolContext, tool


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetPlan(_A):
    scope: Literal["clip", "campaign", "global"]
    scope_id: str | None = Field(default=None, description="clip id or campaign id")
    items: list[str] = Field(min_length=1, max_length=12)


@tool(
    "agenda",
    "set_plan",
    "Replace your open to-do list for a clip/campaign (shown live on the Edit page).",
    SetPlan,
)
async def set_plan(ctx: ToolContext, a: SetPlan) -> dict[str, Any]:
    return {"item_ids": ctx.core.agenda.set_plan(a.scope, a.scope_id, a.items, session_id=ctx.session_id)}


class Check(_A):
    item_id: int
    status: Literal["in_progress", "done", "skipped"]
    result: str | None = Field(default=None, max_length=300)


@tool("agenda", "check", "Mark a plan item in progress, done or skipped (with a short result).", Check)
async def check(ctx: ToolContext, a: Check) -> dict[str, Any]:
    ctx.core.agenda.check(a.item_id, a.status, a.result)
    return {"ok": True}


class Notes(_A):
    scope: Literal["clip", "campaign", "creator", "global"]
    scope_id: str | None = None


@tool("agenda", "get_notes", "The user's notes for a clip/campaign/creator plus pinned global notes.", Notes)
async def get_notes(ctx: ToolContext, a: Notes) -> dict[str, Any]:
    return {"notes": ctx.core.agenda.notes(a.scope, a.scope_id)}


class Ack(_A):
    note_id: int
    response: str = Field(min_length=2, max_length=500, description="e.g. 'Got it: hook cut to 1.2s'")


@tool("agenda", "ack_note", "Reply under a user's note after acting on it.", Ack)
async def ack_note(ctx: ToolContext, a: Ack) -> dict[str, Any]:
    ctx.core.agenda.ack_note(a.note_id, a.response, session_id=ctx.session_id)
    return {"ok": True}
