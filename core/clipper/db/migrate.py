"""Alembic helpers (implemented in WP1)."""

from __future__ import annotations

from pathlib import Path


def upgrade_to_head(db_path: Path) -> None:
    raise NotImplementedError("WP1")


def current_revision(db_path: Path) -> str | None:
    raise NotImplementedError("WP1")


def head_revision() -> str | None:
    raise NotImplementedError("WP1")
