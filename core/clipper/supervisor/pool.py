"""Slot pool decisions (PLAN §17.1): priorities, one slot reserved for P0, shrinking under high usage,
P0/P1-only near the limit, nothing while rate-limited. ``pick()`` is pure."""

from __future__ import annotations

from collections.abc import Sequence
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
