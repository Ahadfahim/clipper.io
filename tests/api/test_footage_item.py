"""The footage item in Needs you: a source waiting for a video from you, its detail, and the routes the
drop zone uses (candidates, inspect, add a file, retry, skip)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import col, select

from clipper.api import needs_you
from clipper.api.app import create_app
from clipper.core import Core
from clipper.db.engine import WriteTx
from clipper.db.models import Job, Source
from clipper.db.types import CampaignStatus, SourceStatus
from clipper.services.recipe_check import check_clip
from tests.conftest import call
from tests.factories import make_campaign, make_source

FRAMEIO = "https://next.frame.io/share/9d3a07f5-9dbf-4acd-8028-86879ad0028b/view/3ea7e8a1"


def _waiting(core: Core, *, url: str = FRAMEIO, **kw: Any) -> tuple[int, int]:
    camp = make_campaign(core.db, **{k: kw.pop(k) for k in ("status",) if k in kw})
    assert camp.id is not None
    src = make_source(
        core.db,
        camp.id,
        url=url,
        status=kw.pop("source_status", SourceStatus.NEEDS_FOOTAGE),
        reason="Clipper can't download next.frame.io links: they are share pages, not video files",
        waiting_since=core.clock.now(),
    )
    assert src.id is not None
    return camp.id, src.id


def _footage(core: Core) -> list[Any]:
    return [i for i in needs_you.build(core) if i.kind == "footage"]


def _failed_download(core: Core, source_id: int, campaign_id: int) -> None:
    def job(tx: WriteTx) -> None:
        tx.add(
            Job(
                kind="download",
                input_json={"source_id": source_id, "url": FRAMEIO},
                status="failed",
                error="This site isn't supported by the downloader",
                result_json={"raw_tail": "ERROR: Unsupported URL"},
                campaign_id=campaign_id,
                created_at=core.clock.now(),
                finished_at=core.clock.now(),
            )
        )

    core.db.write(job)


def test_a_waiting_source_is_an_item_with_a_link_to_the_page_and_the_campaign(core: Core) -> None:
    cid, sid = _waiting(core)
    (item,) = _footage(core)
    assert item.key == f"footage:{sid}" and item.campaign_id == cid and item.urgency == 1
    assert item.title == "Add the video from next.frame.io"
    assert "share pages" in item.detail
    source, campaign = item.links
    assert (source.kind, source.host, source.open_in, source.url) == (
        "source",
        "next.frame.io",
        "default",
        FRAMEIO,
    )
    assert campaign.kind == "marketplace"
    assert [a.action for a in item.actions] == ["add_file", "retry_source", "skip_source"]
    assert item.activity is None and not item.dismissable


def test_its_failed_download_is_not_listed_a_second_time(core: Core) -> None:
    cid, sid = _waiting(core, source_status=SourceStatus.FAILED)
    _failed_download(core, sid, cid)
    assert [i.kind for i in needs_you.build(core)] == ["footage"]
    # a failure that has nothing to do with a waiting source still shows
    _failed_download(core, 9999, cid)
    assert sorted(i.kind for i in needs_you.build(core)) == ["failure", "footage"]


def test_sources_that_are_over_or_not_http_are_handled(core: Core) -> None:
    _waiting(core, status=CampaignStatus.ENDED)
    _waiting(core, source_status=SourceStatus.SKIPPED)
    assert _footage(core) == []
    _cid, sid = _waiting(core, url="javascript:alert(1)")
    (item,) = _footage(core)
    assert item.key == f"footage:{sid}" and [link.kind for link in item.links] == ["marketplace"]


def test_a_file_being_added_shows_its_progress_on_the_item(core: Core) -> None:
    cid, sid = _waiting(core)

    def job(tx: WriteTx) -> None:
        tx.add(
            Job(
                kind="import",
                input_json={"source_id": sid, "path": "x.mp4"},
                status="running",
                progress=0.4,
                campaign_id=cid,
            )
        )

    core.db.write(job)
    (item,) = _footage(core)
    assert item.activity is not None and item.activity.kind == "import" and item.activity.progress == 0.4


def test_the_detail_says_where_the_file_goes_and_how_long_it_must_be(core: Core) -> None:
    from clipper.rules.spec import ClipSpec

    cid, sid = _waiting(core)
    core.campaigns.save_spec(cid, ClipSpec(duration_min_s=45.0))
    _failed_download(core, sid, cid)
    detail = needs_you.detail(core, f"footage:{sid}")
    assert detail is not None and detail.footage is not None
    f = detail.footage
    assert (f.source_id, f.host, f.support, f.minimum_s) == (sid, "next.frame.io", "no", 45.0)
    assert f.drop_folder == str(core.media.drop_folder(cid))
    labels = {row.label: row.value for row in detail.facts}
    assert (
        labels["Clips need to be at least"] == "45 seconds" and "Drop folder" not in labels
    )  # the drop box shows it
    assert detail.body.startswith(
        "Clipper can't download next.frame.io links: they are share pages, not video files. Download"
    )
    assert detail.evidence is not None and "Unsupported URL" in (detail.evidence.raw_tail or "")
    assert detail.reply_to == "campaign"


def test_it_can_be_snoozed_but_not_dismissed_and_a_reply_goes_to_the_agent(core: Core) -> None:
    from clipper.services.base import ServiceError

    cid, sid = _waiting(core)
    key = f"footage:{sid}"
    with pytest.raises(ServiceError, match="snoozed"):
        core.attention.dismiss(key)
    core.attention.snooze(key, 60)
    assert _footage(core) == []
    core.attention.reopen(key)
    assert len(_footage(core)) == 1
    out = core.attention.reply(key, "I'll get it tonight", about="the footage")
    assert out["routed_to"] == "campaign" and core.attention.campaign_of(key) == cid


async def test_the_agent_tool_is_limited_to_its_own_campaign(core: Core) -> None:
    cid, sid = _waiting(core, source_status=SourceStatus.FAILED)
    other = make_campaign(core.db)
    assert other.id is not None
    refused = await call(
        core,
        "media",
        "need_footage",
        {"source_id": sid, "reason": "nope"},
        role="campaign",
        campaign_id=other.id,
    )
    assert refused.is_error and "another campaign" in refused.content[0]["text"]
    ok = await call(
        core,
        "media",
        "need_footage",
        {"source_id": sid, "reason": "It is a share page"},
        role="campaign",
        campaign_id=cid,
    )
    assert not ok.is_error
    assert core.media.source(sid).status == SourceStatus.NEEDS_FOOTAGE
    assert [i.key for i in _footage(core)] == [f"footage:{sid}"]


# ---------------------------------------------------------------- the routes the drop zone uses


@pytest.fixture
def client(core: Core) -> Iterator[TestClient]:
    app = create_app(core=core, start_background=False, settings=core.settings, allow_test_host=True)
    with TestClient(app) as c:
        yield c


@pytest.mark.ffmpeg
def test_inspect_candidates_and_add_a_file(core: Core, client: TestClient, tmp_path: Path) -> None:
    downloads = tmp_path / "Recent"
    downloads.mkdir()
    object.__setattr__(core.settings.media, "downloads_dirs", [downloads])
    video = downloads / "episode.mp4"
    shutil.copy(check_clip(core), video)
    _cid, sid = _waiting(core)

    found = client.get(f"/api/sources/{sid}/candidates").json()
    assert [c["name"] for c in found] == ["episode.mp4"]

    info = client.post(f"/api/sources/{sid}/inspect", json={"path": str(video)}).json()
    assert info["has_audio"] and [w["code"] for w in info["warnings"]] == ["short"]
    bad = client.post(f"/api/sources/{sid}/inspect", json={"path": str(tmp_path / "nope.mp4")})
    assert bad.status_code == 400 and "no such file" in bad.json()["detail"]

    res = client.post(f"/api/sources/{sid}/file", json={"path": str(video), "move": False})
    assert res.status_code == 200 and res.json()["id"]
    with core.db.read() as s:
        job = s.get(Job, res.json()["id"])
    assert job is not None and job.kind == "import" and job.input_json["source_id"] == sid
    (item,) = _footage(core)
    assert item.activity is not None  # the item stays, with its progress, until the file has landed
    again = client.post(f"/api/sources/{sid}/file", json={"path": str(video)})
    assert again.status_code == 400 and "already being added" in again.json()["detail"]


def test_retry_needs_force_for_a_share_page_and_skip_ends_the_item(core: Core, client: TestClient) -> None:
    cid, sid = _waiting(core)
    first = client.post(f"/api/sources/{sid}/retry").json()
    assert first["id"] is None and core.media.source(sid).status == SourceStatus.NEEDS_FOOTAGE
    forced = client.post(f"/api/sources/{sid}/retry", params={"force": "true"}).json()
    assert forced["id"] and core.media.source(sid).status == SourceStatus.QUEUED
    assert _footage(core) == []  # downloading again: nothing for you to do

    cid2, sid2 = _waiting(core)
    assert client.post(f"/api/sources/{sid2}/skip").status_code == 200
    assert core.media.source(sid2).status == SourceStatus.SKIPPED
    assert _footage(core) == []
    assert client.post("/api/sources/99999/skip").status_code == 400
    with core.db.read() as s:
        left = s.exec(select(Source).where(col(Source.status) == SourceStatus.QUEUED)).all()
    assert [x.id for x in left] == [sid] and cid != cid2
