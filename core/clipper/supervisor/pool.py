"""Slot pool decisions (PLAN §17.1): priorities, one slot reserved for P0, shrinking under high usage,
P0/P1-only near the limit, nothing while rate-limited. ``pick()`` is pure."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

SINGLETON_ROLES = frozenset({"scout", "analyst", "director"})


@dataclass(frozen=True)
class QueuedView:
    id: int
    priority: int
    role: str
    campaign_id: int | None
    queued_at: datetime


@dataclass(frozen=True)
class RunningView:
    id: int
    priority: int
    role: str
    campaign_id: int | None


@dataclass(frozen=True)
class PoolLimits:
    capacity: int  # slots available right now (setting, override and usage shrink applied)
    reserve_p0: bool
    p01_only: bool  # usage near the limit, or the daily run cap reached
    halted: bool  # kill switch, pause, or rate-limited
    low_memory: bool = False  # free RAM under agents.min_free_ram_gb: only the user's own (P0) work starts
    halt_reason: str | None = None  # why `halted` is set, in words ("Clipper is paused.")
    p01_reason: str | None = None  # why only P0/P1 start ("Claude usage is at 92%.")


def pick(
    queued: Sequence[QueuedView], running: Sequence[RunningView], limits: PoolLimits
) -> QueuedView | None:
    if limits.halted or len(running) >= limits.capacity:
        return None
    busy_campaigns = {r.campaign_id for r in running if r.campaign_id is not None}
    busy_roles = {r.role for r in running if r.role in SINGLETON_ROLES}
    non_p0 = sum(1 for r in running if r.priority > 0)
    for q in sorted(queued, key=lambda q: (q.priority, q.queued_at, q.id)):
        if q.campaign_id is not None and q.campaign_id in busy_campaigns:
            continue  # one session per campaign at a time (the lease); events merge meanwhile
        if q.role in busy_roles:
            continue
        if limits.p01_only and q.priority > 1:
            continue
        if limits.low_memory and q.priority > 0:
            continue
        if q.priority > 0 and limits.reserve_p0 and limits.capacity >= 2 and non_p0 >= limits.capacity - 1:
            continue  # keep one slot free for the user
        return q
    return None


def explain_wait(
    queued: Sequence[QueuedView],
    running: Sequence[RunningView],
    limits: PoolLimits,
    *,
    lease_blocked: Mapping[int, str] | None = None,
) -> dict[int, str | None]:
    """Why each queued request hasn't started: the first rule of ``pick`` that stops it, in words. A
    request that nothing stops (it is next in line) maps to None. Pure, like ``pick``."""
    lease_blocked = lease_blocked or {}
    busy_campaigns = {r.campaign_id for r in running if r.campaign_id is not None}
    busy_roles = {r.role for r in running if r.role in SINGLETON_ROLES}
    non_p0 = sum(1 for r in running if r.priority > 0)
    out: dict[int, str | None] = {}
    for q in queued:
        reason: str | None = None
        if limits.halted:
            reason = limits.halt_reason or "Agents are halted."
        elif len(running) >= limits.capacity:
            names = ", ".join(
                f"campaign {r.campaign_id}" if r.campaign_id is not None else r.role for r in running
            )
            reason = f"All {limits.capacity} agent slot{'s are' if limits.capacity != 1 else ' is'} busy ({names})."
        elif q.campaign_id is not None and q.campaign_id in busy_campaigns:
            reason = f"Campaign {q.campaign_id} has an agent running; this starts when it finishes."
        elif q.role in busy_roles:
            reason = f"The {q.role} agent is already running."
        elif q.id in lease_blocked:
            reason = lease_blocked[q.id]
        elif limits.p01_only and q.priority > 1:
            reason = limits.p01_reason or "Only P0 and P1 requests start right now."
        elif limits.low_memory and q.priority > 0:
            reason = "Free memory is low: only your own requests (P0) start."
        elif q.priority > 0 and limits.reserve_p0 and limits.capacity >= 2 and non_p0 >= limits.capacity - 1:
            reason = "The last slot is kept free for your own requests."
        out[q.id] = reason
    return out
