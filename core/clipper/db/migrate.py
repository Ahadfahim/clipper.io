"""Alembic helpers: upgrade, current and head revisions, autogenerate (dev)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


def upgrade_to_head(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(db_path), "head")
    from clipper.db.engine import make_engine

    engine = make_engine(db_path)  # sets WAL on first connect
    with engine.connect():
        pass
    engine.dispose()


def current_revision(db_path: Path) -> str | None:
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config(Path("unused.sqlite"))).get_current_head()


def autogenerate(db_path: Path, message: str) -> None:
    """Dev helper: diff the models against ``db_path`` (at head) and write a new revision."""
    command.revision(alembic_config(db_path), message=message, autogenerate=True)
