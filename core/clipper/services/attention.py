"""What you do about a Needs you item: snooze it, dismiss it, bring it back, or answer in your own words.

The items themselves are computed from the other tables on every read (``api/needs_you.py``). This
service only remembers what you decided about one, in the ``attention`` table, and sends a free-text
reply to whoever can act on it: the agent that asked, the campaign's agent, or the Director.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import select

from clipper.db.engine import WriteTx
from clipper.db.models import Attention, Event, Job, ReviewBatch
from clipper.events.types import AttentionChanged, UserChat
from clipper.services.base import Service, ServiceError

KEY = re.compile(r"^(?:(?:challenge|question|join|review|campaign|alert):\d+|failure:job:\d+)$")
# Only these can be dismissed. A question, a blocked account or a review that is waiting for you would
# stay unanswered if it vanished, and an agent or a posting schedule would wait on it silently.
DISMISSABLE = ("alert", "failure")
MAX_SNOOZE_MIN = 7 * 24 * 60
MAX_REPLY = 2000
NOTE_LIMIT = 1000  # what the agenda keeps of a note


def kind_of(key: str) -> str:
    return key.split(":", 1)[0]


def key_of(slug: str) -> str:
    """The key an address stands for. A key has colons (``failure:job:2``), which can't be in a file
    name (the static UI fixtures) and are awkward in a URL, so addresses use dashes instead."""
    return slug.replace("-", ":")


def slug_of(key: str) -> str:
    return key.replace(":", "-")


def check_key(key: str) -> str:
    if not KEY.match(key):
        raise ServiceError(f"{key!r} is not a Needs you item")
    return key


class AttentionService(Service):
    def hidden(self, now: datetime | None = None) -> set[str]:
        """Keys you dismissed, or snoozed and whose time has not come yet."""
        now = now or self.now()
        with self.db.read() as s:
            rows = s.exec(select(Attention)).all()
        out: set[str] = set()
        for r in rows:
            if r.state == "dismissed" or (
                r.state == "snoozed" and r.snoozed_until is not None and _utc(r.snoozed_until) > now
            ):
                out.add(r.key)
        return out

    def dismiss(self, key: str, *, note: str | None = None, by: str = "user") -> None:
        check_key(key)
        if kind_of(key) not in DISMISSABLE:
            raise ServiceError("this one is waiting for you, so it can only be snoozed")
        self._set(key, "dismissed", None, note, by)

    def snooze(self, key: str, minutes: int, *, by: str = "user") -> datetime:
        check_key(key)
        if not 1 <= minutes <= MAX_SNOOZE_MIN:
            raise ServiceError(f"snooze between 1 minute and {MAX_SNOOZE_MIN // 1440} days")
        until = self.now() + timedelta(minutes=minutes)
        self._set(key, "snoozed", until, None, by)
        return until

    def reopen(self, key: str, *, by: str = "user") -> None:
        check_key(key)

        def job(tx: WriteTx) -> None:
            row = tx.session.get(Attention, key)
            if row is not None:
                tx.session.delete(row)
            tx.publish(AttentionChanged(key=key, state="open", by=by))

        self.db.write(job)

    def _set(self, key: str, state: str, until: datetime | None, note: str | None, by: str) -> None:
        now = self.now()

        def job(tx: WriteTx) -> None:
            row = tx.session.get(Attention, key) or Attention(key=key, state=state)
            row.state, row.snoozed_until, row.note, row.by, row.updated_at = state, until, note, by, now
            tx.add(row)
            tx.publish(AttentionChanged(key=key, state=state, by=by))

        self.db.write(job)

    # ------------------------------------------------------------ replies

    def campaign_of(self, key: str) -> int | None:
        """The campaign an item is about, if any."""
        check_key(key)
        kind, _, rest = key.partition(":")
        ident = int(rest.rsplit(":", 1)[-1])
        with self.db.read() as s:
            if kind in ("campaign", "join"):
                return ident
            if kind == "review":
                batch = s.get(ReviewBatch, ident)
                return batch.campaign_id if batch else None
            if kind == "failure":
                job = s.get(Job, ident)
                return job.campaign_id if job else None
            if kind == "alert":
                ev = s.get(Event, ident)
                cid = ev.payload.get("campaign_id") if ev else None
                return int(cid) if cid is not None else None
        return None

    def reply(
        self, key: str, text: str, *, about: str, by: str = "user", via: str = "dashboard"
    ) -> dict[str, Any]:
        """Your own words for an item. A question gets them as its answer; anything else goes to the
        campaign's agent as a note (it resumes at once), or to the Director when no campaign is involved."""
        check_key(key)
        text = text.strip()
        if not text:
            raise ServiceError("write something first")
        if len(text) > MAX_REPLY:
            raise ServiceError(f"keep it under {MAX_REPLY} characters")
        if kind_of(key) == "question":
            qid = int(key.split(":")[1])
            self.core.notify.answer(qid, text, by=by, via=via, custom=True)
            return {"routed_to": "question", "id": qid}
        campaign_id = self.campaign_of(key)
        framed = f"About: {about}. {text}"
        if campaign_id is not None:
            if len(framed) > NOTE_LIMIT:
                raise ServiceError(
                    f"keep it under {NOTE_LIMIT - len(framed) + len(text)} characters for the campaign's agent"
                )
            note_id = self.core.agenda.add_note(
                "campaign", str(campaign_id), framed, author=by, campaign_id=campaign_id
            )
            return {"routed_to": "campaign", "id": note_id}
        env = self.core.bus.publish(UserChat(text=framed, via=via))
        return {"routed_to": "director", "id": env.id}


def _utc(value: datetime) -> datetime:
    from clipper.clock import ensure_utc

    return ensure_utc(value)
