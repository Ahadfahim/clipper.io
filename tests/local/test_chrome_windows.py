"""LOCAL-VERIFY: Clipper's Chrome windows on a real Windows desktop.

Starts a scratch Chrome profile (its own ``--user-data-dir`` in the pytest temp folder, never the
logged-in ``main`` profile), hides and shows it several times and checks that the window is in front
and drawn after every show, both as it appears on screen and as the window renders itself: a hidden
Chrome that is shown from outside can come back as a flat black rectangle (no tab strip, no page).
A Chrome window flashes on screen for about a second per cycle.

    $env:CLIPPER_LOCAL = "1"; uv run pytest tests/local/test_chrome_windows.py -v

``CLIPPER_CHROME_CYCLES`` sets how many show/hide cycles run (default 5).
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path

import pytest

from clipper.browser.manager import ChromeManager
from clipper.browser.windows import Win32WindowOps
from clipper.settings import Settings, load_settings

pytestmark = [pytest.mark.local, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]

PROFILE = "scratch"


def _gdi() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:  # type: ignore[name-defined]
    u = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
    g = ctypes.WinDLL("gdi32", use_last_error=True)  # type: ignore[attr-defined]
    h = wintypes.HANDLE
    u.GetDC.argtypes, u.GetDC.restype = [h], h
    u.ReleaseDC.argtypes = [h, h]
    u.PrintWindow.argtypes, u.PrintWindow.restype = [h, h, wintypes.UINT], wintypes.BOOL
    u.GetWindowRect.argtypes = [h, ctypes.POINTER(wintypes.RECT)]
    g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [h], h
    g.CreateCompatibleBitmap.argtypes, g.CreateCompatibleBitmap.restype = [h, ctypes.c_int, ctypes.c_int], h
    g.SelectObject.argtypes, g.SelectObject.restype = [h, h], h
    g.DeleteObject.argtypes = [h]
    g.DeleteDC.argtypes = [h]
    g.GetDIBits.argtypes = [
        h,
        h,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    return u, g


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [  # pyright: ignore[reportIncompatibleVariableOverride]
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def capture(hwnd: int) -> tuple[int, int, memoryview]:
    """The window's pixels as drawn by the browser (PrintWindow with full content), 32-bit BGRA."""
    u, g = _gdi()
    rect = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    screen = u.GetDC(None)
    mem = g.CreateCompatibleDC(screen)
    bmp = g.CreateCompatibleBitmap(screen, w, h)
    g.SelectObject(mem, bmp)
    u.PrintWindow(hwnd, mem, 2)  # PW_RENDERFULLCONTENT
    header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), w, -h, 1, 32, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(header), 0)
    g.DeleteObject(bmp)
    g.DeleteDC(mem)
    u.ReleaseDC(None, screen)
    return w, h, memoryview(bytes(buf)).cast("I")


def capture_screen(hwnd: int) -> tuple[int, int, memoryview]:
    """What is on the screen where the window is (BitBlt from the desktop), i.e. what you would see.
    ``capture`` asks the window to draw itself, which can look right while the screen shows black."""
    u, g = _gdi()
    g.BitBlt.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HANDLE, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
    ]  # fmt: skip
    rect = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    screen = u.GetDC(None)
    mem = g.CreateCompatibleDC(screen)
    bmp = g.CreateCompatibleBitmap(screen, w, h)
    g.SelectObject(mem, bmp)
    g.BitBlt(mem, 0, 0, w, h, screen, rect.left, rect.top, 0x00CC0020 | 0x40000000)  # SRCCOPY | CAPTUREBLT
    header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), w, -h, 1, 32, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(header), 0)
    g.DeleteObject(bmp)
    g.DeleteDC(mem)
    u.ReleaseDC(None, screen)
    return w, h, memoryview(bytes(buf)).cast("I")


