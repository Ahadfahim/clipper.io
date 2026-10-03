"""Read models for the dashboard: one function per screen/panel, built from the database."""

from __future__ import annotations

import shutil
import subprocess
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, col, func, select

from clipper import __version__
from clipper.agents.access import ACCESS, CATALOG, SUBAGENTS
from clipper.api import schemas as S  # noqa: N812
from clipper.db.models import (
    Account,
    AgendaItem,
    AgentEvent,
    AgentRequest,
    AgentSession,
    Analysis,
    Campaign,
    Clip,
    EditOp,
    Edl,
    Event,
    Job,
    Lesson,
    Marketplace,
    Metric,
    Moment,
    Note,
    Platform,
    Post,
    Question,
    RecipeRun,
    Review,
    ReviewBatch,
    Source,
    Submission,
    Wakeup,
)
from clipper.rules.caps import local_day_bounds
from clipper.rules.spec import ClipSpec
from clipper.services.control import kv_get, read_control
from clipper.services.media import load_words

if TYPE_CHECKING:
    from clipper.core import Core

STAGES = ["Brief", "Sources", "Analyze", "Clips", "Review", "Post", "Submit"]
PLATFORM_NAMES = {"youtube": "YouTube Shorts", "tiktok": "TikTok", "instagram": "Instagram Reels", "x": "X"}


def file_url(kind: str, clip_id: int, path: str | None) -> str | None:
    return f"/api/files/clip/{clip_id}/{kind}" if path else None


# ---------------------------------------------------------------- shared lookups


def _latest_metrics(s: Session) -> dict[int, Metric]:
    rows = s.exec(select(Metric).order_by(col(Metric.ts))).all()
    out: dict[int, Metric] = {}
    for m in rows:
        out[m.post_id] = m
    return out


def _editing_live(s: Session, now: datetime) -> set[int]:
    rows = s.exec(
        select(Event).where(
            col(Event.type).in_(["edit.status", "edit.op"]), col(Event.ts) >= now - timedelta(minutes=5)
        )
    ).all()
    return {
        int(e.entity_id)
        for e in rows
        if e.entity_id and str(e.payload.get("actor", "")).startswith("session:")
    }


def clip_rows(core: Core, s: Session, clips: list[Clip]) -> list[S.ClipRow]:
    if not clips:
        return []
    moment_ids = {c.moment_id for c in clips}
    moments = {m.id: m for m in s.exec(select(Moment).where(col(Moment.id).in_(moment_ids))).all()}
    camps = {c.id: c for c in s.exec(select(Campaign)).all()}
    clip_ids = [c.id for c in clips if c.id is not None]
    reviews = {r.clip_id: r for r in s.exec(select(Review).where(col(Review.clip_id).in_(clip_ids))).all()}
    posts = s.exec(select(Post).where(col(Post.clip_id).in_(clip_ids))).all()
    metrics = _latest_metrics(s)
    live = _editing_live(s, core.clock.now())
    posted: dict[int, set[str]] = defaultdict(set)
    views: dict[int, int] = defaultdict(int)
    for p in posts:
        if p.status in ("live", "simulated"):
            posted[p.clip_id].add(p.platform)
        if p.id in metrics:
            views[p.clip_id] += metrics[p.id].views
    out: list[S.ClipRow] = []
    for c in clips:
        assert c.id is not None
        m = moments.get(c.moment_id)
        camp = camps.get(c.campaign_id)
        out.append(
            S.ClipRow(
                id=c.id,
                campaign_id=c.campaign_id,
                campaign_title=camp.title if camp else None,
                moment_id=c.moment_id,
                score=m.final_score if m else 0.0,
                duration=c.duration,
                status=c.status,
                layout=c.layout,
                caption_style=c.caption_style,
                hook=m.hook if m else "",
                version=c.version,
                variant_label=c.variant_label,
                thumb_url=file_url("thumb", c.id, c.thumb_path),
                preview_url=file_url("preview", c.id, c.preview_path),
                platforms_posted=sorted(posted[c.id]),
                views=views[c.id],
                decision=reviews[c.id].decision if c.id in reviews else None,
                editing_live=c.id in live,
            )
        )
    return out


def post_out(p: Post, acct: Account | None, metric: Metric | None, clip: Clip | None) -> S.PostOut:
    assert p.id is not None
    return S.PostOut(
        id=p.id,
        clip_id=p.clip_id,
        account_id=p.account_id,
        handle=acct.handle if acct else "?",
        platform=p.platform,
        scheduled_at=p.scheduled_at,
        posted_at=p.posted_at,
        url=p.url,
        status=p.status,
        dry_run=p.dry_run,
        views=metric.views if metric else 0,
        earnings=metric.earnings if metric else 0.0,
        error=p.error,
        thumb_url=file_url("thumb", p.clip_id, clip.thumb_path if clip else None),
    )


# ---------------------------------------------------------------- system


def gpu_util() -> float | None:  # LOCAL-VERIFY (nvidia-smi on the RTX 5080)
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return float(out.stdout.strip().splitlines()[0]) / 100
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def control_state(core: Core) -> S.ControlState:
    c = read_control(core.db)
    return S.ControlState(
        paused=c.paused,
        dry_run=c.dry_run,
        kill_switch=c.kill_switch,
        slots=c.slots,
        auto_approve_tier=c.auto_approve_tier,
    )


def switches(core: Core) -> S.SwitchesOut:
    with core.db.read() as s:
        markets = s.exec(select(Marketplace)).all()
        plats = s.exec(select(Platform)).all()
        accounts = s.exec(select(Account)).all()
    counts: dict[str, int] = defaultdict(int)
    for a in accounts:
        counts[a.platform] += 1
    return S.SwitchesOut(
        marketplaces={
            m.id: S.MarketSwitch(name=m.name, enabled=m.enabled, session_ok=m.session_ok, mode=m.mode)
            for m in markets
        },
        socials={p.id: S.SocialSwitch(name=p.name, enabled=p.enabled, accounts=counts[p.id]) for p in plats},
        accounts=[
            S.AccountSwitch(
                id=a.id or 0,
                platform=a.platform,
                handle=a.handle,
                enabled=a.enabled,
                status=a.status,
                paused_reason=a.paused_reason,
            )
            for a in accounts
        ],
    )


