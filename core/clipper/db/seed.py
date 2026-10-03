"""Seeding: base rows every install needs, and demo fixtures for UI work."""

from __future__ import annotations

from clipper.db.engine import Database, WriteTx
from clipper.db.models import KV, Marketplace, Platform
from clipper.settings import Settings

MARKETPLACE_NAMES = {"vyro": "Vyro", "whop": "Whop Content Rewards"}
PLATFORM_NAMES = {"youtube": "YouTube Shorts", "tiktok": "TikTok", "instagram": "Instagram Reels", "x": "X"}


def seed_base(db: Database, settings: Settings) -> None:
    """Idempotent: creates marketplaces, platforms and control defaults if missing."""

    def job(tx: WriteTx) -> None:
        s = tx.session
        for mid, name in MARKETPLACE_NAMES.items():
            if s.get(Marketplace, mid) is None:
                tx.add(
                    Marketplace(
                        id=mid,
                        name=name,
                        enabled=settings.switches.marketplaces.get(mid, True),
                        mode=settings.scout.mode,
                    )
                )
        for pid, name in PLATFORM_NAMES.items():
            if s.get(Platform, pid) is None:
                tx.add(Platform(id=pid, name=name, enabled=settings.switches.socials.get(pid, pid != "x")))
        defaults = {"dry_run": settings.dry_run_default, "paused": False, "kill_switch": False}
        for key, value in defaults.items():
            if s.get(KV, key) is None:
                tx.add(KV(key=key, value_json=value))

    db.write(job)


def seed_fixtures(db: Database, settings: Settings) -> None:
    from clipper.fixtures.seed import seed_demo

    seed_base(db, settings)
    seed_demo(db, settings)
