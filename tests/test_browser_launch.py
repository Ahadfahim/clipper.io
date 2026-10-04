from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from clipper.browser.launch import chrome_command, open_profile
from clipper.settings import Settings


def test_chrome_command_uses_a_profile_folder_and_no_automation_flags(tmp_path: Path) -> None:
    s = Settings().with_data_dir(tmp_path)
    cmd = chrome_command(s, "main", "https://www.tiktok.com/upload")
    assert cmd[0] == str(s.paths.chrome_exe)
    assert cmd[1] == f"--user-data-dir={s.paths.chrome_profiles_dir / 'main'}"
    assert cmd[-1] == "https://www.tiktok.com/upload"
    assert not any("automation" in c or "remote-debugging" in c or "user-agent" in c for c in cmd)


@pytest.mark.parametrize("bad", ["../etc", "a/b", "", "x" * 80, "..", "main;calc"])
def test_profile_names_are_validated(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="bad profile name"):
        chrome_command(Settings().with_data_dir(tmp_path), bad)


def test_open_profile_runs_chrome(tmp_path: Path) -> None:
    calls: list[Any] = []
    open_profile(Settings().with_data_dir(tmp_path), "beast", popen=calls.append)
    assert len(calls) == 1 and "--user-data-dir=" in calls[0][1]
    with pytest.raises(ValueError, match="https"):
        chrome_command(Settings().with_data_dir(tmp_path), "main", "http://insecure.example")
