"""``notify`` server: alerts, questions for the user (answer resumes the session), reports."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clipper.tools.base import ToolContext, tool


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AlertArgs(_A):
    level: Literal["info", "warning", "error"]
    text: str = Field(min_length=1, max_length=1000)


@tool("notify", "alert", "Post to #alerts and the dashboard's Problems tab.", AlertArgs)
async def alert(ctx: ToolContext, a: AlertArgs) -> dict[str, Any]:
    ctx.core.notify.alert(a.level, a.text, source=ctx.role, campaign_id=ctx.campaign_id)
    return {"sent": True}


class Ask(_A):
    question: str = Field(min_length=5, max_length=1000)
    options: list[str] = Field(min_length=1, max_length=5)
    timeout_minutes: float | None = Field(default=None, gt=0, le=10080)


@tool(
    "notify",
    "ask_user",
    "Ask the user instead of guessing. End your turn after asking: the answer resumes this session.",
    Ask,
)
async def ask_user(ctx: ToolContext, a: Ask) -> dict[str, Any]:
    qid = ctx.core.notify.ask_user(
        a.question,
        a.options,
        session_id=ctx.session_id,
        campaign_id=ctx.campaign_id,
        timeout_s=a.timeout_minutes * 60 if a.timeout_minutes else None,
    )
    return {"question_id": qid, "next": "end your turn; you will be resumed with the answer"}


class ReportArgs(_A):
    markdown: str = Field(min_length=10, max_length=8000)


@tool(
    "notify",
    "send_report",
    "Send a markdown report (daily Analyst report) to Discord and the dashboard.",
    ReportArgs,
)
async def send_report(ctx: ToolContext, a: ReportArgs) -> dict[str, Any]:
    ctx.core.notify.send_report(a.markdown, source=ctx.role)
    return {"sent": True}
