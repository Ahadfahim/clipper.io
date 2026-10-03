"""Long-term lessons per creator, marketplace, platform, account, recipe (PLAN §16.1 memory)."""

from __future__ import annotations

from typing import Any

from sqlmodel import col, or_, select

from clipper.db.engine import WriteTx
from clipper.db.models import Lesson
from clipper.services.base import Service, ServiceError

SCOPES = ("creator", "marketplace", "platform", "account", "recipe", "campaign", "global", "tuning")


def _row(lesson: Lesson) -> dict[str, Any]:
    return {
        "id": lesson.id,
        "scope": lesson.scope,
        "entity": lesson.entity_id,
        "note": lesson.note,
        "evidence": lesson.evidence_ref,
        "by": lesson.created_by,
    }


class MemoryService(Service):
    def recall(
        self,
        *,
        scope: str | None = None,
        entity: str | None = None,
        query: str | None = None,
        limit: int = 15,
    ) -> list[dict[str, Any]]:
        with self.db.read() as s:
            q = select(Lesson).where(col(Lesson.active)).order_by(col(Lesson.id).desc()).limit(limit)
            if scope:
                q = q.where(Lesson.scope == scope)
            if entity:
                q = q.where(or_(Lesson.entity_id == entity, col(Lesson.entity_id).is_(None)))
            if query:
                for term in query.split()[:5]:
                    q = q.where(col(Lesson.note).ilike(f"%{term}%"))
            return [_row(r) for r in s.exec(q).all()]

    def remember(
        self,
        scope: str,
        note: str,
        *,
        entity: str | None = None,
        evidence: str | None = None,
        by: str = "agent",
    ) -> int:
        if scope not in SCOPES:
            raise ServiceError(f"scope must be one of {', '.join(SCOPES)}")
        if not evidence and by != "user":
            raise ServiceError(
                "every lesson needs the evidence behind it (a clip, post, review or page reference)"
            )

        def job(tx: WriteTx) -> int:
            row = Lesson(scope=scope, entity_id=entity, note=note[:600], evidence_ref=evidence, created_by=by)
            tx.add(row)
            tx.flush()
            assert row.id is not None
            return row.id

        return self.db.write(job)

    def forget(self, lesson_id: int) -> None:
        def job(tx: WriteTx) -> None:
            row = tx.session.get(Lesson, lesson_id)
            if row is None:
                raise ServiceError(f"lesson {lesson_id} not found")
            row.active = False
            tx.add(row)

        self.db.write(job)

    def list(self, scope: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self.recall(scope=scope, limit=limit)

    def set_tuning(self, key: str, value: float | str, reason: str, *, by: str = "analyst") -> int:
        """Analyst knobs (e.g. editor quality threshold): a 'tuning' lesson; the newest active one wins."""

        def job(tx: WriteTx) -> int:
            for old in tx.session.exec(
                select(Lesson).where(Lesson.scope == "tuning", Lesson.entity_id == key, col(Lesson.active))
            ).all():
                old.active = False
                tx.add(old)
            row = Lesson(
                scope="tuning", entity_id=key, note=str(value), evidence_ref=reason[:300], created_by=by
            )
            tx.add(row)
            tx.flush()
            assert row.id is not None
            return row.id

        return self.db.write(job)

    def tuning(self) -> dict[str, str]:
        with self.db.read() as s:
            rows = s.exec(select(Lesson).where(Lesson.scope == "tuning", col(Lesson.active))).all()
        return {r.entity_id or "": r.note for r in rows}
