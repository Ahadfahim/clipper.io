"""Find, show and hide the windows of a Clipper Chrome profile (Windows, via Win32 calls).

Clipper runs its own Chrome per profile (``--user-data-dir`` under ``paths.chrome_profiles_dir``) and
keeps it hidden unless you ask to see it. Hiding is plain ``ShowWindow(SW_HIDE)`` on the browser's
top-level windows: Chrome keeps running normally, it just has no window or taskbar button.

Two things go wrong with a window that is hidden by another process, and both end in a black or
half-drawn window: a window Chrome believes is hidden produces no frames, so showing it from outside
leaves a blank rectangle until something makes Chrome repaint; and a new window (a popup, a restored
session) is visible for as long as it takes the next poll to hide it. So ``show`` repaints the window
and checks it is on a monitor, and ``watch`` hides a profile's new windows the moment they appear.

Nothing here sends messages to Chrome's windows (``GetWindowText`` and friends do, and wait for its
UI thread): a Chrome that is busy or hung must not freeze Clipper too.
LOCAL-VERIFY: Windows only; tests use ``FakeWindowOps``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

# Win32 constants
SW_HIDE, SW_SHOW, SW_RESTORE = 0, 5, 9
GW_OWNER = 4
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION, WS_EX_TOOLWINDOW = 0x00C00000, 0x00000080
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x20, 0x40
HWND_TOP, HWND_TOPMOST, HWND_NOTOPMOST = 0, -1, -2
RDW_INVALIDATE, RDW_ERASE, RDW_FRAME, RDW_ALLCHILDREN, RDW_UPDATENOW = 0x1, 0x4, 0x400, 0x80, 0x100
EVENT_OBJECT_SHOW, WINEVENT_OUTOFCONTEXT, OBJID_WINDOW = 0x8002, 0x0, 0
MONITOR_DEFAULTTONEAREST = 2
QS_ALLINPUT, PM_REMOVE = 0x4FF, 0x1


class WindowOps(Protocol):
    def launch(self, cmd: Sequence[str], *, hidden: bool = True) -> int: ...
    def browser_pid(self, user_data_dir: Path) -> int | None: ...
    def windows(self, pid: int) -> list[int]: ...
    def visible(self, hwnd: int) -> bool: ...
    def hung(self, hwnd: int) -> bool: ...
    def show(self, hwnd: int) -> None: ...
    def hide(self, hwnd: int) -> None: ...
    def watch(self, pid: int, should_hide: Callable[[], bool]) -> None: ...
    def unwatch(self, pid: int) -> None: ...
    def kill(self, pid: int) -> None: ...


def _same_dir(cmdline: str, user_data_dir: Path) -> bool:
    want = str(user_data_dir).rstrip("\\/").lower()
    low = cmdline.lower()
    for quoted in (f'--user-data-dir="{want}"', f"--user-data-dir={want}"):
        i = low.find(quoted)
        if i >= 0:
            end = i + len(quoted)
            return end == len(low) or low[end] in ' "\\/'
    return False


def is_browser_window(
    *, cls: str, style: int, exstyle: int, owned: bool, visible: bool, titled: bool
) -> bool:
    """Is this one of Chrome's real browser windows (not a tooltip, a menu, an IME or helper window)?

    A real window has a caption and no owner and is not a tool window. A hidden window that has no
    title yet is left out: it may be a helper Chrome created for a moment, and showing it would put a
    stray empty window on screen. A visible one is always counted so it can be hidden."""
    return (
        cls == "Chrome_WidgetWin_1"
        and not owned
        and style & WS_CAPTION == WS_CAPTION
        and not exstyle & WS_EX_TOOLWINDOW
        and (visible or titled)
    )


def _monitor_info_type() -> Any:
    """ctypes' MONITORINFO, built on first use (ctypes.wintypes is only complete on Windows)."""
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [  # pyright: ignore[reportIncompatibleVariableOverride]
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    return MONITORINFO


class _User32:
    """user32 with real signatures. ctypes' default (a C int for every argument) would cut a 64-bit
    window handle in half."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes, self.wintypes = ctypes, wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
        self.u = u
        h, ui, i, b = wintypes.HWND, wintypes.UINT, ctypes.c_int, wintypes.BOOL
        sig: dict[str, tuple[list[Any], Any]] = {
            "ShowWindow": ([h, i], b),
            "IsWindowVisible": ([h], b),
            "IsIconic": ([h], b),
            "IsZoomed": ([h], b),
            "IsHungAppWindow": ([h], b),
            "GetWindow": ([h, ui], h),
            "GetWindowLongW": ([h, i], ctypes.c_long),
            "GetClassNameW": ([h, wintypes.LPWSTR, i], i),
            "InternalGetWindowText": ([h, wintypes.LPWSTR, i], i),
            "GetWindowRect": ([h, ctypes.POINTER(wintypes.RECT)], b),
            "GetWindowThreadProcessId": ([h, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            "SetWindowPos": ([h, h, i, i, i, i, ui], b),
            "RedrawWindow": ([h, ctypes.c_void_p, ctypes.c_void_p, ui], b),
            "SetForegroundWindow": ([h], b),
            "GetForegroundWindow": ([], h),
            "MonitorFromRect": ([ctypes.POINTER(wintypes.RECT), wintypes.DWORD], wintypes.HANDLE),
            "GetMonitorInfoW": ([wintypes.HANDLE, ctypes.c_void_p], b),
            "MsgWaitForMultipleObjects": (
                [wintypes.DWORD, ctypes.c_void_p, b, wintypes.DWORD, wintypes.DWORD],
                wintypes.DWORD,
            ),
            "PeekMessageW": ([ctypes.c_void_p, h, ui, ui, ui], b),
            "TranslateMessage": ([ctypes.c_void_p], b),
            "DispatchMessageW": ([ctypes.c_void_p], ctypes.c_ssize_t),
            "UnhookWinEvent": ([wintypes.HANDLE], b),
            "EnumWindows": ([ctypes.c_void_p, wintypes.LPARAM], b),
        }
        for name, (args, res) in sig.items():
            fn = getattr(u, name)
            fn.argtypes, fn.restype = args, res

    # ---- reads (none of these send a message to the window)

    def info(self, hwnd: int) -> tuple[str, int, int, bool, bool, bool]:
        ct = self.ctypes
        cls = ct.create_unicode_buffer(64)
        self.u.GetClassNameW(hwnd, cls, 64)
        title = ct.create_unicode_buffer(8)
        titled = bool(self.u.InternalGetWindowText(hwnd, title, 8))
        return (
            cls.value,
            self.u.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF,
            self.u.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF,
            bool(self.u.GetWindow(hwnd, GW_OWNER)),
            bool(self.u.IsWindowVisible(hwnd)),
            titled,
        )

    def is_browser_window(self, hwnd: int) -> bool:
        cls, style, exstyle, owned, visible, titled = self.info(hwnd)
        return is_browser_window(
            cls=cls, style=style, exstyle=exstyle, owned=owned, visible=visible, titled=titled
        )

    def pid_of(self, hwnd: int) -> int:
        owner = self.wintypes.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, self.ctypes.byref(owner))
        return int(owner.value)

    def rect(self, hwnd: int) -> tuple[int, int, int, int]:
        r = self.wintypes.RECT()
        self.u.GetWindowRect(hwnd, self.ctypes.byref(r))
        return r.left, r.top, r.right - r.left, r.bottom - r.top

    def work_area(self, left: int, top: int, width: int, height: int) -> tuple[int, int, int, int]:
        """The work area of the monitor nearest to a rectangle: (x, y, w, h)."""
        ct, wt = self.ctypes, self.wintypes

        rect = wt.RECT(left, top, left + width, top + height)
        mon = self.u.MonitorFromRect(ct.byref(rect), MONITOR_DEFAULTTONEAREST)
        info = _monitor_info_type()()
        info.cbSize = ct.sizeof(info)
        self.u.GetMonitorInfoW(mon, ct.byref(info))
        w = info.rcWork
        return w.left, w.top, w.right - w.left, w.bottom - w.top


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    x = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    y = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return x * y


def fit_on_monitor(
    rect: tuple[int, int, int, int], work: tuple[int, int, int, int]
) -> tuple[int, int, int, int] | None:
    """Where a window should move so it can be seen, or None when most of it already is.
    ``work`` is the work area of the nearest monitor. The size is kept unless it doesn't fit."""
    if _overlap(rect, work) * 2 >= rect[2] * rect[3]:
        return None
    w, h = min(rect[2], work[2]), min(rect[3], work[3])
    return work[0] + (work[2] - w) // 2, work[1] + (work[3] - h) // 2, w, h


class _ShowWatcher(threading.Thread):
    """Hides a profile's new windows as soon as Windows reports them (EVENT_OBJECT_SHOW), instead of
    on the next poll. Needs its own message loop: out-of-context hooks are delivered to it."""

    def __init__(self, user32: _User32, pid: int, should_hide: Callable[[], bool]) -> None:
        super().__init__(name=f"clipper-chrome-watch-{pid}", daemon=True)
        self.user32, self.pid, self.should_hide = user32, pid, should_hide
        self._halt = threading.Event()

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        ct, wt, u = self.user32.ctypes, self.user32.wintypes, self.user32.u
        proc_type = ct.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)  # type: ignore[attr-defined]

        def on_event(
            _hook: Any, _event: int, hwnd: int, id_object: int, id_child: int, _t: int, _ms: int
        ) -> None:
            try:
                if (
                    id_object == OBJID_WINDOW
                    and id_child == 0
                    and hwnd
                    and self.should_hide()
                    and self.user32.is_browser_window(hwnd)
                ):
                    u.ShowWindow(hwnd, SW_HIDE)
            except Exception:  # a callback must never raise into Windows
                pass

        callback = proc_type(on_event)  # kept alive for the life of the hook
        set_hook = u.SetWinEventHook
        set_hook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, proc_type, wt.DWORD, wt.DWORD, wt.DWORD]
        set_hook.restype = wt.HANDLE
        hook = set_hook(
            EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, None, callback, self.pid, 0, WINEVENT_OUTOFCONTEXT
        )
        if not hook:
            return  # the polling loop still hides new windows, a second later
        msg = ct.create_string_buffer(64)  # a MSG is 48 bytes on 64-bit Windows
        try:
            while not self._halt.is_set():
                u.MsgWaitForMultipleObjects(0, None, False, 200, QS_ALLINPUT)
                while u.PeekMessageW(msg, None, 0, 0, PM_REMOVE):
                    u.TranslateMessage(msg)
                    u.DispatchMessageW(msg)
        finally:
            u.UnhookWinEvent(hook)


