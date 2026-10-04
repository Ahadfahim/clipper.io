"""``trends`` server: niche trends, hashtags, saturation, best post times."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clipper.tools.base import ToolContext, tool


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Niche(_A):
    niche: str = Field(min_length=2, max_length=80)


@tool("trends", "niche_trends", "Trending Shorts/TikToks in a niche (titles, views).", Niche)
async def niche_trends(ctx: ToolContext, a: Niche) -> dict[str, Any]:
    return {"items": ctx.core.trends.niche_trends(a.niche)}


class Tags(_A):
    niche: str = Field(min_length=2, max_length=80)
    platform: Literal["youtube", "tiktok", "instagram", "x"]


@tool("trends", "hashtags", "Hashtags that are working in a niche on a platform.", Tags)
async def hashtags(ctx: ToolContext, a: Tags) -> dict[str, Any]:
    return {"hashtags": ctx.core.trends.hashtags(a.niche, a.platform)}


class SourceArg(_A):
    source_id: int


@tool(
    "trends",
    "saturation",
    "How many clips of this source already exist and which moments they used.",
    SourceArg,
)
async def saturation(ctx: ToolContext, a: SourceArg) -> dict[str, Any]:
    return ctx.core.trends.saturation(a.source_id)


class AccountArg(_A):
    account_id: int


@tool(
    "trends",
    "best_post_times",
    "Best local posting times for an account (own history, else platform defaults).",
    AccountArg,
)
async def best_post_times(ctx: ToolContext, a: AccountArg) -> dict[str, Any]:
    return ctx.core.trends.best_post_times(a.account_id)