def status(core: Core, fixture_mode: bool) -> S.StatusOut:
    now = core.clock.now()
    day_start, _ = local_day_bounds(now, core.settings.triggers.timezone)
    with core.db.read() as s:
        running = s.exec(
            select(func.count()).select_from(AgentRequest).where(AgentRequest.status == "running")
        ).one()
        jobs_running = s.exec(select(func.count()).select_from(Job).where(Job.status == "running")).one()
        jobs_queued = s.exec(select(func.count()).select_from(Job).where(Job.status == "queued")).one()
        earned = s.exec(
            select(func.coalesce(func.sum(Metric.earnings), 0.0)).where(col(Metric.ts) >= day_start)
        ).one()
        pending = s.exec(select(func.count()).select_from(Review).where(Review.decision == "pending")).one()
        camps = s.exec(
            select(Campaign.marketplace, func.count())
            .where(col(Campaign.status).in_(["active", "suggested", "paused", "ending", "needs_user"]))
            .group_by(Campaign.marketplace)
        ).all()
        library = s.exec(select(func.count()).select_from(Clip)).one()
    usage = core.usage.as_dict()
    heartbeat = kv_get(core.db, "discord.heartbeat")
    discord_online = bool(heartbeat) and now - datetime.fromisoformat(str(heartbeat)) < timedelta(minutes=3)
    needs = overview_needs_you(core)
    return S.StatusOut(
        version=__version__,
        fixture_mode=fixture_mode,
        control=control_state(core),
        usage=S.UsageOut(**usage),
        agents_running=running,
        agents_capacity=min(
            read_control(core.db).slots or core.settings.agents.slots, core.usage.max_slots()
        ),
        jobs_running=jobs_running,
        jobs_queued=jobs_queued,
        gpu_util=None if fixture_mode else gpu_util(),
        extension_profiles=core.adapters.browser.connected_profiles(),
        discord_online=discord_online,
        earned_today=round(float(earned), 2),
        needs_you=len(needs),
        review_pending=pending,
        campaigns_by_market={m: n for m, n in camps},
        library_count=library,
    )


# ---------------------------------------------------------------- overview


def overview_needs_you(core: Core) -> list[S.NeedsYouItem]:
    items: list[S.NeedsYouItem] = []
    with core.db.read() as s:
        for a in s.exec(select(Account).where(Account.status == "paused")).all():
            items.append(
                S.NeedsYouItem(
                    kind="challenge",
                    urgency=0,
                    title=f"{PLATFORM_NAMES.get(a.platform, a.platform)} {a.handle} paused",
                    detail=a.paused_reason or "challenge screen",
                    actions=[
                        S.NeedsYouAction(
                            label="Open window", action="open_profile", args={"profile": a.chrome_profile}
                        ),
                        S.NeedsYouAction(label="Resume", action="resume_account", args={"account_id": a.id}),
                    ],
                )
            )
        for q in s.exec(select(Question).where(Question.status == "open").order_by(col(Question.id))).all():
            items.append(
                S.NeedsYouItem(
                    kind="question",
                    urgency=1,
                    title=q.text,
                    detail=f"Asked by the campaign agent{f' (campaign {q.campaign_id})' if q.campaign_id else ''}",
                    actions=[
                        S.NeedsYouAction(label=o, action="answer", args={"question_id": q.id, "answer": o})
                        for o in q.options_json
                    ],
                )
            )
        for b in s.exec(
            select(ReviewBatch).where(ReviewBatch.status != "shipped").order_by(col(ReviewBatch.timeout_at))
        ).all():
            camp = s.get(Campaign, b.campaign_id)
            pending = s.exec(
                select(func.count())
                .select_from(Review)
                .where(Review.batch_id == b.id, Review.decision == "pending")
            ).one()
            total = s.exec(select(func.count()).select_from(Review).where(Review.batch_id == b.id)).one()
            items.append(
                S.NeedsYouItem(
                    kind="review",
                    urgency=2,
                    title=f"{pending} of {total} clips to review: {camp.title if camp else b.campaign_id}",
                    detail=f"Batch {b.id}"
                    + (f", times out {b.timeout_at.isoformat()}" if b.timeout_at else ""),
                    actions=[S.NeedsYouAction(label="Review", action="review", args={"batch_id": b.id})],
                )
            )
        for c in s.exec(
            select(Campaign)
            .where(col(Campaign.status).in_(["suggested", "needs_user"]))
            .order_by(col(Campaign.score).desc())
        ).all():
            if c.status == "suggested" and (c.score or 0) < core.settings.scout.min_score_to_post_card:
                continue
            take = S.NeedsYouAction(label="Take", action="take", args={"campaign_id": c.id})
            skip = S.NeedsYouAction(label="Skip", action="skip", args={"campaign_id": c.id})
            title = (
                f"New campaign: {c.title}, score {c.score:.0f}, ${c.cpm:g} CPM"
                if c.status == "suggested"
                else f"{c.title}: {c.score_reason or 'needs you'}"
            )
            items.append(
                S.NeedsYouItem(
                    kind="campaign",
                    urgency=3,
                    title=title,
                    detail=c.marketplace.capitalize(),
                    actions=[take, skip]
                    if c.status == "suggested"
                    else [S.NeedsYouAction(label="Open", action="open_campaign", args={"campaign_id": c.id})],
                )
            )
        for j in s.exec(
            select(Job).where(Job.status == "failed").order_by(col(Job.id).desc()).limit(3)
        ).all():
            items.append(
                S.NeedsYouItem(
                    kind="failure",
                    urgency=4,
                    title=f"{j.kind} failed",
                    detail=(j.error or "")[:200],
                    actions=[],
                )
            )
    return sorted(items, key=lambda i: i.urgency)


def _stages(s: Session, c: Campaign) -> list[S.Stage]:
    assert c.id is not None
    sources = s.exec(select(Source).where(Source.campaign_id == c.id)).all()
    clips = s.exec(select(Clip).where(Clip.campaign_id == c.id)).all()
    reviews = s.exec(
        select(Review).join(Clip, col(Clip.id) == col(Review.clip_id)).where(Clip.campaign_id == c.id)
    ).all()
    posts = s.exec(select(Post).where(Post.campaign_id == c.id)).all()
    subs = s.exec(select(Submission).where(Submission.campaign_id == c.id)).all()
    done = [
        bool(c.spec_json),
        any(x.status in ("downloaded", "analyzing", "analyzed") for x in sources),
        any(x.status == "analyzed" for x in sources),
        bool(clips),
        any(r.decision != "pending" for r in reviews) and all(r.decision != "pending" for r in reviews),
        any(p.status in ("live", "simulated") for p in posts),
        bool(subs),
    ]
    active_idx = next((i for i, d in enumerate(done) if not d), len(done))
    stages: list[S.Stage] = []
    for i, name in enumerate(STAGES):
        # a stepper reads left to right: everything after the first unfinished stage is still to do
        state = "done" if i < active_idx else ("active" if i == active_idx else "todo")
        stages.append(S.Stage(name=name, state=state))  # type: ignore[arg-type]
    return stages


