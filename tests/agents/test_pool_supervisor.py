"""Slot pool decisions and supervisor controls on the FakeAgentRunner."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from clipper.agents.runner import FakeAgentRunner, RateLimited, RunRequest, Say, Step
from clipper.clock import FakeClock
from clipper.core import Core
from clipper.db.models import AgentRequest, AgentSession
from clipper.events.types import Alert, UserChat
from clipper.services.control import set_control
from clipper.settings import Settings
from clipper.supervisor.pool import PoolLimits, QueuedView, RunningView, pick
from clipper.supervisor.router import P0, P1, P2, P3, RequestSpec
from clipper.supervisor.supervisor import Supervisor
from tests.factories import make_campaign

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def q(id_: int, prio: int, role: str = "campaign", cid: int | None = None, age: int = 0) -> QueuedView:
    return QueuedView(id_, prio, role, cid, T0 + timedelta(seconds=age))


def r(id_: int, prio: int, role: str = "campaign", cid: int | None = None) -> RunningView:
    return RunningView(id_, prio, role, cid)


L4 = PoolLimits(capacity=4, reserve_p0=True, p01_only=False, halted=False)


def test_priority_then_age() -> None:
    queued = [
        q(1, P3, "scout", age=0),
        q(2, P2, cid=1, age=5),
        q(3, P1, cid=2, age=9),
        q(4, P1, cid=3, age=1),
    ]
    assert pick(queued, [], L4).id == 4  # type: ignore[union-attr]


def test_one_slot_reserved_for_p0() -> None:
    running = [r(10, P2, cid=1), r(11, P2, cid=2), r(12, P3, "scout")]
    assert pick([q(1, P2, cid=3)], running, L4) is None  # 3 non-P0 running out of 4
    assert pick([q(1, P2, cid=3), q(2, P0, "director")], running, L4).id == 2  # type: ignore[union-attr]
    assert pick([q(2, P0, "director")], [*running, r(13, P0, "director")], L4) is None  # full


def test_shrinks_and_p01_only_and_halt() -> None:
    queued = [q(1, P2, cid=1), q(2, P1, cid=2)]
    assert (
        pick(queued, [r(9, P2, cid=9)], PoolLimits(2, True, False, False)) is None
    )  # 2 slots: 1 kept for P0
    assert pick(queued, [], PoolLimits(4, True, True, False)).id == 2  # type: ignore[union-attr]
    assert pick([q(1, P2, cid=1)], [], PoolLimits(4, True, True, False)) is None
    assert pick(queued, [], PoolLimits(4, True, False, True)) is None
    assert pick(queued, [], PoolLimits(0, True, False, False)) is None


def test_one_session_per_campaign_and_singletons() -> None:
    assert pick([q(1, P0, cid=7)], [r(9, P2, cid=7)], L4) is None
    assert pick([q(1, P3, "scout")], [r(9, P3, "scout")], L4) is None
    assert pick([q(1, P3, "scout"), q(2, P2, cid=8)], [r(9, P3, "scout")], L4).id == 2  # type: ignore[union-attr]


@pytest.fixture
def env(settings: Settings) -> Iterator[tuple[Core, FakeAgentRunner, Supervisor, FakeClock]]:
    clock = FakeClock(T0)
    core = Core.create(settings, fakes=True, clock=clock)
    runner = FakeAgentRunner(core, {})
    yield core, runner, Supervisor(core, runner), clock
    core.close()


async def test_events_merge_while_queued(env: tuple[Core, FakeAgentRunner, Supervisor, FakeClock]) -> None:
    core, _runner, sup, _clock = env
    camp = make_campaign(core.db)
    assert camp.id is not None
    a = sup.enqueue(
        RequestSpec(P2, "campaign", "job.done", camp.id, {"id": 1, "type": "job.done", "payload": {}})
    )
    b = sup.enqueue(
        RequestSpec(P0, "campaign", "note.added", camp.id, {"id": 2, "type": "note.added", "payload": {}})
    )
    assert a == b
    with core.db.read() as s:
        req = s.get(AgentRequest, a)
    assert (
        req is not None and req.merged_count == 1 and req.priority == P0 and len(req.payload["events"]) == 2
    )


async def test_usage_shrinks_pool_and_rate_limit_pauses_then_resumes(
    env: tuple[Core, FakeAgentRunner, Supervisor, FakeClock],
) -> None:
    core, runner, sup, clock = env
    core.usage.record(utilization=0.85, resets_at=T0 + timedelta(hours=2), rate_limited=False)
    assert sup.limits().capacity == 2
    core.usage.record(utilization=0.95, resets_at=T0 + timedelta(hours=2), rate_limited=False)
    assert sup.limits().p01_only

    calls: list[int] = []

    def director(req: RunRequest) -> list[Step]:
        calls.append(1)
        return [RateLimited(resets_in_s=600)] if len(calls) == 1 else [Say("hello again")]

    runner.scripts["director"] = director
    alerts: list[str] = []
    core.bus.add_listener(lambda e: alerts.append(e.payload["text"]), types=["alert"])
    await core.bus.apublish(UserChat(text="how much today?"))
    await sup.run_until_idle()
    with core.db.read() as s:
        req = s.exec(select(AgentRequest).where(AgentRequest.role == "director")).one()
    assert req.status == "queued" and sup.limits().halted  # paused until the reset
    assert any("usage limit reached" in a for a in alerts)
    clock.advance(seconds=601)  # after the reset the window is fresh again
    assert not sup.limits().halted
    await sup.run_until_idle()
    with core.db.read() as s:
        req = s.exec(select(AgentRequest).where(AgentRequest.role == "director")).one()
    assert req.status == "done" and len(calls) == 2


async def test_kill_switch_and_pause_stop_dispatch(
    env: tuple[Core, FakeAgentRunner, Supervisor, FakeClock],
) -> None:
    core, runner, sup, _clock = env
    runner.scripts["director"] = lambda req: [Say("hi")]
    set_control(core.db, "paused", True)
    await core.bus.apublish(UserChat(text="status?"))
    await sup.run_until_idle()
    assert runner.runs == []
    set_control(core.db, "paused", False)
    set_control(core.db, "kill_switch", True)
    await sup.run_until_idle()
    assert runner.runs == []
    set_control(core.db, "kill_switch", False)
    await sup.run_until_idle()
    assert len(runner.runs) == 1


async def test_director_keeps_one_conversation(
    env: tuple[Core, FakeAgentRunner, Supervisor, FakeClock],
) -> None:
    core, runner, sup, _clock = env
    runner.scripts["director"] = lambda req: [Say("ok")]
    for text in ("first", "second"):
        await core.bus.apublish(UserChat(text=text))
        await sup.run_until_idle()
    with core.db.read() as s:
        sessions = s.exec(select(AgentSession).where(AgentSession.role == "director")).all()
    assert len(sessions) == 1
    assert (
        runner.runs[1].resume == runner.runs[0].resume or runner.runs[1].resume == sessions[0].sdk_session_id
    )
    assert "User (dashboard): second" in runner.runs[1].prompt


async def test_watchdog_nudges_idle_campaigns(
    env: tuple[Core, FakeAgentRunner, Supervisor, FakeClock],
) -> None:
    core, runner, sup, clock = env
    runner.scripts["campaign"] = lambda req: [Say("on it")]
    camp = make_campaign(core.db)
    assert camp.id is not None
    sup.enqueue(
        RequestSpec(
            P2,
            "campaign",
            "campaign.taken",
            camp.id,
            {"id": 0, "type": "campaign.taken", "payload": {"campaign_id": camp.id}},
        )
    )
    await sup.run_until_idle()
    assert sup.watchdog() == []
    clock.advance(minutes=181)
    assert sup.watchdog() == [camp.id]
    assert sup.watchdog() == []  # not again until another stale period
    await sup.run_until_idle()
    assert runner.runs[-1].kind == "watchdog.nudge" and "Status check" in runner.runs[-1].prompt


async def test_daily_run_cap_keeps_p0_p1_only(
    env: tuple[Core, FakeAgentRunner, Supervisor, FakeClock], settings: Settings
) -> None:
    core, runner, sup, _clock = env
    object.__setattr__(core.settings.usage, "daily_agent_run_cap", 1)
    runner.scripts["scout"] = lambda req: [Say("scouted")]
    runner.scripts["director"] = lambda req: [Say("hi")]
    sup.enqueue(
        RequestSpec(
            P3,
            "scout",
            "trigger.fired",
            None,
            {"id": 1, "type": "trigger.fired", "payload": {"name": "scout"}},
        )
    )
    await sup.run_until_idle()
    sup.enqueue(
        RequestSpec(
            P3,
            "scout",
            "trigger.fired",
            None,
            {"id": 2, "type": "trigger.fired", "payload": {"name": "scout"}},
        )
    )
    await core.bus.apublish(UserChat(text="hi"))
    await sup.run_until_idle()
    assert [r.role for r in runner.runs] == ["scout", "director"]
    await core.bus.apublish(Alert(level="info", text="noise"))  # unrouted events are ignored
    await sup.run_until_idle()
