"""Write a dotted-path patch into ``config/settings.toml`` (validated against ``Settings`` first)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, cast

import tomli_w

from clipper.settings import DEFAULT_SETTINGS_PATH, Settings

FORBIDDEN = ("api.host",)  # the API stays on loopback


def patch_settings_file(values: dict[str, Any], path: Path | None = None) -> Path:
    target = path or Path(os.environ.get("CLIPPER_SETTINGS", DEFAULT_SETTINGS_PATH))
    data: dict[str, Any] = tomllib.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    for dotted, value in values.items():
        if dotted in FORBIDDEN:
            raise ValueError(f"{dotted} can't be changed from the app")
        node: dict[str, Any] = data
        keys = dotted.split(".")
        for key in keys[:-1]:
            child: Any = node.setdefault(key, {})
            if not isinstance(child, dict):
                raise ValueError(f"{dotted}: {key} is not a section")
            node = cast(dict[str, Any], child)
        node[keys[-1]] = value
    Settings.model_validate(data)  # raises on unknown keys / bad values
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(tomli_w.dumps(data), encoding="utf-8")
    return target
