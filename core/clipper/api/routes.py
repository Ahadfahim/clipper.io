"""REST routes. All mutations go through the same services (and guards) the agents use."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlmodel import col, select

from clipper.api import schemas as S  # noqa: N812
from clipper.api import views
from clipper.browser.protocol import RecipeResult
from clipper.core import Core
from clipper.db.engine import WriteTx
from clipper.db.models import (
    Account,
    AgentSession,
    Campaign,
    Clip,
    DiscordRef,
    Event,
    Lesson,
    Moment,
    Post,
    RecipeRun,
    Source,
)
from clipper.doctor import SECRETS_FIX
from clipper.events.types import UserChat
from clipper.media.edl.ops import EditError
from clipper.rules.spec import ClipSpec
from clipper.secrets import SECRET_NAMES, get_secret, set_secret
from clipper.services.base import ServiceError
from clipper.services.control import set_control
from clipper.services.recipe_check import CLIP_NAME, run_check_upload


def get_core(request: Request) -> Core:
    return request.app.state.core


CoreDep = Annotated[Core, Depends(get_core)]


def _fail(exc: Exception, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=str(exc))


system = APIRouter(prefix="/api", tags=["system"])
agents = APIRouter(prefix="/api/agents", tags=["agents"])
campaigns = APIRouter(prefix="/api/campaigns", tags=["campaigns"])
library = APIRouter(prefix="/api/clips", tags=["library"])
review = APIRouter(prefix="/api/review", tags=["review"])
edit = APIRouter(prefix="/api/edit", tags=["edit"])
publishing = APIRouter(prefix="/api/publishing", tags=["publishing"])
earnings = APIRouter(prefix="/api/earnings", tags=["earnings"])
settings_r = APIRouter(prefix="/api/settings", tags=["settings"])
files = APIRouter(prefix="/api/files", tags=["files"])
discord = APIRouter(prefix="/api/discord", tags=["discord"])


# ---------------------------------------------------------------- system


@system.get("/health")
def health_check(request: Request) -> dict[str, Any]:
    return {"ok": True, "fixture_mode": request.app.state.fixture_mode}


@system.get("/status", response_model=S.StatusOut)
def status(core: CoreDep, request: Request) -> S.StatusOut:
    return views.status(core, request.app.state.fixture_mode)


@system.get("/overview", response_model=S.OverviewOut)
def overview(core: CoreDep) -> S.OverviewOut:
    return views.overview(core)


@system.post("/control", response_model=S.ControlState)
def control(core: CoreDep, body: S.ControlIn) -> S.ControlState:
    try:
        set_control(core.db, body.key, body.value, by="user", via=body.via)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return views.control_state(core)


@system.get("/switches", response_model=S.SwitchesOut)
def switches(core: CoreDep) -> S.SwitchesOut:
    return views.switches(core)


@system.get("/switches/preview", response_model=S.SwitchPreview)
def switch_preview(core: CoreDep, level: str, name: str) -> S.SwitchPreview:
    return S.SwitchPreview(**core.toggles.preview_off(level, name))  # type: ignore[arg-type]


@system.post("/switches", response_model=S.SwitchResult)
def set_switch(core: CoreDep, body: S.SwitchIn) -> S.SwitchResult:
    try:
        res = core.toggles.set(
            body.level,
            body.name,
            body.enabled,
            by="user",
            via=body.via,
            on_active=body.on_active,
            on_scheduled=body.on_scheduled,
        )
    except ServiceError as exc:
        raise _fail(exc) from exc
    return S.SwitchResult(ok=res["ok"], needs_setup=res.get("needs_setup"), effects=res.get("effects", {}))


FIXTURE_DOCTOR = [
    S.HealthItem(name="python", status="ok", detail="Python 3.12.14 (uv)"),
    S.HealthItem(
        name="claude-billing-env",
        status="ok",
        detail="No API key in the environment; agents use the plan login",
    ),
    S.HealthItem(name="claude-login", status="ok", detail="Logged in with a Claude Max plan"),
    S.HealthItem(name="data-dir", status="ok", detail=r"D:\Clipper.io\data writable, 79 GB free"),
    S.HealthItem(name="database", status="ok", detail="at 0001_initial"),
    S.HealthItem(name="ffmpeg", status="ok", detail="nvenc=yes x264=yes libass=yes"),
    S.HealthItem(name="yt-dlp", status="ok", detail="2026.03.17"),
    S.HealthItem(name="gpu-env", status="ok", detail="2.8.0+cu128 True 12.8"),
    S.HealthItem(name="secrets", status="warn", detail="missing: hf_token", fix=SECRETS_FIX),
]


@system.get("/doctor", response_model=list[S.HealthItem])
def doctor(core: CoreDep, request: Request) -> list[S.HealthItem]:
    from clipper.doctor import run_checks

    if request.app.state.fixture_mode:
        return FIXTURE_DOCTOR
    return [S.HealthItem.model_validate(r.as_dict()) for r in run_checks(core.settings, include_slow=False)]


@system.get("/events", response_model=list[S.EventOut])
def events(
    core: CoreDep,
    after: int = 0,
    limit: int = Query(default=200, le=1000),
    types: str | None = None,
    latest: bool = False,
) -> list[S.EventOut]:
    """Events after ``after`` (oldest first); ``latest=true`` returns the newest ``limit`` instead."""
    wanted = types.split(",") if types else None
    envs = core.bus.latest(limit, wanted) if latest else core.bus.since(after, limit=limit, types=wanted)
    return [S.EventOut(**e.model_dump()) for e in envs]


@system.get("/jobs", response_model=list[S.JobOut])
def jobs(core: CoreDep, limit: int = 50) -> list[S.JobOut]:
    return views.jobs(core, limit)


@system.post("/jobs/{job_id}/retry", response_model=S.OkOut)
def job_retry(core: CoreDep, job_id: int) -> S.OkOut:
    """Run a failed or cancelled job again (same input)."""
    try:
        new_id = core.jobs.retry(job_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return S.OkOut(id=new_id, detail=f"queued again as job {new_id}")


@system.post("/sources/{source_id}/retry", response_model=S.OkOut)
def source_retry(core: CoreDep, source_id: int) -> S.OkOut:
    """Try a source's download again."""
    try:
        src = core.media.source(source_id)
        res = core.media.request_download(src.campaign_id, src.url)
    except ServiceError as exc:
        raise _fail(exc) from exc
    return S.OkOut(id=res.get("job_id"), detail=str(res.get("note") or "download queued"))