def overview(core: Core) -> S.OverviewOut:
    now = core.clock.now()
    tz = core.settings.triggers.timezone
    day_start, day_end = local_day_bounds(now, tz)
    with core.db.read() as s:
        metrics = s.exec(select(Metric)).all()
        posts_all = {p.id: p for p in s.exec(select(Post)).all()}
        camps = {c.id: c for c in s.exec(select(Campaign)).all()}
        accounts = {a.id: a for a in s.exec(select(Account)).all()}
        clips = {c.id: c for c in s.exec(select(Clip)).all()}

        def day_sum(start: datetime, attr: str, market: str | None = None) -> float:
            total = 0.0
            for m in metrics:
                if start <= m.ts < start + timedelta(days=1):
                    p = posts_all.get(m.post_id)
                    camp = camps.get(p.campaign_id) if p else None
                    if market is None or (camp is not None and camp.marketplace == market):
                        total += float(getattr(m, attr))
            return total

        earned_today = day_sum(day_start, "earnings")
        earned_yday = day_sum(day_start - timedelta(days=1), "earnings")
        views_today = day_sum(day_start, "views")
        spark = [round(day_sum(day_start - timedelta(days=d), "earnings"), 2) for d in range(13, -1, -1)]
        vspark = [day_sum(day_start - timedelta(days=d), "views") for d in range(13, -1, -1)]
        posted_today = sum(
            1
            for p in posts_all.values()
            if p.posted_at and day_start <= p.posted_at < day_end and p.status in ("live", "simulated")
        )
        cap_today = sum(
            a.daily_cap or core.settings.posting.default_daily_cap for a in accounts.values() if a.enabled
        )
        active = [c for c in camps.values() if c.status in ("active", "ending")]
        active_rows = [
            S.ActiveCampaign(
                id=c.id or 0,
                title=c.title,
                marketplace=c.marketplace,
                status=c.status,
                stages=_stages(s, c),
                budget_left=c.budget_left,
                budget_total=c.budget_total,
                runs_out_at=c.budget_runs_out_at,
                deadline=c.deadline,
            )
            for c in sorted(active, key=lambda c: -(c.score or 0))
        ]
        upcoming = [
            S.UpcomingPost(
                id=p.id or 0,
                account_id=p.account_id,
                handle=accounts[p.account_id].handle if p.account_id in accounts else "?",
                platform=p.platform,
                scheduled_at=p.scheduled_at,
                clip_id=p.clip_id,
                status=p.status,
                thumb_url=file_url(
                    "thumb", p.clip_id, clips[p.clip_id].thumb_path if p.clip_id in clips else None
                ),
            )
            for p in sorted(posts_all.values(), key=lambda p: p.scheduled_at)
            if p.status == "scheduled" and now <= p.scheduled_at <= now + timedelta(hours=24)
        ]
        agenda: list[S.AgendaEntry] = []
        for r in s.exec(
            select(AgentRequest)
            .where(AgentRequest.status == "queued")
            .order_by(col(AgentRequest.priority), col(AgentRequest.queued_at))
        ).all():
            camp = camps.get(r.campaign_id)
            agenda.append(
                S.AgendaEntry(
                    kind="request",
                    when=r.queued_at,
                    text=f"{r.role}{f' · {camp.title}' if camp else ''}: {r.kind}",
                    priority=r.priority,
                )
            )
        for w in s.exec(
            select(Wakeup).where(Wakeup.status == "pending").order_by(col(Wakeup.due_at)).limit(10)
        ).all():
            agenda.append(S.AgendaEntry(kind="wakeup", when=w.due_at, text=w.reason))
        for u in upcoming[:6]:
            agenda.append(
                S.AgendaEntry(kind="post", when=u.scheduled_at, text=f"Post clip {u.clip_id} on {u.handle}")
            )
        notes = [
            note_out(n) for n in s.exec(select(Note).where(Note.scope == "global", col(Note.pinned))).all()
        ]
    usage = core.usage.as_dict()
    median = median_find_to_post_hours(camps.values(), posts_all.values())
    by_market = {m: round(day_sum(day_start, "earnings", m), 2) for m in ("vyro", "whop")}
    delta = round((earned_today - earned_yday) / earned_yday * 100, 1) if earned_yday else None
    kpis = [
        S.Kpi(
            key="earned_today",
            label="Earned today",
            value=round(earned_today, 2),
            display=f"${earned_today:,.2f}",
            delta_pct=delta,
            spark=spark,
            split=by_market,
            unit="usd",
        ),
        S.Kpi(
            key="views_today",
            label="Views today",
            value=views_today,
            display=_short(views_today),
            spark=vspark,
        ),
        S.Kpi(
            key="posted_today",
            label="Clips posted",
            value=posted_today,
            display=f"{posted_today}/{cap_today}",
        ),
        S.Kpi(
            key="usage",
            label="Claude usage",
            value=usage["utilization"],
            display=f"{usage['utilization']:.0%}",
            unit="ratio",
        ),
        S.Kpi(
            key="find_to_post", label="Find → post", value=median or 0.0, display=_hours(median), unit="hours"
        ),
    ]
    last = kv_get(core.db, "trigger.scout.last")
    next_scout = None
    if last:
        next_scout = max(
            0,
            int(
                (
                    datetime.fromisoformat(str(last))
                    + timedelta(minutes=core.settings.triggers.scout_every_min)
                    - now
                ).total_seconds()
            ),
        )
    return S.OverviewOut(
        needs_you=overview_needs_you(core),
        kpis=kpis,
        active_campaigns=active_rows,
        upcoming_posts=upcoming,
        agenda=agenda,
        notes=notes,
        health=health(core),
        next_scout_in_s=next_scout,
    )


def _short(n: float) -> str:
    return f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else f"{n / 1000:.1f}k" if n >= 1000 else f"{n:.0f}"


def _hours(h: float | None) -> str:
    if h is None:
        return "–"
    return f"{int(h)}h {int((h % 1) * 60):02d}m"


def note_out(n: Note) -> S.NoteOut:
    return S.NoteOut(
        id=n.id or 0,
        scope=n.scope,
        scope_id=n.scope_id,
        text=n.text,
        author=n.author,
        pinned=n.pinned,
        response=n.response,
        created_at=n.created_at,
    )


