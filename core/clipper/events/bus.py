"""In-process event bus on top of the writer queue's commit hook.

- ``publish()`` persists an ``event`` row through the writer queue.
- Events emitted inside any write job (``tx.publish(...)``) are persisted in that job's transaction.
- After commit, every event is delivered to listeners (sync callbacks, called on the writer thread,
  must be quick) and subscriptions (asyncio queues, safe to consume from any event loop).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator, Callable, Iterable
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlmodel import col, select

from clipper.db.engine import Database
from clipper.db.models import Event
from clipper.events.types import EVENT_TYPES, EventPayload

log = logging.getLogger(__name__)


class EventEnvelope(BaseModel):
    id: int
    type: str
    entity: str | None
    entity_id: str | None
    payload: dict[str, Any]
    ts: datetime

    @classmethod
    def from_row(cls, row: Event) -> EventEnvelope:
        assert row.id is not None
        return cls(
            id=row.id,
            type=row.type,
            entity=row.entity,
            entity_id=row.entity_id,
            payload=dict(row.payload),
            ts=row.ts,
        )

    def typed(self) -> EventPayload | None:
        model = EVENT_TYPES.get(self.type)
        return None if model is None else model.model_validate(self.payload)


Listener = Callable[[EventEnvelope], None]


def _matches(types: frozenset[str] | None, type_: str) -> bool:
    if types is None:
        return True
    return type_ in types or any(t.endswith(".*") and type_.startswith(t[:-1]) for t in types)


class Subscription:
    """An async iterator of envelopes. Close it when done."""

    def __init__(
        self, bus: EventBus, types: frozenset[str] | None, loop: asyncio.AbstractEventLoop, maxsize: int
    ) -> None:
        self._bus = bus
        self.types = types
        self._loop = loop
        self._queue: asyncio.Queue[EventEnvelope | None] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0
        self.closed = False

    def offer(self, env: EventEnvelope) -> None:
        if self.closed or not _matches(self.types, env.type):
            return

        def put() -> None:
            try:
                self._queue.put_nowait(env)
            except asyncio.QueueFull:
                self.dropped += 1

        try:
            self._loop.call_soon_threadsafe(put)
        except RuntimeError:  # loop closed
            self.closed = True

    def get_nowait(self) -> EventEnvelope | None:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def pending(self) -> int:
        return self._queue.qsize()

    async def get(self, timeout: float | None = None) -> EventEnvelope | None:
        if timeout is None:
            return await self._queue.get()
        try:
            return await asyncio.wait_for(self._queue.get(), timeout)
        except TimeoutError:
            return None

    def __aiter__(self) -> AsyncIterator[EventEnvelope]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[EventEnvelope]:
        while not self.closed:
            env = await self._queue.get()
            if env is None:
                return
            yield env

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._bus.remove_subscription(self)
        with contextlib.suppress(RuntimeError, asyncio.QueueFull):
            self._loop.call_soon_threadsafe(self._queue.put_nowait, None)


class EventBus:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._lock = threading.Lock()
        self._subs: list[Subscription] = []
        self._listeners: list[tuple[frozenset[str] | None, Listener]] = []
        db.writer.add_commit_listener(self._on_commit)

    # ------------------------------------------------------------ publishing

    def publish(self, payload: EventPayload) -> EventEnvelope:
        row = self.db.write(lambda tx: tx.publish(payload))
        return EventEnvelope.from_row(row)

    async def apublish(self, payload: EventPayload) -> EventEnvelope:
        row = await self.db.awrite(lambda tx: tx.publish(payload))
        return EventEnvelope.from_row(row)

    # ------------------------------------------------------------ consuming

    def subscribe(
        self,
        types: Iterable[str] | None = None,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        maxsize: int = 10_000,
    ) -> Subscription:
        sub = Subscription(
            self, None if types is None else frozenset(types), loop or asyncio.get_running_loop(), maxsize
        )
        with self._lock:
            self._subs.append(sub)
        return sub

    def add_listener(self, listener: Listener, types: Iterable[str] | None = None) -> None:
        with self._lock:
            self._listeners.append((None if types is None else frozenset(types), listener))

    def remove_subscription(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def _on_commit(self, rows: list[Event]) -> None:
        envs = [EventEnvelope.from_row(r) for r in rows]
        with self._lock:
            subs = list(self._subs)
            listeners = list(self._listeners)
        for env in envs:
            for types, listener in listeners:
                if _matches(types, env.type):
                    try:
                        listener(env)
                    except Exception:
                        log.exception("event listener failed for %s", env.type)
            for sub in subs:
                sub.offer(env)

    # ------------------------------------------------------------ history

    def since(
        self, after_id: int, limit: int = 500, types: Iterable[str] | None = None
    ) -> list[EventEnvelope]:
        with self.db.read() as s:
            q = select(Event).where(col(Event.id) > after_id).order_by(col(Event.id)).limit(limit)
            if types is not None:
                q = q.where(col(Event.type).in_(list(types)))
            return [EventEnvelope.from_row(r) for r in s.exec(q).all()]
