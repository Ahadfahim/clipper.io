"""``BrowserBridge``: how core drives Chrome. ``CompanionBridge`` is the real WebSocket server the
Companion extension connects to; ``FakeBrowserBridge`` scripts results for tests.

Rules enforced here (PLAN §5, §17.3): pairing token required, one action at a time per Chrome profile,
a challenge (login/CAPTCHA/verification) is reported, never solved.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from clipper.browser.protocol import PROTOCOL_VERSION, Hello, RecipeResult, Result, Status

log = logging.getLogger(__name__)


class BridgeError(RuntimeError):
    pass


class ProfileNotConnected(BridgeError):
    pass


class BrowserBridge(Protocol):
    def connected_profiles(self) -> list[str]: ...
    def current_url(self, profile: str | None) -> str | None: ...
    async def run_recipe(
        self, profile: str, recipe: str, params: dict[str, Any], *, dry_run: bool = False
    ) -> RecipeResult: ...
    async def action(self, profile: str, action: dict[str, Any]) -> RecipeResult: ...
    async def reload_extension(self, profile: str) -> None: ...


# ------------------------------------------------------------------ fake


@dataclass
class FakeBrowserBridge:
    """Scripted bridge: ``recipes[name]`` is a RecipeResult or a callable(params) -> RecipeResult."""

    profiles: dict[str, str | None] = field(default_factory=lambda: {"main": "https://studio.youtube.com/"})
    recipes: dict[str, RecipeResult | Callable[[dict[str, Any]], RecipeResult]] = field(
        default_factory=lambda: {}
    )
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=lambda: [])

    def connected_profiles(self) -> list[str]:
        return list(self.profiles)

    def current_url(self, profile: str | None) -> str | None:
        if profile is None:
            return next(iter(self.profiles.values()), None)
        return self.profiles.get(profile)

    async def run_recipe(
        self, profile: str, recipe: str, params: dict[str, Any], *, dry_run: bool = False
    ) -> RecipeResult:
        if profile not in self.profiles:
            raise ProfileNotConnected(f"Chrome profile {profile!r} is not connected")
        self.calls.append((profile, recipe, params))
        scripted = self.recipes.get(recipe)
        if scripted is None:
            return RecipeResult(ok=False, error=f"no scripted result for {recipe}")
        return scripted(params) if callable(scripted) else scripted

    async def action(self, profile: str, action: dict[str, Any]) -> RecipeResult:
        if profile not in self.profiles:
            raise ProfileNotConnected(f"Chrome profile {profile!r} is not connected")
        self.calls.append((profile, f"action:{action.get('kind')}", action))
        if action.get("kind") == "navigate":
            self.profiles[profile] = str(action.get("url"))
            return RecipeResult(ok=True, data={"url": action.get("url")})
        if action.get("kind") in ("snapshot", "screenshot"):
            return RecipeResult(
                ok=True,
                data={"url": self.profiles[profile]},
                screenshot="data:image/png;base64,",
                dom="<main/>",
            )
        return RecipeResult(ok=True, data={})

    async def reload_extension(self, profile: str) -> None:
        if profile not in self.profiles:
            raise ProfileNotConnected(f"Chrome profile {profile!r} is not connected")
        self.calls.append((profile, "reload", {}))


# ------------------------------------------------------------------ real


@dataclass
class _Peer:
    profile: str
    conn: ServerConnection
    url: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict[str, asyncio.Future[Result]] = field(default_factory=lambda: {})


EXTENSION_ORIGIN = re.compile(r"chrome-extension://[a-p]{32}")
# a result carries a screenshot (JPEG, normally well under 1 MB) and a simplified DOM
MAX_MESSAGE_BYTES = 64 * 2**20


class CompanionBridge:
    """WebSocket server on 127.0.0.1 for the Companion extension(s), one connection per Chrome profile."""

    def __init__(
        self,
        token: str,
        host: str = "127.0.0.1",
        port: int = 8766,
        timeout_s: float = 90.0,
        on_status: Callable[[str, str | None], None] | None = None,
    ) -> None:
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("the Companion bridge listens on loopback only")
        self.token = token
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self.on_status = on_status
        self._peers: dict[str, _Peer] = {}
        self._server: Server | None = None

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(24)

    async def start(self) -> int:
        self._server = await serve(
            self._handle,
            self.host,
            self.port,
            origins=[EXTENSION_ORIGIN, None],
            max_size=MAX_MESSAGE_BYTES,
        )
        sock = next(iter(self._server.sockets))
        self.port = int(sock.getsockname()[1])
        return self.port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    def connected_profiles(self) -> list[str]:
        return sorted(self._peers)

    def current_url(self, profile: str | None) -> str | None:
        if profile is None:
            if len(self._peers) == 1:
                return next(iter(self._peers.values())).url
            return None
        peer = self._peers.get(profile)
        return peer.url if peer else None

    async def _handle(self, conn: ServerConnection) -> None:
        try:
            raw = await asyncio.wait_for(conn.recv(), timeout=10)
            hello = Hello.model_validate(json.loads(raw))
        except (TimeoutError, ValidationError, ValueError, ConnectionClosed):
            await conn.close(code=4400, reason="expected hello")
            return
        if not secrets.compare_digest(hello.token, self.token):
            await conn.close(code=4401, reason="bad pairing token")
            return
        if hello.protocol != PROTOCOL_VERSION:
            await conn.close(code=4426, reason=f"protocol {hello.protocol} != {PROTOCOL_VERSION}")
            return
        old = self._peers.get(hello.profile)
        if old is not None:
            with contextlib.suppress(Exception):
                await old.conn.close(code=4409, reason="replaced by a new connection")
        peer = _Peer(hello.profile, conn, hello.url)
        self._peers[hello.profile] = peer
        log.info("Companion %s connected (extension %s)", hello.profile, hello.version)
        await conn.send(
            json.dumps({"type": "welcome", "profile": hello.profile, "protocol": PROTOCOL_VERSION})
        )
        try:
            async for raw_msg in conn:
                self._on_message(peer, raw_msg)
        except ConnectionClosed:
            pass
        finally:
            log.info(
                "Companion %s disconnected (code %s %s)",
                hello.profile,
                conn.close_code,
                conn.close_reason or "",
            )
            if self._peers.get(hello.profile) is peer:
                del self._peers[hello.profile]
            for fut in peer.pending.values():
                if not fut.done():
                    fut.set_exception(BridgeError(f"Chrome profile {peer.profile!r} disconnected"))

    def _on_message(self, peer: _Peer, raw: str | bytes) -> None:
        try:
            msg: dict[str, Any] = json.loads(raw)
        except ValueError:
            return
        kind = msg.get("type")
        if kind == "result":
            try:
                result = Result.model_validate(msg)
            except ValidationError:
                return
            fut = peer.pending.pop(result.id, None)
            if fut is not None and not fut.done():
                fut.set_result(result)
            if result.data.get("url"):
                peer.url = str(result.data["url"])
        elif kind == "status":
            status = Status.model_validate(msg)
            peer.url = status.url
            if self.on_status is not None:
                self.on_status(peer.profile, status.url)

    async def _request(self, profile: str, message: dict[str, Any]) -> RecipeResult:
        peer = self._peers.get(profile)
        if peer is None:
            raise ProfileNotConnected(f"Chrome profile {profile!r} is not connected")
        async with peer.lock:  # one action at a time per profile
            req_id = uuid.uuid4().hex
            fut: asyncio.Future[Result] = asyncio.get_running_loop().create_future()
            peer.pending[req_id] = fut
            try:
                await peer.conn.send(json.dumps({**message, "id": req_id}))
                result = await asyncio.wait_for(fut, timeout=self.timeout_s)
            except TimeoutError as exc:
                raise BridgeError(
                    f"{message.get('recipe') or message.get('action')} timed out after {self.timeout_s:.0f}s"
                ) from exc
            finally:
                peer.pending.pop(req_id, None)
            return RecipeResult.from_result(result)

    async def run_recipe(
        self, profile: str, recipe: str, params: dict[str, Any], *, dry_run: bool = False
    ) -> RecipeResult:
        return await self._request(
            profile, {"type": "run", "recipe": recipe, "params": params, "dry_run": dry_run}
        )

    async def action(self, profile: str, action: dict[str, Any]) -> RecipeResult:
        return await self._request(profile, {"type": "action", "action": action})

    async def reload_extension(self, profile: str) -> None:
        """Ask the extension to reload itself (after `just build` changed its recipes). It reconnects
        on its own a few seconds later."""
        peer = self._peers.get(profile)
        if peer is None:
            raise ProfileNotConnected(f"Chrome profile {profile!r} is not connected")
        await peer.conn.send(json.dumps({"type": "reload"}))
