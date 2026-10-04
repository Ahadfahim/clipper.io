from __future__ import annotations

import asyncio
import threading

import pytest

from clipper.db.engine import Database, WriteTx
from clipper.db.models import KV, Event
from clipper.events.bus import EventBus, EventEnvelope
from clipper.events.types import Alert, JobDone


def _incr(tx: WriteTx) -> int:
    row = tx.session.get(KV, "counter")
    value = 0 if row is None else int(row.value_json)
    if row is None:
        row = KV(key="counter", value_json=value + 1)
    else:
        row.value_json = value + 1
    tx.add(row)
    return value + 1


def test_writes_are_serialized_under_concurrency(db: Database) -> None:
    threads = 16
    per_thread = 40
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(per_thread):
                db.write(_incr)
        except BaseException as exc:
            errors.append(exc)

    pool = [threading.Thread(target=worker) for _ in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    assert not errors
    with db.read() as s:
        row = s.get(KV, "counter")
        assert row is not None
        assert row.value_json == threads * per_thread


async def test_async_writes_from_many_tasks(db: Database) -> None:
    results = await asyncio.gather(*(db.awrite(_incr) for _ in range(100)))
    assert sorted(results) == list(range(1, 101))


def test_failed_job_rolls_back_and_emits_nothing(db: Database, bus: EventBus) -> None:
    seen: list[EventEnvelope] = []
    bus.add_listener(seen.append)

    def bad(tx: WriteTx) -> None:
        tx.add(KV(key="half-written", value_json=1))
        tx.publish(Alert(level="info", text="never committed"))
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        db.write(bad)
    with db.read() as s:
        assert s.get(KV, "half-written") is None
        assert s.exec(__import__("sqlmodel").select(Event)).all() == []
    assert seen == []
    # the writer keeps working after a failure
    assert db.write(_incr) == 1


def test_nested_write_from_writer_thread_is_refused(db: Database) -> None:
    def nested(tx: WriteTx) -> None:
        db.write(_incr)

    with pytest.raises(RuntimeError, match="nested write"):
        db.write(nested)


def test_readonly_connection_cannot_write(db: Database) -> None:
    import sqlite3

    conn = db.readonly()
    try:
        assert conn.execute("select count(*) from marketplace").fetchone()[0] == 2
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("insert into kv(key, value_json, updated_at) values ('x', '1', '2026-01-01')")
    finally:
        conn.close()


async def test_event_bus_persists_and_delivers(db: Database, bus: EventBus) -> None:
    sub = bus.subscribe(["job.*"])
    everything = bus.subscribe()
    listener_seen: list[str] = []
    bus.add_listener(lambda env: listener_seen.append(env.type), types=["alert"])

    env = await bus.apublish(JobDone(job_id=7, kind="download", status="done", campaign_id=3))
    await bus.apublish(Alert(level="warning", text="disk low"))

    got = await sub.get(timeout=2)
    assert got is not None
    assert got.type == "job.done"
    assert got.entity == "job"
    assert got.entity_id == "7"
    typed = got.typed()
    assert isinstance(typed, JobDone)
    assert typed.campaign_id == 3
    assert await sub.get(timeout=0.2) is None  # alert filtered out

    first = await everything.get(timeout=2)
    second = await everything.get(timeout=2)
    assert first is not None and second is not None
    assert [first.type, second.type] == ["job.done", "alert"]
    assert listener_seen == ["alert"]

    history = bus.since(0)
    assert [h.id for h in history] == [env.id, env.id + 1]
    sub.close()
    everything.close()


async def test_events_emitted_inside_a_write_are_delivered_after_commit(db: Database, bus: EventBus) -> None:
    sub = bus.subscribe(["alert"])

    def job(tx: WriteTx) -> int:
        tx.add(KV(key="k", value_json=1))
        tx.publish(Alert(level="info", text="with state change"))
        return 1

    await db.awrite(job)
    env = await sub.get(timeout=2)
    assert env is not None
    assert env.payload["text"] == "with state change"
    sub.close()
