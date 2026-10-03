"""``review`` server: batches to Discord + the dashboard, campaign cards, decisions (PLAN §7)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clipper.tools.base import ToolContext, tool


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PostBatch(_A):
    campaign_id: int
    clip_ids: list[int] = Field(min_length=1, max_length=25, description="strongest first")
    copy_by_clip: dict[str, dict[str, str]] = Field(
        default_factory=dict, description="{clip_id: {platform: caption/title}} from the copywriter"
    )
    source_id: int | None = None


@tool(
    "review",
    "post_batch",
    "Send rendered clips for human review (Discord forum post + Review page). Returns the batch id.",
    PostBatch,
)
async def post_batch(ctx: ToolContext, a: PostBatch) -> dict[str, Any]:
    copy = {int(k): v for k, v in a.copy_by_clip.items() if k.isdigit()}
    batch_id = ctx.core.review.post_batch(a.campaign_id, a.clip_ids, copy=copy, source_id=a.source_id)
    return {"batch_id": batch_id, "clips": len(a.clip_ids)}


class Card(_A):
    campaign_id: int
    reasoning: str = Field(
        min_length=10, max_length=1500, description="why it scores what it does (shown on the card)"
    )


@tool(
    "review",
    "post_campaign_card",
    "Post a Take/Skip card for a scored campaign (#campaigns + Needs you).",
    Card,
)
async def post_campaign_card(ctx: ToolContext, a: Card) -> dict[str, Any]:
    ctx.core.review.post_campaign_card(a.campaign_id, a.reasoning)
    return {"campaign_id": a.campaign_id, "posted": True}


class BatchArg(_A):
    batch_id: int


@tool(
    "review", "get_batch_status", "How far a review batch is: pending / approved / rejected counts.", BatchArg
)
async def get_batch_status(ctx: ToolContext, a: BatchArg) -> dict[str, Any]:
    return ctx.core.review.batch_status(a.batch_id)


class Decisions(_A):
    batch_id: int | None = None
    campaign_id: int | None = None

    @model_validator(mode="after")
    def _one(self) -> Decisions:
        if self.batch_id is None and self.campaign_id is None:
            raise ValueError("give batch_id or campaign_id")
        return self


@tool(
    "review",
    "get_decisions",
    "Human decisions per clip: approved/rejected, reason, platforms, edited captions.",
    Decisions,
)
async def get_decisions(ctx: ToolContext, a: Decisions) -> dict[str, Any]:
    return {"decisions": ctx.core.review.decisions(batch_id=a.batch_id, campaign_id=a.campaign_id)}


class ClipArg(_A):
    clip_id: int


@tool(
    "review",
    "replace_preview",
    "Re-render a clip's preview after edits; Discord and the Review page swap it in place.",
    ClipArg,
)
async def replace_preview(ctx: ToolContext, a: ClipArg) -> dict[str, Any]:
    return {"clip_id": a.clip_id, "job_id": ctx.core.media.request_preview(a.clip_id)}
