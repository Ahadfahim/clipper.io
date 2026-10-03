"""``ClaudeAgentOptions`` and ``AgentDefinition``s per role (PLAN §3, §16.3).

Every session:
- ``setting_sources=[]``: the user's personal Claude Code settings, CLAUDE.md files and plugins don't leak in.
- built-in tools limited to what the role needs (``Agent`` for subagents, web for research), everything
  else comes from our in-process MCP servers; ``permission_mode="dontAsk"`` denies anything not
  pre-approved in ``allowed_tools``.
- the main thread runs *as* the role's agent definition (``--agent <role>``) so it only sees its own
  <= 25 tools while its subagents see theirs. LOCAL-VERIFY: confirm with a real CLI run.
- the PreToolUse guard hook and the PostToolUse logger.
- ``env`` blanks every billing variable: agents run on the user's Claude plan login. There is no
  ``max_budget_usd`` and no $ tracking anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, HookMatcher

from clipper.agents.access import ACCESS, BUILTIN_TOOLS, SUBAGENTS, split_fq
from clipper.agents.env import agent_subprocess_env
from clipper.agents.hooks import (
    Guard,
    SessionBinding,
    ToolResultRecorder,
    make_post_tool_use_hook,
    make_pre_tool_use_hook,
)
from clipper.settings import Settings

if TYPE_CHECKING:
    from clipper.tools.base import ToolContext

PROMPTS_DIR = Path(__file__).parent / "prompts"

DESCRIPTIONS: dict[str, str] = {
    "scout": "Finds, scores and pre-fetches campaigns; posts Take/Skip cards.",
    "campaign": "Owns one campaign from brief to submitted posts.",
    "analyst": "Daily metrics, tuning and report.",
    "director": "The user's interface: answers with numbers and steers the system.",
    "brief-reader": "Turns a campaign page (untrusted text) into a ClipSpec JSON. Changes nothing.",
    "research": "Looks things up on the web and returns a cited summary.",
    "editor": "Reads a source's transcript and signals and returns ranked moments as JSON.",
    "cutter": "Edits one clip's EDL (hook, fillers, silences, layout, captions) and renders a preview.",
    "qa-checker": "Checks a rendered clip against its spec and returns pass/fail with fixes.",
    "copywriter": "Writes per-platform titles, captions and hashtags for a batch of clips.",
    "browser-fixer": "Finishes a broken upload/marketplace recipe step by looking at the page; stops on challenges.",
}


@cache
def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> str:
    sub = prompts_dir / "subagents" / f"{name}.md"
    path = sub if sub.exists() else prompts_dir / f"{name}.md"
    shared = (prompts_dir / "shared.md").read_text(encoding="utf-8")
    return shared.strip() + "\n\n" + path.read_text(encoding="utf-8").strip() + "\n"


def builtins_for(role: str) -> list[str]:
    """Built-in tools the session must provide (for the role or any of its subagents)."""
    names = set(ACCESS[role])
    for sub in SUBAGENTS.get(role, []):
        names.update(ACCESS[sub])
    return sorted(n for n in names if n in BUILTIN_TOOLS)


def session_tools(role: str) -> set[str]:
    """Every tool the session's agents may use (role + its subagents)."""
    names = set(ACCESS[role])
    for sub in SUBAGENTS.get(role, []):
        names.update(ACCESS[sub])
    return names


def agent_definitions(role: str, settings: Settings) -> dict[str, AgentDefinition]:
    model = settings.agents.model
    prompts_dir = settings.agents.prompts_dir or PROMPTS_DIR
    role_cfg = settings.agents.roles[role]
    defs: dict[str, AgentDefinition] = {
        role: AgentDefinition(
            description=DESCRIPTIONS[role],
            prompt=load_prompt(role, prompts_dir),
            tools=list(ACCESS[role]),
            model=model,
            effort=role_cfg.effort,
            maxTurns=role_cfg.max_turns,
        )
    }
    for sub in SUBAGENTS.get(role, []):
        cfg = settings.agents.subagents[sub]
        defs[sub] = AgentDefinition(
            description=DESCRIPTIONS[sub],
            prompt=load_prompt(sub, prompts_dir),
            tools=list(ACCESS[sub]),
            model=model,
            effort=cfg.effort,
            maxTurns=cfg.max_turns,
        )
    return defs


@dataclass(frozen=True)
class SessionSpec:
    role: str
    session_id: int | None
    campaign_id: int | None
    resume: str | None  # SDK session id to resume
    cwd: Path


def build_options(
    spec: SessionSpec,
    settings: Settings,
    *,
    guard: Guard,
    tool_ctx: ToolContext,
    record_builtin: ToolResultRecorder,
    turns: Any = None,
) -> ClaudeAgentOptions:
    from clipper.tools.base import sdk_server

    role = spec.role
    role_cfg = settings.agents.roles[role]
    tools = session_tools(role)
    by_server: dict[str, set[str]] = {}
    for name in tools:
        parts = split_fq(name)
        if parts is not None:
            by_server.setdefault(parts[0], set()).add(name)
    mcp_servers: dict[str, Any] = {
        server: sdk_server(server, tool_ctx, only=names) for server, names in sorted(by_server.items())
    }
    binding = SessionBinding(
        role=role,
        session_id=spec.session_id,
        campaign_id=spec.campaign_id,
        max_turns=role_cfg.max_turns,
        turns=turns or (lambda: 0),
    )
    spec.cwd.mkdir(parents=True, exist_ok=True)
    return ClaudeAgentOptions(
        system_prompt=load_prompt(role, settings.agents.prompts_dir or PROMPTS_DIR),
        tools=builtins_for(role),
        allowed_tools=sorted(tools),
        permission_mode="dontAsk",
        mcp_servers=mcp_servers,
        strict_mcp_config=True,
        agents=agent_definitions(role, settings),
        extra_args={"agent": role},  # main thread = the role's agent definition (LOCAL-VERIFY)
        setting_sources=[],
        model=settings.agents.model,
        effort=role_cfg.effort,
        max_turns=role_cfg.max_turns,
        resume=spec.resume,
        cwd=str(spec.cwd),
        cli_path=str(settings.agents.cli_path) if settings.agents.cli_path else None,
        env=agent_subprocess_env({"CLIPPER_ROLE": role}),
        hooks={
            "PreToolUse": [HookMatcher(hooks=[make_pre_tool_use_hook(guard, binding)])],  # type: ignore[list-item]
            "PostToolUse": [HookMatcher(hooks=[make_post_tool_use_hook(record_builtin)])],  # type: ignore[list-item]
        },
    )
