"""``clipper fixtures-export <dir>``: snapshot every GET the dashboard uses, from the fixture API.

The desktop UI's fixture mode (``vite --mode fixtures``) serves these files instead of calling the API,
so screens can be developed and screenshotted without Python. Media is copied next to them.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

FIXED_NOW = datetime(2026, 10, 2, 18, 0, tzinfo=UTC)  # 14:00 in New York: stable screenshots


def _name(path: str) -> str:
    base, _, query = path.partition("?")
    name = base.strip("/")
    if query:
        name += "__" + quote(query, safe="=&")
    return name + ".json"


def _scrub(obj: Any, replacements: list[tuple[str, str]]) -> Any:
    """Replace machine-specific absolute paths so the export is identical on every machine."""
    if isinstance(obj, str):
        for old, new in replacements:
            # The rest of a rewritten path gets forward slashes too, so Windows and Linux exports match.
            obj = re.sub(
                re.escape(old) + r"[^\s\"']*",
                lambda m, old=old, new=new: new + m.group(0)[len(old) :].replace("\\", "/"),
                obj,
            )
        return obj
    if isinstance(obj, list):
        return [_scrub(x, replacements) for x in cast(list[Any], obj)]
    if isinstance(obj, dict):
        return {k: _scrub(v, replacements) for k, v in cast(dict[str, Any], obj).items()}
    return obj


@contextmanager
def _pinned_disk_space() -> Generator[None]:
    """Free disk space is a live reading of the exporting machine; pin it so the export is identical everywhere."""
    from clipper.api import views

    real = views.disk_free_gb
    views.disk_free_gb = lambda _path: 79.0
    try:
        yield
    finally:
        views.disk_free_gb = real


def _secrets_on_this_pc() -> dict[str, str]:
    """This PC's real secrets, only to make sure none of them ends up in the export."""
    from clipper.secrets import SECRET_NAMES, get_secret

    found: dict[str, str] = {}
    for name in SECRET_NAMES:
        try:
            value = get_secret(name)
        except Exception:  # no credential store (CI): nothing to leak
            continue
        if value and len(value) >= 8:
            found[name] = value
    return found


def export_fixtures(out_dir: Path) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from clipper.api.app import create_app
    from clipper.clock import FakeClock
    from clipper.core import Core
    from clipper.fixtures.seed import demo_adapters, seed_demo
    from clipper.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="clipper-fixtures-"))
    settings = Settings().with_data_dir(tmp)
    core = Core.create(settings, fakes=True, clock=FakeClock(FIXED_NOW))
    demo_adapters(core)
    ids = seed_demo(core.db, settings, now=FIXED_NOW)
    app = create_app(core=core, start_background=False, settings=settings, allow_test_host=True)
    app.state.fixture_mode = True
    paths = [
        "/api/status",
        "/api/overview",
        "/api/switches",
        "/api/events?after=0",
        "/api/jobs",
        "/api/questions",
        "/api/notes",
        "/api/agents/board",
        "/api/agents/sessions",
        "/api/agents/director/messages",
        "/api/campaigns",
        "/api/clips",
        "/api/review/batches",
        "/api/review/auto-approve",
        "/api/publishing/accounts",
        "/api/publishing/calendar",
        "/api/publishing/recipes",
        "/api/earnings",
        "/api/settings",
        "/api/settings/lessons",
        "/api/settings/tools",
        "/api/settings/prompts",
        "/api/doctor",
    ]
    paths += [f"/api/campaigns/{cid}" for cid in ids["campaigns"].values()]
    paths += [f"/api/clips/{cid}" for cid in ids["clips"]]
    paths += [f"/api/agents/sessions/{sid}" for sid in ids["sessions"].values()]
    paths += [f"/api/review/batches/{ids['batch']}", f"/api/edit/{ids['clips'][2]}"]
    paths += [
        f"/api/switches/preview?level={lvl}&name={n}"
        for lvl, n in (
            ("marketplace", "vyro"),
            ("marketplace", "whop"),
            ("social", "youtube"),
            ("social", "tiktok"),
            ("social", "instagram"),
            ("social", "x"),
        )
    ]
    from clipper.settings import REPO_ROOT

    replacements = [(str(tmp), "D:/Clipper.io/data"), (str(REPO_ROOT), "D:/Clipper.io")]
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "files").mkdir(parents=True)
    secrets = _secrets_on_this_pc()
    with _pinned_disk_space(), TestClient(app) as client:
        for path in paths:
            res = client.get(path)
            res.raise_for_status()
            target = out_dir / _name(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(_scrub(res.json(), replacements), indent=1, sort_keys=True) + "\n"
            # these files are committed: never write one of this PC's secrets into them
            leaked = [name for name, value in secrets.items() if value in text]
            if leaked:
                raise RuntimeError(f"{path} contains this PC's {', '.join(leaked)}: not exported")
            target.write_text(text, encoding="utf-8", newline="\n")
        files: dict[str, str] = {}
        for cid in ids["clips"]:
            for kind, ext in (("thumb", "jpg"), ("preview", "mp4")):
                res = client.get(f"/api/files/clip/{cid}/{kind}")
                if res.status_code != 200:
                    continue
                name = "preview.mp4" if kind == "preview" else f"clip_{cid}_thumb.{ext}"
                (out_dir / "files" / name).write_bytes(res.content)
                files[f"/api/files/clip/{cid}/{kind}"] = f"files/{name}"
            res = client.get(f"/api/files/clip/{cid}/proxy")
            if res.status_code == 200:
                # every demo clip is cut from the same fixture source: one copy serves them all
                if not (out_dir / "files" / "source.mp4").exists():
                    (out_dir / "files" / "source.mp4").write_bytes(res.content)
                files[f"/api/files/clip/{cid}/proxy"] = "files/source.mp4"
    manifest = {
        "generated_at": FIXED_NOW.isoformat(),
        "paths": sorted(_name(p) for p in paths),
        "files": files,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    core.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return manifest
