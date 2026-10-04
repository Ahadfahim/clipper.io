"""Agent options: plan login only (no API key, no budget), isolation, tools, prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from clipper.agents.access import ACCESS, SUBAGENTS
from clipper.agents.definitions import SessionSpec, build_options, builtins_for, load_prompt
from clipper.agents.env import BILLING_ENV_KEYS
from clipper.core import Core
from clipper.tools.base import ToolContext

ROLES = ("scout", "campaign", "analyst", "director")


def _options(core: Core, role: str, tmp_path: Path) -> Any:
    ctx = ToolContext(core, role=role, session_id=1, campaign_id=5 if role == "campaign" else None)
    return build_options(
        SessionSpec(role, 1, 5 if role == "campaign" else None, None, tmp_path / role),
        core.settings,
        guard=core.guard,
        tool_ctx=ctx,
        record_builtin=lambda *a: None,
    )


@pytest.mark.parametrize("role", ROLES)
def test_options_isolated_and_on_plan_login(core: Core, role: str, tmp_path: Path) -> None:
    opts = _options(core, role, tmp_path)
    assert opts.setting_sources == []
    assert opts.permission_mode == "dontAsk"
    assert opts.model == "claude-opus-5-5"
    assert opts.max_budget_usd is None
    assert opts.effort == core.settings.agents.roles[role].effort
    assert opts.max_turns == core.settings.agents.roles[role].max_turns
    assert opts.tools == builtins_for(role)
    assert set(opts.tools) <= {"Agent", "WebSearch", "WebFetch"}
    assert opts.extra_args == {"agent": role}
    assert opts.strict_mcp_config is True
    for key in BILLING_ENV_KEYS:
        assert opts.env[key] == ""
    defs = opts.agents
    assert set(defs) == {role, *SUBAGENTS[role]}
    for name, d in defs.items():
        assert d.tools == ACCESS[name] and len(d.tools) <= 25
        assert d.model == "claude-opus-5-5"
    assert "PreToolUse" in opts.hooks and "PostToolUse" in opts.hooks
    # every MCP tool the session's agents may use is served, and nothing else
    served = set(opts.mcp_servers)
    assert served == {t.split("__")[1] for name in defs for t in ACCESS[name] if t.startswith("mcp__")}


def test_web_tools_only_where_research_runs() -> None:
    assert builtins_for("analyst") == ["Agent", "WebFetch", "WebSearch"]
    assert builtins_for("campaign") == ["Agent"]
    assert builtins_for("scout") == [] and builtins_for("director") == []


@pytest.mark.parametrize("name", [*ROLES, *SUBAGENTS["campaign"], "research"])
def test_prompts_carry_the_untrusted_content_rules(name: str) -> None:
    text = load_prompt(name)
    assert "Untrusted content" in text and "never instructions" in text
    assert len(text.split()) < 1400  # short enough to cache


async def test_api_key_never_reaches_the_cli(
    core: Core, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spawn the SDK's real transport against a fake CLI and capture the subprocess environment."""
    import claude_agent_sdk._internal.transport.subprocess_cli as transport_mod
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leaked")  # as if something set it after startup
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "leaked-token")
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    fake_cli = tmp_path / "claude"
    fake_cli.write_text("#!/bin/sh\nexit 0\n")
    fake_cli.chmod(0o755)
    opts = _options(core, "campaign", tmp_path)
    opts.cli_path = str(fake_cli)
    captured: dict[str, Any] = {}

    async def fake_open_process(cmd: list[str], **kwargs: Any) -> Any:
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        raise RuntimeError("stop here")

    monkeypatch.setattr(transport_mod.anyio, "open_process", fake_open_process)  # pyright: ignore[reportPrivateImportUsage]
    t = SubprocessCLITransport("hi", opts)
    with pytest.raises(Exception, match="stop here"):
        await t.connect()
    env = captured["env"]
    for key in BILLING_ENV_KEYS:
        assert env.get(key, "") == "", key
    cmd = captured["cmd"]
    assert "--max-budget-usd" not in cmd
    assert "--setting-sources=" in cmd and "--agent" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"


def test_options_follow_the_apps_model_choice_with_a_fallback(core: Core, tmp_path: Path) -> None:
    from clipper.agents import models as am

    assert _options(core, "director", tmp_path).fallback_model == "claude-sonnet-5-5"
    am.set_models(core.db, am.PRESETS["balanced"])
    scout = _options(core, "scout", tmp_path)
    assert scout.model == am.HAIKU and scout.fallback_model == "claude-sonnet-5-5"
    campaign = _options(core, "campaign", tmp_path)
    assert campaign.model == am.SONNET and campaign.fallback_model is None  # never equal to the model
