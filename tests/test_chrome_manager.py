"""Clipper's own Chrome: started hidden, shown on request, kept hidden, relaunched when closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipper.browser.manager import KEEP_RUNNING_FLAGS, ChromeManager
from clipper.browser.windows import FakeWindowOps, _same_dir  # pyright: ignore[reportPrivateUsage]
from clipper.settings import Settings


@pytest.fixture
def chrome(settings: Settings) -> tuple[ChromeManager, FakeWindowOps]:
    ops = FakeWindowOps()
    return ChromeManager(settings, ops), ops


def test_start_launches_autostart_profiles_hidden(chrome: tuple[ChromeManager, FakeWindowOps]) -> None:
    mgr, ops = chrome
    mgr.start()
    try:
        cmd = ops.launched[0]
        assert any(a.startswith("--user-data-dir=") and a.endswith("main") for a in cmd)
        assert all(flag in cmd for flag in KEEP_RUNNING_FLAGS)
        assert not any("automation" in a or "headless" in a for a in cmd)
        mgr.tick()  # Chrome opened its first window visibly; the loop hides it
        assert [(s.name, s.running, s.visible) for s in mgr.states() if s.name == "main"] == [
            ("main", True, False)
        ]
    finally:
        mgr.stop()


def test_show_and_hide(chrome: tuple[ChromeManager, FakeWindowOps]) -> None:
    mgr, _ = chrome
    assert mgr.show("main").visible
    mgr.tick()
    assert next(s for s in mgr.states() if s.name == "main").visible  # a shown window stays shown
    assert not mgr.hide("main").visible
    assert mgr.toggle("main").visible


def test_new_windows_of_a_hidden_profile_get_hidden(chrome: tuple[ChromeManager, FakeWindowOps]) -> None:
    mgr, ops = chrome
    pid = mgr.ensure_running("main")
    mgr.hide("main")
    ops.shown[pid * 10 + 1] = True  # a popup opened by a site
    mgr.tick()
    assert not any(ops.shown[h] for h in ops.windows(pid))


def test_closed_chrome_comes_back_hidden(
    chrome: tuple[ChromeManager, FakeWindowOps], settings: Settings
) -> None:
    mgr, ops = chrome
    mgr.show("main")
    ops.close(settings.paths.chrome_profiles_dir / "main")  # the user closed the visible window
    for _ in range(10):  # the pid recheck runs every few ticks
        mgr.tick()
    state = next(s for s in mgr.states() if s.name == "main")
    assert state.running and not state.visible and len(ops.launched) == 2


def test_bad_profile_names_are_refused(chrome: tuple[ChromeManager, FakeWindowOps]) -> None:
    mgr, _ = chrome
    for bad in ("..", "a/b", "", "x" * 80):
        with pytest.raises(ValueError, match="bad profile name"):
            mgr.show(bad)


def test_profile_match_ignores_case_and_quotes() -> None:
    d = Path(r"C:\ClipperData\chrome\main")
    assert _same_dir(r'chrome.exe --user-data-dir="C:\ClipperData\Chrome\Main" --no-first-run', d)
    assert _same_dir(r"chrome.exe --user-data-dir=C:\ClipperData\chrome\main", d)
    assert not _same_dir(r"chrome.exe --user-data-dir=C:\ClipperData\chrome\main2", d)
    assert not _same_dir(r"chrome.exe --type=renderer", d)


def test_tests_never_touch_the_real_profiles(settings: Settings) -> None:
    assert "ClipperData" not in str(settings.paths.chrome_profiles_dir)
