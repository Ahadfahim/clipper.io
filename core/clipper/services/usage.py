"""Claude plan usage window (no money): utilization from SDK rate-limit events, pacing decisions.

The supervisor's pool (``clipper.supervisor.pool``) reads ``max_slots()`` and ``p01_only()``; the
``supervisor.get_usage`` tool shows the same numbers to agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlmodel import col, select

from clipper.db.engine import WriteTx
from clipper.db.models import UsageWindow
from clipper.events.types import UsageUpdated
from clipper.services.base import Service


@dataclass(frozen=True)
class UsageSnapshot:
    utilization: float
    resets_at: datetime | None
    rate_limited: bool
    window_type: str


class UsageTracker(Service):
    def current(self) -> UsageSnapshot:
        with self.db.read() as s:
            row = s.exec(select(UsageWindow).order_by(col(UsageWindow.id).desc()).limit(1)).first()
        if row is None:
            return UsageSnapshot(0.0, None, False, "five_hour")
        if row.resets_at is not None and row.resets_at <= self.now():
            return UsageSnapshot(0.0, None, False, row.window_type)
        return UsageSnapshot(row.utilization, row.resets_at, row.rate_limited, row.window_type)

    def record(
        self,
        *,
        utilization: float | None,
        resets_at: datetime | None,
        rate_limited: bool,
        window_type: str = "five_hour",
        tokens: int = 0,
    ) -> UsageSnapshot:
        def job(tx: WriteTx) -> UsageSnapshot:
            row = tx.session.exec(select(UsageWindow).order_by(col(UsageWindow.id).desc()).limit(1)).first()
            if row is None or (
                row.resets_at is not None
                and resets_at is not None
                and abs((row.resets_at - resets_at).total_seconds()) > 60
            ):
                row = UsageWindow(started=self.now(), resets_at=resets_at, window_type=window_type)
            if utilization is not None:
                row.utilization = max(0.0, min(1.0, utilization))
            if rate_limited:
                row.utilization = max(row.utilization, 1.0)
            row.rate_limited = rate_limited
            row.resets_at = resets_at or row.resets_at
            row.tokens += tokens
            tx.add(row)
            snap = UsageSnapshot(row.utilization, row.resets_at, row.rate_limited, row.window_type)
            tx.publish(
                UsageUpdated(
                    utilization=snap.utilization,
                    resets_at=snap.resets_at.isoformat() if snap.resets_at else None,
                    rate_limited=snap.rate_limited,
                    max_slots=self.max_slots(snap),
                )
            )
            return snap

        return self.db.write(job)

    def add_tokens(self, tokens: int) -> None:
        def job(tx: WriteTx) -> None:
            row = tx.session.exec(select(UsageWindow).order_by(col(UsageWindow.id).desc()).limit(1)).first()
            if row is None:
                row = UsageWindow(started=self.now())
            row.tokens += tokens
            tx.add(row)

        self.db.write(job)

    def max_slots(self, snap: UsageSnapshot | None = None) -> int:
        snap = snap or self.current()
        slots = self.settings.agents.slots
        if snap.rate_limited:
            return 0
        steps = sorted(
            ((float(k), v) for k, v in self.settings.usage.shrink_steps.items()), key=lambda kv: kv[0]
        )
        for threshold, cap in steps:
            if snap.utilization >= threshold:
                slots = min(slots, cap)
        return slots

    def p01_only(self, snap: UsageSnapshot | None = None) -> bool:
        snap = snap or self.current()
        return snap.utilization >= self.settings.usage.p01_only_at

    def as_dict(self) -> dict[str, Any]:
        snap = self.current()
        pace = "normal"
        if snap.rate_limited:
            pace = "stopped until reset"
        elif self.p01_only(snap):
            pace = "only user-facing and money-critical work"
        elif self.max_slots(snap) < self.settings.agents.slots:
            pace = "slowed"
        return {
            "utilization": round(snap.utilization, 3),
            "resets_at": snap.resets_at.isoformat() if snap.resets_at else None,
            "rate_limited": snap.rate_limited,
            "max_slots": self.max_slots(snap),
            "pace": pace,
        }