def health(core: Core) -> list[S.HealthItem]:
    st = status_light(core)
    out = [
        S.HealthItem(
            name="Extension",
            status="ok" if st["profiles"] else "warn",
            detail=f"{len(st['profiles'])} profile(s) connected",
        ),
        S.HealthItem(
            name="Discord bot",
            status="ok" if st["discord"] else "warn",
            detail="online" if st["discord"] else "offline",
        ),
        S.HealthItem(
            name="GPU worker", status="ok", detail=f"{st['jobs_running']} running, {st['jobs_queued']} queued"
        ),
    ]
    for m in switches(core).marketplaces.values():
        out.append(
            S.HealthItem(
                name=m.name,
                status="ok" if m.session_ok else ("warn" if m.enabled else "skip"),
                detail="session valid" if m.session_ok else "needs login",
            )
        )
    usage = core.usage.as_dict()
    out.append(
        S.HealthItem(
            name="Claude usage",
            status="warn" if usage["utilization"] >= 0.8 else "ok",
            detail=f"{usage['utilization']:.0%} · {usage['pace']}",
        )
    )
    try:
        free = shutil.disk_usage(core.settings.paths.data_dir).free / 1e9
        out.append(
            S.HealthItem(name="Disk", status="ok" if free > 30 else "warn", detail=f"{free:.0f} GB free")
        )
    except OSError:
        pass
    return out


def status_light(core: Core) -> dict[str, Any]:
    with core.db.read() as s:
        jr = s.exec(select(func.count()).select_from(Job).where(Job.status == "running")).one()
        jq = s.exec(select(func.count()).select_from(Job).where(Job.status == "queued")).one()
    hb = kv_get(core.db, "discord.heartbeat")
    return {
        "profiles": core.adapters.browser.connected_profiles(),
        "discord": bool(hb) and core.clock.now() - datetime.fromisoformat(str(hb)) < timedelta(minutes=3),
        "jobs_running": jr,
        "jobs_queued": jq,
    }


# ---------------------------------------------------------------- agents


def board(core: Core) -> S.BoardOut:
    ctl = read_control(core.db)
    configured = ctl.slots or core.settings.agents.slots
    capacity = min(configured, core.usage.max_slots())
    with core.db.read() as s:
        running = s.exec(
            select(AgentRequest).where(AgentRequest.status == "running").order_by(col(AgentRequest.slot))
        ).all()
        queued = s.exec(
            select(AgentRequest)
            .where(AgentRequest.status == "queued")
            .order_by(col(AgentRequest.priority), col(AgentRequest.queued_at))
        ).all()
        camps = {c.id: c.title for c in s.exec(select(Campaign)).all()}
        sessions = {
            (a.role, a.campaign_id): a
            for a in s.exec(select(AgentSession).order_by(col(AgentSession.id))).all()
        }
        tools: dict[int, str | None] = {}
        for sess in sessions.values():
            if sess.id is not None:
                ev = s.exec(
                    select(AgentEvent)
                    .where(AgentEvent.session_id == sess.id, AgentEvent.type == "tool_call")
                    .order_by(col(AgentEvent.id).desc())
                    .limit(1)
                ).first()
                tools[sess.id] = ev.tool if ev else None
    by_slot = {r.slot: r for r in running}
    slots: list[S.SlotOut] = []
    for i in range(configured):
        r = by_slot.get(i)
        sess = sessions.get((r.role, r.campaign_id)) if r else None
        slots.append(
            S.SlotOut(
                slot=i,
                request_id=r.id if r else None,
                session_id=sess.id if sess else None,
                role=r.role if r else None,
                campaign_id=r.campaign_id if r else None,
                campaign_title=camps.get(r.campaign_id) if r else None,
                kind=r.kind if r else None,
                priority=r.priority if r else None,
                started=r.started_at if r else None,
                current_tool=tools.get(sess.id) if sess and sess.id else None,
                dimmed=i >= capacity,
            )
        )
    queue = [
        S.QueueItem(
            request_id=r.id or 0,
            priority=r.priority,
            role=r.role,
            kind=r.kind,
            campaign_id=r.campaign_id,
            campaign_title=camps.get(r.campaign_id),
            merged=r.merged_count,
            queued_at=r.queued_at,
        )
        for r in queued
    ]
    return S.BoardOut(
        capacity=capacity,
        configured_slots=configured,
        halted=ctl.kill_switch or ctl.paused,
        p01_only=core.usage.p01_only(),
        slots=slots,
        queue=queue,
    )


def session_out(core: Core, a: AgentSession, titles: dict[int | None, str]) -> S.SessionOut:
    role_cfg = core.settings.agents.roles.get(a.role)
    return S.SessionOut(
        id=a.id or 0,
        role=a.role,
        campaign_id=a.campaign_id,
        campaign_title=titles.get(a.campaign_id),
        status=a.status,
        turns=a.turns,
        max_turns=role_cfg.max_turns if role_cfg else 0,
        input_tokens=a.input_tokens,
        output_tokens=a.output_tokens,
        started=a.started,
        last_active=a.last_active,
        summary=a.summary,
        sdk_session_id=a.sdk_session_id,
    )


def sessions(core: Core) -> list[S.SessionOut]:
    with core.db.read() as s:
        rows = s.exec(select(AgentSession).order_by(col(AgentSession.last_active).desc()).limit(100)).all()
        titles: dict[int | None, str] = {c.id: c.title for c in s.exec(select(Campaign)).all()}
    return [session_out(core, a, titles) for a in rows]


def agent_event_out(e: AgentEvent) -> S.AgentEventOut:
    inp = dict(e.input_json)
    text = inp.get("text") if isinstance(inp.get("text"), str) else None
    if e.type == "blocked":
        text = f"[{e.output_json.get('rule')}] {e.output_json.get('reason')}"
    return S.AgentEventOut(
        id=e.id or 0,
        session_id=e.session_id,
        ts=e.ts,
        type=e.type,
        tool=e.tool,
        subagent=inp.get("subagent"),
        text=text,
        input=inp,
        output=dict(e.output_json),
    )


