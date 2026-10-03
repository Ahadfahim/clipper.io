"""Wire protocol between clipper-core and the Companion extension (JSON over WebSocket).

Mirrored in ``apps/extension/src/shared/protocol.ts``; keep both in sync (PROTOCOL_VERSION).

extension -> core
  {"type": "hello", "profile": "main", "token": "<pairing token>", "version": "0.1.0", "protocol": 1, "url": "..."}
  {"type": "result", "id": "<request id>", "ok": true, "data": {...}}
  {"type": "result", "id": "...", "ok": false, "error": "...", "step": 3, "screenshot": "data:image/png;base64,...",
   "dom": "<simplified DOM>", "challenge": null | "login" | "captcha" | "verification"}
  {"type": "status", "url": "https://...", "title": "..."}          (active tab changed)
  {"type": "pong"}
core -> extension
  {"type": "welcome", "profile": "main", "protocol": 1}
  {"type": "run", "id": "...", "recipe": "youtube.upload_short", "params": {...}, "dry_run": false}
  {"type": "action", "id": "...", "action": {"kind": "navigate" | "click" | "type" | "attach_file" | "snapshot" | ..., ...}}
  {"type": "ping"}
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1
Challenge = Literal["login", "captcha", "verification"]


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Hello(_M):
    type: Literal["hello"]
    profile: str
    token: str
    version: str = "0"
    protocol: int = PROTOCOL_VERSION
    url: str | None = None


class Result(_M):
    type: Literal["result"]
    id: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    step: int | None = None
    screenshot: str | None = None
    dom: str | None = None
    challenge: Challenge | None = None


class Status(_M):
    type: Literal["status"]
    url: str | None = None
    title: str | None = None


class RecipeResult(_M):
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    step: int | None = None
    screenshot: str | None = None
    dom: str | None = None
    challenge: Challenge | None = None

    @classmethod
    def from_result(cls, r: Result) -> RecipeResult:
        return cls(
            ok=r.ok,
            data=r.data,
            error=r.error,
            step=r.step,
            screenshot=r.screenshot,
            dom=r.dom,
            challenge=r.challenge,
        )


ActionKind = Literal[
    "navigate", "wait_for", "query", "click", "type", "attach_file", "read_text", "screenshot", "snapshot"
]
