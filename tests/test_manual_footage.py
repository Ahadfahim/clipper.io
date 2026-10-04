"""Footage you download yourself: attach a file to a source, or drop it in the campaign's folder.
And retrying a failed download or job."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlmodel import select

from clipper.core import Core
from clipper.db.models import Job, Question, Source
from clipper.db.types import JobStatus, SourceStatus
from clipper.services.base import ServiceError
from clipper.services.recipe_check import check_clip
from tests.factories import make_campaign, make_source

pytestmark = pytest.mark.ffmpeg


@pytest.fixture
def video(core: Core, tmp_path: Path) -> Path:
    out = tmp_path / "Downloads" / "MrBeast grocery store.mp4"
    out.parent.mkdir()
    shutil.copy(check_clip(core), out)
    return out


def _failed_source(core: Core) -> tuple[int, int]:
    camp = make_campaign(core.db)
    assert camp.id is not None
    src = make_source(core.db, camp.id, url="https://f.io/rnWUqe5F", status=SourceStatus.FAILED)
    assert src.id is not None
    return camp.id, src.id


def _jobs(core: Core, kind: str) -> list[Job]:
    with core.db.read() as s:
        return list(s.exec(select(Job).where(Job.kind == kind)).all())


def test_attach_copies_the_file_in_and_queues_the_analysis(core: Core, video: Path) -> None:
    cid, sid = _failed_source(core)
    qid = core.notify.ask_user(
        "Campaign 2: the Frame.io download failed. How should I get the episode?",
        ["I'll attach the file", "Pause this campaign"],
        session_id=None,
        campaign_id=cid,
    )
    res = core.media.attach_file(sid, video)
    copied = Path(res["path"])
    assert copied.parent == core.media.drop_folder(cid) and copied.is_file() and video.is_file()
    src = core.media.source(sid)
    assert src.status == SourceStatus.DOWNLOADED and src.path == str(copied) and (src.duration or 0) > 7
    assert [j.input_json["source_id"] for j in _jobs(core, "analyze")] == [sid]
    with core.db.read() as s:
        q = s.get(Question, qid)
    assert q is not None and q.status == "answered" and "MrBeast grocery store.mp4" in (q.answer or "")


def test_attach_refuses_what_isnt_a_video(core: Core, tmp_path: Path) -> None:
    _cid, sid = _failed_source(core)
    with pytest.raises(ServiceError, match="no such file"):
        core.media.attach_file(sid, tmp_path / "nope.mp4")
    notes = tmp_path / "notes.txt"
    notes.write_text("hi")
    with pytest.raises(ServiceError, match="isn't a video"):
        core.media.attach_file(sid, notes)
    fake = tmp_path / "broken.mp4"
    fake.write_bytes(b"not a video")
    with pytest.raises(ServiceError, match="doesn't read as a video"):
        core.media.attach_file(sid, fake)


def test_a_file_dropped_in_the_campaign_folder_is_attached_once_it_stops_growing(
    core: Core, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("clipper.services.media.DROP_SCAN_EVERY_S", 0.0)
    cid, sid = _failed_source(core)
    folder = core.media.drop_folder(cid)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(video, folder / video.name)
    assert core.media.scan_drop_folders() == []  # first sighting: could still be copying
    attached = core.media.scan_drop_folders()  # same size on the next scan: done
    assert [a["source_id"] for a in attached] == [sid]
    assert core.media.source(sid).path == str(folder / video.name)  # used in place, not copied
    assert core.media.scan_drop_folders() == []  # known now


def test_retry_a_failed_download_and_a_failed_job(core: Core) -> None:
    cid, sid = _failed_source(core)
    res = core.media.request_download(cid, "https://f.io/rnWUqe5F")
    assert res["source_id"] == sid and res["job_id"] is not None
    with core.db.read() as s:
        src = s.get(Source, sid)
    assert src is not None and src.status == SourceStatus.QUEUED

    def fail(tx: object) -> None:
        row = tx.session.get(Job, res["job_id"])  # type: ignore[attr-defined]
        row.status = JobStatus.FAILED
        tx.add(row)  # type: ignore[attr-defined]

    core.db.write(fail)
    new_id = core.jobs.retry(res["job_id"])
    assert new_id != res["job_id"] and len(_jobs(core, "download")) == 2
    with pytest.raises(ValueError, match="only failed or cancelled"):
        core.jobs.retry(new_id)
