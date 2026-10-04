"""Durable job queue with per-resource concurrency (PLAN §17.3: 1 WhisperX + up to 3 NVENC encodes).

Jobs live in the ``job`` table, so nothing is lost on a crash: ``recover()`` puts interrupted jobs
back in the queue at startup. Handlers are plain functions run in worker threads (the heavy lifting
happens in ffmpeg / yt-dlp / WhisperX subprocesses). Every finished job emits ``job.done``, which the
supervisor turns into a resume of the owning Campaign agent.

Deviation from PLAN §2 (Huey): see HANDOFF §6.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from clipper.db.engine import WriteTx
from clipper.db.models import Job
from clipper.db.types import JobStatus
from clipper.events.types import JobDone, JobProgress, JobQueued
from clipper.services.control import read_control

if TYPE_CHECKING:
    from clipper.core import Core

log = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


@dataclass
class JobContext:
    core: Core
    job_id: int
    kind: str
    campaign_id: int | None
    _last_progress: float = 0.0
    _last_write: float = 0.0

    def progress(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        now = time.monotonic()
        if value < 1.0 and (value - self._last_progress < 0.05 or now - self._last_write < 0.5):
            return
        self._last_progress, self._last_write = value, now
        job_id, kind, cid = self.job_id, self.kind, self.campaign_id

        def write(tx: WriteTx) -> None:
            row = tx.session.get(Job, job_id)
            if row is not None:
                row.progress = value
                tx.add(row)
            tx.publish(JobProgress(job_id=job_id, kind=kind, progress=value, campaign_id=cid))

        self.core.db.write(write)

    def enqueue(self, kind: str, data: dict[str, Any], campaign_id: int | None = None) -> int:
        return self.core.jobs.enqueue(
            kind, data, campaign_id=campaign_id if campaign_id is not None else self.campaign_id
        )


JobHandler = Callable[[JobContext, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Registered:
    handler: JobHandler
    resource: str


class JobQueue:
    def __init__(self, core: Core) -> None:
        self.core = core
        media = core.settings.media
        self.limits: dict[str, int] = {
            "gpu": media.max_concurrent_transcribes,
            "encode": media.max_concurrent_encodes,
            "download": media.max_concurrent_downloads,
            "cpu": 2,
            "net": 4,
        }
        self.handlers: dict[str, Registered] = {}
        self._running: dict[str, int] = {}
        self._lock = threading.Lock()
        self._wake: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def register(self, kind: str, handler: JobHandler, resource: str) -> None:
        if resource not in self.limits:
            raise ValueError(f"unknown resource {resource}")
        self.handlers[kind] = Registered(handler, resource)

    # ------------------------------------------------------------ producing

    def enqueue(self, kind: str, data: dict[str, Any], *, campaign_id: int | None = None) -> int:
        if kind not in self.handlers:
            raise ValueError(f"no handler for job kind {kind!r}")

        def job(tx: WriteTx) -> int:
            row = Job(kind=kind, input_json=data, campaign_id=campaign_id, status=JobStatus.QUEUED)
            tx.add(row)
            tx.flush()
            assert row.id is not None
            tx.publish(JobQueued(job_id=row.id, kind=kind, campaign_id=campaign_id))
            return row.id

        job_id = self.core.db.write(job)
        self._poke()
        return job_id

    def cancel(self, job_id: int) -> bool:
        def job(tx: WriteTx) -> bool:
            row = tx.session.get(Job, job_id)
            if row is None or row.status != JobStatus.QUEUED:
                return False
            row.status = JobStatus.CANCELLED
            tx.add(row)
            tx.publish(JobDone(job_id=job_id, kind=row.kind, status="cancelled", campaign_id=row.campaign_id))
            return True

        return self.core.db.write(job)

    def retry(self, job_id: int) -> int:
        """Queue a failed or cancelled job again with the same input. Returns the new job's id."""
        with self.core.db.read() as s:
            row = s.get(Job, job_id)
        if row is None:
            raise ValueError(f"job {job_id} not found")
        if row.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
            raise ValueError(f"job {job_id} is {row.status}; only failed or cancelled jobs can be retried")
        return self.enqueue(row.kind, dict(row.input_json), campaign_id=row.campaign_id)

    def recover(self) -> int:
        """Put jobs that were running when the process died back in the queue."""

        def job(tx: WriteTx) -> int:
            rows = tx.session.exec(select(Job).where(Job.status == JobStatus.RUNNING)).all()
            for r in rows:
                r.status = JobStatus.QUEUED
                r.progress = 0.0
                tx.add(r)
            return len(rows)

        return self.core.db.write(job)

    def _poke(self) -> None:
        if self._loop is not None and self._wake is not None:
            self._loop.call_soon_threadsafe(self._wake.set)

    # ------------------------------------------------------------ consuming

    def _claim(self) -> list[tuple[int, Registered]]:
        with self._lock:
            free = {r: self.limits[r] - self._running.get(r, 0) for r in self.limits}
        if all(v <= 0 for v in free.values()):
            return []

        def job(tx: WriteTx) -> list[tuple[int, str]]:
            rows = tx.session.exec(
                select(Job).where(Job.status == JobStatus.QUEUED).order_by(col(Job.id)).limit(50)
            ).all()
            claimed: list[tuple[int, str]] = []
            for r in rows:
                reg = self.handlers.get(r.kind)
                if reg is None or free.get(reg.resource, 0) <= 0:
                    continue
                free[reg.resource] -= 1
                r.status = JobStatus.RUNNING
                r.started_at = self.core.clock.now()
                tx.add(r)
                assert r.id is not None
                claimed.append((r.id, r.kind))
            return claimed

        out: list[tuple[int, Registered]] = []
        for job_id, kind in self.core.db.write(job):
            reg = self.handlers[kind]
            with self._lock:
                self._running[reg.resource] = self._running.get(reg.resource, 0) + 1
            out.append((job_id, reg))
        return out

    def _execute(self, job_id: int, reg: Registered) -> None:
        with self.core.db.read() as s:
            row = s.get(Job, job_id)
            assert row is not None
            kind, data, cid = row.kind, dict(row.input_json), row.campaign_id
        ctx = JobContext(self.core, job_id, kind, cid)
        try:
            result = reg.handler(ctx, data)
            status, error = JobStatus.DONE, None
        except JobCancelled:
            result, status, error = {}, JobStatus.CANCELLED, "cancelled"
        except Exception as exc:
            log.exception("job %s (%s) failed", job_id, kind)
            result, status, error = {}, JobStatus.FAILED, f"{type(exc).__name__}: {exc}"[:2000]
        finally:
            with self._lock:
                self._running[reg.resource] -= 1

        def finish(tx: WriteTx) -> None:
            r = tx.session.get(Job, job_id)
            assert r is not None
            r.status = status
            r.result_json = result
            r.error = error
            r.progress = 1.0 if status == JobStatus.DONE else r.progress
            r.finished_at = self.core.clock.now()
            tx.add(r)
            tx.publish(
                JobDone(
                    job_id=job_id, kind=kind, status=status.value, campaign_id=cid, result=result, error=error
                )
            )  # type: ignore[arg-type]

        self.core.db.write(finish)
        self._poke()

    async def run_once(self) -> int:
        if read_control(self.core.db).kill_switch:
            return 0
        claimed = self._claim()
        for job_id, reg in claimed:
            task = asyncio.create_task(asyncio.to_thread(self._execute, job_id, reg))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return len(claimed)

    async def run_forever(self, stop: asyncio.Event, poll_s: float = 2.0) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self.recover()
        while not stop.is_set():
            await self.run_once()
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=poll_s)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def drain(self, timeout: float = 120.0) -> None:
        """Run until no job is queued or running (tests and the e2e flow)."""
        deadline = time.monotonic() + timeout
        while True:
            await self.run_once()
            if self._tasks:
                await asyncio.wait(list(self._tasks), timeout=0.5)
            with self.core.db.read() as s:
                pending = s.exec(
                    select(Job.id).where(col(Job.status).in_([JobStatus.QUEUED, JobStatus.RUNNING]))
                ).first()
            if pending is None and not self._tasks:
                return
            if time.monotonic() > deadline:
                raise TimeoutError("jobs did not finish in time")
            await asyncio.sleep(0.02)
