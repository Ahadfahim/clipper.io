"""`clipper doctor` reads the Claude Code CLI's JSON `auth status` (plan login, never an API key)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from clipper import doctor
from clipper.settings import Settings


def _with_cli(settings: Settings) -> Settings:
    agents = settings.agents.model_copy(update={"cli_path": Path("claude.exe")})
    return settings.model_copy(update={"agents": agents})


def _fake_status(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], code: int = 0) -> None:
    def run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        assert args[1:] == ["auth", "status"]
        return subprocess.CompletedProcess(args, code, stdout=json.dumps(payload, indent=2), stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", run)


def test_logged_out_cli_fails(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_status(monkeypatch, {"loggedIn": False, "authMethod": "none"}, code=1)
    res = doctor.check_claude_login(_with_cli(settings))
    assert res.status == "fail" and "/login" in res.fix


def test_logged_out_cli_fails_even_with_exit_code_zero(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_status(monkeypatch, {"loggedIn": False, "authMethod": "none"})
    assert doctor.check_claude_login(_with_cli(settings)).status == "fail"


def test_plan_login_passes(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_status(monkeypatch, {"loggedIn": True, "authMethod": "claude.ai", "email": "me@example.com"})
    res = doctor.check_claude_login(_with_cli(settings))
    assert res.status == "ok" and "claude.ai" in res.detail and "{" not in res.detail


def test_api_key_login_fails(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_status(monkeypatch, {"loggedIn": True, "authMethod": "api_key"})
    res = doctor.check_claude_login(_with_cli(settings))
    assert res.status == "fail" and "API key" in res.fix