@system.post("/sources/{source_id}/file", response_model=S.OkOut)
def source_attach_file(core: CoreDep, source_id: int, body: S.AttachFileIn) -> S.OkOut:
    """Use a video you downloaded yourself as this source's footage, then analyze it."""
    try:
        res = core.media.attach_file(source_id, body.path)
    except ServiceError as exc:
        raise _fail(exc) from exc
    return S.OkOut(id=res["job_id"], detail=f"attached {Path(res['path']).name}; analyzing")


@system.get("/questions", response_model=list[S.QuestionOut])
def questions(core: CoreDep, status: str | None = "open") -> list[S.QuestionOut]:
    return views.questions(core, status)


@system.post("/questions/{question_id}/answer", response_model=S.OkOut)
def answer(core: CoreDep, question_id: int, body: S.AnswerIn) -> S.OkOut:
    try:
        core.notify.answer(question_id, body.answer, by=body.by, via=body.via)
    except ServiceError as exc:
        raise _fail(exc) from exc
    return S.OkOut(id=question_id)


@system.get("/notes", response_model=list[S.NoteOut])
def notes(core: CoreDep, scope: str | None = None, scope_id: str | None = None) -> list[S.NoteOut]:
    from clipper.db.models import Note

    with core.db.read() as s:
        q = select(Note).order_by(col(Note.id))
        if scope:
            q = q.where(Note.scope == scope)
        if scope_id:
            q = q.where(Note.scope_id == scope_id)
        return [views.note_out(n) for n in s.exec(q).all()]


@system.post("/notes", response_model=S.OkOut)
def add_note(core: CoreDep, body: S.NoteIn) -> S.OkOut:
    try:
        note_id = core.agenda.add_note(
            body.scope,
            body.scope_id,
            body.text,
            author="user",
            pinned=body.pinned,
            campaign_id=body.campaign_id,
        )
        if body.scope == "creator" and body.scope_id:
            core.memory.remember(
                "creator", body.text, entity=body.scope_id, evidence=f"note {note_id}", by="user"
            )
    except ServiceError as exc:
        raise _fail(exc) from exc
    return S.OkOut(id=note_id)


@system.delete("/notes/{note_id}", response_model=S.OkOut)
def clear_note(core: CoreDep, note_id: int) -> S.OkOut:
    core.agenda.clear_note(note_id)
    return S.OkOut(id=note_id)


# ---------------------------------------------------------------- agents


@agents.get("/board", response_model=S.BoardOut)
def board(core: CoreDep) -> S.BoardOut:
    return views.board(core)


@agents.get("/sessions", response_model=list[S.SessionOut])
def sessions(core: CoreDep) -> list[S.SessionOut]:
    return views.sessions(core)


@agents.get("/sessions/{session_id}", response_model=S.SessionDetail)
def session(
    core: CoreDep, session_id: int, after: int = 0, limit: int = Query(default=200, le=1000)
) -> S.SessionDetail:
    detail = views.session_detail(core, session_id, after, limit)
    if detail is None:
        raise HTTPException(404, f"session {session_id} not found")
    return detail


@agents.post("/sessions/{session_id}/interrupt", response_model=S.OkOut)
async def interrupt(request: Request, session_id: int) -> S.OkOut:
    sup = request.app.state.supervisor
    if sup is not None:
        await sup.interrupt(session_id)
    return S.OkOut(id=session_id)


@agents.post("/sessions/{session_id}/nudge", response_model=S.OkOut)
def nudge(core: CoreDep, session_id: int) -> S.OkOut:
    from clipper.events.types import WatchdogNudge

    with core.db.read() as s:
        sess = s.get(AgentSession, session_id)
    if sess is None or sess.campaign_id is None:
        raise HTTPException(400, "only campaign sessions can be nudged")
    core.bus.publish(WatchdogNudge(campaign_id=sess.campaign_id, idle_minutes=0))
    return S.OkOut(id=session_id)


