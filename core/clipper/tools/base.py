"""Tool plumbing: typed specs, one wrapper for every call path, and Agent SDK / stdio server builders.

Every call (agent session, stdio server, API) goes through ``call_tool``:
validate args (pydantic) -> guard (same rules as the PreToolUse hook) -> handler -> small result ->
``agent_event`` row. Handlers return plain dicts (JSON) and may attach images (frames, contact sheets).
"""

from __future__ import annotations

import base64
import importlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from clipper.agents.access import CATALOG, fq
from clipper.agents.hooks import ToolCall
from clipper.db.engine import WriteTx
from clipper.db.models import AgentEvent
from clipper.events.types import AgentEventLogged
from clipper.services.base import ServiceError

if TYPE_CHECKING:
    from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool

    from clipper.core import Core

log = logging.getLogger(__name__)

MAX_RESULT_CHARS = 8000


class ToolFailure(Exception):
    """Expected failure with a message for the agent (shown as an error result)."""


@dataclass
class ToolOutput:
    data: dict[str, Any]
    images: list[Path] = field(default_factory=lambda: [])


@dataclass
class ToolContext:
    core: Core
    role: str  # main role, subagent, "umbrella" (Claude Desktop) or "developer" (stdio dev servers)
    session_id: int | None = None
    campaign_id: int | None = None
    skip_rules: frozenset[str] = frozenset()

    @property
    def actor(self) -> str:
        return f"session:{self.session_id}" if self.session_id is not None else self.role


Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any] | ToolOutput]]


@dataclass(frozen=True)
class ToolSpec:
    server: str
    name: str
    description: str
    args: type[BaseModel]
    handler: Handler

    @property
    def fq(self) -> str:
        return fq(self.server, self.name)

    @property
    def read_only(self) -> bool:
        return CATALOG[self.server][self.name]


REGISTRY: dict[str, dict[str, ToolSpec]] = {}


def tool(server: str, name: str, description: str, args: type[BaseModel]) -> Callable[[Handler], Handler]:
    if name not in CATALOG.get(server, {}):
        raise KeyError(f"{server}.{name} is not in the access catalog (clipper.agents.access.CATALOG)")

    def deco(fn: Handler) -> Handler:
        REGISTRY.setdefault(server, {})[name] = ToolSpec(server, name, description, args, fn)
        return fn

    return deco


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.setdefault("properties", {})
    schema["type"] = "object"
    return schema


@dataclass
class CallResult:
    content: list[dict[str, Any]]
    is_error: bool
    data: dict[str, Any] | None = None


def _text(payload: Any) -> str:
    text = json.dumps(payload, default=str, ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '..."(truncated: ask for a smaller page)"'
    return text


def _image_block(path: Path) -> dict[str, Any]:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return {"type": "image", "data": base64.b64encode(path.read_bytes()).decode("ascii"), "mimeType": mime}


async def call_tool(ctx: ToolContext, spec: ToolSpec, raw: dict[str, Any]) -> CallResult:
    try:
        args = spec.args.model_validate(raw)
    except ValidationError as exc:
        errs = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
        return CallResult([{"type": "text", "text": f"invalid arguments: {errs}"}], True)
    call = ToolCall(
        tool=spec.fq, args=raw, role=ctx.role, session_id=ctx.session_id, campaign_id=ctx.campaign_id
    )
    verdict = ctx.core.guard.check(call, skip=ctx.skip_rules)
    if not verdict.allowed:
        return CallResult([{"type": "text", "text": f"blocked: {verdict.message}"}], True)
    try:
        out = await spec.handler(ctx, args)
    except (ToolFailure, ServiceError, ValueError) as exc:
        result = CallResult([{"type": "text", "text": f"error: {exc}"}], True)
        _record(ctx, spec, raw, {"error": str(exc)})
        return result
    except Exception as exc:
        log.exception("tool %s crashed", spec.fq)
        _record(ctx, spec, raw, {"error": f"{type(exc).__name__}: {exc}"})
        return CallResult(
            [{"type": "text", "text": f"internal error in {spec.fq}: {type(exc).__name__}: {exc}"}], True
        )
    data = out.data if isinstance(out, ToolOutput) else out
    if verdict.dry_run:
        data = {**data, "dry_run": True}
    content: list[dict[str, Any]] = [{"type": "text", "text": _text(data)}]
    if isinstance(out, ToolOutput):
        content += [_image_block(p) for p in out.images[:8] if p.exists()]
    _record(ctx, spec, raw, data)
    return CallResult(content, False, data)


def _record(ctx: ToolContext, spec: ToolSpec, raw: dict[str, Any], output: dict[str, Any]) -> None:
    summary = _text(output)[:300]

    def job(tx: WriteTx) -> None:
        row = AgentEvent(
            session_id=ctx.session_id,
            type="tool_result",
            tool=spec.fq,
            input_json={"args": raw, "role": ctx.role},
            output_json=json.loads(_text(output))
            if len(_text(output)) < MAX_RESULT_CHARS
            else {"summary": summary},
        )
        tx.add(row)
        tx.flush()
        assert row.id is not None
        tx.publish(
            AgentEventLogged(
                session_id=ctx.session_id,
                agent_event_id=row.id,
                kind="tool_result",
                tool=spec.fq,
                summary=summary,
            )
        )

    try:
        ctx.core.db.write(job)
    except Exception:
        log.exception("failed to record tool result")


SERVER_MODULES = (
    "agenda", "browser", "clipper_server", "edit", "insights", "market", "media",
    "memory", "notify", "publish", "review", "state", "supervisor", "trends",
)  # fmt: skip


def ensure_loaded() -> None:
    """Import every server module so the registry is complete."""
    for name in SERVER_MODULES:
        importlib.import_module(f"clipper.tools.{name}")


def specs(server: str, only: set[str] | None = None) -> list[ToolSpec]:
    ensure_loaded()
    return [s for s in REGISTRY.get(server, {}).values() if only is None or s.fq in only]


def sdk_server(server: str, ctx: ToolContext, only: set[str] | None = None) -> McpSdkServerConfig:
    """An in-process Agent SDK MCP server exposing ``server``'s tools (optionally a subset) for one session."""
    from claude_agent_sdk import ToolAnnotations, create_sdk_mcp_server
    from claude_agent_sdk import tool as sdk_tool

    tools: list[SdkMcpTool[Any]] = []
    for spec in specs(server, only):

        async def handler(args: dict[str, Any], spec: ToolSpec = spec) -> dict[str, Any]:
            res = await call_tool(ctx, spec, args)
            return {"content": res.content, "is_error": res.is_error}

        annotations = ToolAnnotations(
            readOnlyHint=spec.read_only,
            destructiveHint=False,
            openWorldHint=spec.server in ("browser", "marketplace", "publish", "trends"),
        )
        tools.append(
            sdk_tool(spec.name, spec.description, json_schema(spec.args), annotations=annotations)(handler)
        )
    return create_sdk_mcp_server(server, "0.1.0", tools)