def session_detail(core: Core, session_id: int, after: int = 0, limit: int = 200) -> S.SessionDetail | None:
    with core.db.read() as s:
        a = s.get(AgentSession, session_id)
        if a is None:
            return None
        titles: dict[int | None, str] = {c.id: c.title for c in s.exec(select(Campaign)).all()}
        events = s.exec(
            select(AgentEvent)
            .where(AgentEvent.session_id == session_id, col(AgentEvent.id) > after)
            .order_by(col(AgentEvent.id))
            .limit(limit)
        ).all()
        q = (
            select(AgentRequest)
            .where(AgentRequest.role == a.role)
            .order_by(col(AgentRequest.id).desc())
            .limit(30)
        )
        q = q.where(AgentRequest.campaign_id == a.campaign_id) if a.campaign_id is not None else q
        reqs = s.exec(q).all()
    return S.SessionDetail(
        session=session_out(core, a, titles),
        requests=[
            S.QueueItem(
                request_id=r.id or 0,
                priority=r.priority,
                role=r.role,
                kind=r.kind,
                campaign_id=r.campaign_id,
                campaign_title=titles.get(r.campaign_id),
                merged=r.merged_count,
                queued_at=r.queued_at,
            )
            for r in reqs
        ],
        events=[agent_event_out(e) for e in events],
    )


# ---------------------------------------------------------------- campaigns


def campaign_rows(core: Core, *, status: str | None = None, market: str | None = None) -> list[S.CampaignRow]:
    with core.db.read() as s:
        q = select(Campaign).order_by(col(Campaign.score).desc())
        if status:
            q = q.where(Campaign.status == status)
        if market:
            q = q.where(Campaign.marketplace == market)
        camps = s.exec(q).all()
        markets = {m.id: m for m in s.exec(select(Marketplace)).all()}
        plats = {p.id: p.enabled for p in s.exec(select(Platform)).all()}
        accounts = s.exec(select(Account)).all()
        posts = s.exec(select(Post)).all()
        metrics = _latest_metrics(s)
    rows: list[S.CampaignRow] = []
    for c in camps:
        assert c.id is not None
        spec = ClipSpec.model_validate(c.spec_json or {})
        allowed = set(c.platforms or PLATFORM_NAMES) & (
            set(spec.platforms) if spec.platforms else set(PLATFORM_NAMES)
        )
        disabled = None
        if not markets[c.marketplace].enabled:
            disabled = f"{markets[c.marketplace].name.split()[0]} is off"
        elif not any(plats.get(p) for p in allowed):
            disabled = "No enabled socials"
        creator_words = {w.lower() for w in (c.creator or c.brand or "").split()}
        matching = [
            a.handle
            for a in accounts
            if a.platform in allowed
            and (
                any(t.split("-")[0] in creator_words or t in (c.title or "").lower() for t in a.niche_tags)
                or (any(t.startswith("podcast") for t in a.niche_tags) and "podcast" in c.title.lower())
                or ("mrbeast-style" in a.niche_tags and "mrbeast" in (c.creator or "").lower())
            )
        ]
        cposts = [p for p in posts if p.campaign_id == c.id and p.status in ("live", "simulated")]
        rows.append(
            S.CampaignRow(
                id=c.id,
                marketplace=c.marketplace,
                title=c.title,
                brand=c.brand,
                creator=c.creator,
                status=c.status,
                score=c.score,
                cpm=c.cpm,
                budget_total=c.budget_total,
                budget_left=c.budget_left,
                runs_out_at=c.budget_runs_out_at,
                deadline=c.deadline,
                content_type=c.content_type,
                platforms=list(c.platforms),
                matching_accounts=matching,
                clips_posted=len(cposts),
                earned=round(sum(metrics[p.id].earnings for p in cposts if p.id in metrics), 2),
                disabled_reason=disabled,
            )
        )
    return rows


def campaign_detail(core: Core, campaign_id: int) -> S.CampaignDetail | None:
    rows = [r for r in campaign_rows(core) if r.id == campaign_id]
    if not rows:
        return None
    with core.db.read() as s:
        c = s.get(Campaign, campaign_id)
        assert c is not None
        sources = s.exec(select(Source).where(Source.campaign_id == campaign_id)).all()
        events = s.exec(
            select(Event)
            .where(Event.entity == "campaign", Event.entity_id == str(campaign_id))
            .order_by(col(Event.id).desc())
            .limit(50)
        ).all()
        posts = s.exec(select(Post).where(Post.campaign_id == campaign_id)).all()
        subs = s.exec(select(Submission).where(Submission.campaign_id == campaign_id)).all()
        metrics = _latest_metrics(s)
    timeline = [S.TimelineEntry(ts=e.ts, type=e.type, text=_event_text(e)) for e in events]
    sub_counts: dict[str, int] = defaultdict(int)
    for x in subs:
        sub_counts[x.external_status] += 1
    live = [p for p in posts if p.status in ("live", "simulated")]
    return S.CampaignDetail(
        campaign=rows[0],
        url=c.url,
        score_reason=c.score_reason,
        payout={
            "cpm": c.cpm,
            "cap_per_post": c.cap_per_clip,
            "min_views_to_pay": c.min_views_to_pay,
            "tracking_window_days": c.tracking_window_days,
            "deliverable": c.deliverable,
        },
        rules_raw=c.rules_raw,
        spec=ClipSpec.model_validate(c.spec_json) if c.spec_json else None,
        sources=[
            S.SourceOut(
                id=x.id or 0,
                url=x.url,
                title=x.title,
                status=x.status,
                duration=x.duration,
                heatmap=[float(h.get("value", 0)) for h in x.heatmap_json],
            )
            for x in sources
        ],
        session_id=c.session_id,
        timeline=timeline,
        money=S.MoneyOut(
            views=sum(metrics[p.id].views for p in live if p.id in metrics),
            earnings=round(sum(metrics[p.id].earnings for p in live if p.id in metrics), 2),
            posts=len(live),
            submissions=dict(sub_counts),
        ),
    )


def _event_text(e: Event) -> str:
    p = e.payload
    texts = {
        "campaign.found": "Found by the Scout",
        "campaign.taken": f"Taken by {p.get('by')} via {p.get('via')}",
        "campaign.skipped": f"Skipped by {p.get('by')}",
        "campaign.updated": f"Updated {', '.join(p.get('fields', []))}"
        + (f" (budget left ${p['budget_left']:,.0f})" if p.get("budget_left") is not None else ""),
        "spec.updated": f"Spec saved by {p.get('by')}",
        "agent.log": str(p.get("text", "")),
        "watchdog.nudge": f"Watchdog nudge after {p.get('idle_minutes', 0):.0f} min",
    }
    return texts.get(e.type, e.type)


# ---------------------------------------------------------------- clips and review


