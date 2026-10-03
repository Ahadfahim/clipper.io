"""Alerts, questions for the user (``ask_user``) and reports (PLAN §16.1 notify)."""

from __future__ import annotations

import contextlib
from datetime import timedelta
from typing import Any

import httpx
from sqlmodel import col, select

from clipper.db.engine import WriteTx
from clipper.db.models import Question
from clipper.db.types import QuestionStatus
from clipper.events.types import Alert, QuestionAnswered, QuestionAsked, Report
from clipper.services.base import Service, ServiceError


class NotifyService(Service):
    def alert(self, level: str, text: str, *, source: str = "system", campaign_id: int | None = None) -> None:
        if level not in ("info", "warning", "error"):
            level = "warning"
        self.db.write(
            lambda tx: tx.publish(
                Alert(level=level, text=text[:1000], source=source, campaign_id=campaign_id)
            )
        )  # type: ignore[arg-type]
        self._push(level, text)

    def _push(self, level: str, text: str) -> None:
        cfg = self.settings.notify
        if not cfg.ntfy_url or not cfg.ntfy_topic or level == "info":
            return
        with contextlib.suppress(httpx.HTTPError):
            httpx.post(
                f"{cfg.ntfy_url.rstrip('/')}/{cfg.ntfy_topic}",
                content=text.encode("utf-8"),
                timeout=5,
                headers={"Title": "Clipper"},
            )

    def ask_user(
        self,
        text: str,
        options: list[str],
        *,
        session_id: int | None,
        campaign_id: int | None,
        timeout_s: float | None = None,
    ) -> int:
        if not options or len(options) > 5:
            raise ServiceError("give 1-5 answer options")
        timeout_at = self.now() + timedelta(seconds=timeout_s) if timeout_s else None

        def job(tx: WriteTx) -> int:
            q = Question(
                session_id=session_id,
                campaign_id=campaign_id,
                text=text[:1000],
                options_json=[o[:80] for o in options],
                timeout_at=timeout_at,
            )
            tx.add(q)
            tx.flush()
            assert q.id is not None
            tx.publish(
                QuestionAsked(
                    question_id=q.id,
                    session_id=session_id,
                    campaign_id=campaign_id,
                    text=q.text,
                    options=q.options_json,
                )
            )
            return q.id

        qid = self.db.write(job)
        self._push("warning", f"Clipper asks: {text}")
        return qid

    def answer(self, question_id: int, answer: str, *, by: str, via: str) -> None:
        def job(tx: WriteTx) -> None:
            q = tx.session.get(Question, question_id)
            if q is None:
                raise ServiceError(f"question {question_id} not found")
            if q.status != QuestionStatus.OPEN:
                raise ServiceError(f"question {question_id} is already {q.status}")
            q.answer = answer[:500]
            q.answered_by = by
            q.via = via
            q.status = QuestionStatus.ANSWERED
            q.answered_at = self.now()
            tx.add(q)
            tx.publish(
                QuestionAnswered(
                    question_id=question_id,
                    session_id=q.session_id,
                    campaign_id=q.campaign_id,
                    answer=q.answer,
                    via=via,
                )
            )

        self.db.write(job)

    def expire(self) -> list[int]:
        now = self.now()

        def job(tx: WriteTx) -> list[int]:
            rows = tx.session.exec(
                select(Question).where(
                    Question.status == QuestionStatus.OPEN, col(Question.timeout_at) <= now
                )
            ).all()
            out: list[int] = []
            for q in rows:
                q.status = QuestionStatus.TIMED_OUT
                q.answer = "(no answer before the timeout)"
                tx.add(q)
                assert q.id is not None
                tx.publish(
                    QuestionAnswered(
                        question_id=q.id,
                        session_id=q.session_id,
                        campaign_id=q.campaign_id,
                        answer=q.answer,
                        via="timeout",
                    )
                )
                out.append(q.id)
            return out

        return self.db.write(job)

    def open_questions(self) -> list[dict[str, Any]]:
        with self.db.read() as s:
            rows = s.exec(
                select(Question).where(Question.status == QuestionStatus.OPEN).order_by(col(Question.id))
            ).all()
        return [
            {
                "id": q.id,
                "text": q.text,
                "options": q.options_json,
                "campaign_id": q.campaign_id,
                "session_id": q.session_id,
            }
            for q in rows
        ]

    def send_report(self, markdown: str, *, source: str = "analyst") -> None:
        self.db.write(lambda tx: tx.publish(Report(markdown=markdown[:8000], source=source)))
