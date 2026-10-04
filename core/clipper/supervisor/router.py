"""Event -> agent request routing (PLAN §3 lifecycle, §17.1 priorities). ``route()`` is pure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from clipper.events.bus import EventEnvelope

P0, P1, P2, P3 = 0, 1, 2, 3

# Jobs whose completion is worth waking the Campaign agent for. Downloads chain analysis on their own;
# final renders feed the posting queue without the agent.
RESUME_JOB_KINDS = {"analyze", "render_preview"}


@dataclass(frozen=True)
class RequestSpec:
    priority: int
    role: str
    kind: str
    campaign_id: int | None
    event: dict[str, Any]


@dataclass(frozen=True)
class SessionInfo:
    role: str
    campaign_id: int | None


SessionLookup = Callable[[int], SessionInfo | None]
ClipCampaign = Callable[[int], int | None]


def compact(env: EventEnvelope) -> dict[str, Any]:
    return {
        "id": env.id,
        "type": env.type,
        "entity_id": env.entity_id,
        "payload": env.payload,
        "ts": env.ts.isoformat(),
    }


def route(env: EventEnvelope, *, session_of: SessionLookup, clip_campaign: ClipCampaign) -> list[RequestSpec]:
    p = env.payload
    ev = compact(env)

    def campaign(priority: int, cid: Any) -> list[RequestSpec]:
        return [RequestSpec(priority, "campaign", env.type, int(cid), ev)] if cid is not None else []

    t = env.type
    if t == "campaign.taken":
        return campaign(P2, p["campaign_id"])
    if t == "job.done":
        if p.get("campaign_id") is None:
            return []
        if p.get("kind") in RESUME_JOB_KINDS or p.get("status") == "failed":
            return campaign(P2, p["campaign_id"])
        return []
    if t == "review.shipped":
        return campaign(P1, p["campaign_id"])
    if t == "post.live":
        return campaign(P1, p.get("campaign_id"))
    if t == "campaign.ending":
        return campaign(P1, p["campaign_id"])
    if t == "recut.requested":
        cid = p.get("campaign_id") or clip_campaign(int(p["clip_id"]))
        return campaign(P0, cid)
    if t == "spec.updated" and p.get("by") == "user":
        return campaign(P0, p["campaign_id"])
    if t == "note.added":
        if p.get("scope") == "global":
            return []  # pinned global notes go into every agent's next run
        cid = p.get("campaign_id")
        if cid is None and p.get("scope") == "campaign":
            cid = p.get("scope_id")
        if cid is None and p.get("scope") == "clip" and p.get("scope_id"):
            cid = clip_campaign(int(p["scope_id"]))
        return campaign(P0, cid) if cid is not None else [RequestSpec(P0, "director", t, None, ev)]
    if t == "question.answered":
        sid = p.get("session_id")
        info = session_of(int(sid)) if sid is not None else None
        if info is not None and info.role == "campaign":
            return campaign(P0, info.campaign_id)
        if info is not None:
            return [RequestSpec(P0, info.role, t, info.campaign_id, ev)]
        return campaign(P0, p.get("campaign_id"))
    if t == "user.chat":
        return [RequestSpec(P0, "director", t, None, ev)]
    if t == "wakeup.due":
        role = p.get("role") or ("campaign" if p.get("campaign_id") else None)
        if role in (None, "campaign"):
            return campaign(P2, p.get("campaign_id"))
        if role in ("scout", "analyst", "director"):
            return [RequestSpec(P0 if role == "director" else P3, role, t, None, ev)]
        return []
    if t == "watchdog.nudge":
        return campaign(P2, p["campaign_id"])
    if t == "trigger.fired":
        return [RequestSpec(P3, str(p["name"]), t, None, ev)]
    return []
