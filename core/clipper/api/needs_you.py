"""Needs you: everything waiting on you, ranked by urgency, and the full story of one item.

Items are computed from the tables on every read (nothing is stored per item). What you did about one
(snoozed, dismissed) is in the ``attention`` table and only hides it. Every item has a stable ``key``
(``question:6``, ``failure:job:2``), which is what the detail and reply routes take.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from sqlmodel import col, func, select

from clipper.api import schemas as S  # noqa: N812
from clipper.api.views import PLATFORM_NAMES, event_text, file_url, link_out
from clipper.db.models import (
    Account,
    AgentEvent,
    AgentSession,
    Campaign,
    Clip,
    Event,
    Job,
    Question,
    RecipeRun,
    Review,
    ReviewBatch,
    Source,
)
from clipper.db.types import SourceStatus
from clipper.rules.urls import download_support, host_of
from clipper.services.attention import DISMISSABLE

if TYPE_CHECKING:
    from clipper.core import Core

URGENCY = {
    "challenge": 0,
    "question": 1,
    "footage": 1,
    "stuck": 2,
    "join": 2,
    "review": 3,
    "campaign": 4,
    "alert": 5,
    "failure": 6,
}
SOON = timedelta(hours=2)  # a review batch that times out within this jumps ahead of campaign picks
ALERT_AGE = timedelta(days=3)
FAILURE_AGE = timedelta(days=7)
MERGE_WINDOW = timedelta(hours=1)
MAX_ALERTS = 5
MAX_FAILURES = 5
MAX_STUCK = 6
STALL_NAMES = {
    "session_hung": "Agent not responding",
    "waiting_on_nothing": "Waiting on nothing",
    "request_blocked": "Request can't start",
    "job_stalled": "Job stopped moving",
    "job_waiting": "Job waiting",
    "recipe_stuck": "Upload stuck",
    "post_overdue": "Post overdue",
}
SNOOZE_MINUTES = [60, 240, 1440]
MARKET_NAMES = {"vyro": "Vyro", "whop": "Whop"}
SUPPORT_TEXT = {
    "yes": "Yes",
    "try": "It might work, but this host often blocks downloaders",
    "no": "No: these are share pages, not video files",
}
JOB_LABEL = {
    "download": "Download",
    "analyze": "Analysis",
    "render_preview": "Preview render",
    "render_final": "Final render",
    "import": "File import",
}


def _utc(value: datetime) -> datetime:
    from clipper.clock import ensure_utc

    return ensure_utc(value)


def _first_paragraph(text: str, limit: int = 220) -> str:
    return text.strip().split("\n\n", 1)[0].replace("\n", " ")[:limit]


# ---------------------------------------------------------------- the list


def build(core: Core, *, include_hidden: bool = False) -> list[S.NeedsYouItem]:
    now = core.clock.now()
    hidden: set[str] = set() if include_hidden else core.attention.hidden(now)
    items: list[S.NeedsYouItem] = []
    with core.db.read() as s:
        camps = {c.id: c for c in s.exec(select(Campaign)).all()}
        titles = {cid: c.title for cid, c in camps.items()}
        sessions = {a.id: a for a in s.exec(select(AgentSession)).all()}
        paused = list(s.exec(select(Account).where(Account.status == "paused")).all())
        paused_at: dict[str, datetime] = {}
        for e in s.exec(select(Event).where(Event.type == "account.paused").order_by(col(Event.id))).all():
            if e.entity_id:
                paused_at[e.entity_id] = e.ts
        for a in paused:
            items.append(
                S.NeedsYouItem(
                    kind="challenge",
                    urgency=URGENCY["challenge"],
                    key=f"challenge:{a.id}",
                    title=f"{PLATFORM_NAMES.get(a.platform, a.platform)} {a.handle} paused",
                    detail=a.paused_reason or "challenge screen",
                    since=paused_at.get(str(a.id)),
                    actions=[
                        S.NeedsYouAction(
                            label="Open window", action="open_profile", args={"profile": a.chrome_profile}
                        ),
                        S.NeedsYouAction(label="Resume", action="resume_account", args={"account_id": a.id}),
                    ],
                )
            )
        for q in s.exec(select(Question).where(Question.status == "open").order_by(col(Question.id))).all():
            session = sessions.get(q.session_id) if q.session_id else None
            who = f"the {session.role} agent" if session else "an agent"
            items.append(
                S.NeedsYouItem(
                    kind="question",
                    urgency=URGENCY["question"],
                    key=f"question:{q.id}",
                    title=q.text,
                    detail=f"Asked by {who}",
                    campaign_id=q.campaign_id,
                    campaign_title=titles.get(q.campaign_id),
                    since=q.created_at,
                    timeout_at=q.timeout_at,
                    options=list(q.options_json),
                    actions=[
                        S.NeedsYouAction(label=o, action="answer", args={"question_id": q.id, "answer": o})
                        for o in q.options_json
                    ],
                )
            )
        for b in s.exec(
            select(ReviewBatch).where(ReviewBatch.status != "shipped").order_by(col(ReviewBatch.timeout_at))
        ).all():
            pending = s.exec(
                select(func.count())
                .select_from(Review)
                .where(Review.batch_id == b.id, Review.decision == "pending")
            ).one()
            total = s.exec(select(func.count()).select_from(Review).where(Review.batch_id == b.id)).one()
            soon = b.timeout_at is not None and _utc(b.timeout_at) - now <= SOON
            items.append(
                S.NeedsYouItem(
                    kind="review",
                    urgency=URGENCY["review"] - (1 if soon else 0),
                    key=f"review:{b.id}",
                    title=f"{pending} of {total} clips to review: {titles.get(b.campaign_id, b.campaign_id)}",
                    detail=f"Batch {b.id}",
                    campaign_id=b.campaign_id,
                    campaign_title=titles.get(b.campaign_id),
                    since=b.created_at,
                    timeout_at=b.timeout_at,
                    actions=[S.NeedsYouAction(label="Review", action="review", args={"batch_id": b.id})],
                )
            )
        joining: set[int] = set()  # campaigns you took that Clipper can't join for you
        for c in s.exec(
            select(Campaign)
            .where(col(Campaign.status).in_(["suggested", "needs_user"]))
            .order_by(col(Campaign.score).desc())
        ).all():
            if c.status == "needs_user" and c.taken_at is not None and c.id is not None:
                joining.add(c.id)
                site = MARKET_NAMES.get(c.marketplace, c.marketplace.capitalize())
                items.append(
                    S.NeedsYouItem(
                        kind="join",
                        urgency=URGENCY["join"],
                        key=f"join:{c.id}",
                        title=f"Join {c.title} on {site}",
                        detail="Clipper can't join this one for you",
                        campaign_id=c.id,
                        campaign_title=c.title,
                        since=c.updated_at,
                        actions=[
                            S.NeedsYouAction(
                                label=f"Open on {site}", action="open_link", args={"campaign_id": c.id}
                            ),
                            S.NeedsYouAction(
                                label="I've joined", action="mark_joined", args={"campaign_id": c.id}
                            ),
                            S.NeedsYouAction(label="Skip", action="skip", args={"campaign_id": c.id}),
                        ],
                    )
                )
                continue
            if c.status == "suggested" and (c.score or 0) < core.settings.scout.min_score_to_post_card:
                continue
            title = (
                f"New campaign: {c.title}, score {c.score:.0f}, ${c.cpm:g} CPM"
                if c.status == "suggested"
                else f"{c.title}: {c.score_reason or 'needs you'}"
            )
            items.append(
                S.NeedsYouItem(
                    kind="campaign",
                    urgency=URGENCY["campaign"],
                    key=f"campaign:{c.id}",
                    title=title,
                    detail=c.marketplace.capitalize(),
                    campaign_id=c.id,
                    campaign_title=c.title,
                    since=c.found_at,
                    actions=[
                        S.NeedsYouAction(label="Take", action="take", args={"campaign_id": c.id}),
                        S.NeedsYouAction(label="Skip", action="skip", args={"campaign_id": c.id}),
                    ]
                    if c.status == "suggested"
                    else [S.NeedsYouAction(label="Open", action="open_campaign", args={"campaign_id": c.id})],
                )
            )
        items += _alerts(core, s, now, titles, [a.handle for a in paused], joining)
        footage, covered = _footage(core, s, now, camps)
        items += footage
        items += _failures(core, s, now, titles, covered)
        items += _stuck(core, titles)
    for i in items:
        camp = camps.get(i.campaign_id)
        if camp is not None:
            i.links = [*i.links, link_out(core, camp)]
    visible = [i for i in items if i.key not in hidden]
    return sorted(visible, key=lambda i: (i.urgency, i.since is None, i.since or now, i.key))


def _alerts(
    core: Core, s: Any, now: datetime, titles: dict[int | None, str], paused: list[str], joining: set[int]
) -> list[S.NeedsYouItem]:
    """Warnings and errors from the last three days, repeats merged, minus what is already shown
    another way (a paused account) or no longer true (a usage limit that has lifted)."""
    rows = s.exec(select(Event).where(Event.type == "alert").order_by(col(Event.id).desc()).limit(300)).all()
    rate_limited = core.usage.current().rate_limited
    groups: dict[tuple[str, int | None, str], list[Event]] = defaultdict(list)
    for e in rows:
        p = e.payload
        text = str(p.get("text", ""))
        if p.get("level") not in ("warning", "error") or now - _utc(e.ts) > ALERT_AGE:
            continue
        if p.get("source") == "stalls":
            continue  # the stuck item says it, and goes away when it is fixed
        if any(handle in text for handle in paused):
            continue  # the blocked account is listed on its own
        if text.startswith("Claude usage limit reached") and not rate_limited:
            continue
        if p.get("campaign_id") in joining and "needs you to join" in text:
            continue  # the join item says it
        groups[(str(p.get("source", "")), p.get("campaign_id"), text)].append(e)
    out: list[S.NeedsYouItem] = []
    for (source, campaign_id, text), events in groups.items():
        newest = events[0]  # rows are newest first
        recent = [e for e in events if _utc(newest.ts) - _utc(e.ts) <= MERGE_WINDOW]
        cid = int(campaign_id) if campaign_id is not None else None
        out.append(
            S.NeedsYouItem(
                kind="alert",
                urgency=URGENCY["alert"],
                key=f"alert:{newest.id}",
                title=text,
                detail=f"{newest.payload.get('level')} from {source or 'the system'}"
                + (f" · seen {len(recent)} times" if len(recent) > 1 else ""),
                campaign_id=cid,
                campaign_title=titles.get(cid),
                since=newest.ts,
                count=len(recent),
                dismissable=True,
                actions=[S.NeedsYouAction(label="Open", action="open_campaign", args={"campaign_id": cid})]
                if cid is not None
                else [],
            )
        )
    return sorted(out, key=lambda i: i.since or now, reverse=True)[:MAX_ALERTS]


def _stuck(core: Core, titles: dict[int | None, str]) -> list[S.NeedsYouItem]:
    """Things that look stuck (a hung agent, a job that stopped moving, a request that can't start), each
    with the actions that could help. The detector is ``supervisor/stalls.py``."""
    from clipper.supervisor.stall_actions import LABELS
    from clipper.supervisor.stalls import build_snapshot, detect_stalls

    out: list[S.NeedsYouItem] = []
    for st in detect_stalls(build_snapshot(core), core.settings.stalls)[:MAX_STUCK]:
        out.append(
            S.NeedsYouItem(
                kind="stuck",
                urgency=URGENCY["stuck"],
                key=f"stuck:{st.key}",
                title=st.summary,
                detail=st.evidence[0] if st.evidence else STALL_NAMES.get(st.kind, st.kind),
                campaign_id=st.campaign_id,
                campaign_title=titles.get(st.campaign_id),
                since=st.since,
                actions=[
                    S.NeedsYouAction(label=LABELS.get(a, a), action=a, args={"stall": st.key})
                    for a in st.actions
                ],
            )
        )
    return out


def source_link(src: Source) -> S.Link | None:
    """The page a source points at, for you to open and download from. It came from a campaign page
    (untrusted), so only a plain http(s) address is offered and the host is shown beside it."""
    host = host_of(src.url)
    if not host or not src.url.lower().startswith(("http://", "https://")):
        return None
    return S.Link(label=f"Open on {host}", url=src.url, kind="source", host=host, open_in="default")


def _importing(s: Any) -> dict[int, Job]:
    """Files being copied in right now: the open import jobs, by the source they are for."""
    out: dict[int, Job] = {}
    for j in s.exec(
        select(Job).where(Job.kind == "import", col(Job.status).in_(["queued", "running"]))
    ).all():
        sid = j.input_json.get("source_id")
        if isinstance(sid, int):
            out[sid] = j
    return out


def _footage(
    core: Core, s: Any, now: datetime, camps: dict[int | None, Campaign]
) -> tuple[list[S.NeedsYouItem], set[int]]:
    """Sources that are waiting for a video from you (the download failed, or can't be tried at all),
    one item each. Returns the items and the source ids they stand for, so their failed jobs aren't
    listed a second time."""
    importing = _importing(s)
    waiting = list(
        s.exec(
            select(Source).where(col(Source.status).in_([SourceStatus.FAILED, SourceStatus.NEEDS_FOOTAGE]))
        ).all()
    )
    out: list[S.NeedsYouItem] = []
    covered: set[int] = set()
    for src in waiting:
        camp = camps.get(src.campaign_id)
        if src.id is None or camp is None or camp.status in ("ended", "skipped"):
            continue
        covered.add(src.id)
        host = host_of(src.url) or "this source"
        job = importing.get(src.id)
        activity = (
            S.JobActivity(job_id=job.id or 0, kind="import", label="Adding your file", progress=job.progress)
            if job is not None
            else None
        )
        link = source_link(src)
        out.append(
            S.NeedsYouItem(
                kind="footage",
                urgency=URGENCY["footage"],
                key=f"footage:{src.id}",
                title=f"Add the video from {host}",
                detail=_first_paragraph(src.reason or "The download didn't work."),
                campaign_id=camp.id,
                campaign_title=camp.title,
                since=src.waiting_since or src.created_at,
                links=[link] if link else [],
                activity=activity,
                actions=[
                    S.NeedsYouAction(label="Add file", action="add_file", args={"source_id": src.id}),
                    S.NeedsYouAction(
                        label="Retry download", action="retry_source", args={"source_id": src.id}
                    ),
                    S.NeedsYouAction(label="Skip source", action="skip_source", args={"source_id": src.id}),
                ],
            )
        )
    for src_id in importing:  # a file is being added: keep the item until it has landed
        covered.add(src_id)
    return out, covered


def _identity(job: Job) -> tuple[str, Any]:
    inp = job.input_json
    return job.kind, inp.get("source_id") or inp.get("clip_id") or inp.get("url") or job.id


def _failures(
    core: Core, s: Any, now: datetime, titles: dict[int | None, str], covered: set[int]
) -> list[S.NeedsYouItem]:
    """Failed jobs that nothing has fixed since: the newest failure per input, with no later success
    and no retry in flight, in the last seven days."""
    rows = list(s.exec(select(Job).order_by(col(Job.id).desc()).limit(300)).all())
    settled: set[tuple[str, Any]] = set()  # inputs a newer job already finished or is still running
    seen: set[tuple[str, Any]] = set()
    out: list[S.NeedsYouItem] = []
    for j in rows:
        ident = _identity(j)
        if j.status in ("done", "queued", "running"):
            settled.add(ident)
            continue
        if j.status != "failed" or ident in settled or ident in seen:
            continue
        if j.kind in ("download", "import") and j.input_json.get("source_id") in covered:
            continue  # the source's own item says it, with a place to drop the file
        seen.add(ident)
        if now - _utc(j.finished_at or j.created_at) > FAILURE_AGE:
            continue
        label = JOB_LABEL.get(j.kind, j.kind)
        actions = [S.NeedsYouAction(label="Retry", action="retry_job", args={"job_id": j.id})]
        if j.campaign_id is not None:
            actions.append(
                S.NeedsYouAction(label="Open", action="open_campaign", args={"campaign_id": j.campaign_id})
            )
        out.append(
            S.NeedsYouItem(
                kind="failure",
                urgency=URGENCY["failure"],
                key=f"failure:job:{j.id}",
                title=f"{label} failed",
                detail=_first_paragraph(j.error or ""),
                campaign_id=j.campaign_id,
                campaign_title=titles.get(j.campaign_id),
                since=j.finished_at or j.created_at,
                dismissable=True,
                actions=actions,
            )
        )
    return out[:MAX_FAILURES]


# ---------------------------------------------------------------- one item


def find(core: Core, key: str) -> S.NeedsYouItem | None:
    return next((i for i in build(core, include_hidden=True) if i.key == key), None)


def detail(core: Core, key: str) -> S.NeedsYouDetail | None:
    item = find(core, key)
    if item is None:
        return None
    kind, _, rest = key.partition(":")
    ident = int(rest.rsplit(":", 1)[-1])
    body, facts = item.title, []  # type: ignore[var-annotated]
    agent: S.AgentSaid | None = None
    evidence: S.EvidenceOut | None = None
    thumbs: list[str] = []
    footage: S.FootageOut | None = None
    reply_to: Literal["question", "campaign", "director"] = "campaign" if item.campaign_id else "director"
    with core.db.read() as s:
        if kind == "question":
            q = s.get(Question, ident)
            reply_to = "question"
            if q is not None:
                body = q.text
                session = s.get(AgentSession, q.session_id) if q.session_id else None
                facts = [
                    S.FactRow(label="Campaign", value=item.campaign_title or "none"),
                    S.FactRow(
                        label="Asked by",
                        value=f"{session.role} agent · session {session.id}" if session else "an agent",
                    ),
                    S.FactRow(label="Asked", value="", at=q.created_at),
                    S.FactRow(label="Times out", value="", at=q.timeout_at)
                    if q.timeout_at
                    else S.FactRow(label="Times out", value="no timeout"),
                ]
                if session is not None:
                    said = s.exec(
                        select(AgentEvent)
                        .where(AgentEvent.session_id == session.id, AgentEvent.type == "message")
                        .order_by(col(AgentEvent.id).desc())
                        .limit(3)
                    ).all()
                    agent = S.AgentSaid(
                        session_id=session.id or 0,
                        role=session.role,
                        status=session.status,
                        messages=[
                            S.AgentMessage(ts=m.ts, text=str(m.input_json.get("text", ""))) for m in said
                        ],
                    )
        elif kind == "challenge":
            a = s.get(Account, ident)
            if a is not None:
                body = a.paused_reason or "A challenge screen stopped the account."
                facts = [
                    S.FactRow(
                        label="Account", value=f"{PLATFORM_NAMES.get(a.platform, a.platform)} {a.handle}"
                    ),
                    S.FactRow(label="Chrome profile", value=a.chrome_profile),
                    S.FactRow(label="Paused", value="", at=item.since)
                    if item.since
                    else S.FactRow(label="Paused", value="unknown"),
                ]
                runs = s.exec(
                    select(RecipeRun)
                    .where(RecipeRun.account_id == a.id)
                    .order_by(col(RecipeRun.id).desc())
                    .limit(5)
                ).all()
                bad = next((r for r in runs if not r.ok), None)
                evidence = S.EvidenceOut(
                    error=bad.error if bad else None,
                    screenshot_url=f"/api/files/screenshot/{bad.id}" if bad and bad.screenshot_path else None,
                )
        elif kind == "review":
            b = s.get(ReviewBatch, ident)
            if b is not None:
                rows = s.exec(select(Review).where(Review.batch_id == b.id)).all()
                counts = {
                    d: sum(1 for r in rows if r.decision == d) for d in ("pending", "approved", "rejected")
                }
                body = f"{counts['pending']} of {len(rows)} clips are waiting for a decision."
                facts = [
                    S.FactRow(label="Campaign", value=item.campaign_title or "none"),
                    S.FactRow(label="Batch", value=str(b.id)),
                    S.FactRow(
                        label="Decided",
                        value=f"{counts['approved']} approved · {counts['rejected']} rejected · {counts['pending']} pending",
                    ),
                    S.FactRow(label="Times out", value="", at=b.timeout_at)
                    if b.timeout_at
                    else S.FactRow(label="Times out", value="no timeout"),
                ]
                for r in rows[:6]:
                    clip = s.get(Clip, r.clip_id)
                    url = file_url("thumb", r.clip_id, clip.thumb_path if clip else None)
                    if url:
                        thumbs.append(url)
        elif kind == "join":
            c = s.get(Campaign, ident)
            if c is not None:
                site = MARKET_NAMES.get(c.marketplace, c.marketplace.capitalize())
                body = (
                    f"Clipper can't join {site} campaigns for you. Open the campaign, press Join there, then "
                    "come back and press I've joined: the campaign's agent carries on from there."
                )
                facts = [
                    S.FactRow(label="Marketplace", value=site),
                    S.FactRow(label="CPM", value=f"${c.cpm:g}"),
                    S.FactRow(label="Deadline", value="no deadline")
                    if c.deadline is None
                    else S.FactRow(label="Deadline", value="", at=c.deadline),
                    S.FactRow(label="Platforms", value=", ".join(c.platforms) or "any"),
                ]
        elif kind == "campaign":
            c = s.get(Campaign, ident)
            if c is not None:
                body = c.score_reason or c.title
                facts = [
                    S.FactRow(label="Marketplace", value=c.marketplace.capitalize()),
                    S.FactRow(label="Score", value=f"{c.score:.0f}" if c.score is not None else "not scored"),
                    S.FactRow(label="CPM", value=f"${c.cpm:g}"),
                    S.FactRow(
                        label="Budget left",
                        value=f"${c.budget_left:,.0f}" if c.budget_left is not None else "unknown",
                    ),
                    S.FactRow(label="Deadline", value="no deadline")
                    if c.deadline is None
                    else S.FactRow(label="Deadline", value="", at=c.deadline),
                    S.FactRow(label="Platforms", value=", ".join(c.platforms) or "any"),
                ]
        elif kind == "alert":
            e = s.get(Event, ident)
            if e is not None:
                body = str(e.payload.get("text", ""))
                facts = [
                    S.FactRow(label="Level", value=str(e.payload.get("level", ""))),
                    S.FactRow(label="From", value=str(e.payload.get("source", "the system"))),
                    S.FactRow(label="Campaign", value=item.campaign_title or "none"),
                    S.FactRow(
                        label="Seen",
                        value=str(item.count) if item.count > 1 else "once",
                        at=e.ts if item.count == 1 else None,
                    ),
                ]
        elif kind == "failure":
            j = s.get(Job, ident)
            if j is not None:
                body = _first_paragraph(j.error or "", 1500) or f"{JOB_LABEL.get(j.kind, j.kind)} failed"
                inp = j.input_json
                what = (
                    inp.get("url")
                    or (f"source {inp['source_id']}" if inp.get("source_id") else None)
                    or (f"clip {inp['clip_id']}" if inp.get("clip_id") else json.dumps(inp)[:120])
                )
                facts = [
                    S.FactRow(label="Job", value=f"{j.kind} #{j.id}"),
                    S.FactRow(label="Campaign", value=item.campaign_title or "none"),
                    S.FactRow(label="Input", value=str(what)),
                    S.FactRow(label="Started", value="", at=j.started_at)
                    if j.started_at
                    else S.FactRow(label="Started", value="never"),
                    S.FactRow(label="Failed", value="", at=j.finished_at)
                    if j.finished_at
                    else S.FactRow(label="Failed", value="unknown"),
                ]
                evidence = S.EvidenceOut(
                    error=j.error, raw_tail=str(j.result_json.get("raw_tail") or "") or None
                )
        elif kind == "stuck":
            from clipper.supervisor.stalls import build_snapshot, detect_stalls

            stall = next(
                (
                    x
                    for x in detect_stalls(build_snapshot(core), core.settings.stalls)
                    if f"stuck:{x.key}" == key
                ),
                None,
            )
            if stall is not None:
                body = stall.summary
                facts = [
                    S.FactRow(label="What", value=STALL_NAMES.get(stall.kind, stall.kind)),
                    S.FactRow(label="Campaign", value=item.campaign_title or "none"),
                    S.FactRow(label="Since", value="", at=stall.since),
                    *(
                        S.FactRow(label="Evidence" if i == 0 else "", value=line)
                        for i, line in enumerate(stall.evidence)
                    ),
                ]
        elif kind == "footage":
            src = s.get(Source, ident)
            if src is not None:
                host = host_of(src.url)
                support = download_support(src.url)
                minimum = core.media.spec_minimum(src.campaign_id)
                drop = str(core.media.drop_folder(src.campaign_id))
                why = (src.reason or "The download didn't work").strip().rstrip(".")
                body = (
                    f"{why}. Download the video yourself, then drop the file here or choose it. Clipper "
                    "copies it into the campaign's folder and the campaign's agent carries on."
                )
                facts = [
                    S.FactRow(label="Campaign", value=item.campaign_title or "none"),
                    S.FactRow(label="Source", value=src.url),
                    S.FactRow(label="Can Clipper download it?", value=SUPPORT_TEXT[support]),
                    S.FactRow(label="Waiting", value="", at=item.since)
                    if item.since
                    else S.FactRow(label="Waiting", value="unknown"),
                ]
                if minimum is not None:
                    facts.append(S.FactRow(label="Clips need to be at least", value=f"{minimum:.0f} seconds"))
                last = s.exec(
                    select(Job)
                    .where(col(Job.kind).in_(["download", "import"]), col(Job.status) == "failed")
                    .order_by(col(Job.id).desc())
                    .limit(30)
                ).all()
                bad = next((j for j in last if j.input_json.get("source_id") == ident), None)
                if bad is not None:
                    evidence = S.EvidenceOut(
                        error=bad.error, raw_tail=str(bad.result_json.get("raw_tail") or "") or None
                    )
                footage = S.FootageOut(
                    source_id=ident,
                    url=src.url,
                    host=host,
                    support=support,
                    status=src.status,
                    reason=src.reason,
                    drop_folder=drop,
                    minimum_s=minimum,
                )
        timeline: list[S.TimelineEntry] = []
        if item.campaign_id is not None:
            events = s.exec(
                select(Event)
                .where(Event.entity == "campaign", Event.entity_id == str(item.campaign_id))
                .order_by(col(Event.id).desc())
                .limit(15)
            ).all()
            timeline = [S.TimelineEntry(ts=e.ts, type=e.type, text=event_text(e)) for e in events]
    return S.NeedsYouDetail(
        item=item,
        body=body,
        facts=facts,
        agent=agent,
        evidence=evidence,
        thumbs=thumbs,
        timeline=timeline,
        reply_to=reply_to,
        snooze_options=SNOOZE_MINUTES,
        footage=footage,
    )


__all__ = ["DISMISSABLE", "build", "detail", "find"]
