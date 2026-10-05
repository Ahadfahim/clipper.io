"""Nudging a stuck agent: who it reaches and how soon, what it says, why a request waits, and the repairs
(restart a hung turn, release a dead lease, run now)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlmodel import select

from clipper.agents.runner import FakeAgentRunner, RunOutcome, RunRequest, Say
from clipper.clock import FakeClock
from clipper.core import Core
from clipper.db.engine import WriteTx
from clipper.db.models import AgentRequest, AgentSession
from clipper.services.base import ServiceError
from clipper.services.control import set_control
from clipper.settings import Settings
from clipper.supervisor import supervisor as supervisor_module
from clipper.supervisor.messages import describe
from clipper.supervisor.pool import PoolLimits, QueuedView, RunningView, explain_wait
from clipper.supervisor.router import P0, P2
from clipper.supervisor.stall_actions import run_action
from clipper.supervisor.stalls import Stall
from clipper.supervisor.supervisor import Running, Supervisor
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


def _requests(core: Core) -> list[AgentRequest]:
    with core.db.read() as s:
        return list(s.exec(select(AgentRequest).order_by(AgentRequest.id)).all())  # type: ignore[arg-type]


# ---------------------------------------------------------------- who it reaches, and what it says


async def test_a_nudge_resumes_the_campaigns_agent_first_in_line_with_your_words(env: Env) -> None:
    core, runner, sup, _ = env
    camp = make_campaign(core.db)
    assert camp.id is not None
    runner.scripts["campaign"] = lambda req: [Say("ok")]
    out = core.nudge.nudge(
        campaign_id=camp.id,
        text="Try the second source",
        stall_key="waiting_on_nothing:1",
        summary="Campaign 1 is waiting on nothing.",
        evidence="The agent finished its turn 45 min ago.",
    )
    assert out["role"] == "campaign" and out["event_id"] > 0
    await sup.run_until_idle()
    (req,) = _requests(core)
    assert req.kind == "user.nudge" and req.priority == P0 and req.status == "done"
    prompt = runner.runs[0].prompt
    assert "The user nudged you: Try the second source" in prompt
    assert "What looks stuck: Campaign 1 is waiting on nothing." in prompt
    assert "Evidence: The agent finished its turn 45 min ago." in prompt
    assert "Check state.get_campaign" in prompt


async def test_without_a_message_it_says_you_look_stuck_and_an_automatic_check_waits_its_turn(
    env: Env,
) -> None:
    core, runner, sup, _ = env
    camp = make_campaign(core.db)
    assert camp.id is not None
    runner.scripts["campaign"] = lambda req: [Say("ok")]
    core.nudge.nudge(campaign_id=camp.id)
    core.nudge.nudge(campaign_id=camp.id, auto=True, by="supervisor")
    sup.attach()
    await asyncio.sleep(0.05)
    await sup.process_inbox()
    (req,) = _requests(core)  # both merge into one request, which keeps the better priority
    assert req.priority == P0 and req.merged_count == 1
    await sup.run_until_idle()
    assert "The user nudged you: You look stuck." in runner.runs[0].prompt
    assert "Automatic check: You look stuck." in runner.runs[0].prompt


async def test_automatic_nudges_are_p2_and_other_roles_get_a_fresh_run(env: Env) -> None:
    core, runner, sup, _ = env
    camp = make_campaign(core.db)
    assert camp.id is not None
    set_control(core.db, "paused", True)  # keep them queued so the priorities can be read
    core.nudge.nudge(campaign_id=camp.id, auto=True, by="supervisor")
    core.nudge.nudge(role="director", text="Are you there?")
    core.nudge.nudge(role="scout", auto=True, by="supervisor")
    sup.attach()
    await asyncio.sleep(0.05)
    await sup.process_inbox()
    got = {(r.role, r.priority) for r in _requests(core)}
    assert got == {("campaign", P2), ("director", P0), ("scout", P2)}
    assert runner.runs == []


def test_what_the_agent_reads() -> None:
    nudge = {"type": "user.nudge", "payload": {"text": "", "role": "scout", "summary": "", "evidence": ""}}
    assert (
        describe(nudge)
        == "The user nudged you: You look stuck. Work out where you stopped, then carry on or ask the user."
    )
    auto = {
        "type": "user.nudge",
        "payload": {"auto": True, "text": "", "role": "campaign", "summary": "Job 4 hasn't moved."},
    }
    assert describe(auto).startswith("Automatic check: You look stuck. What looks stuck: Job 4 hasn't moved.")


def test_a_nudge_must_name_something_real(env: Env) -> None:
    core, _, _, _ = env
    camp = make_campaign(core.db, status="ended")
    assert camp.id is not None
    with pytest.raises(ServiceError, match="nothing left to nudge"):
        core.nudge.nudge(campaign_id=camp.id)
    with pytest.raises(ServiceError, match="not found"):
        core.nudge.nudge(campaign_id=999)
    with pytest.raises(ServiceError, match="session 99 not found"):
        core.nudge.nudge(session_id=99)
    with pytest.raises(ServiceError, match="name a session"):
        core.nudge.nudge()
    live = make_campaign(core.db)
    with pytest.raises(ServiceError, match="under 1000"):
        core.nudge.nudge(campaign_id=live.id, text="x" * 1001)


def test_a_nudge_for_a_session_goes_to_its_role_and_campaign(env: Env) -> None:
    core, _, _, _ = env
    camp = make_campaign(core.db)
    assert camp.id is not None

    def job(tx: WriteTx) -> int:
        sess = AgentSession(role="campaign", campaign_id=camp.id, status="waiting")
        tx.add(sess)
        tx.flush()
        assert sess.id is not None
        return sess.id

    sid = core.db.write(job)
    out = core.nudge.nudge(session_id=sid, text="hello")
    assert (out["role"], out["campaign_id"], out["session_id"]) == ("campaign", camp.id, sid)
    seen = core.bus.latest(10, ["user.nudge", "nudge.sent"])
    assert {e.type for e in seen} == {"user.nudge", "nudge.sent"}


# ---------------------------------------------------------------- why a request waits


def _q(i: int, prio: int, cid: int | None = None, role: str = "campaign") -> QueuedView:
    return QueuedView(i, prio, role, cid, T0)


def test_each_waiting_request_says_why() -> None:
    running = [RunningView(1, 2, "campaign", 7), RunningView(2, 3, "scout", None)]
    limits = PoolLimits(capacity=3, reserve_p0=True, p01_only=False, halted=False)
    why = explain_wait([_q(10, 2, 7), _q(11, 3, role="scout"), _q(12, 2, 8)], running, limits)
    assert "Campaign 7 has an agent running" in str(why[10])
    assert why[11] == "The scout agent is already running."
    assert why[12] == "The last slot is kept free for your own requests."
    assert explain_wait([_q(13, 0, 9)], running, limits) == {13: None}  # nothing stops it: it is next
    full = PoolLimits(capacity=2, reserve_p0=False, p01_only=False, halted=False)
    assert "All 2 agent slots are busy (campaign 7, scout)" in str(
        explain_wait([_q(1, 0, 9)], running, full)[1]
    )
    halted = PoolLimits(
        capacity=3, reserve_p0=True, p01_only=False, halted=True, halt_reason="Clipper is paused."
    )
    assert explain_wait([_q(1, 0, 9)], [], halted) == {1: "Clipper is paused."}
    high = PoolLimits(
        capacity=3,
        reserve_p0=False,
        p01_only=True,
        halted=False,
        p01_reason="Claude usage is at 92%: only P0 and P1 requests start.",
    )
    assert explain_wait([_q(1, 3, 9), _q(2, 1, 8)], [], high) == {1: high.p01_reason, 2: None}
    low = PoolLimits(capacity=3, reserve_p0=False, p01_only=False, halted=False, low_memory=True)
    assert "memory is low" in str(explain_wait([_q(1, 2, 9)], [], low)[1])
    assert explain_wait([_q(5, 2, 9)], [], limits, lease_blocked={5: "held by session 4"}) == {
        5: "held by session 4"
    }


async def test_the_reason_is_written_on_the_queued_request(env: Env) -> None:
    core, runner, sup, _ = env
    camp = make_campaign(core.db)
    assert camp.id is not None
    runner.scripts["campaign"] = lambda req: [Say("ok")]
    set_control(core.db, "paused", True)
    core.nudge.nudge(campaign_id=camp.id)
    sup.attach()
    await asyncio.sleep(0.05)
    await sup.process_inbox()
    await sup.dispatch()
    (req,) = _requests(core)
    assert req.status == "queued" and req.waiting_reason == "Clipper is paused."
    set_control(core.db, "paused", False)
    await sup.run_until_idle()
    assert _requests(core)[0].status == "done"


async def test_a_lease_that_says_no_is_named(env: Env) -> None:
    core, runner, sup, _ = env
    camp = make_campaign(core.db)
    assert camp.id is not None
    runner.scripts["campaign"] = lambda req: [Say("ok")]
    assert sup.leases.acquire(f"campaign:{camp.id}", "session:99", 3600)
    core.nudge.nudge(campaign_id=camp.id)
    sup.attach()
    await asyncio.sleep(0.05)
    await sup.process_inbox()
    await sup.dispatch()
    (req,) = _requests(core)
    assert req.status == "queued" and "held by session 99" in (req.waiting_reason or "")
    assert sup.release_dead_leases() == [f"campaign:{camp.id}"]  # session 99 isn't running
    await sup.dispatch()
    assert _requests(core)[0].status in ("running", "done")
    await sup.run_until_idle()


# ---------------------------------------------------------------- repairs


async def test_a_lease_of_a_running_session_is_not_released(env: Env) -> None:
    core, _, sup, _ = env
    camp = make_campaign(core.db)
    assert camp.id is not None
    sup.leases.acquire(f"campaign:{camp.id}", "session:5", 3600)
    sup._running[1] = Running(1, 5, "campaign", camp.id, 2, 0, "x", T0)
    assert sup.release_dead_leases() == []
    with pytest.raises(ValueError, match="is running"):
        sup.release_lease(camp.id)
    sup._running.clear()
    assert sup.release_lease(camp.id) is True
    assert sup.release_lease(camp.id) is False


class HangingRunner:
    """A turn that never ends. ``obeys`` says whether an interrupt stops it (a stuck tool call doesn't)."""

    def __init__(self, obeys: bool) -> None:
        self.obeys = obeys
        self.stop = asyncio.Event()
        self.started = asyncio.Event()
        self.interrupted: list[int] = []

    async def run(self, req: RunRequest) -> RunOutcome:
        self.started.set()
        await self.stop.wait()
        return RunOutcome(req.resume, interrupted=True)

    async def interrupt(self, session_id: int) -> None:
        self.interrupted.append(session_id)
        if self.obeys:
            self.stop.set()
        else:
            await asyncio.sleep(3600)


@pytest.mark.parametrize("obeys", [True, False], ids=["interrupt works", "interrupt hangs, task cancelled"])
async def test_restarting_a_hung_turn_fails_its_request_frees_the_lease_and_a_nudge_follows(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, obeys: bool
) -> None:
    monkeypatch.setattr(supervisor_module, "RESTART_WAIT_S", 0.2)
    core = Core.create(settings, fakes=True, clock=FakeClock(T0))
    runner = HangingRunner(obeys)
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
        (entry,) = sup._running.values()
        stall = Stall(
            key=f"session_hung:{entry.session_id}", kind="session_hung", since=T0, summary="quiet", evidence=["No activity"],
            actions=["restart_turn", "nudge"], campaign_id=camp.id, session_id=entry.session_id, request_id=entry.request_id,
        )  # fmt: skip
        runner.stop = asyncio.Event() if obeys else runner.stop  # a second run must not return at once
        said = await run_action(core, sup, stall, "restart_turn", text="Try again", by="user")
        assert "Restarted" in said
        assert runner.interrupted == [entry.session_id]
        await asyncio.gather(*(e.task for e in [entry] if e.task), return_exceptions=True)
        first = _requests(core)[0]
        assert first.status == "failed" and first.error == "interrupted by your nudge"
        assert sup.leases.holder(f"campaign:{camp.id}") is None
        await asyncio.sleep(0.05)  # let the committed events reach the subscription
        await sup.process_inbox()
        queued = [r for r in _requests(core) if r.status == "queued"]
        assert len(queued) == 1 and queued[0].kind == "user.nudge" and queued[0].priority == P0
        types = {e.type for e in core.bus.latest(20, ["nudge.sent"])}
        assert types == {"nudge.sent"}
        with pytest.raises(ServiceError, match="isn't running any more"):
            await run_action(core, sup, stall, "restart_turn")
    finally:
        runner.stop.set()
        for t in list(sup._running.values()):
            if t.task:
                t.task.cancel()
        await asyncio.sleep(0.05)
        core.close()


async def test_run_now_and_release_lease_actions(env: Env) -> None:
    core, runner, sup, _ = env
    camp = make_campaign(core.db)
    assert camp.id is not None
    set_control(core.db, "paused", True)
    core.nudge.nudge(campaign_id=camp.id, auto=True, by="supervisor")
    sup.attach()
    await asyncio.sleep(0.05)
    await sup.process_inbox()
    (req,) = _requests(core)
    assert req.priority == P2
    stall = Stall(
        key=f"request_blocked:{req.id}", kind="request_blocked", since=T0, summary="s", evidence=["Clipper is paused."],
        actions=["run_now", "release_lease"], campaign_id=camp.id, request_id=req.id,
    )  # fmt: skip
    assert "front" in await run_action(core, sup, stall, "run_now")
    assert _requests(core)[0].priority == P0
    with pytest.raises(ServiceError, match="nothing held that campaign"):
        await run_action(core, sup, stall, "release_lease")
    sup.leases.acquire(f"campaign:{camp.id}", "session:42", 3600)
    assert "Released the lease" in await run_action(core, sup, stall, "release_lease")
    with pytest.raises(ServiceError, match="isn't something to do"):
        await run_action(core, sup, stall, "restart_turn")
    with pytest.raises(ServiceError, match="isn't something to do"):
        await run_action(core, sup, stall, "show_jobs")
    assert core.bus.latest(20, ["nudge.sent"]) and sup.leases.holder(f"campaign:{camp.id}") is None
    runner.scripts["campaign"] = lambda req: [Say("ok")]
    set_control(core.db, "paused", False)
    await sup.run_until_idle()


async def test_cancel_and_retry_through_the_action(env: Env) -> None:
    core, _, sup, _ = env
    core.jobs.register("dummy", lambda ctx, data: {}, "cpu")
    job_id = core.jobs.enqueue("dummy", {"n": 1})
    stall = Stall(
        key=f"job_stalled:{job_id}",
        kind="job_stalled",
        since=T0,
        summary="s",
        evidence=[],
        actions=["cancel_retry"],
        job_id=job_id,
    )
    said = await run_action(core, sup, stall, "cancel_retry")
    assert "queued it again as job" in said
