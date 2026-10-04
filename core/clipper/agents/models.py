"""Which Claude model each agent runs on (docs/plans/model-selection.md).

Resolution for a subagent: its own choice → its role's model → the default. For a role: its own
choice → the default. Choices made in the app live in the control KV (key ``models``) and apply to
the next session without a restart; the settings file (``agents.model``, ``agents.roles.<r>.model``,
``agents.subagents.<s>.model``) is the fallback. Everything runs on the user's Claude plan login.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from clipper.agents.access import MAIN_ROLES, SUBAGENTS
from clipper.db.engine import Database, WriteTx
from clipper.events.types import ControlChanged
from clipper.services.control import kv_get, kv_set_tx
from clipper.settings import Settings

KV_KEY = "models"
MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9.\-]{2,80}$")


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    use_for: str
    usage: str  # how fast it uses the plan's allowance: "most" | "medium" | "least"


CATALOGUE: tuple[ModelInfo, ...] = (
    ModelInfo("claude-opus-5-5", "Opus 5.5", "hardest judgment: planning, talking to you", "most"),
    ModelInfo("claude-sonnet-5-5", "Sonnet 5.5", "the main work: rules, picking moments, editing", "medium"),
    ModelInfo(
        "claude-haiku-4-5-20251001", "Haiku 4.5", "frequent simple jobs: scouting, checks, captions", "least"
    ),
)
# Not listed: claude-fable-5-1. On this Pro plan it "requires usage credits" (paid extra usage; checked
# 2026-10-03), and Clipper only uses what the plan includes. A custom id can still be tested.
KNOWN = {m.id for m in CATALOGUE}

OPUS, SONNET, HAIKU = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5-20251001"
LIGHT = ("scout", "qa-checker", "copywriter", "research")

PRESETS: dict[str, dict[str, Any]] = {
    # recommended on a Pro plan: Opus only where it's rare and matters, Haiku for frequent simple work
    "balanced": {
        "default": SONNET,
        "roles": {"director": OPUS, "scout": HAIKU},
        "subagents": {"qa-checker": HAIKU, "copywriter": HAIKU, "research": HAIKU},
    },
    "save_usage": {
        "default": SONNET,
        "roles": {"scout": HAIKU},
        "subagents": {"qa-checker": HAIKU, "copywriter": HAIKU, "research": HAIKU},
    },
    "best_quality": {"default": OPUS, "roles": {}, "subagents": {}},
}


def parent_of(sub: str) -> str | None:
    return next((r for r, subs in SUBAGENTS.items() if sub in subs), None)


def as_map(x: Any) -> dict[str, Any]:
    return cast(dict[str, Any], x) if isinstance(x, dict) else {}


def overrides(db: Database) -> dict[str, Any]:
    return as_map(kv_get(db, KV_KEY, None))


def model_for(settings: Settings, db: Database | None, role: str, sub: str | None = None) -> str:
    """The model a role (or one of its subagents) runs on right now."""
    o = overrides(db) if db is not None else {}
    agents = settings.agents
    default = str(o.get("default") or agents.model)
    role_file = agents.roles[role].model if role in agents.roles else None
    role_model = str(as_map(o.get("roles")).get(role) or role_file or default)
    if sub is None:
        return role_model
    sub_file = agents.subagents[sub].model if sub in agents.subagents else None
    return str(as_map(o.get("subagents")).get(sub) or sub_file or role_model)


def resolved(settings: Settings, db: Database | None) -> dict[str, str]:
    """Every agent's effective model: {"director": ..., "campaign/cutter": ...}."""
    out: dict[str, str] = {}
    for role in MAIN_ROLES:
        out[role] = model_for(settings, db, role)
        for sub in SUBAGENTS.get(role, []):
            out[f"{role}/{sub}"] = model_for(settings, db, role, sub)
    return out


def _check(model: Any, tested: set[str], where: str) -> str:
    if not isinstance(model, str) or not MODEL_ID.match(model):
        raise ValueError(f"{where}: not a model id")
    if model not in KNOWN and model not in tested:
        raise ValueError(f"{where}: {model} isn't in the list; test it first (Test button)")
    return model


def set_models(db: Database, value: dict[str, Any], *, by: str = "user", via: str = "app") -> dict[str, Any]:
    """Replace the app's model choices (the whole map). ``None``/missing entries fall back to the
    settings file. Custom ids must have passed ``mark_tested`` first."""
    current = overrides(db)
    tested = set(current.get("tested") or [])
    clean: dict[str, Any] = {"roles": {}, "subagents": {}, "tested": sorted(tested)}
    if value.get("default") is not None:
        clean["default"] = _check(value["default"], tested, "default")
    for role, m in as_map(value.get("roles")).items():
        if role not in MAIN_ROLES:
            raise ValueError(f"unknown agent {role}")
        if m is not None:
            clean["roles"][role] = _check(m, tested, role)
    for sub, m in as_map(value.get("subagents")).items():
        if parent_of(sub) is None:
            raise ValueError(f"unknown subagent {sub}")
        if m is not None:
            clean["subagents"][sub] = _check(m, tested, sub)
    preset = value.get("preset")
    if preset is not None:
        clean["preset"] = str(preset)

    def job(tx: WriteTx) -> None:
        kv_set_tx(tx, KV_KEY, clean)
        tx.publish(ControlChanged(key="models", value=clean, by=by, via=via))

    db.write(job)
    return clean


def mark_tested(db: Database, model: str) -> None:
    """Remember a custom model id that worked on this plan (so it can be chosen)."""
    if not MODEL_ID.match(model):
        raise ValueError("not a model id")
    current = overrides(db)
    tested = sorted({*(current.get("tested") or []), model})

    def job(tx: WriteTx) -> None:
        kv_set_tx(tx, KV_KEY, {**current, "tested": tested})

    db.write(job)


@dataclass(frozen=True)
class ModelCheck:
    ok: bool
    model: str
    reported: str | None = None  # what Claude Code said it ran
    error: str | None = None


async def check_model(settings: Settings, model: str) -> ModelCheck:
    """One tiny turn ("reply OK", no tools) on the plan login, to see if this plan can use the model.
    Billing keys are stripped like for every agent: a model the plan lacks fails, it isn't billed."""
    if not MODEL_ID.match(model):
        return ModelCheck(False, model, error="not a model id")
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, SystemMessage

    from clipper.agents.env import agent_subprocess_env

    options = ClaudeAgentOptions(
        system_prompt="Reply with the single word OK.",
        tools=[],
        allowed_tools=[],
        permission_mode="dontAsk",
        setting_sources=[],
        strict_mcp_config=True,
        model=model,
        max_turns=1,
        cli_path=str(settings.agents.cli_path) if settings.agents.cli_path else None,
        env=agent_subprocess_env({"CLIPPER_ROLE": "model-check"}),
    )
    reported: str | None = None
    try:
        async with ClaudeSDKClient(options) as client:
            await client.query("OK?")
            async for msg in client.receive_response():
                if isinstance(msg, SystemMessage) and msg.subtype == "init":
                    reported = str(msg.data.get("model") or "") or None
                elif isinstance(msg, ResultMessage) and msg.is_error:
                    why = "; ".join(msg.errors or []) or msg.result or msg.subtype
                    return ModelCheck(False, model, reported, why)
    except Exception as exc:  # CLI missing, not logged in, model refused
        return ModelCheck(False, model, reported, f"{type(exc).__name__}: {str(exc)[-300:]}")
    if reported and reported != model:
        return ModelCheck(False, model, reported, f"Claude Code ran {reported} instead")
    return ModelCheck(True, model, reported)
