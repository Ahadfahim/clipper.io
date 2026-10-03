"""API in fixture mode: every screen's endpoint, the main mutations, files, loopback protection, WS."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

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


def test_events_latest_returns_newest_oldest_first(client: TestClient) -> None:
    all_events = client.get("/api/events?after=0&limit=1000").json()
    latest = client.get("/api/events?latest=true&limit=3").json()
    assert [e["id"] for e in latest] == [e["id"] for e in all_events[-3:]]


def test_trigger_scout_publishes_event(client: TestClient) -> None:
    res = client.post("/api/agents/trigger/scout")
    assert res.status_code == 200
    ev = client.get("/api/events?latest=true&limit=1").json()[0]
    assert ev["type"] == "trigger.fired" and ev["payload"]["name"] == "scout"
    assert client.post("/api/agents/trigger/nope").status_code == 422


def test_replay_runs_read_only_calls_and_rechecks_guard(tmp_path: Path) -> None:
    # a fresh demo DB: other tests in this module approve and ship clips
    app = create_app(
        fixture_mode=True,
        start_background=False,
        settings=Settings().with_data_dir(tmp_path),
        allow_test_host=True,
    )
    with TestClient(app) as fresh:
        events = fresh.get("/api/agents/sessions/1").json()["events"]
        read = next(e for e in events if e["type"] == "tool_call" and e["tool"] == "mcp__state__get_campaign")
        out = fresh.post(f"/api/agents/events/{read['id']}/replay").json()
        assert out["allowed"] and out["executed"] and out["output"]
        blocked = next(e for e in events if e["type"] == "blocked")
        out = fresh.post(f"/api/agents/events/{blocked['id']}/replay").json()
        assert not out["allowed"] and out["rule"] == "approval" and not out["executed"]
        clip_id = blocked["input"]["args"]["clip_id"]
        fresh.post(
            f"/api/review/clips/{clip_id}/decision",
            json={"decision": "approved", "reviewer": "test", "via": "dashboard"},
        )
        out = fresh.post(f"/api/agents/events/{blocked['id']}/replay").json()
        assert not out["executed"]  # changes state: never executed from the replay button
        msg = next(e for e in events if e["type"] == "message")
        assert fresh.post(f"/api/agents/events/{msg['id']}/replay").status_code == 400


def test_director_messages_include_your_side(client: TestClient) -> None:
    client.post("/api/agents/director/chat", json={"text": "how much did we make today?", "via": "dashboard"})
    msgs = client.get("/api/agents/director/messages").json()
    assert msgs[-1]["type"] == "user" and msgs[-1]["text"] == "how much did we make today?"


def test_fixture_mode_never_reads_this_pcs_secrets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # its responses are exported into the repo; a real pairing token once ended up there
    monkeypatch.setattr("clipper.api.routes.get_secret", lambda _name: "real-secret-from-this-pc")
    body = client.get("/api/settings").json()
    assert body["pairing_token"] is None
    assert not any(body["secrets_present"].values())
    assert "real-secret-from-this-pc" not in json.dumps(body)


def test_browser_probe_runs_read_only_steps_only(client: TestClient) -> None:
    steps = [
        {"action": "navigate", "url": "https://app.vyro.com/campaigns"},
        {"action": "outline", "selector": "h3", "text": "mrbeast", "up": 3},
    ]
    r = client.post("/api/browser/profiles/main/probe", json={"steps": steps})
    assert r.status_code == 200, r.text
    assert [(s["action"], s["ok"]) for s in r.json()] == [("navigate", True), ("outline", True)]
    for refused in ({"action": "click", "selector": "#post"}, {"action": "outline", "up": 99}):
        assert client.post("/api/browser/profiles/main/probe", json={"steps": [refused]}).status_code == 422
