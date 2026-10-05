"""Footage you download yourself: attach a file to a source, or drop it in the campaign's folder.
And retrying a failed download or job."""

from __future__ import annotations

import asyncio
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
    res = core.media.request_download(cid, "https://f.io/rnWUqe5F", force=True)  # Try download anyway
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


def test_file_hosts_have_no_comments(core: Core) -> None:
    _cid, sid = _failed_source(core)  # https://f.io/... (Frame.io)
    assert core.media.comments(sid) == []


def test_campaigns_whose_payouts_ended_are_never_suggested_and_wind_down(core: Core) -> None:
    from clipper.db.models import Campaign
    from clipper.db.types import CampaignStatus
    from clipper.marketplaces.base import CampaignCard

    def card(ext: str, ended: bool) -> CampaignCard:
        return CampaignCard(marketplace="vyro", external_id=ext, title=ext, cpm_usd=1.0, payouts_ended=ended)

    core.campaigns.upsert_cards([card("fresh", False), card("dead", True)])
    with core.db.read() as s:
        rows = {c.external_id: c.status for c in s.exec(select(Campaign)).all()}
    assert rows["fresh"] == CampaignStatus.SUGGESTED and rows["dead"] == CampaignStatus.ENDED

    def activate(tx: object) -> None:
        row = tx.session.exec(select(Campaign).where(Campaign.external_id == "fresh")).one()  # type: ignore[attr-defined]
        row.status = CampaignStatus.ACTIVE
        tx.add(row)  # type: ignore[attr-defined]

    core.db.write(activate)
    core.campaigns.upsert_cards([card("fresh", True)])  # its payouts ended while we work on it
    with core.db.read() as s:
        status = s.exec(select(Campaign).where(Campaign.external_id == "fresh")).one().status
    assert status == CampaignStatus.ENDING


# ---------------------------------------------------------------- the drop folder only takes the right file


def _drop(core: Core, cid: int, video: Path, *, age_s: float = 0.0) -> Path:
    import os
    import time

    folder = core.media.drop_folder(cid)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / video.name
    shutil.copy(video, target)
    when = time.time() - age_s
    os.utime(target, (when, when))
    return target


def _alerts(core: Core) -> list[str]:
    seen: list[str] = []
    core.bus.add_listener(lambda e: seen.append(str(e.payload["text"])), types=["alert"])
    return seen


