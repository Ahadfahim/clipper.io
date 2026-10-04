"""Self-scheduled follow-ups (``supervisor.wake_me``): agents have no clock (PLAN §16.1)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlmodel import col, select

from clipper.db.engine import WriteTx
from clipper.db.models import Wakeup
from clipper.db.types import WakeupStatus
from clipper.events.types import WakeupDue
from clipper.services.base import Service, ServiceError

MAX_AHEAD = timedelta(days=14)


class WakeupService(Service):
    def wake_me(
        self,
        *,
        at: datetime | None,
        in_minutes: float | None,
        reason: str,
        session_id: int | None,
        campaign_id: int | None,
        role: str | None,
    ) -> int:
        now = self.now()
        due = (
            at
            if at is not None
            else (now + timedelta(minutes=in_minutes) if in_minutes is not None else None)
        )
        if due is None:
            raise ServiceError("give 'at' (ISO time) or 'in_minutes'")
        if due < now - timedelta(minutes=1) or due > now + MAX_AHEAD:
            raise ServiceError("wake-ups must be between now and 14 days ahead")

        def job(tx: WriteTx) -> int:
            row = Wakeup(
                session_id=session_id, campaign_id=campaign_id, role=role, due_at=due, reason=reason[:300]
            )
            tx.add(row)
            tx.flush()
            assert row.id is not None
            return row.id

        return self.db.write(job)

    def list(self, *, session_id: int | None = None, campaign_id: int | None = None) -> list[dict[str, Any]]:
        with self.db.read() as s:
            q = select(Wakeup).where(Wakeup.status == WakeupStatus.PENDING).order_by(col(Wakeup.due_at))
            if campaign_id is not None:
                q = q.where(Wakeup.campaign_id == campaign_id)
            elif session_id is not None:
                q = q.where(Wakeup.session_id == session_id)
            rows = s.exec(q.limit(50)).all()
        return [
            {
                "id": w.id,
                "due_at": w.due_at.isoformat(),
                "reason": w.reason,
                "campaign_id": w.campaign_id,
                "role": w.role,
            }
            for w in rows
        ]

    def cancel(self, wakeup_id: int) -> None:
        def job(tx: WriteTx) -> None:
            row = tx.session.get(Wakeup, wakeup_id)
            if row is None or row.status != WakeupStatus.PENDING:
                raise ServiceError(f"wake-up {wakeup_id} is not pending")
            row.status = WakeupStatus.CANCELLED
            tx.add(row)

        self.db.write(job)

    def fire_due(self) -> list[int]:
        now = self.now()

        def job(tx: WriteTx) -> list[int]:
            rows = tx.session.exec(
                select(Wakeup).where(Wakeup.status == WakeupStatus.PENDING, col(Wakeup.due_at) <= now)
            ).all()
            out: list[int] = []
            for w in rows:
                w.status = WakeupStatus.FIRED
                tx.add(w)
                assert w.id is not None
                tx.publish(
                    WakeupDue(
                        wakeup_id=w.id,
                        session_id=w.session_id,
                        campaign_id=w.campaign_id,
                        role=w.role,
                        reason=w.reason,
                    )
                )
                out.append(w.id)
            return out

        return self.db.write(job)
