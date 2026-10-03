from __future__ import annotations

import pytest

from clipper.db.engine import Database, WriteTx
from clipper.db.models import Analysis, Clip
from clipper.events.bus import EventBus, EventEnvelope
from clipper.media.edl.ops import EditError
from clipper.media.edl.schema import Edl
from clipper.media.edl.service import EdlService, LockedError
from tests.factories import make_campaign, make_clip, make_source
from tests.media.conftest import FIXTURE_SILENCES


def _clip(db: Database) -> int:
    camp = make_campaign(db)
    assert camp.id is not None
    src = make_source(db, camp.id)
    assert src.id is not None
    clip = make_clip(db, camp.id, src.id)
    assert clip.id is not None
    sid = src.id

    def analysis(tx: WriteTx) -> None:
        tx.add(Analysis(source_id=sid, signals_json={"silences": [list(s) for s in FIXTURE_SILENCES]}))

    db.write(analysis)
    return clip.id


def test_ops_are_logged_broadcast_and_undoable(db: Database, bus: EventBus, edl: Edl) -> None:
    seen: list[EventEnvelope] = []
    bus.add_listener(seen.append, types=["edit.op"])
    svc = EdlService(db)
    clip_id = _clip(db)
    svc.init(clip_id, edl)
    a = svc.apply(clip_id, "trim", {"start": 1.0, "end": 9.0}, actor="session:3", reason="tighter start")
    b = svc.apply(
        clip_id, "remove_silences", {"level": "medium"}, actor="session:3"
    )  # silences come from analysis
    c = svc.apply(clip_id, "set_hook", {"type": "text", "text": "Wait for it"}, actor="user")
    cur, version, _ = svc.get(clip_id)
    assert version == 4
    assert cur.duration < 8.0
    assert [e.payload["op"] for e in seen] == ["init", "trim", "remove_silences", "set_hook"]
    assert seen[1].payload["actor"] == "session:3" and seen[1].payload["reason"] == "tighter start"

    undone, skipped = svc.undo(clip_id, b.op_id, actor="user")
    assert skipped == []
    assert undone.duration == pytest.approx(8.0)
    assert undone.overlays and undone.overlays[0].props["text"] == "Wait for it"  # later op kept
    redone, _ = svc.undo(clip_id, b.op_id, actor="user")  # undo again = redo
    assert redone.duration == pytest.approx(cur.duration)
    hist = svc.history(clip_id)
    assert [h.op for h in hist] == ["init", "trim", "remove_silences", "set_hook"]
    assert a.op_id < c.op_id


def test_take_over_blocks_agent_until_hand_back(db: Database, edl: Edl) -> None:
    svc = EdlService(db)
    clip_id = _clip(db)
    svc.init(clip_id, edl)
    svc.take_over(clip_id)
    with pytest.raises(LockedError):
        svc.apply(clip_id, "trim", {"start": 1.0, "end": 9.0}, actor="session:3")
    svc.apply(clip_id, "trim", {"start": 1.0, "end": 9.0}, actor="user")  # the user can edit
    svc.hand_back(clip_id)
    svc.apply(clip_id, "trim", {"start": 2.0, "end": 9.0}, actor="session:3")
    assert svc.get(clip_id)[0].duration == pytest.approx(7.0)


def test_invalid_op_changes_nothing(db: Database, edl: Edl) -> None:
    svc = EdlService(db)
    clip_id = _clip(db)
    svc.init(clip_id, edl)
    with pytest.raises(EditError):
        svc.apply(clip_id, "delete_range", {"start": 0.0, "end": 10.0}, actor="user")
    assert svc.get(clip_id)[1] == 1
    assert len(svc.history(clip_id)) == 1


def test_make_variant(db: Database, edl: Edl) -> None:
    svc = EdlService(db)
    clip_id = _clip(db)
    svc.init(clip_id, edl)
    vid = svc.make_variant(
        clip_id,
        [{"op": "set_hook", "args": {"type": "cold_open", "start": 6.2, "end": 7.4}}],
        label="cold open",
        actor="session:3",
    )
    variant, _, _ = svc.get(vid)
    assert variant.variant == "cold open"
    assert variant.segments[0].kind == "teaser"
    with db.read() as s:
        row = s.get(Clip, vid)
        assert row is not None and row.variant_of == clip_id and row.variant_label == "cold open"
