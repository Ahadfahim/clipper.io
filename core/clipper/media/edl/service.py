"""EDL persistence: every operation becomes an ``edit_op`` row and an ``edit.op`` event.

- ``init`` stores the first EDL as the op ``init`` (its args are the whole document).
- ``apply`` loads the current EDL, runs the pure op, saves the result and logs it, all in one writer job.
- ``undo`` marks an op undone and rebuilds the EDL by replaying the remaining ops from ``init``.
- ``take_over`` / ``hand_back`` set the per-clip edit lock (PLAN §17.3, §18.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlmodel import col, select

from clipper.clock import utcnow
from clipper.db.engine import Database, WriteTx
from clipper.db.models import Analysis, Clip, EditOp, Moment, Source
from clipper.db.models import Edl as EdlRow
from clipper.events.types import ClipUpdated, EditOpApplied, EditStatus
from clipper.media.edl.ops import EditError, apply_op, replay
from clipper.media.edl.schema import Edl

INIT = "init"


@dataclass(frozen=True)
class Applied:
    op_id: int
    version: int
    edl: Edl
    summary: str
    out_range: tuple[float, float] | None


class LockedError(EditError):
    """The clip is locked by someone else (the user took over)."""


def _load(tx: WriteTx, clip_id: int) -> EdlRow:
    row = tx.session.get(EdlRow, clip_id)
    if row is None:
        raise EditError(f"clip {clip_id} has no EDL yet")
    return row


def _ops(tx: WriteTx, clip_id: int) -> list[EditOp]:
    return list(
        tx.session.exec(select(EditOp).where(EditOp.clip_id == clip_id).order_by(col(EditOp.id))).all()
    )


class EdlService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------ reads

    def get(self, clip_id: int) -> tuple[Edl, int, str | None]:
        with self.db.read() as s:
            row = s.get(EdlRow, clip_id)
            if row is None:
                raise EditError(f"clip {clip_id} has no EDL yet")
            return Edl.model_validate(row.data), row.version, row.locked_by

    def history(self, clip_id: int) -> list[EditOp]:
        with self.db.read() as s:
            return list(
                s.exec(select(EditOp).where(EditOp.clip_id == clip_id).order_by(col(EditOp.id))).all()
            )

    def silences_for(self, clip_id: int) -> list[tuple[float, float]]:
        with self.db.read() as s:
            clip = s.get(Clip, clip_id)
            moment = s.get(Moment, clip.moment_id) if clip else None
            analysis = s.get(Analysis, moment.source_id) if moment else None
            raw: list[list[float]] = (analysis.signals_json.get("silences", []) if analysis else []) or []
            return [(float(a), float(b)) for a, b in raw]

    # ------------------------------------------------------------ writes

    def init(self, clip_id: int, edl: Edl, actor: str = "system", reason: str = "first cut") -> int:
        def job(tx: WriteTx) -> int:
            row = tx.session.get(EdlRow, clip_id)
            data = edl.model_dump(mode="json")
            if row is None:
                row = EdlRow(clip_id=clip_id, version=1, data=data)
            else:
                row.version += 1
                row.data = data
                row.updated_at = utcnow()
            tx.add(row)
            op = EditOp(
                clip_id=clip_id, version=row.version, actor=actor, op=INIT, args_json=data, reason=reason
            )
            tx.add(op)
            tx.flush()
            assert op.id is not None
            tx.publish(
                EditOpApplied(
                    clip_id=clip_id, op_id=op.id, op=INIT, actor=actor, version=row.version, reason=reason
                )
            )
            return row.version

        return self.db.write(job)

    def apply(self, clip_id: int, op: str, args: dict[str, Any], *, actor: str, reason: str = "") -> Applied:
        if op == "remove_silences" and not args.get("silences"):
            args = {**args, "silences": self.silences_for(clip_id)}

        def job(tx: WriteTx) -> Applied:
            row = _load(tx, clip_id)
            if row.locked_by == "user" and actor != "user":
                raise LockedError(f"the user took over clip {clip_id}")
            current = Edl.model_validate(row.data)
            result = apply_op(current, op, args)
            row.version += 1
            row.data = result.edl.model_dump(mode="json")
            row.updated_at = utcnow()
            tx.add(row)
            rec = EditOp(
                clip_id=clip_id,
                version=row.version,
                actor=actor,
                op=op,
                args_json=args,
                reason=reason or result.summary,
            )
            tx.add(rec)
            tx.flush()
            assert rec.id is not None
            tx.publish(
                EditOpApplied(
                    clip_id=clip_id,
                    op_id=rec.id,
                    op=op,
                    actor=actor,
                    version=row.version,
                    reason=rec.reason,
                    range=list(result.out_range) if result.out_range else None,
                )
            )
            return Applied(rec.id, row.version, result.edl, result.summary, result.out_range)

        return self.db.write(job)

    def undo(self, clip_id: int, op_id: int, *, actor: str) -> tuple[Edl, list[str]]:
        def job(tx: WriteTx) -> tuple[Edl, list[str]]:
            row = _load(tx, clip_id)
            if row.locked_by == "user" and actor != "user":
                raise LockedError(f"the user took over clip {clip_id}")
            ops = _ops(tx, clip_id)
            target = next((o for o in ops if o.id == op_id), None)
            if target is None or target.op == INIT:
                raise EditError(f"op {op_id} can't be undone")
            target.undone = not target.undone  # undo twice = redo
            tx.add(target)
            inits = [o for o in ops if o.op == INIT]
            base = inits[-1]
            later = [
                o for o in ops if o.id is not None and base.id is not None and o.id > base.id and not o.undone
            ]
            edl, skipped = replay(
                Edl.model_validate(base.args_json), [(o.op, dict(o.args_json)) for o in later]
            )
            row.version += 1
            row.data = edl.model_dump(mode="json")
            row.updated_at = utcnow()
            tx.add(row)
            tx.publish(
                EditOpApplied(
                    clip_id=clip_id,
                    op_id=op_id,
                    op=target.op,
                    actor=actor,
                    version=row.version,
                    reason="undo",
                    undone=target.undone,
                )
            )
            return edl, skipped

        return self.db.write(job)

    def take_over(self, clip_id: int, holder: str = "user") -> None:
        self._set_lock(clip_id, holder, "took over")

    def hand_back(self, clip_id: int) -> None:
        self._set_lock(clip_id, None, "handed back")

    def _set_lock(self, clip_id: int, holder: str | None, text: str) -> None:
        def job(tx: WriteTx) -> None:
            row = _load(tx, clip_id)
            row.locked_by = holder
            tx.add(row)
            tx.publish(EditStatus(clip_id=clip_id, actor=holder or "user", text=f"{holder or 'user'} {text}"))

        self.db.write(job)

    def status(
        self, clip_id: int, actor: str, text: str, out_range: tuple[float, float] | None = None
    ) -> None:
        """Live 'Claude is editing: ...' line for the Edit page (no state change)."""
        self.db.write(
            lambda tx: tx.publish(
                EditStatus(
                    clip_id=clip_id, actor=actor, text=text, range=list(out_range) if out_range else None
                )
            )
        )

    def make_variant(self, clip_id: int, changes: list[dict[str, Any]], *, label: str, actor: str) -> int:
        """Copy the clip and its current EDL, apply ``changes`` ([{op, args}]) to the copy. Returns the new clip id."""
        edl, _, _ = self.get(clip_id)
        for change in changes:
            edl = apply_op(edl, str(change["op"]), dict(change.get("args", {}))).edl

        def job(tx: WriteTx) -> int:
            src = tx.session.get(Clip, clip_id)
            if src is None:
                raise EditError(f"clip {clip_id} not found")
            clone = Clip(
                moment_id=src.moment_id,
                campaign_id=src.campaign_id,
                version=1,
                variant_of=src.variant_of or src.id,
                variant_label=label,
                layout=src.layout,
                caption_style=edl.captions.style,
                status="draft",
            )
            tx.add(clone)
            tx.flush()
            assert clone.id is not None
            data = edl.model_copy(update={"variant": label}).model_dump(mode="json")
            tx.add(EdlRow(clip_id=clone.id, version=1, data=data))
            op = EditOp(
                clip_id=clone.id,
                version=1,
                actor=actor,
                op=INIT,
                args_json=data,
                reason=f"variant of clip {clip_id}: {label}",
            )
            tx.add(op)
            tx.flush()
            assert op.id is not None
            tx.publish(
                ClipUpdated(clip_id=clone.id, status="draft", campaign_id=clone.campaign_id, version=1)
            )
            return clone.id

        return self.db.write(job)


def source_path_for_clip(db: Database, clip_id: int) -> str | None:
    with db.read() as s:
        clip = s.get(Clip, clip_id)
        moment = s.get(Moment, clip.moment_id) if clip else None
        source = s.get(Source, moment.source_id) if moment else None
        return source.path if source else None
