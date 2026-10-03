from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from clipper.agents.env import scrub_process_env
from clipper.clock import FakeClock
from clipper.db.engine import Database
from clipper.events.bus import EventBus
from clipper.secrets import use_memory_backend
from clipper.settings import Settings, load_settings

if TYPE_CHECKING:
    from clipper.core import Core
    from clipper.tools.base import CallResult, ToolContext

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


@pytest.fixture
def core(settings: Settings) -> Iterator[Core]:
    from clipper.core import Core

    c = Core.create(settings, fakes=True)
    yield c
    c.close()


def tool_ctx(core: Core, role: str = "developer", **kw: object) -> ToolContext:
    from clipper.tools.base import ToolContext

    skip = frozenset({"access", "max_turns"}) if role == "developer" else frozenset()
    return ToolContext(core, role=role, skip_rules=skip, **kw)  # type: ignore[arg-type]


async def call(
    core: Core, server: str, name: str, args: dict[str, object], role: str = "developer", **kw: object
) -> CallResult:
    from clipper.tools.base import REGISTRY, call_tool, ensure_loaded

    ensure_loaded()
    return await call_tool(tool_ctx(core, role, **kw), REGISTRY[server][name], dict(args))