def test_a_source_that_was_only_listed_never_takes_a_file_from_the_folder(
    core: Core, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("clipper.services.media.DROP_SCAN_EVERY_S", 0.0)
    camp = make_campaign(core.db)
    assert camp.id is not None
    for status in (SourceStatus.LISTED, SourceStatus.QUEUED, SourceStatus.DOWNLOADING):
        make_source(core.db, camp.id, url=f"https://f.io/{status}", status=status)
    _drop(core, camp.id, video)
    assert core.media.scan_drop_folders() == []
    assert core.media.scan_drop_folders() == []  # stable size, still not taken
    with core.db.read() as s:
        assert all(x.path is None for x in s.exec(select(Source)).all())


def test_a_file_older_than_the_request_is_left_alone_and_mentioned_once(
    core: Core, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("clipper.services.media.DROP_SCAN_EVERY_S", 0.0)
    cid, sid = _failed_source(core)
    _drop(core, cid, video, age_s=3600)  # a leftover from before the source existed
    alerts = _alerts(core)
    assert [core.media.scan_drop_folders() for _ in range(4)] == [[], [], [], []]
    assert core.media.source(sid).path is None
    assert len(alerts) == 1 and "older than the request" in alerts[0] and video.name in alerts[0]


def test_a_file_shorter_than_the_spec_minimum_is_left_alone_and_mentioned_once(
    core: Core, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from clipper.rules.spec import ClipSpec

    monkeypatch.setattr("clipper.services.media.DROP_SCAN_EVERY_S", 0.0)
    cid, sid = _failed_source(core)
    core.campaigns.save_spec(cid, ClipSpec(duration_min_s=45.0))
    _drop(core, cid, video)  # the test clip is about 8 s long
    alerts = _alerts(core)
    assert [core.media.scan_drop_folders() for _ in range(4)] == [[], [], [], []]
    assert core.media.source(sid).path is None
    assert len(alerts) == 1 and "only 0:0" in alerts[0] and "at least 0:45" in alerts[0]


def test_without_a_spec_the_length_is_not_checked(core: Core, video: Path) -> None:
    _cid, sid = _failed_source(core)
    assert core.media.attach_file(sid, video, check=True)["source_id"] == sid
    assert core.media.source(sid).status == SourceStatus.DOWNLOADED


def test_attach_with_check_raises_suspicious_footage(core: Core, video: Path) -> None:
    from clipper.rules.spec import ClipSpec
    from clipper.services.media import SuspiciousFootage

    cid, sid = _failed_source(core)
    core.campaigns.save_spec(cid, ClipSpec(duration_min_s=45.0))
    with pytest.raises(SuspiciousFootage) as err:
        core.media.attach_file(sid, video, check=True)
    assert err.value.minimum == 45.0 and 7 < err.value.duration < 12
    assert core.media.source(sid).status == SourceStatus.FAILED
    assert core.media.attach_file(sid, video)["source_id"] == sid  # the user confirmed


# ---------------------------------------------------------------- footage that needs you


def test_a_share_page_is_not_downloaded_it_asks_for_the_file(core: Core) -> None:
    camp = make_campaign(core.db)
    assert camp.id is not None
    seen: list[object] = []
    core.bus.add_listener(lambda e: seen.append(e.payload), types=["source.needs_footage"])
    res = core.media.request_download(camp.id, "https://f.io/rnWUqe5F")
    assert res["job_id"] is None and res["status"] == "needs_footage"
    assert _jobs(core, "download") == []
    src = core.media.source(res["source_id"])
    assert (
        src.status == SourceStatus.NEEDS_FOOTAGE
        and "f.io links" in (src.reason or "")
        and src.waiting_since is not None
    )
    assert len(seen) == 1
    # a normal link is queued as before, and "Try download anyway" queues the blocked one
    ok = core.media.request_download(camp.id, "https://www.youtube.com/watch?v=abc123")
    assert ok["job_id"] is not None
    forced = core.media.request_download(camp.id, "https://f.io/rnWUqe5F", force=True)
    assert forced["job_id"] is not None and core.media.source(res["source_id"]).status == SourceStatus.QUEUED


def test_the_agent_can_say_a_source_needs_footage(core: Core) -> None:
    cid, sid = _failed_source(core)
    out = core.media.need_footage(sid, "The only source is a Frame.io share link")
    assert out["status"] == "needs_footage" and "end your turn" in out["next"]
    src = core.media.source(sid)
    assert (
        src.status == SourceStatus.NEEDS_FOOTAGE and src.reason == "The only source is a Frame.io share link"
    )
    done = make_source(core.db, cid, url="https://x.example/a", status=SourceStatus.ANALYZED)
    with pytest.raises(ServiceError, match="already has its video"):
        core.media.need_footage(done.id or 0, "nope")
    with pytest.raises(ServiceError, match="not found"):
        core.media.need_footage(999, "x")


def test_the_drop_folder_also_serves_a_source_that_needs_footage(
    core: Core, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("clipper.services.media.DROP_SCAN_EVERY_S", 0.0)
    camp = make_campaign(core.db)
    res = core.media.request_download(camp.id or 0, "https://we.tl/t-abc")
    _drop(core, camp.id or 0, video)
    assert core.media.scan_drop_folders() == []
    assert [a["source_id"] for a in core.media.scan_drop_folders()] == [res["source_id"]]


def test_a_skipped_source_leaves_the_agent_a_note(core: Core) -> None:
    _cid, sid = _failed_source(core)
    notes: list[object] = []
    core.bus.add_listener(lambda e: notes.append(e.payload), types=["note.added"])
    core.media.skip_source(sid)
    assert core.media.source(sid).status == SourceStatus.SKIPPED
    assert notes and "skipped source" in str(notes[0])


def test_inspecting_a_file_warns_when_it_looks_wrong(core: Core, video: Path) -> None:
    from clipper.rules.spec import ClipSpec

    cid, sid = _failed_source(core)
    info = core.media.inspect_file(sid, video)
    assert info["name"] == video.name and 7 < info["duration"] < 12 and info["has_audio"]
    assert [w["code"] for w in info["warnings"]] == ["short"]  # about 8 s: far from a source video
    core.campaigns.save_spec(cid, ClipSpec(duration_min_s=45.0))
    assert "at least 0:45" in core.media.inspect_file(sid, video)["warnings"][0]["text"]
    note = video.with_suffix(".txt")
    note.write_text("x")
    with pytest.raises(ServiceError, match="isn't a video"):
        core.media.inspect_file(sid, note)


def test_recent_downloads_are_offered_newest_first_and_only_videos(
    core: Core, video: Path, tmp_path: Path
) -> None:
    import os
    import time

    downloads = tmp_path / "Recent"
    downloads.mkdir()
    object.__setattr__(core.settings.media, "downloads_dirs", [downloads])
    _cid, sid = _failed_source(core)
    now = time.time()
    for name, age_h in (("new.mp4", 1), ("older.mp4", 5), ("ancient.mp4", 80)):
        f = downloads / name
        shutil.copy(video, f)
        stamp = now - age_h * 3600
        os.utime(f, (stamp, stamp))
    (downloads / "notes.txt").write_text("x")
    names = [c["name"] for c in core.media.candidates(sid)]
    assert names == ["new.mp4", "older.mp4"]  # 80 h old is too old; a text file is never listed
    first = core.media.candidates(sid)[0]
    assert first["size"] > 0 and 7 < first["duration"] < 12 and not first["in_drop_folder"]
    core.media.attach_file(sid, downloads / "new.mp4")  # used now: no longer offered
    assert [c["name"] for c in core.media.candidates(sid)] == ["older.mp4"]


async def test_importing_a_file_is_a_job_with_progress_and_ends_attached(core: Core, video: Path) -> None:
    cid, sid = _failed_source(core)
    job_id = core.media.import_file(sid, video)
    with pytest.raises(ServiceError, match="already being added"):
        core.media.import_file(sid, video)
    progress: list[float] = []
    core.bus.add_listener(
        lambda e: e.payload["kind"] == "import" and progress.append(float(e.payload["progress"])),
        types=["job.progress"],
    )
    await core.jobs.drain(timeout=60)
    with core.db.read() as s:
        job = s.get(Job, job_id)
    assert job is not None and job.status == JobStatus.DONE, job.error if job else None
    src = core.media.source(sid)
    assert src.status in (SourceStatus.DOWNLOADED, SourceStatus.ANALYZING, SourceStatus.ANALYZED)
    copied = Path(src.path or "")
    assert copied.parent == core.media.drop_folder(cid)
    assert await asyncio.to_thread(video.exists)  # copied: the original stays
    assert progress and progress[-1] >= 0.9
    assert len(_jobs(core, "analyze")) == 1


async def test_importing_can_move_the_file_instead(core: Core, video: Path) -> None:
    _cid, sid = _failed_source(core)
    core.media.import_file(sid, video, move=True)
    await core.jobs.drain(timeout=60)
    moved = Path(core.media.source(sid).path or "")
    assert await asyncio.to_thread(lambda: not video.exists() and moved.is_file())