@agents.post("/requests/{request_id}/bump", response_model=S.OkOut)
def bump(request: Request, request_id: int, body: S.BumpIn) -> S.OkOut:
    sup = request.app.state.supervisor
    if sup is not None:
        sup.bump(request_id, body.priority)
    return S.OkOut(id=request_id)


@agents.delete("/requests/{request_id}", response_model=S.OkOut)
def cancel_request(request: Request, request_id: int) -> S.OkOut:
    sup = request.app.state.supervisor
    if sup is not None:
        sup.cancel(request_id)
    return S.OkOut(id=request_id)


@system.post("/browser/profiles/{profile}/probe", response_model=list[S.ProbeResult])
async def browser_probe(core: CoreDep, profile: str, body: S.ProbeIn) -> list[S.ProbeResult]:
    """Look at a page in Clipper's browser without changing anything: navigate, wait, query, read,
    snapshot only (no click, type or upload). Used to write and fix recipe selectors. The extension
    applies the site allowlist and stops on login/CAPTCHA/verification screens."""
    out: list[S.ProbeResult] = []
    for step in body.steps:
        action = step.model_dump(exclude_none=True, exclude_defaults=True) | {"action": step.action}
        try:
            res = await core.adapters.browser.action(profile, action)
        except Exception as exc:  # not connected, timed out
            out.append(S.ProbeResult(action=step.action, ok=False, error=str(exc)))
            break
        out.append(
            S.ProbeResult(
                action=step.action,
                ok=res.ok,
                data=res.data,
                error=res.error,
                challenge=res.challenge,
                dom=res.dom,
            )
        )
        if not res.ok:
            break
    return out


@system.post("/browser/profiles/{profile}/extension/reload", response_model=S.OkOut)
async def browser_extension_reload(core: CoreDep, profile: str) -> S.OkOut:
    """Reload the Companion extension in a profile after `just build` (new or fixed recipes)."""
    try:
        await core.adapters.browser.reload_extension(profile)
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    return S.OkOut(detail=f"extension in {profile} is reloading; it reconnects in a few seconds")


@system.get("/browser/profiles", response_model=list[S.BrowserProfileOut])
def browser_profiles(core: CoreDep) -> list[S.BrowserProfileOut]:
    return views.browser_profiles(core)


@system.post("/browser/profiles/{profile}/{action}", response_model=S.BrowserProfileOut)
def browser_window(
    core: CoreDep, profile: str, action: Literal["show", "hide", "toggle", "open"]
) -> S.BrowserProfileOut:
    """Show or hide Clipper's own Chrome for a profile (watch the agents, log in, fix a challenge).
    ``open`` is the older name for ``show``. Clipper starts the profile's Chrome if it isn't running."""
    chrome = core.chrome
    try:
        state = {"show": chrome.show, "open": chrome.show, "hide": chrome.hide, "toggle": chrome.toggle}[
            action
        ](profile)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"couldn't start Chrome: {exc}") from exc
    connected = profile in core.adapters.browser.connected_profiles()
    return S.BrowserProfileOut(
        name=state.name, running=state.running, visible=state.visible, extension_connected=connected
    )


@agents.post("/trigger/{name}", response_model=S.OkOut)
def trigger(core: CoreDep, name: Literal["scout", "analyst"]) -> S.OkOut:
    """Scout now / Analyst now: the supervisor routes ``trigger.fired`` like a scheduled run."""
    from clipper.events.types import TriggerFired

    env = core.bus.publish(TriggerFired(name=name))
    return S.OkOut(id=env.id)


@agents.post("/events/{event_id}/replay", response_model=S.ReplayOut)
async def replay_event(core: CoreDep, event_id: int) -> S.ReplayOut:
    """Debug a recorded tool call: re-check it against today's guard rules and re-run it only if it
    is read-only. Calls that change state are never executed from here."""
    from clipper.agents.access import is_read_only, split_fq
    from clipper.agents.hooks import ToolCall
    from clipper.db.models import AgentEvent
    from clipper.tools.base import REGISTRY, ToolContext, call_tool, ensure_loaded

    with core.db.read() as s:
        ev = s.get(AgentEvent, event_id)
        sess = s.get(AgentSession, ev.session_id) if ev and ev.session_id else None
    if ev is None or not ev.tool or split_fq(ev.tool) is None:
        raise HTTPException(400, "not a recorded MCP tool call")
    server, name = split_fq(ev.tool) or ("", "")
    args = dict(ev.input_json.get("args") or {})
    role = str(ev.input_json.get("subagent") or (sess.role if sess else "developer"))
    call = ToolCall(
        tool=ev.tool,
        args=args,
        role=role,
        session_id=sess.id if sess else None,
        campaign_id=sess.campaign_id if sess else None,
    )
    verdict = core.guard.evaluate(call)
    out = S.ReplayOut(tool=ev.tool, allowed=verdict.allowed, rule=verdict.rule, reason=verdict.reason)
    if not verdict.allowed:
        return out
    if not is_read_only(ev.tool):
        out.detail = "Allowed by the guard today. Not executed: this tool changes state."
        return out
    ensure_loaded()
    spec = REGISTRY.get(server, {}).get(name)
    if spec is None:
        raise HTTPException(400, f"{ev.tool} is not registered")
    ctx = ToolContext(core=core, role=role, session_id=None, campaign_id=call.campaign_id)
    result = await call_tool(ctx, spec, args)
    out.executed = True
    out.output = result.data or {"content": result.content, "is_error": result.is_error}
    return out


