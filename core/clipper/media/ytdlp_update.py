"""yt-dlp's version, how old it is, and a one-click update.

Sites change their pages every few weeks and yt-dlp releases fixes just as often, so an old copy
fails downloads that a current one handles. The doctor warns when it is older than
``media.ytdlp_max_age_days``; Settings -> Media has an Update button.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_VERSION = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")

Runner = Callable[[list[str]], tuple[int, str]]


def release_date(version: str) -> date | None:
    """yt-dlp versions start with their release date: 2026.03.17, 2026.03.17.232541 (nightly)."""
    m = _VERSION.search(version)
    if m is None:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def age_days(version: str, today: date) -> int | None:
    released = release_date(version)
    return None if released is None else (today - released).days


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _owning_python(exe: str) -> str | None:
    """The interpreter that pip-installed ``yt-dlp``: a sibling of its Scripts folder, or ours."""
    found = shutil.which(exe)
    if found is None:
        return None
    scripts = Path(found).resolve().parent
    for candidate in (
        scripts / "python.exe",
        scripts / "python",
        scripts.parent / "python.exe",
        scripts.parent / "python",
    ):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


@dataclass(frozen=True)
class UpdateResult:
    ok: bool
    before: str
    after: str
    detail: str


def update_ytdlp(exe: str = "yt-dlp", run: Runner = _run) -> UpdateResult:
    """Update yt-dlp in place. A standalone build updates itself (``-U``); a pip install is updated
    with the pip of the Python that owns it."""
    code, before_out = run([exe, "--version"])
    if code != 0:
        return UpdateResult(False, "", "", "yt-dlp isn't installed or isn't on PATH")
    before = before_out.strip().splitlines()[-1] if before_out.strip() else ""
    code, out = run([exe, "-U"])
    if code != 0 and re.search(r"pip|pypi|wheel", out, re.I):
        py = _owning_python(exe)
        if py is None:
            return UpdateResult(False, before, before, "couldn't find the Python that owns yt-dlp")
        code, out = run([py, "-m", "pip", "install", "--upgrade", "yt-dlp"])
        if code != 0:
            return UpdateResult(False, before, before, out.strip()[-400:] or "pip failed")
    elif code != 0:
        return UpdateResult(False, before, before, out.strip()[-400:] or "update failed")
    _, after_out = run([exe, "--version"])
    after = after_out.strip().splitlines()[-1] if after_out.strip() else before
    return UpdateResult(
        True, before, after, "already up to date" if after == before else f"updated to {after}"
    )
