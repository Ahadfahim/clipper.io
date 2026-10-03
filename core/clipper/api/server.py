"""``clipper api``: uvicorn on 127.0.0.1 (the Tauri app launches this as its sidecar)."""

from __future__ import annotations

import uvicorn

from clipper.agents.env import scrub_process_env
from clipper.api.app import create_app
from clipper.settings import get_settings


def serve(*, fixture_mode: bool = False) -> None:
    scrub_process_env()
    settings = get_settings()
    fixture = fixture_mode or settings.api.fixture_mode
    app = create_app(fixture_mode=fixture, settings=settings)
    uvicorn.run(app, host=settings.api.host, port=settings.api.port, log_level="info", ws="websockets")