@agents.post("/director/chat", response_model=S.OkOut)
def director_chat(core: CoreDep, body: S.ChatIn) -> S.OkOut:
    env = core.bus.publish(UserChat(text=body.text, via=body.via, reply_to=body.reply_to))
    return S.OkOut(id=env.id)


@agents.get("/director/messages", response_model=list[S.AgentEventOut])
def director_messages(core: CoreDep, limit: int = 50) -> list[S.AgentEventOut]:
    from clipper.db.models import AgentEvent

    with core.db.read() as s:
        sids = [a.id for a in s.exec(select(AgentSession).where(AgentSession.role == "director")).all()]
        rows = s.exec(
            select(AgentEvent)
            .where(col(AgentEvent.session_id).in_(sids), AgentEvent.type == "message")
            .order_by(col(AgentEvent.id).desc())
            .limit(limit)
        ).all()
        chats = s.exec(
            select(Event).where(Event.type == "user.chat").order_by(col(Event.id).desc()).limit(limit)
        ).all()
    msgs = [views.agent_event_out(e) for e in rows]
    # your side of the conversation (from Ctrl+K, the Agents page or Discord #control)
    msgs += [
        S.AgentEventOut(
            id=-(c.id or 0),
            session_id=None,
            ts=c.ts,
            type="user",
            tool=None,
            subagent=None,
            text=str(c.payload.get("text", "")),
            input={"via": c.payload.get("via")},
            output={},
        )
        for c in chats
    ]
    msgs.sort(key=lambda m: (m.ts, m.id))
    return msgs[-limit:]


# ---------------------------------------------------------------- campaigns


@campaigns.get("", response_model=list[S.CampaignRow])
def campaign_list(core: CoreDep, status: str | None = None, market: str | None = None) -> list[S.CampaignRow]:
    return views.campaign_rows(core, status=status, market=market)


@campaigns.get("/{campaign_id}", response_model=S.CampaignDetail)
def campaign_get(core: CoreDep, campaign_id: int) -> S.CampaignDetail:
    detail = views.campaign_detail(core, campaign_id)
    if detail is None:
        raise HTTPException(404, f"campaign {campaign_id} not found")
    return detail


@campaigns.post("/{campaign_id}/take", response_model=S.OkOut)
def take(core: CoreDep, campaign_id: int, via: str = "dashboard") -> S.OkOut:
    try:
        core.campaigns.take(campaign_id, by="user", via=via)
    except ServiceError as exc:
        raise _fail(exc) from exc
    return S.OkOut(id=campaign_id)


@campaigns.post("/{campaign_id}/skip", response_model=S.OkOut)
def skip(core: CoreDep, campaign_id: int, via: str = "dashboard") -> S.OkOut:
    core.campaigns.skip(campaign_id, by="user", via=via)
    return S.OkOut(id=campaign_id)


@campaigns.post("/{campaign_id}/pause", response_model=S.OkOut)
def pause_campaign(core: CoreDep, campaign_id: int) -> S.OkOut:
    core.campaigns.update(campaign_id, {"status": "paused"}, by="user")
    return S.OkOut(id=campaign_id)


@campaigns.put("/{campaign_id}/spec", response_model=ClipSpec)
def put_spec(core: CoreDep, campaign_id: int, spec: ClipSpec) -> ClipSpec:
    try:
        return core.campaigns.save_spec(campaign_id, spec, by="user")
    except ServiceError as exc:
        raise _fail(exc) from exc


@campaigns.post("/manual", response_model=S.OkOut)
def manual(core: CoreDep, body: S.ManualCampaignIn) -> S.OkOut:
    from clipper.marketplaces.base import CampaignCard

    ext = "manual-" + body.url.rstrip("/").rsplit("/", 1)[-1][:40]
    res = core.campaigns.upsert_cards(
        [
            CampaignCard(
                marketplace=body.marketplace,
                external_id=ext,
                title=body.title or body.url,
                cpm_usd=0.0,
                url=body.url,
            )
        ]
    )
    return S.OkOut(id=res[0][0], detail="added; the Scout reads its page on the next run")


# ---------------------------------------------------------------- library


@library.get("", response_model=list[S.ClipRow])
def clip_list(
    core: CoreDep, campaign_id: int | None = None, status: str | None = None, min_score: float | None = None
) -> list[S.ClipRow]:
    return views.clips(core, campaign_id=campaign_id, status=status, min_score=min_score)


