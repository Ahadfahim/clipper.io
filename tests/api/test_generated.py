"""Generated artifacts stay in sync with the code: the OpenAPI schema (source of the TS client) and the
UI fixture export (what Playwright and `dev:fixtures` render)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipper.api.app import create_app
from clipper.fixtures.export import export_fixtures

ROOT = Path(__file__).resolve().parents[2]
OPENAPI = ROOT / "core" / "clipper" / "api" / "openapi.json"
FIXTURES = ROOT / "apps" / "desktop" / "public" / "fixtures"
REGEN = "regenerate with `just gen-api`"


def test_openapi_schema_is_current() -> None:
    app = create_app(fixture_mode=True, start_background=False)
    fresh = json.dumps(app.openapi(), indent=1, sort_keys=True) + "\n"
    assert OPENAPI.read_text(encoding="utf-8") == fresh, f"core/clipper/api/openapi.json is stale: {REGEN}"


@pytest.mark.ffmpeg
def test_fixture_export_is_current(tmp_path: Path) -> None:
    export_fixtures(tmp_path)
    fresh = sorted(p.relative_to(tmp_path).as_posix() for p in (tmp_path / "api").rglob("*.json"))
    committed = sorted(p.relative_to(FIXTURES).as_posix() for p in (FIXTURES / "api").rglob("*.json"))
    assert fresh == committed, f"fixture response set changed: {REGEN}"
    # files/ holds ffmpeg output, which differs between ffmpeg builds; compare the JSON only.
    for rel in [*fresh, "manifest.json"]:
        assert (tmp_path / rel).read_text(encoding="utf-8") == (FIXTURES / rel).read_text(encoding="utf-8"), (
            f"{rel} is stale: {REGEN}"
        )
