"""Agent plans and the user's notes (PLAN §18.5). Notes are the user's; the guard still blocks anything
against the rules, whatever a note says."""

from __future__ import annotations

from typing import Any

from sqlmodel import col, or_, select

from clipper.db.engine import WriteTx
from clipper.db.models import AgendaItem, Note
from clipper.db.types import AgendaStatus
from clipper.events.types import AgendaUpdated, NoteAdded
from clipper.services.base import Service, ServiceError

PLAN_SCOPES = ("clip", "campaign", "global")
NOTE_SCOPES = ("clip", "campaign", "creator", "global")


class AgendaService(Service):
    def set_plan(
        self, scope: str, scope_id: str | None, items: list[str], *, session_id: int | None
    ) -> list[int]:
        if scope not in PLAN_SCOPES:
            raise ServiceError(f"scope must be one of {', '.join(PLAN_SCOPES)}")
        if not items or len(items) > 12:
            raise ServiceError("a plan has 1-12 items")

        def job(tx: WriteTx) -> list[int]:
            old = tx.session.exec(
                select(AgendaItem).where(AgendaItem.scope == scope, AgendaItem.scope_id == scope_id)
            ).all()
            for o in old:
                if o.status in (AgendaStatus.QUEUED, AgendaStatus.IN_PROGRESS):
                    tx.session.delete(o)
            start = (
                max((o.ord for o in old if o.status in (AgendaStatus.DONE, AgendaStatus.SKIPPED)), default=-1)
                + 1
            )
            ids: list[int] = []
            for i, text in enumerate(items):
                row = AgendaItem(
                    scope=scope, scope_id=scope_id, session_id=session_id, text=text[:200], ord=start + i
                )
                tx.add(row)
                tx.flush()
                assert row.id is not None
                ids.append(row.id)
            tx.publish(AgendaUpdated(scope=scope, scope_id=scope_id))
            return ids

        return self.db.write(job)

    def check(self, item_id: int, status: str, result: str | None = None) -> None:
        if status not in (
            AgendaStatus.IN_PROGRESS,
            AgendaStatus.DONE,
            AgendaStatus.SKIPPED,
            AgendaStatus.QUEUED,
        ):
            raise ServiceError("status must be in_progress, done, skipped or queued")

        def job(tx: WriteTx) -> None:
            row = tx.session.get(AgendaItem, item_id)
            if row is None:
                raise ServiceError(f"agenda item {item_id} not found")
            row.status = status
            row.result = (result or "")[:300] or None
            tx.add(row)
            tx.publish(AgendaUpdated(scope=row.scope, scope_id=row.scope_id))

        self.db.write(job)

    def plan(self, scope: str, scope_id: str | None) -> list[dict[str, Any]]:
        with self.db.read() as s:
            rows = s.exec(
                select(AgendaItem)
                .where(AgendaItem.scope == scope, AgendaItem.scope_id == scope_id)
                .order_by(col(AgendaItem.ord))
            ).all()
        return [{"id": r.id, "text": r.text, "status": r.status, "result": r.result} for r in rows]

    def add_note(
        self,
        scope: str,
        scope_id: str | None,
        text: str,
        *,
        author: str = "user",
        pinned: bool = False,
        campaign_id: int | None = None,
    ) -> int:
        if scope not in NOTE_SCOPES:
            raise ServiceError(f"scope must be one of {', '.join(NOTE_SCOPES)}")

        def job(tx: WriteTx) -> int:
            row = Note(
                scope=scope,
                scope_id=scope_id,
                text=text[:1000],
                author=author,
                pinned=pinned or scope == "global",
            )
            tx.add(row)
            tx.flush()
            assert row.id is not None
            tx.publish(
                NoteAdded(
                    note_id=row.id, scope=scope, scope_id=scope_id, text=row.text, campaign_id=campaign_id
                )
            )
            return row.id

        return self.db.write(job)

    def notes(
        self, scope: str | None = None, scope_id: str | None = None, *, include_acked: bool = False
    ) -> list[dict[str, Any]]:
        with self.db.read() as s:
            q = select(Note).order_by(col(Note.id))
            if scope is not None:
                q = q.where(
                    or_(
                        col(Note.pinned) & (Note.scope == "global"),
                        (Note.scope == scope) & (Note.scope_id == scope_id),
                    )
                )
            if not include_acked:
                q = q.where(or_(col(Note.acked_by_session).is_(None), col(Note.pinned)))
            rows = s.exec(q).all()
        return [
            {
                "id": n.id,
                "scope": n.scope,
                "scope_id": n.scope_id,
                "text": n.text,
                "pinned": n.pinned,
                "response": n.response,
            }
            for n in rows
        ]

    def ack_note(self, note_id: int, response: str, *, session_id: int | None) -> None:
        def job(tx: WriteTx) -> None:
            row = tx.session.get(Note, note_id)
            if row is None:
                raise ServiceError(f"note {note_id} not found")
            row.acked_by_session = session_id or 0
            row.response = response[:500]
            tx.add(row)
            tx.publish(AgendaUpdated(scope=row.scope, scope_id=row.scope_id))

        self.db.write(job)

    def clear_note(self, note_id: int) -> None:
        def job(tx: WriteTx) -> None:
            row = tx.session.get(Note, note_id)
            if row is not None:
                row.pinned = False
                row.acked_by_session = row.acked_by_session or 0
                tx.add(row)
                tx.publish(AgendaUpdated(scope=row.scope, scope_id=row.scope_id))

        self.db.write(job)