@library.get("/{clip_id}", response_model=S.ClipDetail)
def clip_get(core: CoreDep, clip_id: int) -> S.ClipDetail:
    detail = views.clip_detail(core, clip_id)
    if detail is None:
        raise HTTPException(404, f"clip {clip_id} not found")
    return detail


# ---------------------------------------------------------------- review


@review.get("/batches", response_model=list[S.BatchRow])
def batch_list(core: CoreDep, status: str | None = None) -> list[S.BatchRow]:
    return views.batches(core, status)


@review.get("/batches/{batch_id}", response_model=S.BatchDetail)
def batch_get(core: CoreDep, batch_id: int) -> S.BatchDetail:
    detail = views.batch_detail(core, batch_id)
    if detail is None:
        raise HTTPException(404, f"batch {batch_id} not found")
    return detail


@review.post("/clips/{clip_id}/decision", response_model=S.OkOut)
def decide(core: CoreDep, clip_id: int, body: S.DecisionIn) -> S.OkOut:
    try:
        core.review.decide(
            clip_id,
            body.decision,
            via=body.via,
            reviewer=body.reviewer,
            reason=body.reason,
            platforms=body.platforms,
        )
    except ServiceError as exc:
        raise _fail(exc) from exc
    return S.OkOut(id=clip_id)


@review.post("/batches/{batch_id}/approve-all", response_model=list[int])
def approve_all(core: CoreDep, batch_id: int, body: S.ThresholdIn) -> list[int]:
    return core.review.approve_all_at_least(batch_id, body.threshold, via=body.via, reviewer=body.reviewer)


@review.post("/batches/{batch_id}/reject-rest", response_model=list[int])
def reject_rest(core: CoreDep, batch_id: int, body: S.RejectRestIn) -> list[int]:
    return core.review.reject_rest(batch_id, via=body.via, reviewer=body.reviewer, reason=body.reason)


@review.post("/batches/{batch_id}/ship", response_model=dict[str, list[int]])
def ship(core: CoreDep, batch_id: int, body: S.ShipIn) -> dict[str, list[int]]:
    try:
        return core.review.ship(batch_id, via=body.via, reviewer=body.reviewer)
    except ServiceError as exc:
        raise _fail(exc) from exc


@review.put("/clips/{clip_id}/caption", response_model=S.OkOut)
def caption(core: CoreDep, clip_id: int, body: S.CaptionIn) -> S.OkOut:
    try:
        core.review.edit_caption(clip_id, body.platform, body.text, via=body.via)
    except ServiceError as exc:
        raise _fail(exc) from exc
    return S.OkOut(id=clip_id)


@review.post("/clips/{clip_id}/recut", response_model=S.OkOut)
def recut(core: CoreDep, clip_id: int, body: S.RecutIn) -> S.OkOut:
    try:
        core.review.request_recut(
            clip_id,
            start_delta=body.start_delta,
            end_delta=body.end_delta,
            layout=body.layout,
            note=body.note,
            via=body.via,
        )
    except ServiceError as exc:
        raise _fail(exc) from exc
    return S.OkOut(id=clip_id)


@review.get("/auto-approve", response_model=S.AutoApproveOffer)
def auto_approve(core: CoreDep) -> S.AutoApproveOffer:
    offer = core.review.auto_approve_offer()
    from clipper.services.control import read_control

    offer["current_tier"] = read_control(core.db).auto_approve_tier
    return S.AutoApproveOffer(**offer)


# ---------------------------------------------------------------- edit


@edit.get("/{clip_id}", response_model=S.EditState)
def edit_get(core: CoreDep, clip_id: int) -> S.EditState:
    state = views.edit_state(core, clip_id)
    if state is None:
        raise HTTPException(404, f"clip {clip_id} has no EDL")
    return state


@edit.post("/{clip_id}/ops", response_model=S.EditState)
def edit_op(core: CoreDep, clip_id: int, body: S.EditOpIn) -> S.EditState:
    try:
        core.edl.apply(clip_id, body.op, body.args, actor="user", reason=body.reason)
    except (EditError, ValueError) as exc:
        raise _fail(exc) from exc
    return edit_get(core, clip_id)


@edit.post("/{clip_id}/undo", response_model=S.EditState)
def edit_undo(core: CoreDep, clip_id: int, body: S.UndoIn) -> S.EditState:
    try:
        core.edl.undo(clip_id, body.op_id, actor="user")
    except EditError as exc:
        raise _fail(exc) from exc
    return edit_get(core, clip_id)


@edit.post("/{clip_id}/take-over", response_model=S.OkOut)
def take_over(core: CoreDep, clip_id: int) -> S.OkOut:
    core.edl.take_over(clip_id)
    return S.OkOut(id=clip_id)


@edit.post("/{clip_id}/hand-back", response_model=S.OkOut)
def hand_back(core: CoreDep, clip_id: int) -> S.OkOut:
    core.edl.hand_back(clip_id)
    core.agenda.add_note(
        "clip",
        str(clip_id),
        "Handed back to Claude: read my edits and notes, then continue.",
        author="user",
        campaign_id=_clip_campaign(core, clip_id),
    )
    return S.OkOut(id=clip_id)