class Win32WindowOps:  # LOCAL-VERIFY
    """Real implementation. Process lookup uses CIM (one PowerShell call); windows use user32."""

    def __init__(self) -> None:
        self._u: _User32 | None = None
        self._watchers: dict[int, _ShowWatcher] = {}

    @property
    def user32(self) -> _User32:
        if self._u is None:
            self._u = _User32()
        return self._u

    def launch(self, cmd: Sequence[str], *, hidden: bool = True) -> int:
        startup = None
        if hidden and sys.platform == "win32":
            startup = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
            startup.wShowWindow = SW_HIDE  # Chrome uses it for its first window
        proc = subprocess.Popen(list(cmd), startupinfo=startup, close_fds=True)
        return proc.pid

    def browser_pid(self, user_data_dir: Path) -> int | None:
        query = (
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            out = subprocess.run(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", query],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            ).stdout
            parsed: Any = json.loads(out) if out.strip() else []
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
        rows = cast(list[dict[str, Any]], parsed if isinstance(parsed, list) else [parsed])
        for row in rows:
            cmd = str(row.get("CommandLine") or "")
            # the browser process is the one without --type= (renderers, GPU etc. carry a type)
            if "--type=" not in cmd and _same_dir(cmd, user_data_dir):
                return int(row["ProcessId"])
        return None

    def windows(self, pid: int) -> list[int]:
        u32 = self.user32
        found: list[int] = []
        enum_type = u32.ctypes.WINFUNCTYPE(u32.wintypes.BOOL, u32.wintypes.HWND, u32.wintypes.LPARAM)  # type: ignore[attr-defined]

        def each(hwnd: int, _: int) -> bool:
            if u32.pid_of(hwnd) == pid and u32.is_browser_window(hwnd):
                found.append(int(hwnd))
            return True

        u32.u.EnumWindows(enum_type(each), 0)
        return found

    def visible(self, hwnd: int) -> bool:
        return bool(self.user32.u.IsWindowVisible(hwnd))

    def hung(self, hwnd: int) -> bool:
        return bool(self.user32.u.IsHungAppWindow(hwnd))

    def show(self, hwnd: int) -> None:
        """Show a window so that it is drawn, on a monitor, and in front."""
        u32 = self.user32
        u = u32.u
        maximized = bool(u.IsZoomed(hwnd))
        u.ShowWindow(hwnd, SW_RESTORE if u.IsIconic(hwnd) else SW_SHOW)
        if not maximized:
            moved = fit_on_monitor(u32.rect(hwnd), u32.work_area(*u32.rect(hwnd)))
            if moved is not None:
                x, y, w, h = moved
                u.SetWindowPos(hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)
        u.SetWindowPos(
            hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
        )
        u.RedrawWindow(
            hwnd, None, None, RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN | RDW_UPDATENOW
        )
        if not maximized:
            # Chrome paints again after a resize, which a window that was hidden by another process
            # doesn't always do on its own. One pixel for a few milliseconds: nobody sees it.
            x, y, w, h = u32.rect(hwnd)
            u.SetWindowPos(hwnd, 0, x, y, w + 1, h, SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOMOVE)
            time.sleep(0.04)
            u.SetWindowPos(hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOMOVE)
        self._to_front(hwnd)

    def _to_front(self, hwnd: int) -> None:
        u = self.user32.u
        u.SetForegroundWindow(hwnd)
        if u.GetForegroundWindow() != hwnd:
            # Windows only lets the foreground app take focus. Raise the window above the others
            # anyway, so it can't be left hidden behind them.
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            u.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
            u.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)

    def hide(self, hwnd: int) -> None:
        self.user32.u.ShowWindow(hwnd, SW_HIDE)

    def watch(self, pid: int, should_hide: Callable[[], bool]) -> None:
        self.unwatch(pid)
        watcher = _ShowWatcher(self.user32, pid, should_hide)
        self._watchers[pid] = watcher
        watcher.start()

    def unwatch(self, pid: int) -> None:
        watcher = self._watchers.pop(pid, None)
        if watcher is not None:
            watcher.stop()

    def kill(self, pid: int) -> None:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)


