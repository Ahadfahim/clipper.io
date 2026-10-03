"""Agent runners: ``SdkAgentRunner`` (Claude Code CLI via ``ClaudeSDKClient``) and ``FakeAgentRunner``
(replays scripted tool calls through the same guard hook and tool wrapper, for tests and dev).

Only tokens and turns are recorded; there is no cost tracking (the agents run on the Claude plan).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from clipper.agents.access import SUBAGENTS, split_fq
from clipper.agents.hooks import SessionBinding, make_pre_tool_use_hook
from clipper.db.engine import WriteTx
from clipper.db.models import AgentEvent
from clipper.events.types import AgentEventLogged

if TYPE_CHECKING:
    from clipper.core import Core

log = logging.getLogger(__name__)


@dataclass
class RunRequest:
    role: str
    kind: str  # what woke the agent: campaign.taken, job.done, trigger, user.chat, ...
    prompt: str
    session_id: int  # agent_session.id
    campaign_id: int | None = None
    resume: str | None = None  # SDK session id
    request_id: int | None = None
    payload: dict[str, Any] = field(default_factory=lambda: {})


@dataclass
class RunOutcome:
    sdk_session_id: str | None
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    result: str | None = None
    rate_limited: bool = False
    resets_at: datetime | None = None
    error: str | None = None
    interrupted: bool = False


class AgentRunner(Protocol):
    async def run(self, req: RunRequest) -> RunOutcome: ...
    async def interrupt(self, session_id: int) -> None: ...


class EventRecorder:
    """Writes the live console (``agent_event``) for one session."""

    def __init__(self, core: Core, session_id: int | None) -> None:
        self.core = core
        self.session_id = session_id

    def record(
        self,
        kind: str,
        *,
        tool: str | None = None,
        data: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        tokens: int = 0,
    ) -> None:
        summary = ""
        if data:
            summary = str(data.get("text") or data.get("summary") or json.dumps(data, default=str))[:300]
        sid = self.session_id

        def job(tx: WriteTx) -> None:
            row = AgentEvent(
                session_id=sid,
                type=kind,
                tool=tool,
                input_json=data or {},
                output_json=output or {},
                tokens=tokens,
            )
            tx.add(row)
            tx.flush()
            assert row.id is not None
            tx.publish(
                AgentEventLogged(session_id=sid, agent_event_id=row.id, kind=kind, tool=tool, summary=summary)
            )

        try:
            self.core.db.write(job)
        except Exception:
            log.exception("failed to record agent event")

    def builtin_result(self, tool: str, args: dict[str, Any], response: Any, agent_type: str | None) -> None:
        """PostToolUse: our MCP tools log themselves; record built-ins (Agent, WebSearch, WebFetch)."""
        if split_fq(tool) is not None:
            return
        text = response if isinstance(response, str) else json.dumps(response, default=str)
        self.record(
            "tool_result", tool=tool, data={"args": args, "agent": agent_type}, output={"text": text[:4000]}
        )


# ---------------------------------------------------------------------- real runner


class SdkAgentRunner:
    """Runs a role in a Claude Code subprocess on the user's plan login. LOCAL-VERIFY (needs `claude` login)."""

    def __init__(self, core: Core) -> None:
        self.core = core
        self._clients: dict[int, Any] = {}

    async def run(self, req: RunRequest) -> RunOutcome:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeSDKClient,
            ClaudeSDKError,
            RateLimitEvent,
            ResultMessage,
            SystemMessage,
            TextBlock,
            ThinkingBlock,
            ToolUseBlock,
        )

        from clipper.agents.definitions import SessionSpec, build_options
        from clipper.tools.base import ToolContext

        core = self.core
        recorder = EventRecorder(core, req.session_id)
        turns = {"n": 0}
        # The PreToolUse hook checks per-agent access (it knows which subagent is calling); the tool
        # wrapper re-checks every other rule.
        ctx = ToolContext(
            core,
            role=req.role,
            session_id=req.session_id,
            campaign_id=req.campaign_id,
            skip_rules=frozenset({"access", "max_turns"}),
        )
        options = build_options(
            SessionSpec(req.role, req.session_id, req.campaign_id, req.resume, core.dir("agents") / req.role),
            core.settings,
            guard=core.guard,
            tool_ctx=ctx,
            record_builtin=recorder.builtin_result,
            turns=lambda: turns["n"],
        )
        outcome = RunOutcome(sdk_session_id=req.resume)
        client = ClaudeSDKClient(options)
        self._clients[req.session_id] = client
        try:
            await client.connect()
            await client.query(req.prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    turns["n"] += 1
                    sub = msg.parent_tool_use_id
                    if msg.error == "rate_limit":
                        outcome.rate_limited = True
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            recorder.record("message", data={"text": block.text[:4000], "subagent": sub})
                        elif isinstance(block, ToolUseBlock):
                            recorder.record(
                                "tool_call", tool=block.name, data={"args": block.input, "subagent": sub}
                            )
                        elif isinstance(block, ThinkingBlock) and block.thinking.strip():
                            recorder.record("thinking", data={"text": block.thinking[:300], "subagent": sub})
                    if msg.usage:
                        outcome.input_tokens += int(msg.usage.get("input_tokens") or 0)
                        outcome.output_tokens += int(msg.usage.get("output_tokens") or 0)
                elif isinstance(msg, SystemMessage) and msg.subtype == "init":
                    outcome.sdk_session_id = (
                        str(msg.data.get("session_id") or outcome.sdk_session_id or "") or None
                    )
                elif isinstance(msg, RateLimitEvent):
                    info = msg.rate_limit_info
                    resets = datetime.fromtimestamp(info.resets_at, UTC) if info.resets_at else None
                    rejected = info.status == "rejected"
                    core.usage.record(
                        utilization=info.utilization,
                        resets_at=resets,
                        rate_limited=rejected,
                        window_type=info.rate_limit_type or "five_hour",
                    )
                    if rejected:
                        outcome.rate_limited, outcome.resets_at = True, resets
                elif isinstance(msg, ResultMessage):
                    outcome.sdk_session_id = msg.session_id or outcome.sdk_session_id
                    outcome.turns = msg.num_turns
                    outcome.result = msg.result
                    if msg.usage:
                        outcome.input_tokens = int(msg.usage.get("input_tokens") or outcome.input_tokens)
                        outcome.output_tokens = int(msg.usage.get("output_tokens") or outcome.output_tokens)
                    if msg.api_error_status == 429:
                        outcome.rate_limited = True
                    if msg.terminal_reason in ("aborted_streaming", "aborted_tools"):
                        outcome.interrupted = True
                    if msg.is_error and not outcome.rate_limited:
                        outcome.error = "; ".join(msg.errors or []) or msg.subtype
                    recorder.record(
                        "result",
                        data={
                            "text": (msg.result or "")[:2000],
                            "turns": msg.num_turns,
                            "stop": msg.stop_reason,
                        },
                    )
        except ClaudeSDKError as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
            recorder.record("error", data={"text": outcome.error})
        finally:
            self._clients.pop(req.session_id, None)
            try:
                await client.disconnect()
            except Exception:
                log.exception("disconnect failed")
        return outcome

    async def interrupt(self, session_id: int) -> None:
        client = self._clients.get(session_id)
        if client is not None:
            await client.interrupt()


# ---------------------------------------------------------------------- fake runner


@dataclass
class ScriptState:
    """Shared across one fake run: results of earlier steps (by ``save_as``) and the request."""

    req: RunRequest
    results: dict[str, Any] = field(default_factory=lambda: {})
    errors: list[str] = field(default_factory=lambda: [])


ArgsFn = Callable[[ScriptState], dict[str, Any]]


@dataclass
class ToolStep:
    server: str
    name: str
    args: dict[str, Any] | ArgsFn = field(default_factory=lambda: {})
    agent: str | None = None  # subagent name when the call comes from a subagent
    save_as: str | None = None
    each: Callable[[ScriptState], list[dict[str, Any]]] | None = None  # repeat the call per args item


@dataclass
class Say:
    text: str


@dataclass
class RateLimited:
    resets_in_s: float = 60.0


Step = ToolStep | Say | RateLimited
Script = Callable[[RunRequest], list[Step]]


class FakeAgentRunner:
    """Replays scripts keyed by ``"<role>:<kind>"`` (falls back to ``"<role>"``)."""

    def __init__(self, core: Core, scripts: dict[str, Script]) -> None:
        self.core = core
        self.scripts = scripts
        self.runs: list[RunRequest] = []
        self.states: list[ScriptState] = []
        self.interrupted: list[int] = []

    def _script(self, req: RunRequest) -> list[Step]:
        fn = self.scripts.get(f"{req.role}:{req.kind}") or self.scripts.get(req.role)
        return fn(req) if fn else [Say(f"(no script for {req.role}:{req.kind})")]

    async def run(self, req: RunRequest) -> RunOutcome:
        from clipper.tools.base import REGISTRY, ToolContext, call_tool, ensure_loaded

        ensure_loaded()
        self.runs.append(req)
        state = ScriptState(req)
        self.states.append(state)
        recorder = EventRecorder(self.core, req.session_id)
        sdk_id = req.resume or f"fake-{uuid.uuid4().hex[:12]}"
        turns = 0
        role_cfg = self.core.settings.agents.roles.get(req.role)
        binding = SessionBinding(
            req.role, req.session_id, req.campaign_id, role_cfg.max_turns if role_cfg else None, lambda: turns
        )
        hook = make_pre_tool_use_hook(self.core.guard, binding)
        for step in self._script(req):
            turns += 1
            if isinstance(step, Say):
                recorder.record("message", data={"text": step.text})
                continue
            if isinstance(step, RateLimited):
                resets = self.core.clock.now().timestamp() + step.resets_in_s
                at = datetime.fromtimestamp(resets, UTC)
                self.core.usage.record(utilization=1.0, resets_at=at, rate_limited=True)
                return RunOutcome(sdk_id, turns=turns, rate_limited=True, resets_at=at)
            if step.agent is not None and step.agent not in SUBAGENTS.get(req.role, []):
                raise AssertionError(f"{req.role} has no subagent {step.agent}")
            calls = (
                step.each(state)
                if step.each
                else [step.args(state) if callable(step.args) else dict(step.args)]
            )
            for args in calls:
                tool = f"mcp__{step.server}__{step.name}"
                hook_input: dict[str, Any] = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": tool,
                    "tool_input": args,
                }
                if step.agent:
                    hook_input["agent_type"] = step.agent
                recorder.record("tool_call", tool=tool, data={"args": args, "subagent": step.agent})
                decision = await hook(hook_input, None, {"signal": None})
                spec_out = decision.get("hookSpecificOutput", {})
                if spec_out.get("permissionDecision") == "deny":
                    state.errors.append(spec_out["permissionDecisionReason"])
                    continue
                ctx = ToolContext(
                    self.core,
                    role=step.agent or req.role,
                    session_id=req.session_id,
                    campaign_id=req.campaign_id,
                    skip_rules=frozenset({"access", "max_turns"}),
                )
                res = await call_tool(ctx, REGISTRY[step.server][step.name], args)
                if res.is_error:
                    state.errors.append(str(res.content[0]["text"]))
                elif step.save_as:
                    value = res.data or {}
                    if step.each:
                        state.results.setdefault(step.save_as, []).append(value)
                    else:
                        state.results[step.save_as] = value
        recorder.record("result", data={"text": f"fake run of {req.role}:{req.kind} done", "turns": turns})
        return RunOutcome(
            sdk_id, turns=turns, input_tokens=100 * turns, output_tokens=40 * turns, result="ok"
        )

    async def interrupt(self, session_id: int) -> None:
        self.interrupted.append(session_id)