def _clip_campaign(core: Core, clip_id: int) -> int | None:
    with core.db.read() as s:
        c = s.get(Clip, clip_id)
        return c.campaign_id if c else None


@edit.post("/{clip_id}/preview", response_model=S.OkOut)
def edit_preview(core: CoreDep, clip_id: int) -> S.OkOut:
    return S.OkOut(id=core.media.request_preview(clip_id), detail="render queued")


# ---------------------------------------------------------------- publishing


@publishing.get("/accounts", response_model=list[S.AccountOut])
def account_list(core: CoreDep) -> list[S.AccountOut]:
    return views.accounts(core)


@publishing.post("/accounts", response_model=S.OkOut)
def account_add(core: CoreDep, body: S.AccountIn) -> S.OkOut:
    def job(tx: WriteTx) -> int:
        a = Account(
            platform=body.platform,
            handle=body.handle,
            chrome_profile=body.chrome_profile,
            niche_tags=body.niche_tags,
            daily_cap=body.daily_cap,
            warmup_started=core.clock.now() if body.new_account else None,
        )
        tx.add(a)
        tx.flush()
        assert a.id is not None
        return a.id

    return S.OkOut(id=core.db.write(job))


@publishing.patch("/accounts/{account_id}", response_model=S.OkOut)
def account_patch(core: CoreDep, account_id: int, body: S.AccountPatch) -> S.OkOut:
    if body.enabled is not None:
        core.toggles.set("account", str(account_id), body.enabled, by="user", via="app")

    def job(tx: WriteTx) -> None:
        a = tx.session.get(Account, account_id)
        if a is None:
            raise ServiceError(f"account {account_id} not found")
        for key in ("niche_tags", "daily_cap", "min_gap_min"):
            value = getattr(body, key)
            if value is not None:
                setattr(a, key, value)
        tx.add(a)

    try:
        core.db.write(job)
    except ServiceError as exc:
        raise _fail(exc, 404) from exc
    return S.OkOut(id=account_id)


@publishing.post("/accounts/{account_id}/resume", response_model=S.OkOut)
def account_resume(core: CoreDep, account_id: int) -> S.OkOut:
    core.publishing.resume_account(account_id)
    return S.OkOut(id=account_id)


@publishing.get("/calendar", response_model=S.CalendarOut)
def calendar(
    core: CoreDep, start: datetime | None = None, days: int = Query(default=7, ge=1, le=31)
) -> S.CalendarOut:
    begin = start or (core.clock.now() - timedelta(days=1))
    return views.calendar(core, begin, begin + timedelta(days=days))


@publishing.post("/posts/{post_id}/reschedule", response_model=S.OkOut)
def reschedule(core: CoreDep, post_id: int, body: S.RescheduleIn) -> S.OkOut:
    with core.db.read() as s:
        post = s.get(Post, post_id)
    if post is None or post.status != "scheduled":
        raise HTTPException(400, "only scheduled posts can be moved")
    core.publishing.cancel(post_id, by="user: reschedule")
    try:
        new = core.publishing.schedule(
            post.clip_id, post.account_id, body.scheduled_at, copy=dict(post.copy_json), created_by="user"
        )
    except ServiceError as exc:
        _restore(core, post_id)
        raise _fail(exc, 409) from exc
    return S.OkOut(id=new.id)


def _restore(core: Core, post_id: int) -> None:
    def job(tx: WriteTx) -> None:
        p = tx.session.get(Post, post_id)
        if p is not None:
            p.status, p.error = "scheduled", None
            tx.add(p)

    core.db.write(job)


@publishing.post("/posts/{post_id}/cancel", response_model=S.OkOut)
def cancel_post(core: CoreDep, post_id: int) -> S.OkOut:
    try:
        core.publishing.cancel(post_id, by="user")
    except ServiceError as exc:
        raise _fail(exc) from exc
    return S.OkOut(id=post_id)


@publishing.get("/recipes", response_model=list[S.RecipeHealth])
def recipes(core: CoreDep) -> list[S.RecipeHealth]:
    return views.recipes(core)


@publishing.post("/recipes/{name}/test", response_model=S.RecipeTestOut)
async def recipe_test(
    core: CoreDep, name: str, profile: str = "main", body: S.RecipeTestIn | None = None
) -> S.RecipeTestOut:
    """Run a recipe in dry run (the final publish/submit click is skipped), with optional params."""
    params = {**(body.params if body else {}), "test": True}
    try:
        res = await core.adapters.browser.run_recipe(profile, name, params, dry_run=True)
    except Exception as exc:  # not connected, timed out
        res = RecipeResult(ok=False, error=str(exc))
    core.db.write(lambda tx: tx.add(RecipeRun(recipe=name, ok=res.ok, dry_run=True, error=res.error)))
    return S.RecipeTestOut(
        ok=res.ok, detail=res.error, data=res.data, step=res.step, challenge=res.challenge, dom=res.dom
    )


