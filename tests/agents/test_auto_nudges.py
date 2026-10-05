"""Clipper's own checks: a hung turn is restarted and a stalled job retried, a few times, and then it
stops and tells you once. Nothing happens while paused."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from clipper.agents.runner import FakeAgentRunner
from clipper.clock import FakeClock
from clipper.core import Core
from clipper.db.engine import WriteTx
from clipper.db.models import AgentRequest, Job
from clipper.services.control import set_control
from clipper.settings import Settings
from clipper.supervisor import supervisor as supervisor_module
from clipper.supervisor.auto import run_auto_checks
from clipper.supervisor.stalls import Stall
from clipper.supervisor.supervisor import Supervisor
from tests.agents.test_nudges import HangingRunner
from tests.conftest import tune
from tests.factories import make_campaign

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
Env = tuple[Core, FakeAgentRunner, Supervisor, FakeClock]


@pytest.fixture
def env(settings: Settings) -> Iterator[Env]:
    clock = FakeClock(T0)
    core = Core.create(settings, fakes=True, clock=clock)
    runner = FakeAgentRunner(core, {})
    yield core, runner, Supervisor(core, runner), clock
    core.close()


def _alerts(core: Core) -> list[dict[str, object]]:
    return [e.payload for e in core.bus.latest(50, ["alert"]) if e.payload.get("source") == "stalls"]


def _stalled_job(core: Core, *, quiet_min: float = 40, **inp: object) -> int:
    """A job that says it is running and hasn't moved for ``quiet_min`` minutes."""

    def job(tx: WriteTx) -> int:
        row = Job(
            kind="dummy",
            input_json=dict(inp) or {"n": 1},
            status="running",
            progress=0.3,
            created_at=core.clock.now() - timedelta(minutes=quiet_min + 1),
            started_at=core.clock.now() - timedelta(minutes=quiet_min + 1),
            progress_at=core.clock.now() - timedelta(minutes=quiet_min),
        )
        tx.add(row)
        tx.flush()
        assert row.id is not None
        return row.id

    return core.db.write(job)


# ---------------------------------------------------------------- jobs


async def test_a_stalled_job_is_cancelled_and_retried_by_itself(env: Env) -> None:
    core, _, sup, _ = env
    core.jobs.register("dummy", lambda ctx, data: {}, "cpu")
    old = _stalled_job(core)
    done = await run_auto_checks(core, sup)
    assert len(done) == 1 and done[0].startswith(f"job_stalled:{old}: Cancelled the job and queued it again")
    with core.db.read() as s:
        rows = {j.id: j for j in s.exec(select(Job)).all()}
    assert rows[old].status == "cancelled" and sorted(j.status for j in rows.values()) == [
        "cancelled",
        "queued",
    ]
    assert await run_auto_checks(core, sup) == []  # the new job is fresh: nothing stalled any more
    assert _alerts(core) == []
    sent = [e.payload for e in core.bus.latest(10, ["nudge.sent"])]
    assert (
        sent
        and sent[-1]["auto"] is True
        and sent[-1]["action"] == "cancel_retry"
        and sent[-1]["by"] == "supervisor"
    )


async def test_when_a_job_has_been_retried_too_often_it_stops_and_tells_you_once(env: Env) -> None:
    core, _, sup, clock = env
    core.jobs.register("dummy", lambda ctx, data: {}, "cpu")
    last = _stalled_job(core)
    for _ in range(3):  # three automatic retries, each one stalls again
        await run_auto_checks(core, sup)
        with core.db.read() as s:
            newest = s.exec(select(Job).order_by(Job.id.desc())).first()  # type: ignore[attr-defined]
        assert newest is not None and newest.id != last
        last = newest.id or 0

        def stall(tx: WriteTx, job_id: int = last) -> None:
            row = tx.session.get(Job, job_id)
            assert row is not None
            row.status, row.progress_at = "running", clock.now() - timedelta(minutes=40)
            tx.add(row)

        core.db.write(stall)
    said = await run_auto_checks(core, sup)
    assert said == [f"job_stalled:{last}: told you"]
    (alert,) = _alerts(core)
    assert alert["stall_key"] == f"job_stalled:{last}" and "tried 4 times already" in str(alert["text"])
    assert "It needs you." in str(alert["text"])
    assert await run_auto_checks(core, sup) == []  # once


