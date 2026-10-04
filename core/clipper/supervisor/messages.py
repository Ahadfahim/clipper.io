"""Resume messages: a short description of what happened, so sessions stay small (PLAN §12)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from clipper.db.models import Account, Campaign, Marketplace
from clipper.services.control import read_control

if TYPE_CHECKING:
    from clipper.core import Core


def describe(ev: dict[str, Any]) -> str:
    t, p = ev["type"], ev.get("payload", {})
    match t:
        case "campaign.taken":
            return f"Campaign {p['campaign_id']} was taken by {p.get('by', 'the user')} via {p.get('via', 'the app')}. Start: read the brief, save the spec, join, download sources."
        case "job.done":
            res: dict[str, Any] = dict(p.get("result") or {})
            detail = ", ".join(
                f"{k}={v}"
                for k, v in res.items()
                if k in ("source_id", "clip_id", "words", "duration", "qa_ok", "scene_cuts")
            )
            if p.get("status") != "done":
                return f"Job {p['job_id']} ({p['kind']}) {p.get('status')}: {p.get('error') or 'no detail'}."
            return f"Job {p['job_id']} ({p['kind']}) finished: {detail}."
        case "review.shipped":
            return f"Review batch {p['batch_id']} shipped via {p.get('via')}: approved {p.get('approved')}, rejected {p.get('rejected')}. Schedule the approved clips."
        case "post.live":
            dry = " (dry run: simulated)" if p.get("dry_run") else ""
            return f"Post {p['post_id']} of clip {p['clip_id']} is live on {p['platform']}{dry}: {p['url']}. Submit it."
        case "campaign.ending":
            return f"Campaign {p['campaign_id']} is ending ({p.get('reason')}). Finish submissions for live posts, then wrap up."
        case "recut.requested":
            return (
                f"The user asked for a re-cut of clip {p['clip_id']} via {p.get('via')}: start {p.get('start_delta', 0):+.1f}s, "
                f"end {p.get('end_delta', 0):+.1f}s, layout {p.get('layout') or 'unchanged'}. Note: {p.get('note') or '-'}"
            )
        case "spec.updated":
            return f"The user edited the spec of campaign {p['campaign_id']}. Re-read it (state.get_campaign) and re-plan."
        case "note.added":
            return f"New note #{p['note_id']} from the user ({p['scope']} {p.get('scope_id') or ''}): {p['text']!r}. Act on it, then agenda.ack_note."
        case "question.answered":
            return f"Your question #{p['question_id']} was answered via {p.get('via')}: {p['answer']!r}."
        case "user.chat":
            return f"User ({p.get('via', 'dashboard')}): {p['text']}"
        case "wakeup.due":
            return f"Wake-up #{p['wakeup_id']} you scheduled: {p['reason']}"
        case "watchdog.nudge":
            return f"Status check: no events for {p['idle_minutes']:.0f} min. What's blocked? Unblock it or ask the user."
        case "trigger.fired":
            return f"Scheduled {p['name']} run."
        case _:
            return f"{t}: {p}"


def context_lines(core: Core, role: str, campaign_id: int | None) -> list[str]:
    lines: list[str] = []
    ctl = read_control(core.db)
    if ctl.dry_run:
        lines.append("Dry run is ON: schedule/submit/join calls are simulated and only logged.")
    usage = core.usage.as_dict()
    resets = f", resets {usage['resets_at']}" if usage["resets_at"] else ""
    lines.append(f"Claude usage: {usage['utilization']:.0%} of the window{resets} (pace: {usage['pace']}).")
    pinned = [n for n in core.agenda.notes("global", None) if n["pinned"]]
    if pinned:
        lines.append("Pinned notes from the user: " + " | ".join(n["text"] for n in pinned[:5]))
    if campaign_id is not None:
        with core.db.read() as s:
            c = s.get(Campaign, campaign_id)
        if c is not None:
            lines.insert(0, f"Your campaign: {c.id} {c.title!r} on {c.marketplace} (status {c.status}).")
    if role == "scout":
        with core.db.read() as s:
            accounts = s.exec(select(Account).where(col(Account.enabled))).all()
            markets = s.exec(select(Marketplace)).all()
        acct = (
            "; ".join(f"#{a.id} {a.platform} {a.handle} [{', '.join(a.niche_tags)}]" for a in accounts)
            or "none yet"
        )
        lines.append(f"Accounts: {acct}.")
        rates = {r["key"]: r["approval_rate"] for r in core.insights.approval_rate_by("marketplace")}
        lines.append(
            "Marketplaces: "
            + "; ".join(
                f"{m.id} {'on' if m.enabled else 'off'} (mode {m.mode}, approval rate {rates.get(m.id, 'n/a')})"
                for m in markets
            )
            + "."
        )
        sc = core.settings.scout
        lines.append(
            f"Card threshold {sc.min_score_to_post_card}; auto-take threshold {sc.auto_take_min_score} (mode {sc.mode}); pre-fetch sources: {sc.prefetch_sources}."
        )
    if role == "analyst":
        lines.append(
            f"Today is {core.clock.now().date().isoformat()}. Current tuning: {core.memory.tuning() or 'defaults'}."
        )
    return lines


def build_prompt(core: Core, role: str, campaign_id: int | None, events: list[dict[str, Any]]) -> str:
    body = [describe(ev) for ev in events[-12:]]
    if len(events) > 12:
        body.insert(0, f"({len(events) - 12} earlier events merged)")
    head = "What happened since your last turn:" if len(events) > 1 else "What happened:"
    return "\n".join([*context_lines(core, role, campaign_id), "", head, *(f"- {b}" for b in body)])
