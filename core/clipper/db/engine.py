"""SQLite engine (WAL), the single writer queue and the read API.

PLAN §17.3: all writes go through one writer queue in clipper-core, so agents and API handlers never
write directly. ``WriterQueue`` owns one thread and one connection; every write job runs inside a
transaction on that thread, one at a time. That serialization is also what makes "check the cap, then
insert the post" atomic (see ``clipper.rules.caps``).

Write jobs receive a ``WriteTx``: the session plus ``emit()`` for events. Events are persisted in the
same transaction (outbox pattern) and dispatched to in-process listeners only after commit.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import sqlite3
import threading
from collections.abc import Callable, Generator
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from clipper.db.models import Event
from clipper.events.types import EventPayload

log = logging.getLogger(__name__)


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _apply_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


def make_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        _sqlite_url(path),
        connect_args={"check_same_thread": False, "timeout": 10},
        poolclass=NullPool,
    )
    event.listen(engine, "connect", _apply_pragmas)
    return engine


def readonly_connection(path: Path) -> sqlite3.Connection:
    """A connection that cannot write (used by the ``insights`` tools)."""
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class WriteTx:
    session: Session
    events: list[Event] = field(default_factory=lambda: [])

    def emit(self, type_: str, *, entity: str | None = None, entity_id: Any = None, **payload: Any) -> Event:
        row = Event(
            type=type_,
            entity=entity,
            entity_id=None if entity_id is None else str(entity_id),
            payload=payload,
        )
        self.session.add(row)
        self.events.append(row)
        return row

    def publish(self, payload: EventPayload) -> Event:
        """Persist a typed event in this transaction; listeners see it after commit."""
        row = Event(
            type=payload.TYPE,
            entity=payload.ENTITY,
            entity_id=payload.entity_id(),
            payload=payload.model_dump(mode="json"),
        )
        self.session.add(row)
        self.events.append(row)
        return row

    def add(self, obj: Any) -> Any:
        self.session.add(obj)
        return obj

    def flush(self) -> None:
        self.session.flush()


CommitListener = Callable[[list[Event]], None]
_STOP = object()


class WriterQueue:
    """One thread, one transaction at a time."""

    def __init__(self, engine: Engine, name: str = "clipper-writer") -> None:
        self._engine = engine
        self._queue: queue.Queue[Any] = queue.Queue()
        self._listeners: list[CommitListener] = []
        self._thread = threading.Thread(target=self._loop, name=name, daemon=True)
        self._closed = False
        self._thread.start()

    def add_commit_listener(self, listener: CommitListener) -> None:
        self._listeners.append(listener)

    def submit[T](self, fn: Callable[[WriteTx], T]) -> Future[T]:
        if self._closed:
            raise RuntimeError("writer queue is closed")
        fut: Future[T] = Future()
        if threading.current_thread() is self._thread:
            # Re-entrant write from inside a write job: run inline in the same transaction is not
            # possible here (we don't have it), so refuse loudly instead of deadlocking.
            raise RuntimeError("nested write submitted from the writer thread")
        self._queue.put((fn, fut))
        return fut

    def run[T](self, fn: Callable[[WriteTx], T], timeout: float | None = 60.0) -> T:
        return self.submit(fn).result(timeout=timeout)

    async def arun[T](self, fn: Callable[[WriteTx], T]) -> T:
        return await asyncio.wrap_future(self.submit(fn))

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            fn, fut = item
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                with Session(self._engine, expire_on_commit=False) as session:
                    tx = WriteTx(session)
                    result = fn(tx)
                    session.commit()
                    events = list(tx.events)
            except BaseException as exc:
                fut.set_exception(exc)
                continue
            fut.set_result(result)
            if events:
                for listener in list(self._listeners):
                    try:
                        listener(events)
                    except Exception:
                        log.exception("commit listener failed")

    def close(self, timeout: float = 10.0) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout)


class Database:
    """Engine + writer queue + read sessions for one SQLite file."""

    def __init__(self, path: Path, *, create: bool = False) -> None:
        self.path = path
        self.engine = make_engine(path)
        if create:
            from clipper.db.migrate import upgrade_to_head

            upgrade_to_head(path)
        self.writer = WriterQueue(self.engine)

    @contextmanager
    def read(self) -> Generator[Session]:
        """A short-lived session for reads. Never commit through it."""
        with Session(self.engine, expire_on_commit=False) as session:
            yield session

    def write[T](self, fn: Callable[[WriteTx], T]) -> T:
        return self.writer.run(fn)

    async def awrite[T](self, fn: Callable[[WriteTx], T]) -> T:
        return await self.writer.arun(fn)

    def readonly(self) -> sqlite3.Connection:
        return readonly_connection(self.path)

    def close(self) -> None:
        self.writer.close()
        self.engine.dispose()