@dataclass
class FakeWindowOps:
    """In-memory Chrome for tests, CI and fixture mode: launching opens one visible window."""

    running: dict[str, int] = field(default_factory=lambda: {})  # user-data-dir -> pid
    shown: dict[int, bool] = field(default_factory=lambda: {})  # hwnd -> visible
    launched: list[list[str]] = field(default_factory=lambda: [])
    launched_hidden: list[bool] = field(default_factory=lambda: [])
    hung_windows: set[int] = field(default_factory=lambda: set())
    killed: list[int] = field(default_factory=lambda: [])
    watchers: dict[int, Callable[[], bool]] = field(default_factory=lambda: {})
    shows: list[int] = field(default_factory=lambda: [])  # hwnds in the order they were shown
    _next: int = 100

    def launch(self, cmd: Sequence[str], *, hidden: bool = True) -> int:
        self.launched.append(list(cmd))
        self.launched_hidden.append(hidden)
        data_dir = next(a.split("=", 1)[1] for a in cmd if a.startswith("--user-data-dir="))
        self._next += 1
        self.running[data_dir.lower()] = self._next
        # a real Chrome can ignore the hidden start flag; a visible launch is shown on purpose
        self.shown[self._next * 10] = True
        return self._next

    def open_window(self, pid: int, n: int = 1) -> int:
        """A site opens a popup, or a session is restored: a new window that starts out visible,
        unless a watcher hides it the moment it appears."""
        hwnd = pid * 10 + n
        self.shown[hwnd] = True
        hide = self.watchers.get(pid)
        if hide is not None and hide():
            self.shown[hwnd] = False
        return hwnd

    def browser_pid(self, user_data_dir: Path) -> int | None:
        return self.running.get(str(user_data_dir).lower())

    def windows(self, pid: int) -> list[int]:
        return [h for h in self.shown if h // 10 == pid]

    def visible(self, hwnd: int) -> bool:
        return self.shown.get(hwnd, False)

    def hung(self, hwnd: int) -> bool:
        return hwnd in self.hung_windows

    def show(self, hwnd: int) -> None:
        self.shown[hwnd] = True
        self.shows.append(hwnd)

    def hide(self, hwnd: int) -> None:
        self.shown[hwnd] = False

    def watch(self, pid: int, should_hide: Callable[[], bool]) -> None:
        self.watchers[pid] = should_hide

    def unwatch(self, pid: int) -> None:
        self.watchers.pop(pid, None)

    def kill(self, pid: int) -> None:
        self.killed.append(pid)
        self.watchers.pop(pid, None)
        for key in [k for k, v in self.running.items() if v == pid]:
            self.running.pop(key)
        for h in [h for h in self.shown if h // 10 == pid]:
            del self.shown[h]

    def close(self, user_data_dir: Path) -> None:
        pid = self.running.pop(str(user_data_dir).lower(), None)
        for h in [h for h in self.shown if pid is not None and h // 10 == pid]:
            del self.shown[h]