async def test_with_the_automatic_retry_off_it_only_tells_you(env: Env) -> None:
    core, _, sup, _ = env
    tune(core, "stalls", auto_retry_stalled_job=False)
    core.jobs.register("dummy", lambda ctx, data: {}, "cpu")
    job_id = _stalled_job(core)
    assert await run_auto_checks(core, sup) == [f"job_stalled:{job_id}: told you"]
    with core.db.read() as s:
        assert s.get(Job, job_id).status == "running"  # type: ignore[union-attr]
    assert len(_alerts(core)) == 1 and _alerts(core)[0]["campaign_id"] is None


async def test_nothing_happens_while_paused_or_with_the_kill_switch(env: Env) -> None:
    core, _, sup, _ = env
    core.jobs.register("dummy", lambda ctx, data: {}, "cpu")
    job_id = _stalled_job(core)
    set_control(core.db, "paused", True)
    assert await run_auto_checks(core, sup) == []
    set_control(core.db, "paused", False)
    set_control(core.db, "kill_switch", True)
    assert await run_auto_checks(core, sup) == []
    with core.db.read() as s:
        assert s.get(Job, job_id).status == "running"  # type: ignore[union-attr]
    set_control(core.db, "kill_switch", False)
    assert len(await run_auto_checks(core, sup)) == 1


# ---------------------------------------------------------------- things Clipper can't fix by itself


async def test_a_request_that_cannot_start_is_reported_once_and_not_duplicated_in_needs_you(env: Env) -> None:
    from clipper.api import needs_you

    core, _, sup, clock = env
    camp = make_campaign(core.db)
    assert camp.id is not None

    def queued(tx: WriteTx) -> None:
        tx.add(
            AgentRequest(
                priority=2, kind="job.done", role="campaign", campaign_id=camp.id, status="queued",
                queued_at=clock.now() - timedelta(minutes=12),
                waiting_reason="Claude usage is at 92%: only P0 and P1 requests start.",
            )
        )  # fmt: skip

    core.db.write(queued)
    said = await run_auto_checks(core, sup)
    assert len(said) == 1 and said[0].endswith("told you")
    (alert,) = _alerts(core)
    assert alert["stall_key"].startswith("request_blocked:") and alert["campaign_id"] == camp.id  # type: ignore[union-attr]
    assert "Claude usage is at 92%" not in str(
        alert["text"]
    )  # the evidence is for the item, the alert is the sentence
    assert await run_auto_checks(core, sup) == []
    kinds = [i.kind for i in needs_you.build(core)]
    assert "stuck" in kinds and "alert" not in kinds  # the stuck item stands for the alert


async def test_a_stall_that_stays_gone_starts_from_zero(env: Env) -> None:
    core, _, sup, clock = env
    tune(core, "stalls", auto_retry_stalled_job=False)
    core.jobs.register("dummy", lambda ctx, data: {}, "cpu")
    job_id = _stalled_job(core)
    await run_auto_checks(core, sup)
    assert len(_alerts(core)) == 1

    def finish(tx: WriteTx) -> None:
        row = tx.session.get(Job, job_id)
        assert row is not None
        row.status = "done"
        tx.add(row)

    core.db.write(finish)
    await run_auto_checks(core, sup)  # gone: remembered for a while
    clock.advance(minutes=7 * 60)
    await run_auto_checks(core, sup)  # gone for 6 hours: forgotten
    again = _stalled_job(core, n=2)
    assert again != job_id
    await run_auto_checks(core, sup)
    assert len(_alerts(core)) == 2  # a new stall is told again


