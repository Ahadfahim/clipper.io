"""Leases with expiry (PLAN §17.3): campaign, clip edit lock, Chrome profile.

Resource names: ``campaign:<id>``, ``clip:<id>``, ``profile:<name>``, ``account:<id>``.
Every operation runs through the writer queue, so acquire/renew/release are atomic.
"""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import col, delete

from clipper.clock import Clock, SystemClock
from clipper.db.engine import Database, WriteTx
from clipper.db.models import Lease


def campaign_resource(campaign_id: int) -> str:
    return f"campaign:{campaign_id}"


def clip_resource(clip_id: int) -> str:
    return f"clip:{clip_id}"


def profile_resource(profile: str) -> str:
    return f"profile:{profile}"


class LeaseManager:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self.db = db
        self.clock = clock or SystemClock()

    def acquire(self, resource: str, holder: str, ttl_s: float) -> bool:
        now = self.clock.now()

        def job(tx: WriteTx) -> bool:
            row = tx.session.get(Lease, resource)
            if row is not None and row.holder_session != holder and row.expires_at > now:
                return False
            if row is None:
                row = Lease(
                    resource=resource, holder_session=holder, expires_at=now + timedelta(seconds=ttl_s)
                )
            else:
                row.holder_session = holder
                row.expires_at = now + timedelta(seconds=ttl_s)
            tx.add(row)
            return True

        return self.db.write(job)

    def renew(self, resource: str, holder: str, ttl_s: float) -> bool:
        now = self.clock.now()

        def job(tx: WriteTx) -> bool:
            row = tx.session.get(Lease, resource)
            if row is None or row.holder_session != holder or row.expires_at <= now:
                return False
            row.expires_at = now + timedelta(seconds=ttl_s)
            tx.add(row)
            return True

        return self.db.write(job)

    def release(self, resource: str, holder: str) -> bool:
        def job(tx: WriteTx) -> bool:
            row = tx.session.get(Lease, resource)
            if row is None or row.holder_session != holder:
                return False
            tx.session.delete(row)
            return True

        return self.db.write(job)

    def holder(self, resource: str) -> str | None:
        with self.db.read() as s:
            row = s.get(Lease, resource)
            if row is None or row.expires_at <= self.clock.now():
                return None
            return row.holder_session

    def sweep(self) -> int:
        now = self.clock.now()

        def job(tx: WriteTx) -> int:
            result = tx.session.exec(delete(Lease).where(col(Lease.expires_at) <= now))
            return int(result.rowcount or 0)

        return self.db.write(job)
