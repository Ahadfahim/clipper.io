"""App-wide control state in the ``kv`` table: dry run, pause, kill switch, slot override.

Reads are cheap (one primary-key lookup) so guard hooks can re-check on every tool call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clipper.clock import utcnow
from clipper.db.engine import Database, WriteTx
from clipper.db.models import KV
from clipper.events.types import ControlChanged

DRY_RUN = "dry_run"
PAUSED = "paused"
KILL_SWITCH = "kill_switch"
SLOTS = "slots"
AUTO_APPROVE_TIER = "auto_approve_tier"


@dataclass(frozen=True)
class ControlState:
    dry_run: bool
    paused: bool
    kill_switch: bool
    slots: int | None
    auto_approve_tier: int | None


def kv_get(db: Database, key: str, default: Any = None) -> Any:
    with db.read() as s:
        row = s.get(KV, key)
        return default if row is None else row.value_json


def kv_set_tx(tx: WriteTx, key: str, value: Any) -> None:
    row = tx.session.get(KV, key)
    if row is None:
        row = KV(key=key, value_json=value)
    else:
        row.value_json = value
        row.updated_at = utcnow()
    tx.add(row)


def read_control(db: Database) -> ControlState:
    with db.read() as s:
        values = {k: (s.get(KV, k)) for k in (DRY_RUN, PAUSED, KILL_SWITCH, SLOTS, AUTO_APPROVE_TIER)}

    def val(key: str, default: Any) -> Any:
        row = values[key]
        return default if row is None or row.value_json is None else row.value_json

    return ControlState(
        dry_run=bool(val(DRY_RUN, True)),
        paused=bool(val(PAUSED, False)),
        kill_switch=bool(val(KILL_SWITCH, False)),
        slots=val(SLOTS, None),
        auto_approve_tier=val(AUTO_APPROVE_TIER, None),
    )


def configured_slots(db: Database, setting: int) -> int:
    """The slot count in force: the app's override if set, else ``agents.slots`` (0 = unlimited)."""
    override = read_control(db).slots
    return setting if override is None else int(override)


def set_control(db: Database, key: str, value: Any, *, by: str = "user", via: str = "app") -> None:
    if key not in (DRY_RUN, PAUSED, KILL_SWITCH, SLOTS, AUTO_APPROVE_TIER):
        raise KeyError(key)
    if (
        key == SLOTS
        and value is not None
        and (isinstance(value, bool) or not isinstance(value, int) or value < 0)
    ):
        raise ValueError("slots must be a whole number ≥ 0 (0 = unlimited) or null for the settings value")

    def job(tx: WriteTx) -> None:
        kv_set_tx(tx, key, value)
        tx.publish(ControlChanged(key=key, value=value, by=by, via=via))  # type: ignore[arg-type]

    db.write(job)
