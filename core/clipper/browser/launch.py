"""Opens a Clipper Chrome profile window (for logging in or fixing a paused account).

Each Clipper profile is its own Chrome user-data folder under ``paths.chrome_profiles_dir`` with
the Companion extension installed. Plain Chrome: no automation flags, no fingerprint changes.
LOCAL-VERIFY: on Windows, with the real Chrome path.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

from clipper.settings import Settings

PROFILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}")


def chrome_command(settings: Settings, profile: str, url: str | None = None) -> list[str]:
    if not PROFILE_RE.fullmatch(profile) or ".." in profile:
        raise ValueError(f"bad profile name: {profile!r}")
    cmd = [
        str(settings.paths.chrome_exe),
        f"--user-data-dir={settings.paths.chrome_profiles_dir / profile}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if url:
        if not url.startswith("https://"):
            raise ValueError("only https URLs")
        cmd.append(url)
    return cmd


def open_profile(
    settings: Settings,
    profile: str,
    url: str | None = None,
    popen: Callable[[Sequence[str]], Any] = subprocess.Popen,
) -> list[str]:
    cmd = chrome_command(settings, profile, url)
    popen(cmd)
    return cmd
