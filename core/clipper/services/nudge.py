"""Nudging an agent that looks stuck.

A nudge is only an event and a resume: it goes through the same guard hooks, approvals, caps, dry run and
switches as any other turn. Its text comes from you (trusted); the evidence line is built from our own
tables, never from web pages. ``nudge`` says it to the agent; the repairs that can go with it (restart the
turn, release a lease, cancel and retry a job) are in ``supervisor/stall_actions.py``.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import select

from clipper.db.engine import WriteTx
from clipper.db.models import AgentSession, Campaign
from clipper.events.types import NudgeSent, UserNudge
from clipper.services.base import Service, ServiceError

MAX_TEXT = 1000
ROLES = ("campaign", "scout", "analyst", "director")


class NudgeService(Service):
    def nudge(
        self,
        *,
        session_id: int | None = None,
        campaign_id: int | None = None,
        role: str | None = None,
        text: str = "",
        stall_key: str | None = None,
        summary: str = "",
        evidence: str = "",
        auto: bool = False,
        by: str = "user",
    ) -> dict[str, Any]:
        """Tell an agent it looks stuck. Name the session, the campaign (its agent) or a role; a session
        is turned into its role and campaign. Returns where it went."""
        text = text.strip()
        if len(text) > MAX_TEXT:
            raise ServiceError(f"keep the message under {MAX_TEXT} characters")
        if session_id is not None:
            with self.db.read() as s:
                sess = s.get(AgentSession, session_id)
            if sess is None:
                raise ServiceError(f"session {session_id} not found")
            role, campaign_id = sess.role, sess.campaign_id
        elif campaign_id is not None:
            role = "campaign"
        if role not in ROLES:
            raise ServiceError("name a session, a campaign or an agent role to nudge")
        if role == "campaign":
            if campaign_id is None:
                raise ServiceError("a campaign agent belongs to a campaign")
            with self.db.read() as s:
                camp = s.exec(select(Campaign).where(Campaign.id == campaign_id)).first()
            if camp is None:
                raise ServiceError(f"campaign {campaign_id} not found")
            if camp.status in ("ended", "skipped"):
                raise ServiceError(f"{camp.title} is {camp.status}: there is nothing left to nudge")

        def job(tx: WriteTx) -> int:
            row = tx.publish(
                UserNudge(
                    campaign_id=campaign_id,
                    role=role or "campaign",
                    session_id=session_id,
                    text=text,
                    stall_key=stall_key,
                    summary=summary[:300],
                    evidence=evidence[:300],
                    auto=auto,
                    by=by,
                )
            )
            tx.publish(
                NudgeSent(
                    campaign_id=campaign_id,
                    target=f"session:{session_id}" if session_id is not None else f"campaign:{campaign_id}",
                    action="nudge",
                    stall_key=stall_key,
                    text=text,
                    auto=auto,
                    by=by,
                )
            )
            tx.flush()
            return int(row.id or 0)

        event_id = self.db.write(job)
        return {"event_id": event_id, "role": role, "campaign_id": campaign_id, "session_id": session_id}

    def nudge_stall(
        self, key: str, *, text: str = "", by: str = "user", auto: bool = False
    ) -> dict[str, Any]:
        """Nudge for a stall found by the detector (``stall_key`` like ``session_hung:3``)."""
        from clipper.supervisor.stalls import build_snapshot, detect_stalls

        stall = next(
            (s for s in detect_stalls(build_snapshot(self.core), self.settings.stalls) if s.key == key), None
        )
        if stall is None:
            raise ServiceError("that isn't stuck any more")
        return self.nudge(
            session_id=stall.session_id if stall.kind in ("session_hung", "waiting_on_nothing") else None,
            campaign_id=stall.campaign_id,
            text=text,
            stall_key=stall.key,
            summary=stall.summary,
            evidence=stall.evidence[0] if stall.evidence else "",
            auto=auto,
            by=by,
        )