def clips(
    core: Core, *, campaign_id: int | None = None, status: str | None = None, min_score: float | None = None
) -> list[S.ClipRow]:
    with core.db.read() as s:
        q = select(Clip).order_by(col(Clip.id).desc())
        if campaign_id is not None:
            q = q.where(Clip.campaign_id == campaign_id)
        if status:
            q = q.where(Clip.status == status)
        rows = clip_rows(core, s, list(s.exec(q.limit(500)).all()))
    if min_score is not None:
        rows = [r for r in rows if r.score >= min_score]
    return rows


def clip_detail(core: Core, clip_id: int) -> S.ClipDetail | None:
    with core.db.read() as s:
        c = s.get(Clip, clip_id)
        if c is None:
            return None
        row = clip_rows(core, s, [c])[0]
        m = s.get(Moment, c.moment_id)
        assert m is not None
        src = s.get(Source, m.source_id)
        analysis = s.get(Analysis, m.source_id)
        review = s.get(Review, clip_id)
        posts = s.exec(select(Post).where(Post.clip_id == clip_id)).all()
        accounts = {a.id: a for a in s.exec(select(Account)).all()}
        metrics = _latest_metrics(s)
        variants = s.exec(
            select(Clip).where(
                (Clip.variant_of == (c.variant_of or c.id)) | (Clip.id == (c.variant_of or -1))
            )
        ).all()
        variant_rows = clip_rows(core, s, [v for v in variants if v.id != clip_id])
    words = [
        w
        for w in load_words(analysis.transcript_path if analysis else None)
        if w["end"] > m.start - 5 and w["start"] < m.end + 5
    ][:600]
    if not words and analysis:
        words = load_words(analysis.transcript_path)[:200]
    signals = dict(analysis.signals_json) if analysis else {}
    signals["heatmap"] = [float(h.get("value", 0)) for h in (src.heatmap_json if src else [])]
    signals["source_duration"] = src.duration if src else None
    return S.ClipDetail(
        clip=row,
        source_id=m.source_id,
        source_title=src.title if src else None,
        source_range=[m.start, m.end],
        reason=m.reason,
        payoff=m.payoff,
        scores=dict(m.scores_json),
        qa=dict(c.qa_json),
        review={
            "decision": review.decision,
            "reason": review.reason,
            "platforms": review.platforms,
            "captions": review.captions_json,
            "via": review.via,
            "reviewer": review.reviewer,
            "batch_id": review.batch_id,
        }
        if review
        else None,
        posts=[post_out(p, accounts.get(p.account_id), metrics.get(p.id or -1), c) for p in posts],
        variants=variant_rows,
        transcript=[S.WordOut(t=w["start"], end=w["end"], text=w["text"]) for w in words],
        signals=signals,
    )


def batches(core: Core, status: str | None = None) -> list[S.BatchRow]:
    with core.db.read() as s:
        q = select(ReviewBatch).order_by(col(ReviewBatch.id).desc())
        if status:
            q = q.where(ReviewBatch.status == status)
        rows = s.exec(q).all()
        out: list[S.BatchRow] = []
        for b in rows:
            camp = s.get(Campaign, b.campaign_id)
            src = s.get(Source, b.source_id) if b.source_id else None
            revs = s.exec(select(Review).where(Review.batch_id == b.id)).all()
            out.append(
                S.BatchRow(
                    id=b.id or 0,
                    campaign_id=b.campaign_id,
                    campaign_title=camp.title if camp else "?",
                    source_title=src.title if src else None,
                    status=b.status,
                    total=len(revs),
                    approved=sum(1 for r in revs if r.decision == "approved"),
                    rejected=sum(1 for r in revs if r.decision == "rejected"),
                    pending=sum(1 for r in revs if r.decision == "pending"),
                    created_at=b.created_at,
                    timeout_at=b.timeout_at,
                )
            )
    return out


def batch_detail(core: Core, batch_id: int) -> S.BatchDetail | None:
    rows = [b for b in batches(core) if b.id == batch_id]
    if not rows:
        return None
    with core.db.read() as s:
        revs = s.exec(
            select(Review, Clip)
            .join(Clip, col(Clip.id) == col(Review.clip_id))
            .where(Review.batch_id == batch_id)
        ).all()
        camp = s.get(Campaign, rows[0].campaign_id)
        enabled = {p.id for p in s.exec(select(Platform).where(col(Platform.enabled))).all()}
        crows = {r.id: r for r in clip_rows(core, s, [c for _, c in revs])}
        moments = {
            m.id: m
            for m in s.exec(select(Moment).where(col(Moment.id).in_([c.moment_id for _, c in revs]))).all()
        }
    spec = ClipSpec.model_validate(camp.spec_json or {}) if camp else ClipSpec()
    allowed_by_campaign = set(camp.platforms) if camp and camp.platforms else set(PLATFORM_NAMES)
    if spec.platforms:
        allowed_by_campaign &= set(spec.platforms)
    platforms_allowed = [p for p in PLATFORM_NAMES if p in allowed_by_campaign and p in enabled]
    clips_out: list[S.ReviewClip] = []
    for r, c in sorted(
        revs, key=lambda rc: -(moments[rc[1].moment_id].final_score if rc[1].moment_id in moments else 0)
    ):
        m = moments.get(c.moment_id)
        assert c.id is not None
        clips_out.append(
            S.ReviewClip(
                clip=crows[c.id],
                source_range=[m.start, m.end] if m else [0, 0],
                reason=m.reason if m else "",
                decision=r.decision,
                decision_reason=r.reason,
                via=r.via,
                reviewer=r.reviewer,
                platforms_allowed=platforms_allowed,
                platforms=[p for p in r.platforms if p in platforms_allowed],
                captions={k: v for k, v in r.captions_json.items() if k in platforms_allowed},
                qa_ok=c.qa_json.get("ok"),
            )
        )
    return S.BatchDetail(
        batch=rows[0], clips=clips_out, approve_all_threshold=core.settings.review.approve_all_threshold
    )


# ---------------------------------------------------------------- edit


