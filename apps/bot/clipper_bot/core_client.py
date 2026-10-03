"""Async client for the core's internal API (127.0.0.1 only). The bot never touches the
database: every decision goes through the same services and guards as the dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx

log = logging.getLogger(__name__)

Via = Literal["discord"]
VIA: Via = "discord"


class CoreError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class CoreClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.base_url, timeout=20.0, transport=transport)

    async def close(self) -> None:
        await self.http.aclose()

    async def _req(self, method: str, path: str, **kw: Any) -> Any:
        res = await self.http.request(method, path, **kw)
        if res.status_code >= 400:
            try:
                detail = res.json().get("detail", res.text)
            except ValueError:
                detail = res.text
            raise CoreError(res.status_code, detail if isinstance(detail, str) else json.dumps(detail))
        return res.json() if res.content else None

    # ------------------------------------------------------------ reads
    async def settings(self) -> dict[str, Any]:
        return (await self._req("GET", "/api/settings"))["settings"]

    async def status(self) -> dict[str, Any]:
        return await self._req("GET", "/api/status")

    async def campaign(self, campaign_id: int) -> dict[str, Any]:
        return await self._req("GET", f"/api/campaigns/{campaign_id}")

    async def batch(self, batch_id: int) -> dict[str, Any]:
        return await self._req("GET", f"/api/review/batches/{batch_id}")

    async def clip(self, clip_id: int) -> dict[str, Any]:
        return await self._req("GET", f"/api/clips/{clip_id}")

    async def question(self, question_id: int) -> dict[str, Any] | None:
        for q in await self._req("GET", "/api/questions"):
            if q["id"] == question_id:
                return q
        return None

    async def session(self, session_id: int) -> dict[str, Any]:
        return await self._req("GET", f"/api/agents/sessions/{session_id}", params={"limit": 1})

    async def preview_path(self, clip_id: int) -> dict[str, Any]:
        return await self._req("GET", f"/api/discord/clip/{clip_id}/preview-path")

    async def ref(self, kind: str, entity_id: str | int) -> dict[str, Any] | None:
        try:
            return await self._req("GET", f"/api/discord/refs/{kind}/{entity_id}")
        except CoreError as e:
            if e.status == 404:
                return None
            raise

    # ------------------------------------------------------------ writes (all via="discord")
    async def put_ref(
        self,
        kind: str,
        entity_id: str | int,
        channel_id: int,
        message_id: int | None,
        thread_id: int | None = None,
    ) -> None:
        await self._req(
            "POST",
            "/api/discord/refs",
            json={
                "kind": kind,
                "entity_id": str(entity_id),
                "channel_id": str(channel_id),
                "message_id": str(message_id) if message_id else None,
                "thread_id": str(thread_id) if thread_id else None,
            },
        )

    async def heartbeat(self) -> None:
        await self._req("POST", "/api/discord/heartbeat")

    async def take(self, campaign_id: int) -> None:
        await self._req("POST", f"/api/campaigns/{campaign_id}/take", params={"via": VIA})

    async def skip(self, campaign_id: int) -> None:
        await self._req("POST", f"/api/campaigns/{campaign_id}/skip", params={"via": VIA})

    async def decide(
        self,
        clip_id: int,
        decision: str,
        reviewer: str,
        reason: str | None = None,
        platforms: list[str] | None = None,
    ) -> None:
        await self._req(
            "POST",
            f"/api/review/clips/{clip_id}/decision",
            json={
                "decision": decision,
                "reason": reason,
                "platforms": platforms,
                "reviewer": reviewer,
                "via": VIA,
            },
        )

    async def caption(self, clip_id: int, platform: str, text: str) -> None:
        await self._req(
            "PUT",
            f"/api/review/clips/{clip_id}/caption",
            json={"platform": platform, "text": text, "via": VIA},
        )

    async def recut(
        self, clip_id: int, start_delta: float, end_delta: float, layout: str | None, note: str | None
    ) -> None:
        await self._req(
            "POST",
            f"/api/review/clips/{clip_id}/recut",
            json={
                "start_delta": start_delta,
                "end_delta": end_delta,
                "layout": layout,
                "note": note,
                "via": VIA,
            },
        )

    async def approve_all(self, batch_id: int, threshold: float, reviewer: str) -> list[int]:
        return await self._req(
            "POST",
            f"/api/review/batches/{batch_id}/approve-all",
            json={"threshold": threshold, "reviewer": reviewer, "via": VIA},
        )

    async def reject_rest(self, batch_id: int, reason: str, reviewer: str) -> list[int]:
        return await self._req(
            "POST",
            f"/api/review/batches/{batch_id}/reject-rest",
            json={"reason": reason, "reviewer": reviewer, "via": VIA},
        )

    async def ship(self, batch_id: int, reviewer: str) -> dict[str, list[int]]:
        return await self._req(
            "POST", f"/api/review/batches/{batch_id}/ship", json={"reviewer": reviewer, "via": VIA}
        )

    async def answer(self, question_id: int, answer: str, by: str) -> None:
        await self._req(
            "POST", f"/api/questions/{question_id}/answer", json={"answer": answer, "by": by, "via": VIA}
        )

    async def chat(self, text: str, reply_to: str | None) -> None:
        await self._req(
            "POST", "/api/agents/director/chat", json={"text": text, "via": VIA, "reply_to": reply_to}
        )

    async def switch(self, level: str, name: str, enabled: bool) -> dict[str, Any]:
        # from Discord, switching off finishes active campaigns and keeps scheduled posts (the
        # gentle default); the dashboard dialog offers the other choices
        return await self._req(
            "POST",
            "/api/switches",
            json={
                "level": level,
                "name": name,
                "enabled": enabled,
                "on_active": "finish",
                "on_scheduled": "keep",
                "via": VIA,
            },
        )

    async def switches(self) -> dict[str, Any]:
        return await self._req("GET", "/api/switches")

    async def patch_settings(self, values: dict[str, Any]) -> None:
        await self._req("PATCH", "/api/settings", json={"values": values})

    # ------------------------------------------------------------ events
    async def events(self, after: int, types: list[str]) -> AsyncIterator[dict[str, Any]]:
        """Yields bus events forever (reconnects with backoff)."""
        from websockets.asyncio.client import connect

        ws_url = self.base_url.replace("http", "ws", 1) + f"/api/ws?after={after}&types={','.join(types)}"
        delay = 1.0
        last = after
        while True:
            try:
                async with connect(ws_url) as ws:
                    delay = 1.0
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("type") == "ping" or "id" not in msg:
                            continue
                        last = max(last, int(msg["id"]))
                        yield msg
            except (TimeoutError, OSError, ConnectionError) as exc:
                log.warning("core event stream lost (%s); retrying in %.0fs", exc, delay)
            except Exception as exc:  # websockets closes with its own exception types
                log.warning("core event stream closed (%s); retrying in %.0fs", exc, delay)
            await asyncio.sleep(delay)
            delay = min(30.0, delay * 2)
            ws_url = self.base_url.replace("http", "ws", 1) + f"/api/ws?after={last}&types={','.join(types)}"
