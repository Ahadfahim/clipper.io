from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from clipper.api.app import create_app
from clipper.core import Core
from clipper.fixtures.seed import demo_adapters, seed_demo
from clipper.settings import Settings
from clipper_bot.actions import Actions, Actor
from clipper_bot.config import BotConfig, Channels
from clipper_bot.core_client import CoreClient

REVIEWER = Actor(id=1, name="you", role_ids=frozenset({500}), role_names=frozenset({"Clipper"}))
OUTSIDER = Actor(id=2, name="stranger", role_ids=frozenset({7}), role_names=frozenset({"everyone"}))


@dataclass
class CoreEnv:
    core: Core
    client: CoreClient
    ids: dict[str, Any]


@pytest.fixture(scope="session")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    """Seed the demo data (with rendered previews) once; each test gets a copy of the database."""
    data = tmp_path_factory.mktemp("bot-seed")
    settings = Settings().with_data_dir(data)
    core = Core.create(settings, fakes=True, db_path=data / "seed.sqlite")
    ids = seed_demo(core.db, settings)
    core.close()
    return data, ids


@pytest.fixture
def core_env(tmp_path: Path, seeded: tuple[Path, dict[str, Any]]) -> Iterator[CoreEnv]:
    """The real core API (fixture data) in-process; the bot talks to it over HTTP."""
    data, ids = seeded
    db = tmp_path / "bot.sqlite"
    shutil.copy(data / "seed.sqlite", db)
    settings = Settings().with_data_dir(data)
    core = Core.create(settings, fakes=True, db_path=db)
    demo_adapters(core)
    app = create_app(core=core, fixture_mode=True, start_background=False, settings=settings)
    client = CoreClient("http://127.0.0.1:8765", transport=httpx.ASGITransport(app=app))
    yield CoreEnv(core=core, client=client, ids=ids)
    core.close()


@pytest.fixture
async def core_client(core_env: CoreEnv) -> AsyncIterator[CoreClient]:
    yield core_env.client
    await core_env.client.close()


@pytest.fixture
def cfg() -> BotConfig:
    return BotConfig(
        reviewer_role_name="Clipper",
        channels=Channels(control=10, campaigns=11, clip_review=12, published=13, alerts=14),
    )


@pytest.fixture
def actions(core_client: CoreClient, cfg: BotConfig) -> Actions:
    return Actions(core_client, cfg)
