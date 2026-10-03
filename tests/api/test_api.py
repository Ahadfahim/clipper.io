"""API in fixture mode: every screen's endpoint, the main mutations, files, loopback protection, WS."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from clipper.api.app import create_app
from clipper.settings import Settings

pytestmark = pytest.mark.ffmpeg


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    data = tmp_path_factory.mktemp("api")
    settings = Settings().with_data_dir(data)
    app = create_app(fixture_mode=True, start_background=False, settings=settings, allow_test_host=True)
    with TestClient(app) as c:
        yield c


GETS = [
    "/api/health",
    "/api/status",
    "/api/overview",
    "/api/switches",
    "/api/switches/preview?level=marketplace&name=vyro",
    "/api/events?after=0",
    "/api/jobs",
    "/api/questions",
    "/api/notes",
    "/api/agents/board",
    "/api/agents/sessions",
    "/api/agents/sessions/1",
    "/api/agents/director/messages",
    "/api/campaigns",
    "/api/campaigns/1",
    "/api/clips",
    "/api/clips/1",
    "/api/review/batches",
    "/api/review/batches/1",
    "/api/review/auto-approve",
    "/api/edit/3",
    "/api/publishing/accounts",
    "/api/publishing/calendar",
    "/api/publishing/recipes",
    "/api/earnings",
    "/api/settings",
    "/api/settings/lessons",
    "/api/settings/tools",
    "/api/settings/prompts",
    "/api/doctor",
]


@pytest.mark.parametrize("path", GETS)
def test_every_screen_endpoint_works(client: TestClient, path: str) -> None:
    res = client.get(path)
    assert res.status_code == 200, res.text


def test_overview_and_status_have_real_content(client: TestClient) -> None:
    ov = client.get("/api/overview").json()
    kinds = [i["kind"] for i in ov["needs_you"]]
    assert kinds[0] == "challenge" and "question" in kinds and "review" in kinds and "campaign" in kinds
    assert {k["key"] for k in ov["kpis"]} == {
        "earned_today",
        "views_today",
        "posted_today",
        "usage",
        "find_to_post",
    }
    assert ov["active_campaigns"][0]["stages"][0]["name"] == "Brief"
    assert ov["upcoming_posts"] and ov["notes"][0]["text"] == "Focus on Whop campaigns today"
    st = client.get("/api/status").json()
    assert st["fixture_mode"] is True and st["control"]["dry_run"] is True
    assert st["review_pending"] == 5 and st["extension_profiles"] == ["main", "beast"]
    board = client.get("/api/agents/board").json()
    assert (
        board["configured_slots"] == 4
        and board["slots"][0]["role"] == "campaign"
        and len(board["queue"]) == 3
    )


def test_review_flow_over_http(client: TestClient) -> None:
    batch = client.get("/api/review/batches/1").json()
    assert batch["clips"][0]["clip"]["score"] >= batch["clips"][-1]["clip"]["score"]  # strongest first
    pending = [c["clip"]["id"] for c in batch["clips"] if c["decision"] == "pending"]
    r = client.post(
        f"/api/review/clips/{pending[0]}/decision", json={"decision": "approved", "reviewer": "ahad"}
    )
    assert r.status_code == 200
    r = client.put(
        f"/api/review/clips/{pending[1]}/caption", json={"platform": "tiktok", "text": "new caption #x"}
    )
    assert r.status_code == 200
    r = client.post(
        f"/api/review/clips/{pending[1]}/recut", json={"start_delta": -1.5, "end_delta": 2, "layout": "split"}
    )
    assert r.status_code == 200
    approved = client.post("/api/review/batches/1/approve-all", json={"threshold": 70}).json()
    rejected = client.post("/api/review/batches/1/reject-rest", json={"reason": "boring"}).json()
    assert set(approved).isdisjoint(rejected)
    shipped = client.post("/api/review/batches/1/ship", json={}).json()
    assert pending[0] in shipped["approved"]
    again = client.post("/api/review/batches/1/ship", json={})
    assert again.status_code == 400 and "already shipped" in again.text


def test_campaign_switch_control_notes_questions(client: TestClient) -> None:
    doac = next(c for c in client.get("/api/campaigns").json() if c["title"].startswith("Diary"))
    assert client.post(f"/api/campaigns/{doac['id']}/take").status_code == 200
    assert client.post(f"/api/campaigns/{doac['id']}/take").status_code == 400
    spec = client.put(
        f"/api/campaigns/{doac['id']}/spec", json={"platforms": ["youtube", "x"], "duration_min_s": 20}
    ).json()
    assert spec["platforms"] == ["youtube"]  # limited to what the campaign allows... and x isn't allowed
    preview = client.get("/api/switches/preview?level=marketplace&name=whop").json()
    assert preview["active_campaigns"] >= 2
    res = client.post(
        "/api/switches", json={"level": "marketplace", "name": "whop", "enabled": False, "via": "ctrl+k"}
    ).json()
    assert res["ok"] and res["effects"]["campaign_status"] == "ending"
    assert client.post("/api/switches", json={"level": "social", "name": "x", "enabled": True}).json()[
        "needs_setup"
    ]
    ctl = client.post("/api/control", json={"key": "dry_run", "value": False}).json()
    assert ctl["dry_run"] is False
    client.post("/api/control", json={"key": "dry_run", "value": True})
    note = client.post(
        "/api/notes",
        json={
            "scope": "creator",
            "scope_id": "MrBeast",
            "text": "Yellow captions for this creator",
            "campaign_id": 1,
        },
    ).json()
    assert note["id"]
    lessons = client.get("/api/settings/lessons?scope=creator").json()
    assert any("Yellow captions" in lesson["note"] for lesson in lessons)
    q = client.get("/api/questions").json()[0]
    assert client.post(f"/api/questions/{q['id']}/answer", json={"answer": "No"}).status_code == 200
    assert client.post(f"/api/questions/{q['id']}/answer", json={"answer": "Yes"}).status_code == 400
    assert client.post("/api/agents/director/chat", json={"text": "pause TikTok"}).status_code == 200


def test_edit_endpoints(client: TestClient) -> None:
    state = client.get("/api/edit/3").json()
    assert state["live_status"] and state["plan"][2]["status"] == "in_progress"
    v0 = state["version"]
    state = client.post(
        "/api/edit/3/ops", json={"op": "trim", "args": {"start": 0.0, "end": 8.0}, "reason": "shorter"}
    ).json()
    assert state["version"] == v0 + 1 and state["history"][-1]["actor"] == "user"
    bad = client.post("/api/edit/3/ops", json={"op": "delete_range", "args": {"start": 0, "end": 99}})
    assert bad.status_code == 400
    assert client.post("/api/edit/3/take-over").status_code == 200
    assert client.get("/api/edit/3").json()["locked_by"] == "user"
    assert client.post("/api/edit/3/hand-back").status_code == 200


def test_publishing_endpoints(client: TestClient) -> None:
    cal = client.get("/api/publishing/calendar").json()
    scheduled = [p for p in cal["posts"] if p["status"] == "scheduled"]
    assert scheduled
    post = scheduled[0]
    from datetime import datetime

    at = datetime.fromisoformat(post["scheduled_at"]) + timedelta(minutes=5)
    res = client.post(f"/api/publishing/posts/{post['id']}/reschedule", json={"scheduled_at": at.isoformat()})
    assert res.status_code in (200, 409)
    acct = client.post(
        "/api/publishing/accounts", json={"platform": "youtube", "handle": "@new", "niche_tags": ["gaming"]}
    ).json()
    accounts = client.get("/api/publishing/accounts").json()
    new = next(a for a in accounts if a["id"] == acct["id"])
    assert new["warmup_week"] == 1 and new["cap_today"] == 1
    assert (
        client.patch(
            f"/api/publishing/accounts/{acct['id']}", json={"enabled": False, "niche_tags": ["x"]}
        ).status_code
        == 200
    )
    paused = next(a for a in accounts if a["status"] == "paused")
    assert client.post(f"/api/publishing/accounts/{paused['id']}/resume").status_code == 200


def test_files_and_traversal(client: TestClient) -> None:
    res = client.get("/api/files/clip/1/preview")
    assert res.status_code == 200 and res.headers["content-type"] == "video/mp4"
    assert client.get("/api/files/clip/1/thumb").headers["content-type"] == "image/jpeg"
    assert client.get("/api/files/clip/99999/preview").status_code == 404
    assert client.get("/api/files/clip/1/final").status_code in (200, 404)


def test_loopback_host_and_origin_protection(client: TestClient) -> None:
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 403
    assert client.get("/api/status", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/status", headers={"origin": "http://127.0.0.1:1420"}).status_code == 200
    ext = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    assert client.get("/api/files/clip/1/thumb", headers={"origin": ext}).status_code == 200
    assert client.get("/api/status", headers={"origin": ext}).status_code == 403
    pre = client.options(
        "/api/control", headers={"origin": "https://evil.example", "access-control-request-method": "POST"}
    )
    assert pre.status_code in (400, 403)  # rejected by CORS before it reaches a handler


def test_websocket_backlog_and_live(client: TestClient) -> None:
    with client.websocket_connect("/api/ws?after=0&types=alert,toggles.changed") as ws:
        first = ws.receive_json()
        assert first["type"] in ("alert", "toggles.changed")
        client.post("/api/switches", json={"level": "social", "name": "instagram", "enabled": False})
        for _ in range(20):
            msg = ws.receive_json()
            if msg["type"] == "toggles.changed" and msg["payload"]["name"] == "instagram":
                break
        else:
            raise AssertionError("no live toggles.changed event")
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("/api/ws", headers={"origin": "https://evil.example"}) as ws,
    ):
        ws.receive_json()
    assert closed.value.code == 4403