# ---------------------------------------------------------------- a hung turn


async def test_a_hung_turn_is_restarted_after_the_wait_and_then_it_tells_you(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(supervisor_module, "RESTART_WAIT_S", 0.2)
    clock = FakeClock(T0)
    core = Core.create(settings, fakes=True, clock=clock)
    tune(core, "stalls", max_auto_nudges=1)
    runner = HangingRunner(obeys=True)
    sup = Supervisor(core, runner)  # type: ignore[arg-type]
    try:
        camp = make_campaign(core.db)
        assert camp.id is not None
        core.nudge.nudge(campaign_id=camp.id, text="start")
        sup.attach()
        await asyncio.sleep(0.05)
        await sup.process_inbox()
        await sup.dispatch()
        await asyncio.wait_for(runner.started.wait(), timeout=5)
        entry = next(iter(sup._running.values()))
        assert await run_auto_checks(core, sup) == []  # just started: not quiet yet
        clock.advance(minutes=20)  # quiet for 20 minutes: hung (10), but not yet old enough to restart (30)
        assert await run_auto_checks(core, sup) == []
        assert _alerts(core) == []  # an automatic restart is still to come: nothing to tell yet
        clock.advance(minutes=15)
        said = await run_auto_checks(core, sup)
        assert len(said) == 1 and "Restarted the turn" in said[0]
        await asyncio.gather(entry.task, return_exceptions=True)  # type: ignore[arg-type]
        await asyncio.sleep(0.05)
        await sup.process_inbox()
        queued = [r for r in _requests(core) if r.status == "queued"]
        assert (
            len(queued) == 1 and queued[0].priority == 2 and queued[0].kind == "user.nudge"
        )  # automatic: P2
        # it hangs again: the one automatic restart is spent, so it tells you
        runner.stop = asyncio.Event()
        runner.started = asyncio.Event()
        await sup.dispatch()
        await asyncio.wait_for(runner.started.wait(), timeout=5)
        clock.advance(minutes=45)
        said = await run_auto_checks(core, sup)
        assert len(said) == 1 and said[0].endswith("told you")
        (alert,) = _alerts(core)
        assert "tried 1 time by itself" in str(alert["text"]) and str(alert["stall_key"]).startswith(
            "session_hung:"
        )
    finally:
        runner.stop.set()
        for e in list(sup._running.values()):
            if e.task:
                e.task.cancel()
        await asyncio.sleep(0.05)
        core.close()


def _requests(core: Core) -> list[AgentRequest]:
    with core.db.read() as s:
        return list(s.exec(select(AgentRequest).order_by(AgentRequest.id)).all())  # type: ignore[arg-type]


def test_the_detector_and_the_automatic_rules_agree() -> None:
    from clipper.settings import StallSettings
    from clipper.supervisor.auto import automatic_action, has_automatic_action

    cfg = StallSettings()
    hung = Stall(
        key="session_hung:1",
        kind="session_hung",
        since=T0,
        summary="s",
        evidence=[],
        actions=["restart_turn", "nudge"],
    )
    assert automatic_action(hung, cfg, T0 + timedelta(minutes=29)) is None
    assert automatic_action(hung, cfg, T0 + timedelta(minutes=30)) == "restart_turn"
    off = StallSettings(auto_restart_hung_min=0)
    assert automatic_action(hung, off, T0 + timedelta(hours=9)) is None and not has_automatic_action(
        hung, off
    )
    waiting = Stall(
        key="request_blocked:2",
        kind="request_blocked",
        since=T0,
        summary="s",
        evidence=[],
        actions=["run_now"],
    )
    assert automatic_action(waiting, cfg, T0 + timedelta(hours=9)) is None and not has_automatic_action(
        waiting, cfg
    )
