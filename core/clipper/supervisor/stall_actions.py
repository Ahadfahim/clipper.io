"""What can be done about a stall: the same actions from the Needs you item, the Agents panel, Discord and
the supervisor's own automatic checks (``auto=True``). Every action works on Clipper's own resources only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from clipper.events.types import NudgeSent
from clipper.services.base import ServiceError
from clipper.supervisor.stalls import Stall

if TYPE_CHECKING:
    from clipper.core import Core
    from clipper.supervisor.supervisor import Supervisor

# actions the server runs; the others (show_jobs, show_browser, open_calendar, show_agents) are links the app follows
SERVER_ACTIONS = ("nudge", "restart_turn", "run_now", "release_lease", "cancel_retry")
LABELS = {
    "nudge": "Nudge agent",
    "restart_turn": "Restart turn",
    "run_now": "Run now",
    "release_lease": "Release lease",
    "cancel_retry": "Cancel and retry",
    "show_jobs": "Show jobs",
    "show_browser": "Show browser",
    "open_calendar": "Open calendar",
    "show_agents": "Show agents",
}


async def run_action(
    core: Core,
    sup: Supervisor | None,
    stall: Stall,
    action: str,
    *,
    text: str = "",
    by: str = "user",
    auto: bool = False,
) -> str:
    """Do one action for a stall. Returns a sentence saying what happened (or raises ``ServiceError``)."""
    if action not in stall.actions or action not in SERVER_ACTIONS:
        raise ServiceError(f"{LABELS.get(action, action)} isn't something to do about this")
    if action == "nudge":
        out = core.nudge.nudge_stall(stall.key, text=text, by=by, auto=auto)
        who = "the campaign's agent" if out["role"] == "campaign" else f"the {out['role']} agent"
        return f"Nudged {who}."
    if action == "restart_turn":
        if sup is None or stall.session_id is None:
            raise ServiceError("agents aren't running, so there is nothing to restart")
        if not await sup.restart_turn(
            stall.session_id,
            why="interrupted by your nudge" if not auto else "interrupted by an automatic check",
        ):
            raise ServiceError("that agent isn't running any more; nudge it instead")
        core.nudge.nudge(
            session_id=stall.session_id,
            text=text,
            stall_key=stall.key,
            summary=stall.summary,
            evidence=stall.evidence[0] if stall.evidence else "",
            auto=auto,
            by=by,
        )
        return "Restarted the turn and nudged the agent."
    if action == "run_now":
        if sup is None or stall.request_id is None:
            raise ServiceError("agents aren't running")
        sup.run_now(stall.request_id)
        core.bus.publish(
            NudgeSent(
                campaign_id=stall.campaign_id,
                target=f"request:{stall.request_id}",
                action="run_now",
                stall_key=stall.key,
                auto=auto,
                by=by,
            )
        )
        return "Moved it to the front. It still waits if Clipper is paused or the usage limit is reached."
    if action == "release_lease":
        if sup is None or stall.campaign_id is None:
            raise ServiceError("agents aren't running")
        try:
            released = sup.release_lease(stall.campaign_id)
        except ValueError as exc:
            raise ServiceError(str(exc)) from exc
        if not released:
            raise ServiceError("nothing held that campaign any more")
        core.bus.publish(
            NudgeSent(
                campaign_id=stall.campaign_id,
                target=f"campaign:{stall.campaign_id}",
                action="release_lease",
                stall_key=stall.key,
                auto=auto,
                by=by,
            )
        )
        return "Released the lease. The waiting request can start."
    if stall.job_id is None:
        raise ServiceError("there is no job to cancel")
    try:
        new_id = core.jobs.cancel_and_retry(stall.job_id)
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc
    core.bus.publish(
        NudgeSent(
            campaign_id=stall.campaign_id,
            target=f"job:{stall.job_id}",
            action="cancel_retry",
            stall_key=stall.key,
            text=f"retry is job {new_id}",
            auto=auto,
            by=by,
        )
    )
    return f"Cancelled the job and queued it again as job {new_id}."
