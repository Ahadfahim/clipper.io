from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from clipper.agents.env import scrub_process_env
from clipper.clock import FakeClock
from clipper.db.engine import Database
from clipper.events.bus import EventBus
from clipper.secrets import use_memory_backend
from clipper.settings import Settings, load_settings

FIXTURES = Path(__file__).parent / "fixtures"

scrub_process_env()
os.environ.pop("CLIPPER_SETTINGS", None)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    skip = pytest.mark.skip(reason="ffmpeg/ffprobe not on PATH")
    for item in items:
        if "ffmpeg" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _memory_keyring() -> None:
    use_memory_backend()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        Path("does-not-exist.toml"),
        overrides={
            "paths": {
                "data_dir": str(tmp_path / "data"),
                "ffmpeg_bin": None,
                "models_dir": str(tmp_path / "models"),
                "gpu_python": str(tmp_path / "no-gpu" / "python"),
            },
            "media": {"encoder": "x264"},
        },
    )


@pytest.fixture
def db(tmp_path: Path, settings: Settings) -> Iterator[Database]:
    from clipper.db.seed import seed_base

    database = Database(tmp_path / "test.sqlite", create=True)
    seed_base(database, settings)
    yield database
    database.close()


@pytest.fixture
def bus(db: Database) -> EventBus:
    return EventBus(db)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
