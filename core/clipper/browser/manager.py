"""Clipper's own Chrome: one process per profile, started by Clipper and hidden unless you ask to see it.

``ChromeManager.start()`` launches the ``browser.autostart_profiles`` (hidden by default) and runs a
small loop that keeps hidden profiles hidden (new windows and popups included) and relaunches a
profile whose Chrome went away. ``show()``/``hide()`` back the Show browser button. The loop caches
the state, so the status bar can read it on every poll without waiting for Chrome.

Slow or blocking calls (finding Chrome's process through PowerShell, enumerating windows) never
happen while a reader of the state is waiting: ``states()`` takes no lock.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
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
HUNG_AFTER_S = 30.0


@dataclass(frozen=True)
class ProfileState:
    name: str
    running: bool
    visible: bool
    hung: bool = False


class ChromeManager:
    def __init__(
        self,
        settings: Settings,
        ops: WindowOps,
        interval_s: float = 1.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.ops = ops
        self.interval_s = interval_s
        self._clock = clock
        self._lock = threading.RLock()
        self._want_hidden: dict[str, bool] = {}
        self._pids: dict[str, int] = {}
        self._state: dict[str, ProfileState] = {}
        self._watched: dict[str, int] = {}
        self._hung_since: dict[str, float] = {}
        self._hung_reported: set[str] = set()
        self._ticks = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # set by Core: called once when a profile's window stops responding for HUNG_AFTER_S
        self.on_hung: Callable[[str], None] | None = None

    # ------------------------------------------------------------ queries

    def profile_dir(self, profile: str) -> Path:
        chrome_command(self.settings, profile)  # validates the name
        return self.settings.paths.chrome_profiles_dir / profile

    def profiles(self) -> list[str]:
        names = set(self.settings.browser.autostart_profiles) | set(list(self._want_hidden))
        root = self.settings.paths.chrome_profiles_dir
        if root.is_dir():
            names |= {p.name for p in root.iterdir() if p.is_dir()}
        return sorted(names)

    def states(self) -> list[ProfileState]:
        """The last state the loop saw. Takes no lock, so a busy or hung Chrome can't block a poll."""
        cached = dict(self._state)
        return [cached.get(n, ProfileState(n, False, False)) for n in self.profiles()]

    def command(self, profile: str, url: str | None = None) -> list[str]:
        cmd = chrome_command(self.settings, profile, url)
        return [*cmd[:-1], *KEEP_RUNNING_FLAGS, cmd[-1]] if url else [*cmd, *KEEP_RUNNING_FLAGS]

    # ------------------------------------------------------------ actions

    def ensure_running(self, profile: str, *, visible: bool = False) -> int:
        """The profile's Chrome pid, starting Chrome when it isn't running. ``visible`` starts a new
        Chrome with its window showing (you asked to see it) instead of hidden."""
        with self._lock:
            pid = self._pid(profile, recheck=True)
            if pid is None:
                if visible:
                    self._want_hidden[profile] = False
                else:
                    self._want_hidden.setdefault(profile, self.settings.browser.start_hidden)
                pid = self.ops.launch(self.command(profile), hidden=self._want_hidden[profile])
                log.info("started Clipper Chrome %s (pid %s)", profile, pid)
            elif profile not in self._want_hidden:
                # Chrome was already open (Clipper restarted, or you opened it yourself): keep it the
                # way you left it instead of hiding a window you may be using right now.
                shown = any(self.ops.visible(h) for h in self.ops.windows(pid))
                self._want_hidden[profile] = not shown
            self._pids[profile] = pid
            self._watch(profile, pid)
            return pid

    def show(self, profile: str) -> ProfileState:
        with self._lock:
            self._want_hidden[profile] = False  # before any launch, so new windows aren't hidden
            pid = self.ensure_running(profile, visible=True)
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

    def restart(self, profile: str) -> ProfileState:
        """Close a Chrome that has stopped responding and start it again the way it was (shown or
        hidden). Logins are kept: they live in the profile folder."""
        with self._lock:
            pid = self._pid(profile, recheck=False) or self.ops.browser_pid(self.profile_dir(profile))
            was_hidden = self._want_hidden.get(profile, self.settings.browser.start_hidden)
            if pid is not None:
                self._unwatch(profile)
                self.ops.kill(pid)
            self._pids.pop(profile, None)
            self._hung_since.pop(profile, None)
            self._hung_reported.discard(profile)
            self._want_hidden[profile] = was_hidden
            self.ensure_running(profile, visible=not was_hidden)
            return self._refresh(profile)

    def tick(self) -> None:
        """Keep hidden profiles hidden and autostart profiles running; refresh the cached state."""
        self._ticks += 1
        recheck = self._ticks % PID_RECHECK_TICKS == 0
        for profile in self.profiles():
            with self._lock:
                pid = self._pids.get(profile)
                known = pid is not None and (not recheck or bool(self.ops.windows(pid)))
            # finding Chrome's process takes a PowerShell call: never while holding the lock
            found = pid if known else self.ops.browser_pid(self.profile_dir(profile))
            with self._lock:
                self._apply_pid(profile, found)
                pid = self._pids.get(profile)
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
                self._watch(profile, pid)
                if self._want_hidden.get(profile, self.settings.browser.start_hidden):
                    for hwnd in self.ops.windows(pid):
                        if self.ops.visible(hwnd):
                            self.ops.hide(hwnd)
                self._check_hung(profile, pid)
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
        with self._lock:
            for profile in list(self._watched):
                self._unwatch(profile)

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
        self._apply_pid(profile, found)
        return found

    def _apply_pid(self, profile: str, found: int | None) -> None:
        if found is None:
            self._pids.pop(profile, None)
            self._unwatch(profile)
        else:
            self._pids[profile] = found

    def _watch(self, profile: str, pid: int) -> None:
        """Hide this profile's new windows the moment they appear, while it should be hidden."""
        if self._watched.get(profile) == pid:
            return
        self._unwatch(profile)
        self._watched[profile] = pid
        self.ops.watch(pid, lambda: self._want_hidden.get(profile, self.settings.browser.start_hidden))

    def _unwatch(self, profile: str) -> None:
        pid = self._watched.pop(profile, None)
        if pid is not None:
            self.ops.unwatch(pid)

    def _check_hung(self, profile: str, pid: int) -> None:
        hwnds = self.ops.windows(pid)
        if not any(self.ops.hung(h) for h in hwnds):
            self._hung_since.pop(profile, None)
            self._hung_reported.discard(profile)
            return
        since = self._hung_since.setdefault(profile, self._clock())
        if self._clock() - since >= HUNG_AFTER_S and profile not in self._hung_reported:
            self._hung_reported.add(profile)
            if self.on_hung is not None:
                try:
                    self.on_hung(profile)
                except Exception:
                    log.exception("on_hung callback")

    def _refresh(self, profile: str) -> ProfileState:
        pid = self._pids.get(profile)
        hwnds = self.ops.windows(pid) if pid is not None else []
        state = ProfileState(
            profile,
            pid is not None,
            any(self.ops.visible(h) for h in hwnds),
            profile in self._hung_reported,
        )
        self._state[profile] = state
        return state
