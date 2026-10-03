from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from clipper.settings import REPO_ROOT, Settings, load_settings

EXAMPLE = REPO_ROOT / "config" / "settings.example.toml"


def _leaf_names(model: type[BaseModel], prefix: str = "") -> list[str]:
    names: list[str] = []
    for name, field in model.model_fields.items():
        ann = field.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            names += _leaf_names(ann, f"{prefix}{name}.")
        else:
            names.append(f"{prefix}{name}")
    return names


def test_example_parses_into_settings() -> None:
    data = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    settings = Settings.model_validate(data)
    assert settings.agents.model == "claude-opus-5-5"
    assert settings.api.host == "127.0.0.1"
    assert settings.switches.socials["x"] is False


def test_example_mentions_every_setting() -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    missing: list[str] = []
    for dotted in _leaf_names(Settings):
        leaf = dotted.rsplit(".", 1)[-1]
        section = dotted.rsplit(".", 1)[0] if "." in dotted else ""
        as_key = re.search(rf"^\s*#?\s*{re.escape(leaf)}\s*=", text, re.M)
        as_table = re.search(rf"^\s*\[{re.escape(dotted)}[\].]", text, re.M) or (
            section and re.search(rf"^\s*\[{re.escape(dotted)}", text, re.M)
        )
        if not (as_key or as_table):
            missing.append(dotted)
    assert not missing, f"settings.example.toml is missing: {missing}"


def test_api_must_bind_loopback() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"api": {"host": "0.0.0.0"}})


def test_unknown_keys_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"agents": {"max_budget_usd": 5}})


def test_data_dir_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLIPPER_DATA_DIR", str(tmp_path))
    s = load_settings(Path("missing.toml"))
    assert s.paths.data_dir == tmp_path
    assert s.paths.database == tmp_path / "clipper.sqlite"
    assert s.paths.sub("clips") == tmp_path / "clips"
