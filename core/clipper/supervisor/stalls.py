"""Finding what is stuck. ``detect_stalls`` is pure: it reads a ``Snapshot`` (plain dataclasses, built from
the tables by ``build_snapshot``) and returns one ``Stall`` per thing that looks stuck, with the evidence to
show and the actions that could help. Nothing here changes anything; the Needs you view and the supervisor's
automatic checks both call it.

What is deliberately not a stall: a job or a request that is simply waiting its turn for a short while, a
campaign that is waiting on you (a question, a review batch, footage, a join) or on a scheduled post, and
anything while Clipper is paused on purpose (it is reported with the reason, not as broken).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from clipper.db.models import (
    Account,
    AgentEvent,
    AgentRequest,
    AgentSession,
    Campaign,
    Job,
    Lease,
    Post,
    Question,
    ReviewBatch,
    Source,
    Submission,
    Wakeup,
)
from clipper.settings import StallSettings

if TYPE_CHECKING:
    from clipper.core import Core

KINDS = (
    "session_hung",
    "waiting_on_nothing",
    "request_blocked",
    "job_stalled",
    "job_waiting",
    "recipe_stuck",
    "post_overdue",
)
SLOW_JOB_KINDS = {"analyze": 2.0}  # a kind that is allowed to be quiet this many times longer
RECIPE_STUCK_MIN = 10  # a post being uploaded for this long


@dataclass(frozen=True)
class Stall:
    key: str  # "session_hung:3": the kind and the id of the thing that is stuck
    kind: str
    since: datetime
    summary: str  # one sentence: what looks stuck
    evidence: list[str]  # lines built from our own tables, never from web pages
    actions: list[str]  # what could help; the first is the default
    campaign_id: int | None = None
    session_id: int | None = None
    request_id: int | None = None
    job_id: int | None = None
    post_id: int | None = None


@dataclass(frozen=True)
class SessionView:
    id: int
    role: str
    campaign_id: int | None
    status: str
    last_active: datetime
    model: str | None = None


@dataclass(frozen=True)
class RequestView:
    id: int
    role: str
    campaign_id: int | None
    status: str  # queued | running
    queued_at: datetime
    started_at: datetime | None
    priority: int
    kind: str
    waiting_reason: str | None
    session_id: int | None  # the session that is running it (running requests)


@dataclass(frozen=True)
class JobView:
    id: int
    kind: str
    status: str  # queued | running
    progress: float
    progress_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    detail: str | None
    campaign_id: int | None
    label: str  # what it works on, in words
    resource: str | None = None


@dataclass(frozen=True)
class EventView:
    ts: datetime
    tool: str | None
    text: str


@dataclass(frozen=True)
class PostView:
    id: int
    campaign_id: int | None
    account_id: int
    platform: str
    scheduled_at: datetime
    status: str  # scheduled | posting
    dry_run: bool


@dataclass(frozen=True)
class CampaignView:
    id: int
    title: str
    status: str
    session_id: int | None


@dataclass
class Snapshot:
    now: datetime
    paused: bool = False
    kill_switch: bool = False
    sessions: dict[int, SessionView] = field(default_factory=lambda: {})
    requests: list[RequestView] = field(default_factory=lambda: [])
    jobs: list[JobView] = field(default_factory=lambda: [])
    last_event: dict[int, EventView] = field(default_factory=lambda: {})  # newest event per session
    last_tool: dict[int, EventView] = field(default_factory=lambda: {})  # newest tool call per session
    last_message: dict[int, EventView] = field(default_factory=lambda: {})  # newest thing it said
    campaigns: dict[int, CampaignView] = field(default_factory=lambda: {})
    waiting_on_you: set[int] = field(
        default_factory=lambda: set()
    )  # campaigns with a question, review or footage open
    pending_wakeups: set[int] = field(default_factory=lambda: set())
    tracking: set[int] = field(
        default_factory=lambda: set()
    )  # campaigns whose live posts are still being tracked
    posts: list[PostView] = field(default_factory=lambda: [])
    paused_accounts: set[int] = field(default_factory=lambda: set())
    leases: dict[str, tuple[str, datetime]] = field(
        default_factory=lambda: {}
    )  # resource -> (holder, expires)


def _ago(now: datetime, then: datetime) -> str:
    minutes = max(0, int((now - then).total_seconds() // 60))
    if minutes < 1:
        return "under a minute"
    if minutes < 90:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def _request_name(snap: Snapshot, r: RequestView) -> str:
    camp = snap.campaigns.get(r.campaign_id) if r.campaign_id is not None else None
    return f"The agent request for {camp.title}" if camp else f"A {r.role} request"


def _clip(text: str, limit: int = 160) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else one[: limit - 1] + "…"


def detect_stalls(snap: Snapshot, cfg: StallSettings) -> list[Stall]:
    now = snap.now
    out: list[Stall] = []
    running_sessions = {r.session_id for r in snap.requests if r.status == "running" and r.session_id}

    # a running session that went quiet
    for r in snap.requests:
        if r.status != "running" or r.session_id is None or r.started_at is None:
            continue
        last = snap.last_event.get(r.session_id)
        quiet_since = max(r.started_at, last.ts) if last else r.started_at
        if now - quiet_since < timedelta(minutes=cfg.session_quiet_min):
            continue
        sess = snap.sessions.get(r.session_id)
        tool = snap.last_tool.get(r.session_id)
        evidence = [
            f"No activity for {_ago(now, quiet_since)}; this run started {_ago(now, r.started_at)} ago."
        ]
        if tool is not None:
            evidence.append(f"Last tool call: {tool.tool or 'unknown'} {tool.text}".strip())
        if sess is not None and sess.model:
            evidence.append(f"Model: {sess.model}")
        out.append(
            Stall(
                key=f"session_hung:{r.session_id}",
                kind="session_hung",
                since=quiet_since,
                summary=f"The {r.role} agent has been quiet for {_ago(now, quiet_since)}.",
                evidence=evidence,
                actions=["restart_turn", "nudge"],
                campaign_id=r.campaign_id,
                session_id=r.session_id,
                request_id=r.id,
            )
        )

    # a campaign that waits on nothing
    busy_campaigns = {r.campaign_id for r in snap.requests if r.campaign_id is not None}
    busy_campaigns |= {j.campaign_id for j in snap.jobs if j.campaign_id is not None}
    busy_campaigns |= snap.waiting_on_you | snap.pending_wakeups | snap.tracking
    busy_campaigns |= {p.campaign_id for p in snap.posts if p.campaign_id is not None}
    if not (snap.paused or snap.kill_switch):
        for c in snap.campaigns.values():
            if c.status not in ("active", "ending") or c.session_id is None or c.id in busy_campaigns:
                continue
            sess = snap.sessions.get(c.session_id)
            if sess is None or sess.status != "waiting":
                continue
            idle = now - sess.last_active
            if idle < timedelta(minutes=cfg.idle_min):
                continue
            said = snap.last_message.get(sess.id)
            evidence = [
                f"The agent finished its turn {_ago(now, sess.last_active)} ago and nothing is queued, running, "
                "scheduled or waiting on you."
            ]
            if said is not None:
                evidence.append(f"It last said: {_clip(said.text)}")
            out.append(
                Stall(
                    key=f"waiting_on_nothing:{c.id}",
                    kind="waiting_on_nothing",
                    since=sess.last_active,
                    summary=f"{c.title} is waiting on nothing.",
                    evidence=evidence,
                    actions=["nudge"],
                    campaign_id=c.id,
                    session_id=sess.id,
                )
            )

    # a request that can't start
    for r in snap.requests:
        if r.status != "queued" or now - r.queued_at < timedelta(minutes=cfg.request_blocked_min):
            continue
        actions = ["run_now"] if r.priority > 0 else []
        holder = snap.leases.get(f"campaign:{r.campaign_id}") if r.campaign_id is not None else None
        if holder is not None and holder[1] > now:
            who = holder[0]
            alive = who.startswith("session:") and int(who.split(":")[1]) in running_sessions
            if not alive:
                actions.append("release_lease")
        reason = r.waiting_reason or "Nothing recorded why it hasn't started."
        out.append(
            Stall(
                key=f"request_blocked:{r.id}",
                kind="request_blocked",
                since=r.queued_at,
                summary=f"{_request_name(snap, r)} has been waiting {_ago(now, r.queued_at)} to start.",
                evidence=[
                    reason,
                    f"Queued {_ago(now, r.queued_at)} ago at priority P{r.priority} ({r.kind}).",
                ],
                actions=actions or ["show_agents"],
                campaign_id=r.campaign_id,
                request_id=r.id,
            )
        )

    # jobs that stopped moving, and jobs that can't get a slot
    running_jobs = [j for j in snap.jobs if j.status == "running"]
    for j in snap.jobs:
        if j.status == "running":
            quiet = timedelta(minutes=cfg.job_quiet_min * SLOW_JOB_KINDS.get(j.kind, 1.0))
            moved = j.progress_at or j.started_at or j.created_at
            if now - moved < quiet:
                continue
            evidence = [
                f"{j.label}: {int(j.progress * 100)}% done, last moved {_ago(now, moved)} ago.",
            ]
            if j.detail:
                evidence.append(f"Last report: {j.detail}")
            out.append(
                Stall(
                    key=f"job_stalled:{j.id}",
                    kind="job_stalled",
                    since=moved,
                    summary=f"{j.label} hasn't moved for {_ago(now, moved)}.",
                    evidence=evidence,
                    actions=["cancel_retry", "show_jobs"],
                    campaign_id=j.campaign_id,
                    job_id=j.id,
                )
            )
        elif now - j.created_at >= timedelta(minutes=cfg.job_waiting_min):
            holders = [x for x in running_jobs if x.resource == j.resource and x.resource is not None]
            why = (
                "The kill switch is on, so no job starts."
                if snap.kill_switch
                else (
                    f"Waiting for a free {j.resource} slot; running there: "
                    + ", ".join(f"job {x.id} ({x.label})" for x in holders[:3])
                    if holders
                    else "Nothing is holding its slot; it should start on the next pass."
                )
            )
            out.append(
                Stall(
                    key=f"job_waiting:{j.id}",
                    kind="job_waiting",
                    since=j.created_at,
                    summary=f"{j.label} has been queued for {_ago(now, j.created_at)}.",
                    evidence=[why],
                    actions=["show_jobs"],
                    campaign_id=j.campaign_id,
                    job_id=j.id,
                )
            )

    # posts that should have gone out
    for p in snap.posts:
        late = now - p.scheduled_at
        if p.status == "posting" and late >= timedelta(minutes=RECIPE_STUCK_MIN):
            out.append(
                Stall(
                    key=f"recipe_stuck:{p.id}",
                    kind="recipe_stuck",
                    since=p.scheduled_at,
                    summary=f"Post {p.id} on {p.platform} has been uploading for {_ago(now, p.scheduled_at)}.",
                    evidence=[
                        "The upload started and hasn't finished. Look at Clipper's Chrome window for a dialog or a challenge screen."
                    ],
                    actions=["show_browser", "nudge"],
                    campaign_id=p.campaign_id,
                    post_id=p.id,
                )
            )
        elif p.status == "scheduled" and late >= timedelta(minutes=cfg.post_overdue_min):
            why = (
                "Clipper is paused."
                if snap.paused
                else "The kill switch is on."
                if snap.kill_switch
                else "The account is paused (a challenge screen)."
                if p.account_id in snap.paused_accounts
                else "Nothing is blocking it that Clipper can see."
            )
            out.append(
                Stall(
                    key=f"post_overdue:{p.id}",
                    kind="post_overdue",
                    since=p.scheduled_at,
                    summary=f"Post {p.id} on {p.platform} is {_ago(now, p.scheduled_at)} past its time.",
                    evidence=[why + (" (dry run: it would only be simulated.)" if p.dry_run else "")],
                    actions=["open_calendar", "nudge"] if p.campaign_id is not None else ["open_calendar"],
                    campaign_id=p.campaign_id,
                    post_id=p.id,
                )
            )
    return sorted(out, key=lambda s: (s.since, s.key))


# ---------------------------------------------------------------- the snapshot, read from the tables


def job_label(j: Job) -> str:
    inp = j.input_json
    kind = {"download": "Download", "analyze": "Analysis", "import": "File import"}.get(
        j.kind, j.kind.replace("_", " ")
    )
    if inp.get("source_id"):
        return f"{kind} of source {inp['source_id']}"
    if inp.get("clip_id"):
        return f"{kind} of clip {inp['clip_id']}"
    return kind


def _event_text(e: AgentEvent) -> str:
    data: dict[str, Any] = dict(e.input_json)
    if e.type == "message":
        return str(data.get("text", ""))
    args = data.get("args")
    return _clip(json.dumps(args, default=str), 120) if args else ""


def build_snapshot(core: Core) -> Snapshot:
    now = core.clock.now()
    from clipper.services.control import read_control

    ctl = read_control(core.db)
    snap = Snapshot(now=now, paused=ctl.paused, kill_switch=ctl.kill_switch)
    handlers = core.jobs.handlers
    with core.db.read() as s:
        snap.sessions = {
            a.id: SessionView(a.id, a.role, a.campaign_id, a.status, a.last_active, a.model)
            for a in s.exec(select(AgentSession)).all()
            if a.id is not None
        }
        camps = s.exec(select(Campaign)).all()
        snap.campaigns = {
            c.id: CampaignView(c.id, c.title, c.status, c.session_id) for c in camps if c.id is not None
        }
        # which session runs a request: the campaign's own session, or the newest of its role
        by_campaign = {c.id: c.session_id for c in camps if c.id is not None}
        newest_of_role: dict[str, int] = {}
        for a in snap.sessions.values():
            if a.campaign_id is None and a.role not in newest_of_role:
                newest_of_role[a.role] = a.id
            elif a.campaign_id is None:
                newest_of_role[a.role] = max(newest_of_role[a.role], a.id)
        for r in s.exec(
            select(AgentRequest).where(col(AgentRequest.status).in_(["queued", "running"]))
        ).all():
            sid: int | None = None
            if r.status == "running":
                sid = (
                    by_campaign.get(r.campaign_id)
                    if r.campaign_id is not None
                    else newest_of_role.get(r.role)
                )
            snap.requests.append(
                RequestView(
                    r.id or 0, r.role, r.campaign_id, r.status, r.queued_at, r.started_at, r.priority, r.kind,
                    r.waiting_reason, sid,
                )
            )  # fmt: skip
        for j in s.exec(select(Job).where(col(Job.status).in_(["queued", "running"]))).all():
            reg = handlers.get(j.kind)
            snap.jobs.append(
                JobView(
                    j.id or 0, j.kind, j.status, j.progress, j.progress_at, j.created_at, j.started_at, j.detail,
                    j.campaign_id, job_label(j), reg.resource if reg else None,
                )
            )  # fmt: skip
        running_sids = [r.session_id for r in snap.requests if r.status == "running" and r.session_id]
        recent = [x for x in snap.sessions.values() if x.id in running_sids or x.status == "waiting"]
        for a in recent:
            events = s.exec(
                select(AgentEvent)
                .where(AgentEvent.session_id == a.id)
                .order_by(col(AgentEvent.id).desc())
                .limit(40)
            ).all()
            for e in events:
                view = EventView(e.ts, e.tool, _event_text(e))
                snap.last_event.setdefault(a.id, view)
                if e.type == "tool_call":
                    snap.last_tool.setdefault(a.id, view)
                if e.type == "message":
                    snap.last_message.setdefault(a.id, view)
        for q in s.exec(select(Question).where(Question.status == "open")).all():
            if q.campaign_id is not None:
                snap.waiting_on_you.add(q.campaign_id)
        for b in s.exec(select(ReviewBatch).where(ReviewBatch.status != "shipped")).all():
            snap.waiting_on_you.add(b.campaign_id)
        for src in s.exec(select(Source).where(col(Source.status).in_(["failed", "needs_footage"]))).all():
            snap.waiting_on_you.add(src.campaign_id)
        for c in camps:
            if c.status == "needs_user" and c.id is not None:
                snap.waiting_on_you.add(c.id)
        for sub_ in s.exec(select(Submission)).all():
            # a submitted post is tracked until its window ends: the campaign waits for payouts, not for nothing
            if sub_.tracking_ends is None or sub_.tracking_ends > now:
                snap.tracking.add(sub_.campaign_id)
        for w in s.exec(select(Wakeup).where(Wakeup.status == "pending")).all():
            if w.campaign_id is not None:
                snap.pending_wakeups.add(w.campaign_id)
        for p in s.exec(select(Post).where(col(Post.status).in_(["scheduled", "posting"]))).all():
            snap.posts.append(
                PostView(
                    p.id or 0, p.campaign_id, p.account_id, p.platform, p.scheduled_at, p.status, p.dry_run
                )
            )
        snap.paused_accounts = {
            a.id for a in s.exec(select(Account).where(Account.status == "paused")).all() if a.id is not None
        }
        snap.leases = {
            lease.resource: (lease.holder_session, lease.expires_at) for lease in s.exec(select(Lease)).all()
        }
    return snap
