from __future__ import annotations

import pytest

from clipper.agents.env import BILLING_ENV_KEYS, agent_subprocess_env, effective_env, scrub_process_env


def test_scrub_removes_billing_keys() -> None:
    env = {"ANTHROPIC_API_KEY": "sk-test", "PATH": "x", "ANTHROPIC_AUTH_TOKEN": "t"}
    removed = scrub_process_env(env)
    assert set(removed) == {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
    assert env == {"PATH": "x"}


def test_options_env_blanks_every_billing_key() -> None:
    env = agent_subprocess_env()
    for key in BILLING_ENV_KEYS:
        assert env[key] == ""
    merged = effective_env({"ANTHROPIC_API_KEY": "sk-leak", "HOME": "/h"}, env)
    assert "ANTHROPIC_API_KEY" not in merged
    assert merged["HOME"] == "/h"


def test_cannot_pass_key_through_extra() -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        agent_subprocess_env({"ANTHROPIC_API_KEY": "sk"})
