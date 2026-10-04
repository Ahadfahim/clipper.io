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


def test_an_already_open_window_stays_open_when_clipper_starts(
    chrome: tuple[ChromeManager, FakeWindowOps], settings: Settings
) -> None:
    mgr, ops = chrome
    ops.launch([f"--user-data-dir={settings.paths.chrome_profiles_dir / 'main'}"])  # you opened it
    mgr.start()
    try:
        mgr.tick()
        assert next(s for s in mgr.states() if s.name == "main").visible
        assert len(ops.launched) == 1  # reused, not a second Chrome
    finally:
        mgr.stop()


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


# ---------------------------------------------------------------- the black-window fixes


def test_a_new_window_of_a_hidden_profile_is_hidden_the_moment_it_appears(
    chrome: tuple[ChromeManager, FakeWindowOps],
) -> None:
    mgr, ops = chrome
    pid = mgr.ensure_running("main")
    mgr.hide("main")
    hwnd = ops.open_window(pid)  # a popup from a site: hidden by the watcher, no tick needed
    assert ops.shown[hwnd] is False
    mgr.show("main")
    assert ops.open_window(pid, 2) and ops.shown[pid * 10 + 2] is True  # a shown profile keeps its popups


def test_show_starts_a_chrome_that_isnt_running_visible_and_hide_starts_nothing(
    chrome: tuple[ChromeManager, FakeWindowOps],
) -> None:
    mgr, ops = chrome
    mgr.hide("main")
    assert ops.launched == []
    mgr.show("main")
    assert ops.launched_hidden == [False]  # you asked to see it: not launched with the hide flag


def test_autostart_launches_hidden(chrome: tuple[ChromeManager, FakeWindowOps]) -> None:
    mgr, ops = chrome
    mgr.ensure_running("main")
    assert ops.launched_hidden == [True]


def test_status_reads_do_not_wait_for_a_chrome_that_is_busy(
    chrome: tuple[ChromeManager, FakeWindowOps], settings: Settings
) -> None:
    import threading
    import time

    mgr, ops = chrome
    mgr.ensure_running("main")
    gate = threading.Event()
    real = ops.browser_pid

    def slow(path: Path) -> int | None:
        gate.wait(5)  # PowerShell taking its time, or Chrome's UI thread stuck
        return real(path)

    ops.browser_pid = slow  # type: ignore[method-assign]
    mgr._pids.clear()  # pyright: ignore[reportPrivateUsage]  # force the slow lookup on the next tick
    busy = threading.Thread(target=mgr.tick, daemon=True)
    busy.start()
    time.sleep(0.1)
    started = time.monotonic()
    assert [s.name for s in mgr.states()] == ["main"]
    assert time.monotonic() - started < 0.5
    gate.set()
    busy.join(5)


def test_a_hung_window_is_reported_once_after_thirty_seconds(
    settings: Settings,
) -> None:
    now = [1000.0]
    ops = FakeWindowOps()
    mgr = ChromeManager(settings, ops, clock=lambda: now[0])
    seen: list[str] = []
    mgr.on_hung = seen.append
    pid = mgr.ensure_running("main")
    ops.hung_windows.add(ops.windows(pid)[0])
    mgr.tick()
    now[0] += 29
    mgr.tick()
    assert seen == [] and not next(s for s in mgr.states() if s.name == "main").hung
    now[0] += 2
    mgr.tick()
    mgr.tick()
    assert seen == ["main"]  # once, not on every tick
    assert next(s for s in mgr.states() if s.name == "main").hung
    ops.hung_windows.clear()
    mgr.tick()
    assert not next(s for s in mgr.states() if s.name == "main").hung


def test_restart_kills_a_stuck_chrome_and_starts_it_again(
    chrome: tuple[ChromeManager, FakeWindowOps],
) -> None:
    mgr, ops = chrome
    pid = mgr.show("main") and mgr.ensure_running("main")
    state = mgr.restart("main")
    assert ops.killed == [pid] and state.running
    assert len(ops.launched) == 2 and ops.launched_hidden == [False, False]  # it was shown: comes back shown


def test_which_windows_count_as_browser_windows() -> None:
    from clipper.browser.windows import WS_CAPTION, WS_EX_TOOLWINDOW, is_browser_window

    def ok(**kw: object) -> bool:
        base: dict[str, object] = {
            "cls": "Chrome_WidgetWin_1",
            "style": WS_CAPTION,
            "exstyle": 0,
            "owned": False,
            "visible": False,
            "titled": True,
        }
        return is_browser_window(**{**base, **kw})  # type: ignore[arg-type]

    assert ok()
    assert ok(titled=False, visible=True)  # brand new and visible: it must be found, to be hidden
    assert not ok(titled=False)  # hidden and nameless: a helper window, leave it alone
    assert not ok(cls="Chrome_WidgetWin_0")  # Chrome's message windows
    assert not ok(owned=True)  # menus and bubbles
    assert not ok(exstyle=WS_EX_TOOLWINDOW)  # tooltips
    assert not ok(style=0)  # no caption


def test_a_window_mostly_off_screen_is_moved_back() -> None:
    from clipper.browser.windows import fit_on_monitor

    work = (0, 0, 2560, 1400)
    assert fit_on_monitor((100, 100, 1080, 1372), work) is None  # fully visible
    assert fit_on_monitor((-300, 50, 1080, 1372), work) is None  # most of it visible
    assert fit_on_monitor((-1000, -900, 1080, 1372), work) == (740, 14, 1080, 1372)  # mostly gone: centred
    assert fit_on_monitor((5000, 0, 3000, 2000), work) == (0, 0, 2560, 1400)  # too big: shrunk to fit