def edit_state(core: Core, clip_id: int) -> S.EditState | None:
    with core.db.read() as s:
        c = s.get(Clip, clip_id)
        row = s.get(Edl, clip_id)
        if c is None or row is None:
            return None
        crow = clip_rows(core, s, [c])[0]
        history = s.exec(select(EditOp).where(EditOp.clip_id == clip_id).order_by(col(EditOp.id))).all()
        plan = s.exec(
            select(AgendaItem)
            .where(AgendaItem.scope == "clip", AgendaItem.scope_id == str(clip_id))
            .order_by(col(AgendaItem.ord))
        ).all()
        notes = s.exec(
            select(Note).where(Note.scope == "clip", Note.scope_id == str(clip_id)).order_by(col(Note.id))
        ).all()
        status_ev = s.exec(
            select(Event)
            .where(Event.type == "edit.status", Event.entity_id == str(clip_id))
            .order_by(col(Event.id).desc())
            .limit(1)
        ).first()
        moment = s.get(Moment, c.moment_id)
        src = s.get(Source, moment.source_id) if moment else None
        variants = s.exec(
            select(Clip).where((Clip.variant_of == clip_id) | (Clip.id == (c.variant_of or -1)))
        ).all()
        vrows = clip_rows(core, s, [v for v in variants if v.id != clip_id])
    fresh = status_ev is not None and core.clock.now() - status_ev.ts < timedelta(minutes=5)
    edl = dict(row.data)
    duration = sum(float(sg["end"]) - float(sg["start"]) for sg in edl.get("segments", []))
    return S.EditState(
        clip=crow,
        edl=edl,
        version=row.version,
        locked_by=row.locked_by,
        duration=round(duration, 3),
        history=[
            S.EditOpOut(
                id=h.id or 0,
                version=h.version,
                actor=h.actor,
                op=h.op,
                reason=h.reason,
                ts=h.ts,
                undone=h.undone,
            )
            for h in history
        ],
        plan=[S.AgendaItemOut(id=p.id or 0, text=p.text, status=p.status, result=p.result) for p in plan],
        notes=[note_out(n) for n in notes],
        live_status=str(status_ev.payload.get("text")) if fresh and status_ev else None,
        live_range=list(status_ev.payload.get("range") or []) or None if fresh and status_ev else None,
        proxy_url=f"/api/files/clip/{clip_id}/proxy" if (src and (src.proxy_path or src.path)) else None,
        variants=vrows,
    )


# ---------------------------------------------------------------- publishing


def accounts(core: Core) -> list[S.AccountOut]:
    now = core.clock.now()
    profiles = set(core.adapters.browser.connected_profiles())
    out: list[S.AccountOut] = []
    raw = {a["id"]: a for a in core.publishing.list_accounts()}
    with core.db.read() as s:
        rows = s.exec(select(Account)).all()
    for a in rows:
        r = raw[a.id]
        week = None
        if a.warmup_started is not None:
            age = now - a.warmup_started
            week = 1 if age < timedelta(days=7) else 2 if age < timedelta(days=14) else None
        out.append(
            S.AccountOut(
                id=a.id or 0,
                platform=a.platform,
                handle=a.handle,
                niche_tags=list(a.niche_tags),
                chrome_profile=a.chrome_profile,
                enabled=a.enabled,
                status=a.status,
                paused_reason=a.paused_reason,
                posts_today=r["posts_today"],
                cap_today=r["cap_today"],
                min_gap_min=r["min_gap_min"],
                warmup_week=week,
                extension_connected=a.chrome_profile in profiles,
            )
        )
    return out


def calendar(core: Core, start: datetime, end: datetime) -> S.CalendarOut:
    with core.db.read() as s:
        posts = s.exec(
            select(Post)
            .where(col(Post.scheduled_at) >= start, col(Post.scheduled_at) < end)
            .order_by(col(Post.scheduled_at))
        ).all()
        accts = {a.id: a for a in s.exec(select(Account)).all()}
        clips_by_id = {c.id: c for c in s.exec(select(Clip)).all()}
        metrics = _latest_metrics(s)
        plats = {p.id: p.enabled for p in s.exec(select(Platform)).all()}
    return S.CalendarOut(
        accounts=accounts(core),
        posts=[
            post_out(p, accts.get(p.account_id), metrics.get(p.id or -1), clips_by_id.get(p.clip_id))
            for p in posts
            if p.status != "cancelled"
        ],
        platforms_enabled=plats,
    )


def recipes(core: Core) -> list[S.RecipeHealth]:
    since = core.clock.now() - timedelta(days=7)
    with core.db.read() as s:
        runs = s.exec(select(RecipeRun).order_by(col(RecipeRun.ts))).all()
    by: dict[str, list[RecipeRun]] = defaultdict(list)
    for r in runs:
        by[r.recipe].append(r)
    names = [
        "youtube.upload_short",
        "tiktok.upload",
        "instagram.upload_reel",
        "x.post_video",
        "vyro.list_campaigns",
        "vyro.submit_url",
        "whop.list_campaigns",
        "whop.submit_url",
    ]
    out: list[S.RecipeHealth] = []
    for name in sorted(set(names) | set(by)):
        rs = by.get(name, [])
        ok = [r for r in rs if r.ok]
        bad = [r for r in rs if not r.ok]
        last_bad = bad[-1] if bad else None
        out.append(
            S.RecipeHealth(
                recipe=name,
                last_success=ok[-1].ts if ok else None,
                last_failure=last_bad.ts if last_bad else None,
                last_error=last_bad.error if last_bad else None,
                screenshot_url=f"/api/files/screenshot/{last_bad.id}"
                if last_bad and last_bad.screenshot_path
                else None,
                runs_7d=sum(1 for r in rs if r.ts >= since),
                failures_7d=sum(1 for r in bad if r.ts >= since),
            )
        )
    return out


# ---------------------------------------------------------------- earnings


