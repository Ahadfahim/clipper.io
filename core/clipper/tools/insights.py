"""``insights`` server: read-only numbers for the Analyst and Director."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clipper.tools.base import ToolContext, tool


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Query(_A):
    sql: str = Field(min_length=6, max_length=4000, description="one SELECT/WITH statement; max 200 rows")


@tool("insights", "query", "Run one read-only SQL SELECT on the Clipper database.", Query)
async def query(ctx: ToolContext, a: Query) -> dict[str, Any]:
    return ctx.core.insights.query(a.sql)


class By(_A):
    dimension: Literal["marketplace", "campaign", "platform", "account", "layout", "caption_style", "hour"]
    days: int = Field(default=30, ge=1, le=365)


@tool("insights", "performance_by", "Posts, views and earnings grouped by a dimension.", By)
async def performance_by(ctx: ToolContext, a: By) -> dict[str, Any]:
    return {"rows": ctx.core.insights.performance_by(a.dimension, a.days)}


class Approval(_A):
    dimension: Literal["campaign", "marketplace", "layout", "caption_style", "score_tier", "reason"]


@tool("insights", "approval_rate_by", "Human approval rate grouped by a dimension.", Approval)
async def approval_rate_by(ctx: ToolContext, a: Approval) -> dict[str, Any]:
    return {"rows": ctx.core.insights.approval_rate_by(a.dimension)}


class Top(_A):
    n: int = Field(default=10, ge=1, le=50)
    metric: Literal["views", "earnings"] = "views"


@tool("insights", "top_clips", "Best clips by views or earnings.", Top)
async def top_clips(ctx: ToolContext, a: Top) -> dict[str, Any]:
    return {"rows": ctx.core.insights.top_clips(a.n, a.metric)}


class CampaignArg(_A):
    campaign_id: int


@tool("insights", "campaign_report", "Clips, decisions, posts and money for one campaign.", CampaignArg)
async def campaign_report(ctx: ToolContext, a: CampaignArg) -> dict[str, Any]:
    return ctx.core.insights.campaign_report(a.campaign_id)
