"""FastAPI app: REST + a WebSocket event stream, bound to 127.0.0.1 only.

Protection for a loopback API: the Host header must be loopback (blocks DNS rebinding), browser
Origins must be the app's own (Tauri webview, Vite dev/preview) or the Companion extension (files
only), and CORS is limited to the same list. Mutations are JSON, so a foreign page can't send them
without a CORS preflight that fails.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from clipper import __version__
from clipper.api.routes import ROUTERS
from clipper.core import Core
from clipper.settings import Settings, get_settings

log = logging.getLogger(__name__)

APP_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://127.0.0.1:1420",
    "http://localhost:1420",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
]
EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def _host_ok(host: str | None, allow_test: bool) -> bool:
    if not host:
        return False
    name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    return name in LOOPBACK_HOSTS or (allow_test and name == "testserver")


def origin_allowed(origin: str | None, path: str) -> bool:
    if origin is None:
        return True  # non-browser clients (the bot, the CLI, curl) send no Origin
    if origin in APP_ORIGINS:
        return True
    return bool(EXTENSION_ORIGIN.match(origin)) and path.startswith("/api/files/")


class LoopbackGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        allow_test = getattr(request.app.state, "allow_test_host", False)
        if not _host_ok(request.headers.get("host"), allow_test):
            return JSONResponse({"detail": "loopback only"}, status_code=403)
        if not origin_allowed(request.headers.get("origin"), request.url.path):
            return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        return await call_next(request)


def _fixture_core(settings: Settings) -> Core:
    from clipper.fixtures.seed import demo_adapters, seed_demo

    data = settings.paths.data_dir / "fixture"
    fixture_settings = settings.with_data_dir(data)
    db_path = data / "fixture.sqlite"
    if data.exists():
        for p in data.glob("fixture.sqlite*"):
            p.unlink()
    data.mkdir(parents=True, exist_ok=True)
    core = Core.create(fixture_settings, fakes=True, db_path=db_path)
    demo_adapters(core)
    seed_demo(core.db, fixture_settings)
    return core


def create_app(
    *,
    fixture_mode: bool = False,
    start_background: bool = True,
    core: Core | None = None,
    settings: Settings | None = None,
    allow_test_host: bool = False,
) -> FastAPI:
    settings = settings or get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        own_core = app.state.core is None
        if own_core:
            app.state.core = _fixture_core(settings) if fixture_mode else Core.create(settings)
        c: Core = app.state.core
        bridge_started = False
        if start_background and not fixture_mode:
            from clipper.agents.runner import SdkAgentRunner
            from clipper.browser.bridge import CompanionBridge
            from clipper.supervisor.supervisor import Supervisor

            if isinstance(c.adapters.browser, CompanionBridge):
                await c.adapters.browser.start()  # LOCAL-VERIFY: extension pairing
                bridge_started = True
            app.state.supervisor = Supervisor(c, SdkAgentRunner(c))
            await app.state.supervisor.start()
        try:
            yield
        finally:
            if app.state.supervisor is not None:
                await app.state.supervisor.stop()
            if bridge_started:
                await c.adapters.browser.stop()  # type: ignore[attr-defined]
            if own_core:
                c.close()

    app = FastAPI(title="Clipper.io core", version=__version__, lifespan=lifespan)
    app.state.core = core
    app.state.supervisor = None
    app.state.fixture_mode = fixture_mode
    app.state.allow_test_host = allow_test_host
    app.add_middleware(LoopbackGuard)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=APP_ORIGINS,
        allow_origin_regex=EXTENSION_ORIGIN.pattern,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["content-type"],
    )
    for router in ROUTERS:
        app.include_router(router)

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket, after: int = 0, types: str | None = None) -> None:
        allow_test = getattr(websocket.app.state, "allow_test_host", False)
        origin = websocket.headers.get("origin")
        if not _host_ok(websocket.headers.get("host"), allow_test) or (
            origin is not None and origin not in APP_ORIGINS
        ):
            await websocket.close(code=4403)
            return
        await websocket.accept()
        c: Core = websocket.app.state.core
        wanted = set(types.split(",")) if types else None
        sub = c.bus.subscribe(wanted)
        try:
            last = after
            for env in c.bus.since(after, limit=500, types=wanted):
                await websocket.send_text(env.model_dump_json())
                last = env.id
            while True:
                env = await sub.get(timeout=15)
                if env is None:
                    await websocket.send_text('{"type":"ping"}')
                    continue
                if env.id <= last:
                    continue
                await websocket.send_text(env.model_dump_json())
                last = env.id
        except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            sub.close()

    @app.get("/api/version")
    def version() -> dict[str, Any]:
        return {"version": __version__, "ffmpeg": shutil.which(settings.paths.ffmpeg("ffmpeg")) is not None}

    return app