def window_at_center(hwnd: int) -> int:
    """The top-level window that is on top at the middle of ``hwnd``'s rectangle."""
    u, _ = _gdi()
    rect = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(rect))
    u.WindowFromPoint.argtypes, u.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
    u.GetAncestor.argtypes, u.GetAncestor.restype = [wintypes.HWND, wintypes.UINT], wintypes.HWND
    top = u.WindowFromPoint(wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2))
    return int(u.GetAncestor(top, 2) or 0)  # GA_ROOT


def distinct_colors(pixels: memoryview, width: int, rows: range) -> int:
    seen: set[int] = set()
    for y in rows:
        seen.update(pixels[y * width : (y + 1) * width])
    return len(seen)


@pytest.fixture
def scratch(tmp_path: Path) -> Iterator[tuple[ChromeManager, Win32WindowOps, Settings]]:
    settings = load_settings().isolated(tmp_path / "data")  # a scratch profile, not the logged-in one
    ops = Win32WindowOps()
    mgr = ChromeManager(settings, ops)
    yield mgr, ops, settings
    pid = ops.browser_pid(mgr.profile_dir(PROFILE))
    mgr.stop()
    if pid is not None:
        ops.kill(pid)


def _wait_for_window(mgr: ChromeManager, ops: Win32WindowOps, timeout: float = 30.0) -> int:
    pid = mgr.ensure_running(PROFILE)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = ops.windows(pid)
        if found:
            return pid
        time.sleep(0.25)
    raise AssertionError("Chrome never opened a window")


def test_a_shown_clipper_chrome_is_drawn_every_time(
    scratch: tuple[ChromeManager, Win32WindowOps, Settings],
) -> None:
    mgr, ops, _ = scratch
    pid = _wait_for_window(mgr, ops)
    time.sleep(2.0)  # let the first page load
    mgr.hide(PROFILE)
    for cycle in range(int(os.environ.get("CLIPPER_CHROME_CYCLES", "5"))):
        mgr.show(PROFILE)
        time.sleep(1.0)
        (hwnd, *_rest) = ops.windows(pid)
        assert ops.visible(hwnd), f"cycle {cycle}: the window is not visible after show"
        assert window_at_center(hwnd) == hwnd, f"cycle {cycle}: the shown window is behind another window"
        for name, grab in (("on screen", capture_screen), ("by PrintWindow", capture)):
            w, h, pixels = grab(hwnd)
            strip = distinct_colors(pixels, w, range(0, min(80, h)))
            page = distinct_colors(pixels, w, range(min(120, h - 1), h, 3))
            assert strip >= 12, f"cycle {cycle}: the tab strip is blank {name} ({strip} colors in {w}x{h})"
            assert page >= 6, f"cycle {cycle}: the page area is blank {name} ({page} colors in {w}x{h})"
        mgr.hide(PROFILE)
        assert not ops.visible(hwnd)


def test_a_popup_of_a_hidden_chrome_never_shows(
    scratch: tuple[ChromeManager, Win32WindowOps, Settings],
) -> None:
    import subprocess

    mgr, ops, settings = scratch
    pid = _wait_for_window(mgr, ops)
    mgr.start()  # the loop and the new-window watcher
    mgr.hide(PROFILE)
    before = set(ops.windows(pid))
    # a second window of the same profile, the way a site's popup or a restored session opens one
    subprocess.Popen(
        [str(settings.paths.chrome_exe), f"--user-data-dir={mgr.profile_dir(PROFILE)}", "--new-window"]
    )
    deadline = time.monotonic() + 15
    seen_visible = False
    new: set[int] = set()
    while time.monotonic() < deadline and not new:
        new = set(ops.windows(pid)) - before
        seen_visible = seen_visible or any(ops.visible(h) for h in new)
        time.sleep(0.01)
    time.sleep(0.5)
    assert new, "Chrome never opened the second window"
    assert not any(ops.visible(h) for h in new)
    assert not seen_visible, "the new window was visible for a moment before it was hidden"