@publishing.post("/recipes/{name}/check-upload", response_model=S.RecipeTestOut)
async def recipe_check_upload(
    core: CoreDep, name: str, body: S.CheckUploadIn, profile: str = "main"
) -> S.RecipeTestOut:
    """One real upload of a synthetic test clip, always Private, to check an upload recipe past the
    point a dry run can reach. Only when you ask for it (confirm); see services/recipe_check.py."""
    try:
        res = await run_check_upload(core, name, profile)
    except ServiceError as exc:
        raise _fail(exc) from exc
    return S.RecipeTestOut(
        ok=res.ok, detail=res.error, data=res.data, step=res.step, challenge=res.challenge, dom=res.dom
    )


# ---------------------------------------------------------------- earnings


@earnings.get("", response_model=S.EarningsOut)
def earnings_get(core: CoreDep, days: int = Query(default=30, ge=1, le=365)) -> S.EarningsOut:
    return views.earnings(core, days)


# ---------------------------------------------------------------- settings, memory, tools, prompts, secrets


@settings_r.get("", response_model=S.SettingsOut)
def settings_get(core: CoreDep, request: Request) -> S.SettingsOut:
    shown = core.settings
    if request.app.state.fixture_mode:
        from clipper.settings import Settings

        # Fixture mode never reads this PC's Credential Manager: its responses are exported into the
        # repo (apps/desktop/public/fixtures) and shown in screenshots.
        return S.SettingsOut(
            settings=json.loads(Settings().with_data_dir(Path(r"D:\Clipper.io\data")).model_dump_json()),
            secrets_present=dict.fromkeys(SECRET_NAMES, False),
            pairing_token=None,
        )
    return S.SettingsOut(
        settings=json.loads(shown.model_dump_json()),
        secrets_present={n: get_secret(n) is not None for n in SECRET_NAMES},
        pairing_token=get_secret("extension_pairing_token"),
    )


@settings_r.post("/secrets/{name}", response_model=S.OkOut)
def secret_set(name: str, body: S.SecretIn) -> S.OkOut:
    if name not in SECRET_NAMES:
        raise HTTPException(404, f"unknown secret {name}")
    set_secret(name, body.value)
    return S.OkOut(detail=f"{name} saved to Windows Credential Manager")


@settings_r.patch("", response_model=S.OkOut)
def settings_patch(core: CoreDep, body: S.SettingsPatch) -> S.OkOut:
    from clipper.api.settings_file import patch_settings_file

    try:
        path = patch_settings_file(body.values)
    except ValueError as exc:
        raise _fail(exc) from exc
    return S.OkOut(detail=f"saved to {path}; restart Clipper to apply")


@settings_r.get("/lessons", response_model=list[S.LessonOut])
def lessons(core: CoreDep, scope: str | None = None, q: str | None = None) -> list[S.LessonOut]:
    return views.lessons(core, scope, q)


@settings_r.patch("/lessons/{lesson_id}", response_model=S.OkOut)
def lesson_patch(core: CoreDep, lesson_id: int, body: S.LessonPatch) -> S.OkOut:
    def job(tx: WriteTx) -> None:
        row = tx.session.get(Lesson, lesson_id)
        if row is None:
            raise ServiceError(f"lesson {lesson_id} not found")
        row.note = body.note
        row.created_by = "user"
        tx.add(row)

    try:
        core.db.write(job)
    except ServiceError as exc:
        raise _fail(exc, 404) from exc
    return S.OkOut(id=lesson_id)


@settings_r.delete("/lessons/{lesson_id}", response_model=S.OkOut)
def lesson_delete(core: CoreDep, lesson_id: int) -> S.OkOut:
    try:
        core.memory.forget(lesson_id)
    except ServiceError as exc:
        raise _fail(exc, 404) from exc
    return S.OkOut(id=lesson_id)


@settings_r.get("/tools", response_model=S.ToolsOut)
def tools(core: CoreDep) -> S.ToolsOut:
    return views.tools_overview(core)


@settings_r.get("/prompts", response_model=list[S.PromptOut])
def prompts(core: CoreDep) -> list[S.PromptOut]:
    from clipper.agents.definitions import PROMPTS_DIR

    override = core.settings.agents.prompts_dir
    out: list[S.PromptOut] = []
    for path in sorted([*PROMPTS_DIR.glob("*.md"), *PROMPTS_DIR.glob("subagents/*.md")]):
        rel = path.relative_to(PROMPTS_DIR).as_posix()
        own = override / rel if override else None
        text = own.read_text(encoding="utf-8") if own and own.exists() else path.read_text(encoding="utf-8")
        out.append(
            S.PromptOut(name=rel.removesuffix(".md"), text=text, overridden=bool(own and own.exists()))
        )
    return out


@settings_r.put("/prompts/{name:path}", response_model=S.PromptSaveOut)
def prompt_put(core: CoreDep, name: str, body: S.PromptIn) -> S.PromptSaveOut:
    from clipper.evaluation import load_manifest

    if not core.settings.agents.prompts_dir:
        raise HTTPException(
            400, "set agents.prompts_dir in settings.toml to edit prompts (copies of the built-in ones)"
        )
    if load_manifest():
        return S.PromptSaveOut(
            saved=False,
            eval_status="run `clipper eval` with the new prompt first; saving requires passing the golden set (PLAN §14)",
        )
    target = core.settings.agents.prompts_dir / f"{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.text, encoding="utf-8")
    return S.PromptSaveOut(saved=True, eval_status="no golden set yet: saved without evaluation")


