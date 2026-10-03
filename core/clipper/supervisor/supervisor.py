"""The supervisor: small and deliberately simple (PLAN §2).

- turns events into queued agent requests (``router.route``), merging events for a campaign that is
  already queued or busy;
- runs requests in a slot pool (``pool.pick``): priorities P0-P3, one slot kept for P0, fewer slots as the
  Claude usage window fills, nothing while rate-limited (auto-resumes after the reset);
- one session per campaign, resumed with ``resume=<sdk session id>``; Scout/Analyst start fresh each run;
  the Director keeps one conversation;
- cron triggers (Scout every 15 min, Analyst daily), wake-ups, watchdog for stuck campaigns, due posts,
  question timeouts; kill switch interrupts every running session.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlmodel import col, func, select

from clipper.agents.runner import AgentRunner, RunOutcome, RunRequest
from clipper.db.engine import WriteTx
from clipper.db.models import AgentRequest, AgentSession, Campaign, Clip, Job
from clipper.db.types import CampaignStatus, JobStatus, RequestStatus, SessionStatus
from clipper.events.bus import EventEnvelope, Subscription
from clipper.events.types import AgentSessionChanged, TriggerFired, WatchdogNudge
from clipper.leases import LeaseManager, campaign_resource
from clipper.rules.caps import local_day_bounds
from clipper.services.control import configured_slots, kv_get, kv_set_tx, read_control
from clipper.supervisor.messages import build_prompt
from clipper.supervisor.pool import PoolLimits, QueuedView, RunningView, pick
from clipper.supervisor.router import RequestSpec, SessionInfo, route
from clipper.system import free_ram_gb

if TYPE_CHECKING:
    from clipper.core import Core

log = logging.getLogger(__name__)
LEASE_TTL_S = 3 * 3600


@dataclass
class Running:
    request_id: int
    session_id: int
    role: str
    campaign_id: int | None
    priority: int
    slot: int
    kind: str
    started: datetime
    task: asyncio.Task[None] | None = None


class Supervisor:
    def __init__(self, core: Core, runner: AgentRunner) -> None:
        self.core = core
        self.runner = runner
        self.leases = LeaseManager(core.db, core.clock)
        self._sub: Subscription | None = None
        self._running: dict[int, Running] = {}
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._rate_alerted_for: datetime | None = None
        self._last_event_id = 0
        self._catch_up = False

    # ------------------------------------------------------------ lifecycle

    def attach(self) -> None:
        """Subscribe to live events and catch up on any committed while we weren't listening."""
        if self._sub is not None:
            return
        self._sub = self.core.bus.subscribe()
        self._recover()
        last = kv_get(self.core.db, "supervisor.last_event_id")
        self._last_event_id = int(last) if last is not None else 0
        self._catch_up = True

    async def _catch_up_from_db(self) -> None:
        self._catch_up = False
        while True:
            batch = self.core.bus.since(self._last_event_id, limit=500)
            if not batch:
                return
            for env in batch:
                await self.handle(env)

    def _recover(self) -> None:
        """Requests left 'running' by a crash go back to the queue; their sessions are waiting again."""

        def job(tx: WriteTx) -> None:
            for r in tx.session.exec(
                select(AgentRequest).where(AgentRequest.status == RequestStatus.RUNNING)
            ).all():
                r.status, r.slot, r.started_at = RequestStatus.QUEUED, None, None
                tx.add(r)
            for s in tx.session.exec(
                select(AgentSession).where(AgentSession.status == SessionStatus.RUNNING)
            ).all():
                s.status = SessionStatus.WAITING
                tx.add(s)

        self.core.db.write(job)

    async def start(self) -> None:
        self.attach()
        self._tasks = [
            asyncio.create_task(self._inbox_loop(), name="supervisor-inbox"),
            asyncio.create_task(self._tick_loop(), name="supervisor-tick"),
            asyncio.create_task(self.core.jobs.run_forever(self._stop), name="jobs"),
        ]

    async def stop(self) -> None:
        self._stop.set()
        for entry in list(self._running.values()):
            with contextlib.suppress(Exception):
                await self.runner.interrupt(entry.session_id)
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(
            *self._tasks, *(e.task for e in self._running.values() if e.task), return_exceptions=True
        )
        if self._sub is not None:
            self._sub.close()

    async def _inbox_loop(self) -> None:
        assert self._sub is not None
        while not self._stop.is_set():
            env = await self._sub.get(timeout=1.0)
            if env is None:
                continue
            await self.handle(env)
            await self.process_inbox()
            self._save_cursor()
            await self.dispatch()

    async def _tick_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("supervisor tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.core.settings.triggers.wakeup_poll_s)

    async def tick(self) -> None:
        self.fire_triggers()
        self.core.wakeups.fire_due()
        self.watchdog()
        self.core.notify.expire()
        await self.core.publishing.run_due()
        await self.process_inbox()
        await self.dispatch()

    # ------------------------------------------------------------ events -> requests

    async def process_inbox(self) -> int:
        if self._catch_up:
            await self._catch_up_from_db()
        n = 0
        while self._sub is not None and (env := self._sub.get_nowait()) is not None:
            await self.handle(env)
            n += 1
        if n:
            self._save_cursor()
        return n

    def _save_cursor(self) -> None:
        last = self._last_event_id
        self.core.db.write(lambda tx: kv_set_tx(tx, "supervisor.last_event_id", last))

    async def handle(self, env: EventEnvelope) -> None:
        if env.id <= self._last_event_id:
            return  # already handled (catch-up and live delivery overlap)
        self._last_event_id = env.id
        if (
            env.type == "control.changed"
            and env.payload.get("key") == "kill_switch"
            and env.payload.get("value")
        ):
            for entry in list(self._running.values()):
                with contextlib.suppress(Exception):
                    await self.runner.interrupt(entry.session_id)
            return
        for spec in route(env, session_of=self._session_info, clip_campaign=self._clip_campaign):
            self.enqueue(spec)

    def _session_info(self, session_id: int) -> SessionInfo | None:
        with self.core.db.read() as s:
            row = s.get(AgentSession, session_id)
            return SessionInfo(row.role, row.campaign_id) if row else None

    def _clip_campaign(self, clip_id: int) -> int | None:
        with self.core.db.read() as s:
            clip = s.get(Clip, clip_id)
            return clip.campaign_id if clip else None

    def enqueue(self, spec: RequestSpec) -> int:
        """Insert a request, or merge the event into a queued one for the same role + campaign."""

        def job(tx: WriteTx) -> int:
            q = select(AgentRequest).where(
                AgentRequest.status == RequestStatus.QUEUED, AgentRequest.role == spec.role
            )
            q = (
                q.where(AgentRequest.campaign_id == spec.campaign_id)
                if spec.campaign_id is not None
                else q.where(col(AgentRequest.campaign_id).is_(None))
            )
            existing = tx.session.exec(q.order_by(col(AgentRequest.id))).first()
            if existing is not None:
                events = list(existing.payload.get("events", []))
                if all(e.get("id") != spec.event.get("id") for e in events):
                    events.append(spec.event)
                    existing.merged_count += 1
                existing.payload = {**existing.payload, "events": events}
                existing.priority = min(existing.priority, spec.priority)
                tx.add(existing)
                assert existing.id is not None
                return existing.id
            row = AgentRequest(
                priority=spec.priority,
                kind=spec.kind,
                role=spec.role,
                campaign_id=spec.campaign_id,
                payload={"events": [spec.event]},
            )
            tx.add(row)
            tx.flush()
            assert row.id is not None
            return row.id

        return self.core.db.write(job)

    # ------------------------------------------------------------ pool

    def limits(self) -> PoolLimits:
        ctl = read_control(self.core.db)
        usage = self.core.usage
        snap = usage.current()
        agents = self.core.settings.agents
        capacity = usage.max_slots(snap, agents.slots if ctl.slots is None else int(ctl.slots))
        free_gb = free_ram_gb() if agents.min_free_ram_gb > 0 else None
        day_start, _ = local_day_bounds(self.core.clock.now(), self.core.settings.triggers.timezone)
        with self.core.db.read() as s:
            runs_today = s.exec(
                select(func.count())
                .select_from(AgentRequest)
                .where(col(AgentRequest.started_at) >= day_start)
            ).one()
        run_cap = self.core.settings.usage.daily_agent_run_cap
        cap_hit = run_cap > 0 and runs_today >= run_cap
        return PoolLimits(
            capacity=capacity,
            reserve_p0=agents.reserve_p0_slot,
            p01_only=usage.p01_only(snap) or cap_hit,
            halted=ctl.kill_switch or ctl.paused or snap.rate_limited,
            low_memory=free_gb is not None and free_gb < agents.min_free_ram_gb,
        )

    def queued(self) -> list[QueuedView]:
        with self.core.db.read() as s:
            rows = s.exec(select(AgentRequest).where(AgentRequest.status == RequestStatus.QUEUED)).all()
        return [QueuedView(r.id or 0, r.priority, r.role, r.campaign_id, r.queued_at) for r in rows]

    async def dispatch(self) -> list[int]:
        started: list[int] = []
        limits = self.limits()
        while True:
            running = [
                RunningView(e.request_id, e.priority, e.role, e.campaign_id) for e in self._running.values()
            ]
            choice = pick(self.queued(), running, limits)
            if choice is None:
                return started
            if not self._begin(choice, limits.capacity):
                return started
            started.append(choice.id)

    def _begin(self, choice: QueuedView, capacity: int) -> bool:
        used = {e.slot for e in self._running.values()}
        slot = next((i for i in range(max(capacity, 1)) if i not in used), len(used))
        session_id, resume = self._session_for(choice)
        if choice.campaign_id is not None and not self.leases.acquire(
            campaign_resource(choice.campaign_id), f"session:{session_id}", LEASE_TTL_S
        ):
            return False
        now = self.core.clock.now()

        def job(tx: WriteTx) -> dict[str, Any] | None:
            r = tx.session.get(AgentRequest, choice.id)
            if r is None or r.status != RequestStatus.QUEUED:
                return None
            r.status, r.slot, r.started_at = RequestStatus.RUNNING, slot, now
            tx.add(r)
            sess = tx.session.get(AgentSession, session_id)
            assert sess is not None
            sess.status = SessionStatus.RUNNING
            sess.last_active = now
            tx.add(sess)
            tx.publish(
                AgentSessionChanged(
                    session_id=session_id, role=sess.role, status=sess.status, campaign_id=sess.campaign_id
                )
            )
            return {"kind": r.kind, "payload": dict(r.payload)}

        claimed = self.core.db.write(job)
        if claimed is None:
            return False
        entry = Running(
            choice.id,
            session_id,
            choice.role,
            choice.campaign_id,
            choice.priority,
            slot,
            claimed["kind"],
            now,
        )
        self._running[choice.id] = entry
        events: list[dict[str, Any]] = list(claimed["payload"].get("events", []))
        prompt = build_prompt(self.core, choice.role, choice.campaign_id, events)
        req = RunRequest(
            choice.role,
            claimed["kind"],
            prompt,
            session_id,
            choice.campaign_id,
            resume,
            choice.id,
            claimed["payload"],
        )
        entry.task = asyncio.create_task(self._run(entry, req))
        return True

    def _session_for(self, choice: QueuedView) -> tuple[int, str | None]:
        """One session per campaign (resumed), one persistent Director conversation, fresh Scout/Analyst runs."""

        def job(tx: WriteTx) -> tuple[int, str | None]:
            sess: AgentSession | None = None
            if choice.role == "campaign" and choice.campaign_id is not None:
                camp = tx.session.get(Campaign, choice.campaign_id)
                if camp is not None and camp.session_id is not None:
                    sess = tx.session.get(AgentSession, camp.session_id)
                if sess is None:
                    sess = AgentSession(
                        role="campaign", campaign_id=choice.campaign_id, status=SessionStatus.WAITING
                    )
                    tx.add(sess)
                    tx.flush()
                    if camp is not None:
                        camp.session_id = sess.id
                        tx.add(camp)
            elif choice.role == "director":
                sess = tx.session.exec(
                    select(AgentSession)
                    .where(AgentSession.role == "director", AgentSession.status != SessionStatus.FAILED)
                    .order_by(col(AgentSession.id).desc())
                ).first()
            if sess is None:
                sess = AgentSession(
                    role=choice.role, campaign_id=choice.campaign_id, status=SessionStatus.WAITING
                )
                tx.add(sess)
                tx.flush()
            assert sess.id is not None
            return sess.id, sess.sdk_session_id

        return self.core.db.write(job)

    async def _run(self, entry: Running, req: RunRequest) -> None:
        outcome: RunOutcome
        try:
            outcome = await self.runner.run(req)
        except Exception as exc:
            log.exception("agent run crashed")
            outcome = RunOutcome(req.resume, error=f"{type(exc).__name__}: {exc}")
        finally:
            self._running.pop(entry.request_id, None)
        self._finish(entry, outcome)
        if entry.campaign_id is not None:
            self.leases.release(campaign_resource(entry.campaign_id), f"session:{entry.session_id}")
        if not self._stop.is_set():
            await self.dispatch()

    def _finish(self, entry: Running, outcome: RunOutcome) -> None:
        now = self.core.clock.now()
        killed = read_control(self.core.db).kill_switch
        requeue = outcome.rate_limited or (outcome.interrupted and killed)

        def job(tx: WriteTx) -> None:
            r = tx.session.get(AgentRequest, entry.request_id)
            assert r is not None
            if requeue:
                r.status, r.slot, r.started_at = RequestStatus.QUEUED, None, None
            else:
                r.status = RequestStatus.FAILED if outcome.error else RequestStatus.DONE
                r.finished_at = now
                r.error = outcome.error
            tx.add(r)
            sess = tx.session.get(AgentSession, entry.session_id)
            assert sess is not None
            sess.sdk_session_id = outcome.sdk_session_id or sess.sdk_session_id
            sess.turns += outcome.turns
            sess.input_tokens += outcome.input_tokens
            sess.output_tokens += outcome.output_tokens
            sess.last_active = now
            if outcome.error and not requeue:
                sess.status = SessionStatus.FAILED if sess.sdk_session_id is None else SessionStatus.WAITING
            elif entry.role in ("scout", "analyst"):
                sess.status = SessionStatus.DONE
            else:
                sess.status = SessionStatus.WAITING
            tx.add(sess)
            if entry.campaign_id is not None:
                camp = tx.session.get(Campaign, entry.campaign_id)
                if camp is not None:
                    camp.agent_turns += outcome.turns
                    tx.add(camp)
            tx.publish(
                AgentSessionChanged(
                    session_id=entry.session_id,
                    role=entry.role,
                    status=sess.status,
                    campaign_id=entry.campaign_id,
                )
            )

        self.core.db.write(job)
        if outcome.input_tokens or outcome.output_tokens:
            self.core.usage.add_tokens(outcome.input_tokens + outcome.output_tokens)
        if outcome.rate_limited:
            resets = outcome.resets_at or self.core.usage.current().resets_at
            if resets != self._rate_alerted_for:
                self._rate_alerted_for = resets
                when = (
                    resets.astimezone(ZoneInfo(self.core.settings.triggers.timezone)).strftime("%H:%M")
                    if resets
                    else "the reset"
                )
                self.core.notify.alert(
                    "warning",
                    f"Claude usage limit reached; agents paused, resuming at {when}. Jobs and uploads keep running.",
                    source="supervisor",
                )
        elif outcome.error:
            self.core.notify.alert(
                "error",
                f"{entry.role} session {entry.session_id} failed: {outcome.error}",
                source="supervisor",
                campaign_id=entry.campaign_id,
            )

    # ------------------------------------------------------------ triggers, watchdog

    def fire_triggers(self) -> list[str]:
        ctl = read_control(self.core.db)
        if ctl.kill_switch or ctl.paused:
            return []
        now = self.core.clock.now()
        cfg = self.core.settings.triggers
        fired: list[str] = []
        last = kv_get(self.core.db, "trigger.scout.last")
        if last is None or now - datetime.fromisoformat(last) >= timedelta(minutes=cfg.scout_every_min):
            fired.append("scout")
        local = now.astimezone(ZoneInfo(cfg.timezone))
        hh, mm = (int(x) for x in cfg.analyst_daily_at.split(":"))
        if (
            local.time() >= time(hh, mm)
            and kv_get(self.core.db, "trigger.analyst.date") != local.date().isoformat()
        ):
            fired.append("analyst")

        def job(tx: WriteTx) -> None:
            for name in fired:
                if name == "scout":
                    kv_set_tx(tx, "trigger.scout.last", now.isoformat())
                else:
                    kv_set_tx(tx, "trigger.analyst.date", local.date().isoformat())
                tx.publish(TriggerFired(name=name))  # type: ignore[arg-type]

        if fired:
            self.core.db.write(job)
        return fired

    def watchdog(self) -> list[int]:
        now = self.core.clock.now()
        stale = timedelta(minutes=self.core.settings.triggers.watchdog_stale_min)
        nudged: list[int] = []
        with self.core.db.read() as s:
            camps = s.exec(
                select(Campaign).where(
                    col(Campaign.status).in_([CampaignStatus.ACTIVE, CampaignStatus.ENDING])
                )
            ).all()
            busy = {
                r.campaign_id
                for r in s.exec(
                    select(AgentRequest).where(
                        col(AgentRequest.status).in_([RequestStatus.QUEUED, RequestStatus.RUNNING])
                    )
                ).all()
            }
            jobs_busy = {
                j.campaign_id
                for j in s.exec(
                    select(Job).where(col(Job.status).in_([JobStatus.QUEUED, JobStatus.RUNNING]))
                ).all()
            }
            sessions = {
                a.id: a for a in s.exec(select(AgentSession).where(AgentSession.role == "campaign")).all()
            }
        for c in camps:
            if c.id is None or c.id in busy or c.id in jobs_busy or c.session_id is None:
                continue
            sess = sessions.get(c.session_id)
            if sess is None:
                continue
            idle = now - sess.last_active
            last_nudge = kv_get(self.core.db, f"watchdog.{c.id}")
            if idle >= stale and (last_nudge is None or now - datetime.fromisoformat(last_nudge) >= stale):
                cid = c.id

                def job(tx: WriteTx, cid: int = cid, idle: timedelta = idle) -> None:
                    kv_set_tx(tx, f"watchdog.{cid}", now.isoformat())
                    tx.publish(WatchdogNudge(campaign_id=cid, idle_minutes=idle.total_seconds() / 60))

                self.core.db.write(job)
                nudged.append(c.id)
        return nudged

    # ------------------------------------------------------------ controls and views

    async def interrupt(self, session_id: int) -> None:
        await self.runner.interrupt(session_id)

    def board(self) -> dict[str, Any]:
        limits = self.limits()
        return {
            "capacity": limits.capacity,
            "configured_slots": configured_slots(self.core.db, self.core.settings.agents.slots),
            "halted": limits.halted,
            "p01_only": limits.p01_only,
            "running": [
                {
                    "slot": e.slot,
                    "request_id": e.request_id,
                    "session_id": e.session_id,
                    "role": e.role,
                    "campaign_id": e.campaign_id,
                    "kind": e.kind,
                    "priority": e.priority,
                    "started": e.started.isoformat(),
                }
                for e in sorted(self._running.values(), key=lambda e: e.slot)
            ],
            "queue": [
                {
                    "request_id": q.id,
                    "priority": q.priority,
                    "role": q.role,
                    "campaign_id": q.campaign_id,
                    "queued_at": q.queued_at.isoformat(),
                }
                for q in sorted(self.queued(), key=lambda q: (q.priority, q.queued_at))
            ],
        }

    def bump(self, request_id: int, priority: int) -> None:
        def job(tx: WriteTx) -> None:
            r = tx.session.get(AgentRequest, request_id)
            if r is not None and r.status == RequestStatus.QUEUED:
                r.priority = max(0, min(3, priority))
                tx.add(r)

        self.core.db.write(job)

    def cancel(self, request_id: int) -> None:
        def job(tx: WriteTx) -> None:
            r = tx.session.get(AgentRequest, request_id)
            if r is not None and r.status == RequestStatus.QUEUED:
                r.status = RequestStatus.CANCELLED
                tx.add(r)

        self.core.db.write(job)

    # ------------------------------------------------------------ test/dev helper

    async def run_until_idle(self, *, max_rounds: int = 100, due_posts: bool = True) -> int:
        """Pump jobs, events and agent runs until nothing is left to do. Returns rounds used."""
        self.attach()
        for rounds in range(1, max_rounds + 1):
            await self.core.jobs.drain()
            if due_posts:
                await self.core.publishing.run_due()
            await asyncio.sleep(0.02)  # let committed events reach the subscription
            await self.process_inbox()
            await self.dispatch()
            if self._running:
                await asyncio.gather(*(e.task for e in list(self._running.values()) if e.task))
                continue
            await asyncio.sleep(0.02)
            if self._sub is not None and self._sub.pending():
                continue
            with self.core.db.read() as s:
                open_jobs = s.exec(
                    select(Job.id).where(col(Job.status).in_([JobStatus.QUEUED, JobStatus.RUNNING]))
                ).first()
            limits = self.limits()
            runnable = pick(self.queued(), [], limits) if not limits.halted else None
            if open_jobs is None and runnable is None and not self._running:
                return rounds
        raise TimeoutError("supervisor did not become idle")
