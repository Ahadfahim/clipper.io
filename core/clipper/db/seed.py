"""Seeding (implemented in WP1/WP6)."""

from __future__ import annotations

from clipper.db.engine import Database
from clipper.settings import Settings


def seed_base(db: Database, settings: Settings) -> None:
    raise NotImplementedError("WP1")


def seed_fixtures(db: Database, settings: Settings) -> None:
    raise NotImplementedError("WP6")