def median_find_to_post_hours(camps: Iterable[Campaign], posts: Iterable[Post]) -> float | None:
    """Median hours from a taken campaign being found to its first live post."""
    posts = list(posts)
    hours: list[float] = []
    for c in camps:
        if not c.taken_at:
            continue
        first = min((p.posted_at for p in posts if p.campaign_id == c.id and p.posted_at), default=None)
        if first is not None and first >= c.found_at:
            hours.append((first - c.found_at).total_seconds() / 3600)
    return sorted(hours)[len(hours) // 2] if hours else None


def earnings(core: Core, days: int = 30) -> S.EarningsOut:
    now = core.clock.now()
    start = now - timedelta(days=days)
    with core.db.read() as s:
        metrics = [m for m in s.exec(select(Metric)).all() if m.ts >= start]
        posts = {p.id: p for p in s.exec(select(Post)).all()}
        camps = {c.id: c for c in s.exec(select(Campaign)).all()}
        accts = {a.id: a for a in s.exec(select(Account)).all()}
        subs = s.exec(select(Submission)).all()
        reviews = s.exec(select(Review).where(col(Review.decision).in_(["approved", "rejected"]))).all()
        clips_by_id = {c.id: c for c in s.exec(select(Clip)).all()}
        top_ids = sorted(
            {p.clip_id for p in posts.values()},
            key=lambda cid: (
                -sum(m.earnings for m in metrics if posts.get(m.post_id) and posts[m.post_id].clip_id == cid)
            ),
        )[:8]
        top = clip_rows(core, s, [clips_by_id[c] for c in top_ids if c in clips_by_id])
    series: dict[str, S.SeriesPoint] = {}
    groups: dict[str, dict[str, dict[str, float]]] = {
        "marketplace": {},
        "campaign": {},
        "platform": {},
        "account": {},
    }
    for m in metrics:
        p = posts.get(m.post_id)
        if p is None:
            continue
        camp = camps.get(p.campaign_id)
        market = camp.marketplace if camp else "other"
        day = m.ts.date().isoformat()
        pt = series.setdefault(day, S.SeriesPoint(day=day, earnings={}, views={}))
        pt.earnings[market] = round(pt.earnings.get(market, 0.0) + m.earnings, 2)
        pt.views[market] = pt.views.get(market, 0) + m.views
        keys = {
            "marketplace": market,
            "campaign": str(p.campaign_id),
            "platform": p.platform,
            "account": str(p.account_id),
        }
        for g, k in keys.items():
            agg = groups[g].setdefault(k, {"earnings": 0.0, "views": 0.0, "posts": 0.0})
            agg["earnings"] += m.earnings
            agg["views"] += m.views
            agg["posts"] += 1

    def label(g: str, k: str) -> str:
        if g == "campaign":
            c = camps.get(int(k)) if k.isdigit() else None
            return c.title if c else k
        if g == "account":
            a = accts.get(int(k)) if k.isdigit() else None
            return a.handle if a else k
        if g == "platform":
            return PLATFORM_NAMES.get(k, k)
        return {"vyro": "Vyro", "whop": "Whop"}.get(k, k)

    def rows(g: str) -> list[S.BreakdownRow]:
        out: list[S.BreakdownRow] = []
        for k, v in sorted(groups[g].items(), key=lambda kv: -kv[1]["earnings"]):
            row = S.BreakdownRow(
                key=k,
                label=label(g, k),
                earnings=round(v["earnings"], 2),
                views=int(v["views"]),
                posts=int(v["posts"]),
            )
            if g == "marketplace":
                ms = [x for x in subs if x.marketplace == k]
                row.approval_rate = (
                    round(sum(1 for x in ms if x.external_status in ("approved", "paid")) / len(ms), 3)
                    if ms
                    else None
                )
                row.avg_cpm = round(v["earnings"] / v["views"] * 1000, 2) if v["views"] else None
                # payout dates aren't tracked yet (needs the marketplace payouts page): unknown, not guessed
                row.payout_delay_days = None
            out.append(row)
        return out

    total = round(sum(m.earnings for m in metrics), 2)
    approval = sum(1 for r in reviews if r.decision == "approved") / len(reviews) if reviews else None
    earning_posts = {m.post_id for m in metrics}
    clip_count = len({posts[pid].clip_id for pid in earning_posts if pid in posts})
    return S.EarningsOut(
        days=days,
        total=total,
        series=[series[k] for k in sorted(series)],
        by_marketplace=rows("marketplace"),
        by_campaign=rows("campaign"),
        by_platform=rows("platform"),
        by_account=rows("account"),
        top_clips=top,
        units={
            "usd_per_clip": round(total / clip_count, 2) if clip_count else None,
            "usd_per_gpu_hour": None,
            "approval_rate": round(approval, 3) if approval is not None else None,
            "median_find_to_post_h": median_find_to_post_hours(camps.values(), posts.values()),
        },
    )


# ---------------------------------------------------------------- tools, lessons, questions


def tools_overview(core: Core) -> S.ToolsOut:
    since = core.clock.now() - timedelta(days=7)
    with core.db.read() as s:
        evs = s.exec(
            select(AgentEvent).where(col(AgentEvent.ts) >= since, col(AgentEvent.tool).is_not(None))
        ).all()
    stats: list[S.ToolStat] = []
    for server, tools in CATALOG.items():
        prefix = f"mcp__{server}__"
        mine = [e for e in evs if (e.tool or "").startswith(prefix)]
        stats.append(
            S.ToolStat(
                server=server,
                tools=len(tools),
                read_only=sum(1 for ro in tools.values() if ro),
                calls_7d=sum(1 for e in mine if e.type == "tool_result"),
                errors_7d=sum(1 for e in mine if e.type == "tool_result" and "error" in e.output_json),
                blocked_7d=sum(1 for e in mine if e.type == "blocked"),
            )
        )
    return S.ToolsOut(
        servers=stats,
        access={k: list(v) for k, v in ACCESS.items()},
        subagents={k: list(v) for k, v in SUBAGENTS.items()},
    )


def lessons(core: Core, scope: str | None = None, q: str | None = None) -> list[S.LessonOut]:
    with core.db.read() as s:
        query = select(Lesson).where(col(Lesson.active)).order_by(col(Lesson.id).desc())
        if scope:
            query = query.where(Lesson.scope == scope)
        if q:
            query = query.where(col(Lesson.note).ilike(f"%{q}%"))
        rows = s.exec(query).all()
    return [S.LessonOut.model_validate(r) for r in rows]


def questions(core: Core, status: str | None = "open") -> list[S.QuestionOut]:
    with core.db.read() as s:
        q = select(Question).order_by(col(Question.id).desc())
        if status:
            q = q.where(Question.status == status)
        rows = s.exec(q).all()
    return [
        S.QuestionOut(
            id=r.id or 0,
            session_id=r.session_id,
            campaign_id=r.campaign_id,
            text=r.text,
            options=list(r.options_json),
            status=r.status,
            answer=r.answer,
            created_at=r.created_at,
            timeout_at=r.timeout_at,
        )
        for r in rows
    ]


def jobs(core: Core, limit: int = 50) -> list[S.JobOut]:
    with core.db.read() as s:
        rows = s.exec(select(Job).order_by(col(Job.id).desc()).limit(limit)).all()
    return [
        S.JobOut(
            id=j.id or 0,
            kind=j.kind,
            status=j.status,
            progress=j.progress,
            campaign_id=j.campaign_id,
            error=j.error,
            created_at=j.created_at,
            started_at=j.started_at,
            finished_at=j.finished_at,
        )
        for j in rows
    ]
