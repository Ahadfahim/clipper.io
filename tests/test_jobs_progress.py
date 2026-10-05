"""Jobs that say how far they are, say what they are doing, can be cancelled while they run (the process
tree is killed), and yt-dlp's progress turns into numbers."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import select

from clipper.core import Core
from clipper.db.models import Job
from clipper.db.types import JobStatus
from clipper.media.download import DownloadHooks, Progress, human_bytes, parse_progress, stream_process
from clipper.system import run_cancellable
from clipper.worker.jobs import JobContext

SAMPLE = Path(__file__).parent / "fixtures" / "ytdlp" / "progress.txt"


def _job(core: Core, job_id: int) -> Job:
    with core.db.read() as s:
        row = s.get(Job, job_id)
    assert row is not None
    return row


# ---------------------------------------------------------------- reading yt-dlp's progress


def test_progress_lines_become_numbers_and_everything_else_is_ignored() -> None:
    lines = SAMPLE.read_text(encoding="utf-8").splitlines()
    parsed = [p for p in (parse_progress(ln) for ln in lines) if p is not None]
    assert [p.downloaded for p in parsed] == [0, 20971520, 1073741824, 3567890123]
    assert parsed[1] == Progress(20971520, 3567890123, 8388608.0)  # total known only as an estimate
    assert parsed[2].total == 3567890123 and abs((parsed[2].fraction or 0) - 0.3) < 0.01
    assert parsed[0].speed is None and parsed[0].fraction == 0.0
    assert parse_progress("[clipper] garbage") is None and parse_progress("ERROR: nope") is None


def test_the_detail_line_has_size_speed_and_time_left() -> None:
    p = Progress(1_288_490_189, 3_650_722_201, 8 * 1024**2)
    assert p.detail() == "1.2 GB of 3.4 GB · 8.0 MB/s · 5 min left"
    assert Progress(500, None, None).detail() == "500 B"
    assert Progress(100, 100, 1).detail() == "100 B of 100 B · 1 B/s"
    assert human_bytes(None) == "?" and human_bytes(2048) == "2 KB"


def test_a_running_process_is_read_line_by_line_and_its_exit_code_returned() -> None:
    seen: list[str] = []
    code, out, err = stream_process(
        [
            sys.executable,
            "-c",
            "import sys; print('[clipper] 1 2 NA 1'); print('path.mp4'); print('oops', file=sys.stderr)",
        ],
        on_line=lambda ln: seen.append(ln.strip()),
        timeout=30,
    )
    assert code == 0 and out == ["[clipper] 1 2 NA 1", "path.mp4"] and "oops" in err
    assert "[clipper] 1 2 NA 1" in seen and "oops" in seen  # stderr lines are heard as they come too


# ---------------------------------------------------------------- jobs report and can be cancelled


def test_a_job_that_reports_stamps_when_it_moved_and_what_it_is_doing(core: Core) -> None:
    def handler(ctx: JobContext, data: dict[str, Any]) -> dict[str, Any]:
        ctx.detail("Transcribing")
        ctx.progress(0.5)
        return {}

    core.jobs.register("dummy", handler, "cpu")
    job_id = core.jobs.enqueue("dummy", {})
    asyncio.run(core.jobs.drain(timeout=30))
    row = _job(core, job_id)
    assert row.status == JobStatus.DONE and row.progress == 1.0
    assert row.detail == "Transcribing" and row.progress_at is not None and row.started_at is not None


def test_the_download_job_shows_the_downloaders_progress_and_words(
    core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.factories import make_campaign, make_source

    camp = make_campaign(core.db)
    assert camp.id is not None
    src = make_source(core.db, camp.id, url="https://www.youtube.com/watch?v=abc123", status="queued")
    real = core.adapters.downloader.download

    def download(url: str, dest: Path, hooks: DownloadHooks | None = None) -> Any:
        assert hooks is not None
        hooks.progress(0.5, "1.5 GB of 3.0 GB · 8.0 MB/s · 3 min left")
        return real(url, dest, hooks)

    monkeypatch.setattr(core.adapters.downloader, "download", download)
    seen: list[str | None] = []
    core.bus.add_listener(lambda e: seen.append(e.payload.get("detail")), types=["job.progress"])
    res = core.media.request_download(camp.id, src.url, analyze=False)
    asyncio.run(core.jobs.drain(timeout=60))
    assert "1.5 GB of 3.0 GB · 8.0 MB/s · 3 min left" in seen
    assert _job(core, res["job_id"]).status == JobStatus.DONE


async def test_cancelling_a_running_job_kills_its_process_and_it_can_be_retried(core: Core) -> None:
    def handler(ctx: JobContext, data: dict[str, Any]) -> dict[str, Any]:
        done = run_cancellable([sys.executable, "-c", "import time; time.sleep(120)"], timeout=300)
        ctx.check_cancelled()
        return {"code": done.returncode}

    core.jobs.register("sleeper", handler, "cpu")
    job_id = core.jobs.enqueue("sleeper", {"n": 1})
    await core.jobs.run_once()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        ctx = core.jobs._live.get(job_id)
        if ctx is not None and ctx._processes:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("the job never started its process")
    assert core.jobs.cancel_running(job_id) is True
    await core.jobs.drain(timeout=30)
    row = _job(core, job_id)
    assert row.status == JobStatus.CANCELLED and row.error == "cancelled"
    assert core.jobs.cancel_running(job_id) is False  # nothing left to cancel
    again = core.jobs.retry(job_id)
    assert again != job_id and _job(core, again).status == JobStatus.QUEUED
    core.jobs.cancel(again)


async def test_cancel_and_retry_queues_the_same_input_again_but_not_forever(core: Core) -> None:
    core.jobs.register("flaky", lambda ctx, data: {}, "cpu")
    first = core.jobs.enqueue("flaky", {"x": 1})
    new = core.jobs.cancel_and_retry(first, max_retries=3)
    assert _job(core, first).status == JobStatus.CANCELLED
    assert _job(core, new).input_json == {"x": 1}
    for _ in range(2):
        new = core.jobs.cancel_and_retry(new, max_retries=3)
    with pytest.raises(ValueError, match="tried 4 times"):
        core.jobs.cancel_and_retry(new, max_retries=3)
    with core.db.read() as s:
        assert len(s.exec(select(Job).where(Job.kind == "flaky")).all()) == 4


async def test_a_job_with_no_live_process_is_closed_by_cancel_and_retry(core: Core) -> None:
    """The app restarted: the row says running, but nothing is running it."""
    core.jobs.register("ghost", lambda ctx, data: {}, "cpu")
    job_id = core.jobs.enqueue("ghost", {})
    with core.db.read() as s:
        row = s.get(Job, job_id)
        assert row is not None
    from clipper.db.engine import WriteTx

    def mark(tx: WriteTx) -> None:
        r = tx.session.get(Job, job_id)
        assert r is not None
        r.status = JobStatus.RUNNING
        tx.add(r)

    core.db.write(mark)
    new = core.jobs.cancel_and_retry(job_id)
    assert _job(core, job_id).status == JobStatus.CANCELLED and _job(core, new).status == JobStatus.QUEUED
