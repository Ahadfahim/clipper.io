"""Clipper's own checks for things that got stuck: a few automatic actions, then it stops and asks you.

Each tick the detector (``stalls.py``) is read. For a stall that has an automatic action, Clipper does
it, at most ``stalls.max_auto_nudges`` times (a hung turn is restarted after ``auto_restart_hung_min``
minutes of quiet; a stalled job is cancelled and retried once if ``auto_retry_stalled_job``). When
the actions are used up, or there never was one (a request that can't start, a late post), it says so
once, in an alert that Discord shows with a button. Nothing runs while Clipper is paused or the kill
switch is on, and an automatic nudge is only a P2 request: it waits behind your own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from clipper.db.engine import WriteTx
from clipper.services.base import ServiceError
from clipper.services.control import kv_get, kv_set_tx, read_control
from clipper.supervisor.stall_actions import run_action
from clipper.supervisor.stalls import Stall, build_snapshot, detect_stalls

if TYPE_CHECKING:
    from clipper.core import Core
    from clipper.settings import StallSettings
    from clipper.supervisor.supervisor import Supervisor

log = logging.getLogger(__name__)

KV_KEY = "stalls.auto"
FORGET_AFTER = timedelta(hours=6)  # a stall that stays gone this long starts from zero next time


@dataclass
class AutoState:
    count: int = 0  # automatic actions taken for this stall
    last_action: str | None = None  # when
    last_seen: str = ""  # the last tick that found it
    alerted: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "last_action": self.last_action,
            "last_seen": self.last_seen,
            "alerted": self.alerted,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> AutoState:
        return cls(
            int(raw.get("count", 0)),
            raw.get("last_action"),
            str(raw.get("last_seen", "")),
            bool(raw.get("alerted", False)),
        )


def automatic_action(stall: Stall, cfg: StallSettings, now: datetime) -> str | None:
    """The action Clipper may take by itself for this stall right now, if any."""
    if stall.kind == "session_hung" and cfg.auto_restart_hung_min > 0:
        quiet_for = now - stall.since
        if quiet_for >= timedelta(minutes=cfg.auto_restart_hung_min):
            return "restart_turn"
    if stall.kind == "job_stalled" and cfg.auto_retry_stalled_job:
        return "cancel_retry"
    return None


def has_automatic_action(stall: Stall, cfg: StallSettings) -> bool:
    """Whether Clipper would ever act on this kind by itself (now or after waiting longer)."""
    return (stall.kind == "session_hung" and cfg.auto_restart_hung_min > 0) or (
        stall.kind == "job_stalled" and cfg.auto_retry_stalled_job
    )


def _load(core: Core) -> dict[str, AutoState]:
    raw: Any = kv_get(core.db, KV_KEY, None)
    if not isinstance(raw, dict):
        return {}
    items = cast(dict[str, Any], raw)
    return {k: AutoState.from_json(cast(dict[str, Any], v)) for k, v in items.items() if isinstance(v, dict)}


def _save(core: Core, states: dict[str, AutoState]) -> None:
    payload = {k: v.as_json() for k, v in states.items()}

    def job(tx: WriteTx) -> None:
        kv_set_tx(tx, KV_KEY, payload)

    core.db.write(job)


async def run_auto_checks(core: Core, sup: Supervisor) -> list[str]:
    """One pass. Returns a sentence for each thing it did (for tests and the log)."""
    ctl = read_control(core.db)
    if ctl.paused or ctl.kill_switch:
        return []
    cfg = core.settings.stalls
    now = core.clock.now()
    stalls = detect_stalls(build_snapshot(core), cfg)
    states = _load(core)
    done: list[str] = []
    live = {s.key for s in stalls}
    for key in [k for k in states if k not in live]:
        last_seen = states[key].last_seen
        if not last_seen or now - datetime.fromisoformat(last_seen) >= FORGET_AFTER:
            del states[key]  # gone for a long while: a new stall of this kind starts from zero
    for stall in stalls:
        st = states.setdefault(stall.key, AutoState())
        st.last_seen = now.isoformat()
        action = automatic_action(stall, cfg, now)
        spent = st.count >= cfg.max_auto_nudges
        why = ""
        if action is not None and not spent:
            try:
                said = await run_action(core, sup, stall, action, by="supervisor", auto=True)
            except ServiceError as exc:
                # it can't be done (a job already retried too often, an agent that is gone): stop and say so
                log.info("automatic %s for %s refused: %s", action, stall.key, exc)
                st.count = max(st.count, cfg.max_auto_nudges)
                why = f" ({exc})"
            else:
                st.count += 1
                st.last_action = now.isoformat()
                done.append(f"{stall.key}: {said}")
                continue
        waiting_for_its_time = has_automatic_action(stall, cfg) and st.count < cfg.max_auto_nudges
        if not waiting_for_its_time and not st.alerted:
            st.alerted = True
            tried = (
                f" Clipper tried {st.count} time{'s' if st.count != 1 else ''} by itself." if st.count else ""
            )
            core.notify.alert(
                "warning",
                f"{stall.summary}{tried}{why} It needs you.",
                source="stalls",
                campaign_id=stall.campaign_id,
                stall_key=stall.key,
            )
            done.append(f"{stall.key}: told you")
    _save(core, states)
    return done
