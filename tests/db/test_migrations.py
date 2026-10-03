from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine
from sqlmodel import SQLModel

import clipper.db.models  # noqa: F401
from clipper.db.engine import Database
from clipper.db.migrate import current_revision, head_revision, upgrade_to_head

PLAN_TABLES = {
    "campaign", "source", "analysis", "moment", "clip", "review", "post", "submission", "marketplace",
    "platform", "metric", "account", "job", "agent_session", "agent_event", "usage_window", "wakeup",
    "question", "lesson", "edl", "edit_op", "agenda_item", "note", "agent_request", "lease", "event",
}  # fmt: skip


def test_upgrade_creates_every_plan_table(tmp_path: Path) -> None:
    db = tmp_path / "m.sqlite"
    upgrade_to_head(db)
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert tables >= PLAN_TABLES
    assert current_revision(db) == head_revision() == "0001_initial"


def test_migration_matches_models(tmp_path: Path) -> None:
    db = tmp_path / "m.sqlite"
    upgrade_to_head(db)
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), SQLModel.metadata)
    engine.dispose()
    assert diff == [], f"models drifted from migrations; run autogenerate: {diff}"


def test_wal_mode_and_foreign_keys(tmp_path: Path) -> None:
    database = Database(tmp_path / "w.sqlite", create=True)
    try:
        with database.engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    finally:
        database.close()


def test_upgrade_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "m.sqlite"
    upgrade_to_head(db)
    upgrade_to_head(db)
    assert current_revision(db) == head_revision()
