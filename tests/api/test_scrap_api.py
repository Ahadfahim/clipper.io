"""Scrapping clips through the API, on the demo data."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipper.api.app import create_app
from clipper.settings import Settings

pytestmark = pytest.mark.ffmpeg


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings().isolated(tmp_path / "data")
    app = create_app(fixture_mode=True, start_background=False, settings=settings, allow_test_host=True)
    with TestClient(app) as c:
        yield c


def _clips(client: TestClient, **params: str) -> list[dict[str, object]]:
    return client.get("/api/clips", params=params).json()


def test_a_scrapped_clip_leaves_the_library_and_shows_in_the_scrapped_view(client: TestClient) -> None:
    clips = _clips(client)
    target = next(c for c in clips if c["status"] in ("ready", "in_review"))
    cid = target["id"]
    pre = client.post("/api/clips/scrap/preview", json={"clip_ids": [cid]}).json()
    assert pre["scrappable"] == 1 and pre["grace_days"] == 7 and pre["clips"][0]["can_scrap"]
    res = client.post("/api/clips/scrap", json={"clip_ids": [cid], "reason": "weak hook"})
    assert res.status_code == 200 and res.json()["scrapped"] == [cid] and res.json()["refused"] == []
    assert cid not in [c["id"] for c in _clips(client)]
    row = next(c for c in _clips(client, status="scrapped") if c["id"] == cid)
    assert (
        row["status"] == "scrapped"
        and row["scrap_reason"] == "weak hook"
        and row["purge_at"]
        and not row["files_purged"]
    )
    back = client.post("/api/clips/restore", json={"clip_ids": [cid]}).json()
    assert back["restored"] == [cid]
    assert cid in [c["id"] for c in _clips(client)]
    assert cid not in [c["id"] for c in _clips(client, status="scrapped")]


def test_a_posted_clip_is_refused_with_the_reason_and_can_be_hidden_instead(client: TestClient) -> None:
    posted = next(c for c in _clips(client) if c["status"] == "posted")
    res = client.post("/api/clips/scrap", json={"clip_ids": [posted["id"]]}).json()
    assert res["scrapped"] == [] and "Hide it instead" in res["refused"][0]["reason"]
    assert client.post("/api/clips/hide", json={"clip_ids": [posted["id"]]}).json() == [posted["id"]]
    assert posted["id"] not in [c["id"] for c in _clips(client)]
    assert posted["id"] in [c["id"] for c in _clips(client, status="hidden")]
    client.post("/api/clips/hide", json={"clip_ids": [posted["id"]], "hidden": False})
    assert posted["id"] in [c["id"] for c in _clips(client)]


def test_purge_and_cleanup_answer(client: TestClient) -> None:
    groups = client.get("/api/clips/cleanup").json()
    assert isinstance(groups, list) and all(
        {"key", "label", "clip_ids", "bytes", "action"} <= set(g) for g in groups
    )
    cid = next(c["id"] for c in _clips(client) if c["status"] in ("ready", "in_review"))
    client.post("/api/clips/scrap", json={"clip_ids": [cid]})
    freed = client.post("/api/clips/purge", json={"clip_ids": [cid]}).json()
    assert freed["clips"] == [cid]
    again = client.post("/api/clips/restore", json={"clip_ids": [cid]}).json()
    assert again["restored"] == [] and again["refused"][0]["reason"] == "This clip's files were deleted."
    assert client.post("/api/clips/purge", json={"old_versions": True}).status_code == 400


def test_limits(client: TestClient) -> None:
    assert client.post("/api/clips/scrap", json={"clip_ids": []}).status_code == 422
    assert client.post("/api/clips/scrap", json={"clip_ids": list(range(501))}).status_code == 422
    assert client.post("/api/clips/scrap/preview", json={"clip_ids": [99999]}).json()["scrappable"] == 0
