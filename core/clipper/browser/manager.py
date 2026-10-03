"""Clipper's own Chrome: one process per profile, started by Clipper and hidden unless you ask to see it.

``ChromeManager.start()`` launches the ``browser.autostart_profiles`` (hidden by default) and runs a
small loop that keeps hidden profiles hidden (new windows and popups included) and relaunches a
profile whose Chrome went away. ``show()``/``hide()`` back the Show browser button. The loop caches
the state, so the status bar can read it on every poll.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from clipper.browser.launch import chrome_command
from clipper.browser.windows import WindowOps
from clipper.settings import Settings

log = logging.getLogger(__name__)

# Hidden windows must keep working at full speed: no background throttling of timers or renderers,
# and no "this window is covered, stop painting" optimisation. These are performance switches only;
# Clipper's Chrome carries no automation or fingerprint flags.
KEEP_RUNNING_FLAGS = (
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "--disable-features=CalculateNativeWinOcclusion",
)
PID_RECHECK_TICKS = 10


@dataclass(frozen=True)
class ProfileState:
    name: str
    running: bool
    visible: bool


class ChromeManager:
    def __init__(self, settings: Settings, ops: WindowOps, interval_s: float = 1.0) -> None:
        self.settings = settings
        self.ops = ops
        self.interval_s = interval_s
        self._lock = threading.RLock()
        self._want_hidden: dict[str, bool] = {}
        self._pids: dict[str, int] = {}
        self._state: dict[str, ProfileState] = {}
        self._ticks = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ queries

    def profile_dir(self, profile: str) -> Path:
        chrome_command(self.settings, profile)  # validates the name
        return self.settings.paths.chrome_profiles_dir / profile

    def profiles(self) -> list[str]:
        names = set(self.settings.browser.autostart_profiles) | set(self._want_hidden)
        root = self.settings.paths.chrome_profiles_dir
        if root.is_dir():
            names |= {p.name for p in root.iterdir() if p.is_dir()}
        return sorted(names)

    def states(self) -> list[ProfileState]:
        with self._lock:
            return [self._state.get(n, ProfileState(n, False, False)) for n in self.profiles()]

    def command(self, profile: str, url: str | None = None) -> list[str]:
        cmd = chrome_command(self.settings, profile, url)
        return [*cmd[:-1], *KEEP_RUNNING_FLAGS, cmd[-1]] if url else [*cmd, *KEEP_RUNNING_FLAGS]

    # ------------------------------------------------------------ actions

    def ensure_running(self, profile: str) -> int:
        with self._lock:
            pid = self._pid(profile, recheck=True)
            if pid is None:
                pid = self.ops.launch(self.command(profile))
                self._want_hidden.setdefault(profile, self.settings.browser.start_hidden)
                log.info("started Clipper Chrome %s (pid %s)", profile, pid)
            self._pids[profile] = pid
            return pid

    def show(self, profile: str) -> ProfileState:
        with self._lock:
            pid = self.ensure_running(profile)
            self._want_hidden[profile] = False
            for hwnd in self.ops.windows(pid):
                self.ops.show(hwnd)
            return self._refresh(profile)

    def hide(self, profile: str) -> ProfileState:
        with self._lock:
            self._want_hidden[profile] = True
            pid = self._pid(profile, recheck=True)
            if pid is not None:
                for hwnd in self.ops.windows(pid):
                    self.ops.hide(hwnd)
            return self._refresh(profile)

    def toggle(self, profile: str) -> ProfileState:
        with self._lock:
            state = self._refresh(profile)
            return self.hide(profile) if state.visible else self.show(profile)

    def tick(self) -> None:
        """Keep hidden profiles hidden and autostart profiles running; refresh the cached state."""
        with self._lock:
            self._ticks += 1
            recheck = self._ticks % PID_RECHECK_TICKS == 0
            for profile in self.profiles():
                pid = self._pid(profile, recheck=recheck)
                if pid is None:
                    if not (
                        self.settings.browser.keep_running
                        and profile in self.settings.browser.autostart_profiles
                    ):
                        self._refresh(profile)
                        continue
                    # Chrome was closed: bring it back the way it starts (hidden by default)
                    self._want_hidden[profile] = self.settings.browser.start_hidden
                    pid = self.ensure_running(profile)
                if self._want_hidden.get(profile, self.settings.browser.start_hidden):
                    for hwnd in self.ops.windows(pid):
                        if self.ops.visible(hwnd):
                            self.ops.hide(hwnd)
                self._refresh(profile)

    def start(self) -> None:
        for profile in self.settings.browser.autostart_profiles:
            try:
                self.ensure_running(profile)
            except (OSError, ValueError) as exc:
                log.warning("couldn't start Clipper Chrome %s: %s", profile, exc)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="clipper-chrome", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ------------------------------------------------------------ internals

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.tick()
            except Exception:  # the loop must survive a bad tick (Chrome restarting, CIM hiccup)
                log.exception("Clipper Chrome loop")

    def _pid(self, profile: str, *, recheck: bool) -> int | None:
        pid = self._pids.get(profile)
        if pid is not None and (not recheck or self.ops.windows(pid)):
            return pid
        found = self.ops.browser_pid(self.profile_dir(profile))
        if found is None:
            self._pids.pop(profile, None)
        else:
            self._pids[profile] = found
        return found

    def _refresh(self, profile: str) -> ProfileState:
        pid = self._pids.get(profile)
        hwnds = self.ops.windows(pid) if pid is not None else []
        state = ProfileState(profile, pid is not None, any(self.ops.visible(h) for h in hwnds))
        self._state[profile] = state
        return state