# ---------------------------------------------------------------- files (loopback only)


def _allowed_file(core: Core, path: str | None) -> Path:
    if not path:
        raise HTTPException(404, "no such file")
    p = Path(path).resolve()
    from clipper.settings import REPO_ROOT

    roots = [core.settings.paths.data_dir.resolve(), (REPO_ROOT / "tests" / "fixtures").resolve()]
    for name in ("sources_dir", "work_dir", "clips_dir", "previews_dir", "screenshots_dir"):
        explicit = getattr(core.settings.paths, name)
        if explicit is not None:
            roots.append(Path(explicit).resolve())
    if not any(p.is_relative_to(r) for r in roots) or not p.is_file():
        raise HTTPException(404, "no such file")
    return p


@files.get("/clip/{clip_id}/{kind}")
def clip_file(core: CoreDep, clip_id: int, kind: str) -> FileResponse:
    with core.db.read() as s:
        clip = s.get(Clip, clip_id)
        if clip is None:
            raise HTTPException(404, "no such clip")
        if kind == "proxy":
            moment = s.get(Moment, clip.moment_id)
            src = s.get(Source, moment.source_id) if moment else None
            path = (src.proxy_path or src.path) if src else None
        else:
            path = {"preview": clip.preview_path, "final": clip.path, "thumb": clip.thumb_path}.get(kind)
    return FileResponse(_allowed_file(core, path))


@files.get("/upload/{post_id}")
def upload_file(core: CoreDep, post_id: int) -> FileResponse:
    """The final render of a post's clip, for the Companion extension's upload recipe."""
    with core.db.read() as s:
        post = s.get(Post, post_id)
        clip = s.get(Clip, post.clip_id) if post else None
    return FileResponse(
        _allowed_file(core, clip.path if clip else None), filename=f"clip_{post.clip_id if post else 0}.mp4"
    )


@files.get("/recipe-check/{name}")
def recipe_check_file(core: CoreDep, name: str) -> FileResponse:
    """The synthetic test clip for a recipe check upload (nothing else is served from here)."""
    if name != CLIP_NAME:
        raise HTTPException(404, "no such file")
    return FileResponse(_allowed_file(core, str(core.dir("recipe_checks") / CLIP_NAME)), filename=CLIP_NAME)


@files.get("/screenshot/{run_id}")
def screenshot(core: CoreDep, run_id: int) -> FileResponse:
    with core.db.read() as s:
        run = s.get(RecipeRun, run_id)
    return FileResponse(_allowed_file(core, run.screenshot_path if run else None))


# ---------------------------------------------------------------- discord bot support


@discord.post("/refs", response_model=S.OkOut)
def ref_put(core: CoreDep, body: S.DiscordRefIn) -> S.OkOut:
    def job(tx: WriteTx) -> int:
        row = tx.session.exec(
            select(DiscordRef).where(DiscordRef.kind == body.kind, DiscordRef.entity_id == body.entity_id)
        ).first()
        row = row or DiscordRef(kind=body.kind, entity_id=body.entity_id, channel_id=body.channel_id)
        row.channel_id, row.message_id, row.thread_id = body.channel_id, body.message_id, body.thread_id
        tx.add(row)
        tx.flush()
        assert row.id is not None
        return row.id

    return S.OkOut(id=core.db.write(job))


@discord.get("/refs/{kind}/{entity_id}", response_model=S.DiscordRefOut)
def ref_get(core: CoreDep, kind: str, entity_id: str) -> S.DiscordRefOut:
    with core.db.read() as s:
        row = s.exec(
            select(DiscordRef).where(DiscordRef.kind == kind, DiscordRef.entity_id == entity_id)
        ).first()
    if row is None:
        raise HTTPException(404, "no ref")
    return S.DiscordRefOut.model_validate(row)


@discord.post("/heartbeat", response_model=S.OkOut)
def heartbeat(core: CoreDep) -> S.OkOut:
    from clipper.services.control import kv_set_tx

    now = core.clock.now().isoformat()
    core.db.write(lambda tx: kv_set_tx(tx, "discord.heartbeat", now))
    return S.OkOut()


@discord.get("/clip/{clip_id}/preview-path")
def preview_path(core: CoreDep, clip_id: int) -> dict[str, Any]:
    """The bot runs on the same machine and uploads the preview file directly."""
    with core.db.read() as s:
        clip = s.get(Clip, clip_id)
        camp = s.get(Campaign, clip.campaign_id) if clip and clip.campaign_id else None
    if clip is None:
        raise HTTPException(404, "no such clip")
    return {
        "clip_id": clip_id,
        "path": clip.preview_path,
        "thumb": clip.thumb_path,
        "campaign": camp.title if camp else None,
    }


ROUTERS = [system, agents, campaigns, library, review, edit, publishing, earnings, settings_r, files, discord]
