"""Find, show and hide the windows of a Clipper Chrome profile (Windows, via Win32 calls).

Clipper runs its own Chrome per profile (``--user-data-dir`` under ``paths.chrome_profiles_dir``) and
keeps it hidden unless you ask to see it. Hiding is plain ``ShowWindow(SW_HIDE)`` on the browser's
top-level windows: Chrome keeps running normally, it just has no window or taskbar button.
LOCAL-VERIFY: Windows only; tests use ``FakeWindowOps``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast


class WindowOps(Protocol):
    def launch(self, cmd: Sequence[str]) -> int: ...
    def browser_pid(self, user_data_dir: Path) -> int | None: ...
    def windows(self, pid: int) -> list[int]: ...
    def visible(self, hwnd: int) -> bool: ...
    def show(self, hwnd: int) -> None: ...
    def hide(self, hwnd: int) -> None: ...


def _same_dir(cmdline: str, user_data_dir: Path) -> bool:
    want = str(user_data_dir).rstrip("\\/").lower()
    low = cmdline.lower()
    for quoted in (f'--user-data-dir="{want}"', f"--user-data-dir={want}"):
        i = low.find(quoted)
        if i >= 0:
            end = i + len(quoted)
            return end == len(low) or low[end] in ' "\\/'
    return False


class Win32WindowOps:  # LOCAL-VERIFY
    """Real implementation. Process lookup uses CIM (one PowerShell call); windows use user32."""

    def launch(self, cmd: Sequence[str]) -> int:
        startup = None
        if sys.platform == "win32":
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0  # SW_HIDE: Chrome uses it for its first window
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
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        found: list[int] = []
        proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def each(hwnd: int, _: int) -> bool:
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid or user32.GetWindow(hwnd, 4):  # GW_OWNER: skip owned popups
                return True
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value == "Chrome_WidgetWin_1" and user32.GetWindowTextLengthW(hwnd) > 0:
                found.append(int(hwnd))
            return True

        user32.EnumWindows(proc(each), 0)
        return found

    def visible(self, hwnd: int) -> bool:
        import ctypes

        return bool(ctypes.windll.user32.IsWindowVisible(hwnd))  # type: ignore[attr-defined]

    def show(self, hwnd: int) -> None:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.ShowWindow(hwnd, 5)  # SW_SHOW
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)

    def hide(self, hwnd: int) -> None:
        import ctypes

        ctypes.windll.user32.ShowWindow(hwnd, 0)  # type: ignore[attr-defined]  # SW_HIDE


@dataclass
class FakeWindowOps:
    """In-memory Chrome for tests, CI and fixture mode: launching opens one visible window."""

    running: dict[str, int] = field(default_factory=lambda: {})  # user-data-dir -> pid
    shown: dict[int, bool] = field(default_factory=lambda: {})  # hwnd -> visible
    launched: list[list[str]] = field(default_factory=lambda: [])
    _next: int = 100

    def launch(self, cmd: Sequence[str]) -> int:
        self.launched.append(list(cmd))
        data_dir = next(a.split("=", 1)[1] for a in cmd if a.startswith("--user-data-dir="))
        self._next += 1
        self.running[data_dir.lower()] = self._next
        self.shown[self._next * 10] = True
        return self._next

    def browser_pid(self, user_data_dir: Path) -> int | None:
        return self.running.get(str(user_data_dir).lower())

    def windows(self, pid: int) -> list[int]:
        return [h for h in self.shown if h // 10 == pid]

    def visible(self, hwnd: int) -> bool:
        return self.shown.get(hwnd, False)

    def show(self, hwnd: int) -> None:
        self.shown[hwnd] = True

    def hide(self, hwnd: int) -> None:
        self.shown[hwnd] = False

    def close(self, user_data_dir: Path) -> None:
        pid = self.running.pop(str(user_data_dir).lower(), None)
        for h in [h for h in self.shown if pid is not None and h // 10 == pid]:
            del self.shown[h]
