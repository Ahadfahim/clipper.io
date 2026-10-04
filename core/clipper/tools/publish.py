"""``publish`` server: accounts, scheduling (approved clips only, under caps), metrics, account health."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clipper.tools.base import ToolContext, tool


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Accounts(_A):
    platform: Literal["youtube", "tiktok", "instagram", "x"] | None = None


@tool(
    "publish",
    "list_accounts",
    "Accounts with niche tags, switch/pause state, and posts today vs today's cap.",
    Accounts,
)
async def list_accounts(ctx: ToolContext, a: Accounts) -> dict[str, Any]:
    return {"accounts": ctx.core.publishing.list_accounts(a.platform)}


class Schedule(_A):
    clip_id: int
    account_id: int
    scheduled_at: str = Field(description="ISO-8601 time (with offset) or 'now'")
    title: str | None = Field(default=None, max_length=100)
    caption: str | None = Field(default=None, max_length=2200)
    hashtags: str | None = Field(default=None, max_length=300, description="space-separated #tags")


@tool(
    "publish",
    "schedule_post",
    "Schedule an approved clip on an account. Caps, warm-up, gaps and switches are enforced.",
    Schedule,
)
async def schedule_post(ctx: ToolContext, a: Schedule) -> dict[str, Any]:
    copy = {k: v for k, v in {"title": a.title, "caption": a.caption, "hashtags": a.hashtags}.items() if v}
    post = ctx.core.publishing.schedule(
        a.clip_id, a.account_id, a.scheduled_at, copy=copy or None, created_by=ctx.actor
    )
    return {
        "post_id": post.id,
        "scheduled_at": post.scheduled_at.isoformat(),
        "platform": post.platform,
        "dry_run": post.dry_run,
    }


class Cancel(_A):
    post_id: int
    reason: str = Field(default="", max_length=200)


@tool("publish", "cancel_post", "Cancel a scheduled post.", Cancel)
async def cancel_post(ctx: ToolContext, a: Cancel) -> dict[str, Any]:
    ctx.core.publishing.cancel(a.post_id, by=f"{ctx.actor}: {a.reason}".strip(": "))
    return {"post_id": a.post_id, "cancelled": True}


class PostArg(_A):
    post_id: int


@tool(
    "publish",
    "get_post_metrics",
    "Views/likes/comments/shares of a live post, read from its public page.",
    PostArg,
)
async def get_post_metrics(ctx: ToolContext, a: PostArg) -> dict[str, Any]:
    return await ctx.core.publishing.refresh_metrics(a.post_id)


class AccountArg(_A):
    account_id: int


@tool(
    "publish",
    "account_health",
    "Followers, recent reach and shadowban warning signs for an account.",
    AccountArg,
)
async def account_health(ctx: ToolContext, a: AccountArg) -> dict[str, Any]:
    return await ctx.core.publishing.account_health(a.account_id)
