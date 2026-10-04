"""CompanionBridge over a real localhost WebSocket, with a test client playing the extension."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from clipper.browser.bridge import BridgeError, CompanionBridge, ProfileNotConnected


async def _extension(
    port: int, token: str, profile: str = "main", *, delay: float = 0.0, log: list[str] | None = None
) -> tuple[ClientConnection, asyncio.Task[None]]:
    ws = await connect(f"ws://127.0.0.1:{port}")
    await ws.send(
        json.dumps(
            {
                "type": "hello",
                "profile": profile,
                "token": token,
                "version": "0.1.0",
                "protocol": 1,
                "url": "https://whop.com/",
            }
        )
    )
    welcome = json.loads(await ws.recv())
    assert welcome["type"] == "welcome"

    async def serve() -> None:
        async for raw in ws:
            msg: dict[str, Any] = json.loads(raw)
            if log is not None:
                log.append(f"start {msg.get('recipe') or msg['action']['kind']}")
            await asyncio.sleep(delay)
            if log is not None:
                log.append(f"end {msg.get('recipe') or msg['action']['kind']}")
            if msg["type"] == "run" and msg["recipe"] == "youtube.upload_short":
                reply = {
                    "type": "result",
                    "id": msg["id"],
                    "ok": True,
                    "data": {"post_url": "https://youtube.com/shorts/abc"},
                }
            elif msg["type"] == "run" and msg["recipe"] == "tiktok.upload":
                reply = {
                    "type": "result",
                    "id": msg["id"],
                    "ok": False,
                    "error": "verification",
                    "challenge": "verification",
                    "screenshot": "data:image/png;base64,AAA",
                    "dom": "<div>verify</div>",
                }
            else:
                reply = {
                    "type": "result",
                    "id": msg["id"],
                    "ok": True,
                    "data": {"url": msg.get("action", {}).get("url")},
                }
            await ws.send(json.dumps(reply))

    return ws, asyncio.create_task(serve())


async def test_pairing_round_trip_and_challenge() -> None:
    bridge = CompanionBridge("secret-token", port=0, timeout_s=5)
    port = await bridge.start()
    try:
        ws, task = await _extension(port, "secret-token")
        await asyncio.sleep(0.05)
        assert bridge.connected_profiles() == ["main"]
        assert bridge.current_url("main") == "https://whop.com/"
        ok = await bridge.run_recipe("main", "youtube.upload_short", {"title": "x"})
        assert ok.ok and ok.data["post_url"] == "https://youtube.com/shorts/abc"
        bad = await bridge.run_recipe("main", "tiktok.upload", {})
        assert not bad.ok and bad.challenge == "verification" and bad.dom
        nav = await bridge.action("main", {"kind": "navigate", "url": "https://www.tiktok.com/upload"})
        assert nav.ok and bridge.current_url("main") == "https://www.tiktok.com/upload"
        with pytest.raises(ProfileNotConnected):
            await bridge.run_recipe("other", "youtube.upload_short", {})
        await ws.close()
        task.cancel()
        await asyncio.sleep(0.05)
        assert bridge.connected_profiles() == []
    finally:
        await bridge.stop()


async def test_wrong_token_is_rejected() -> None:
    bridge = CompanionBridge("right", port=0)
    port = await bridge.start()
    try:
        ws = await connect(f"ws://127.0.0.1:{port}")
        await ws.send(json.dumps({"type": "hello", "profile": "main", "token": "wrong", "protocol": 1}))
        with pytest.raises(ConnectionClosed):
            await ws.recv()
        assert ws.close_code == 4401
        assert bridge.connected_profiles() == []
    finally:
        await bridge.stop()


async def test_one_action_at_a_time_per_profile() -> None:
    bridge = CompanionBridge("t", port=0, timeout_s=5)
    port = await bridge.start()
    log: list[str] = []
    try:
        _ws, task = await _extension(port, "t", delay=0.1, log=log)
        await asyncio.sleep(0.05)
        await asyncio.gather(
            bridge.action("main", {"kind": "navigate", "url": "https://a.example"}),
            bridge.action("main", {"kind": "navigate", "url": "https://b.example"}),
        )
        assert log == ["start navigate", "end navigate", "start navigate", "end navigate"]
        task.cancel()
    finally:
        await bridge.stop()


async def test_timeout_raises() -> None:
    bridge = CompanionBridge("t", port=0, timeout_s=0.2)
    port = await bridge.start()
    try:
        ws = await connect(f"ws://127.0.0.1:{port}")
        await ws.send(json.dumps({"type": "hello", "profile": "main", "token": "t", "protocol": 1}))
        await ws.recv()
        with pytest.raises(BridgeError, match="timed out"):
            await bridge.action("main", {"kind": "snapshot"})
        await ws.close()
    finally:
        await bridge.stop()


def test_bridge_refuses_non_loopback() -> None:
    with pytest.raises(ValueError, match="loopback"):
        CompanionBridge("t", host="0.0.0.0")
