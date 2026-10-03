"""``memory`` server: long-term lessons with evidence (PLAN §16.1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clipper.tools.base import ToolContext, tool

Scope = Literal["creator", "marketplace", "platform", "account", "recipe", "campaign", "global"]


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Recall(_A):
    scope: Scope | None = None
    entity: str | None = Field(
        default=None, description="creator name, marketplace id, account id, recipe name..."
    )
    query: str | None = Field(default=None, max_length=200)


@tool("memory", "recall", "Lessons that apply (e.g. 'this creator rejects clips with music').", Recall)
async def recall(ctx: ToolContext, a: Recall) -> dict[str, Any]:
    return {"lessons": ctx.core.memory.recall(scope=a.scope, entity=a.entity, query=a.query)}


class Remember(_A):
    scope: Scope
    note: str = Field(min_length=5, max_length=600)
    entity: str | None = None
    evidence: str = Field(
        min_length=3, max_length=300, description="clip/post/review id or page the lesson comes from"
    )


@tool("memory", "remember", "Save a lesson with the evidence behind it.", Remember)
async def remember(ctx: ToolContext, a: Remember) -> dict[str, Any]:
    return {
        "lesson_id": ctx.core.memory.remember(
            a.scope, a.note, entity=a.entity, evidence=a.evidence, by=ctx.actor
        )
    }


class Forget(_A):
    lesson_id: int


@tool("memory", "forget", "Retire a lesson that turned out wrong.", Forget)
async def forget(ctx: ToolContext, a: Forget) -> dict[str, Any]:
    ctx.core.memory.forget(a.lesson_id)
    return {"forgotten": a.lesson_id}


class ListLessons(_A):
    scope: Scope | None = None


@tool("memory", "list_lessons", "List active lessons in a scope.", ListLessons)
async def list_lessons(ctx: ToolContext, a: ListLessons) -> dict[str, Any]:
    return {"lessons": ctx.core.memory.list(a.scope)}
