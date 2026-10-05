"""Stuck things through the API, on the demo data: the list, the Needs you items, and what you can do."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipper.api.app import create_app
from clipper.settings import Settings


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings().isolated(tmp_path / "data")
    app = create_app(fixture_mode=True, start_background=False, settings=settings, allow_test_host=True)
    with TestClient(app) as c:
        yield c


def _stalls(client: TestClient) -> dict[str, dict[str, object]]:
    return {s["key"]: s for s in client.get("/api/stalls").json()}


def test_the_demo_has_a_stalled_job_and_a_request_that_cannot_start(client: TestClient) -> None:
    found = _stalls(client)
    assert set(found) == {"job_stalled:2", "request_blocked:3"}
    job = found["job_stalled:2"]
    assert job["campaign_title"] == "Ali Abdaal podcast cuts" and job["job_id"] == 2
    assert [a["action"] for a in job["actions"]] == ["cancel_retry", "show_jobs"]  # type: ignore[union-attr]
    assert [a["server"] for a in job["actions"]] == [True, False]  # type: ignore[union-attr]
    blocked = found["request_blocked:3"]
    assert "held by session 4" in blocked["evidence"][0]  # type: ignore[index]
    assert [a["action"] for a in blocked["actions"]] == ["run_now", "release_lease"]  # type: ignore[union-attr]


def test_stuck_things_are_needs_you_items_with_their_own_actions(client: TestClient) -> None:
    items = {i["key"]: i for i in client.get("/api/needs-you").json()}
    stuck = items["stuck:job_stalled:2"]
    assert stuck["kind"] == "stuck" and stuck["urgency"] == 2 and not stuck["dismissable"]
    assert [a["label"] for a in stuck["actions"]] == ["Cancel and retry", "Show jobs"]
    assert stuck["actions"][0]["args"] == {"stall": "job_stalled:2"}
    detail = client.get("/api/needs-you/stuck-job_stalled-2").json()
    assert detail["body"].startswith("Analysis of source 3 hasn't moved")
    assert {f["label"] for f in detail["facts"]} >= {"What", "Campaign", "Since", "Evidence"}
    assert detail["reply_to"] == "campaign"
    # snoozing works like any other item; dismissing doesn't (it would hide something broken)
    assert client.post("/api/needs-you/stuck-job_stalled-2/dismiss", json={}).status_code == 400
    assert client.post("/api/needs-you/stuck-job_stalled-2/snooze", json={"minutes": 60}).status_code == 200
    assert "stuck:job_stalled:2" not in {i["key"] for i in client.get("/api/needs-you").json()}


def test_cancel_and_retry_a_stalled_job_and_it_is_not_stuck_any_more(client: TestClient) -> None:
    res = client.post("/api/stalls/job_stalled-2/act", json={"action": "cancel_retry"})
    assert res.status_code == 200 and "queued it again as job" in res.json()["detail"]
    assert "job_stalled:2" not in _stalls(client)
    jobs = {j["id"]: j for j in client.get("/api/jobs").json()}
    assert jobs[2]["status"] == "cancelled"
    again = client.post("/api/stalls/job_stalled-2/act", json={"action": "cancel_retry"})
    assert again.status_code == 404 and "isn't stuck any more" in again.json()["detail"]


def test_an_action_the_stall_doesnt_offer_is_refused(client: TestClient) -> None:
    res = client.post("/api/stalls/job_stalled-2/act", json={"action": "restart_turn"})
    assert res.status_code == 400 and "isn't something to do" in res.json()["detail"]
    shown = client.post("/api/stalls/job_stalled-2/act", json={"action": "show_jobs"})
    assert shown.status_code == 400  # a link the app follows, not something the server does
    without_agents = client.post("/api/stalls/request_blocked-3/act", json={"action": "run_now"})
    assert without_agents.status_code == 400 and "agents aren't running" in without_agents.json()["detail"]


def test_the_jobs_list_flags_the_stalled_one_and_says_what_each_is_doing(client: TestClient) -> None:
    jobs = {j["id"]: j for j in client.get("/api/jobs").json()}
    assert jobs[2]["stalled"] is True and jobs[2]["detail"] == "Tracking faces"
    assert jobs[2]["label"] == "Analysis of source 3" and jobs[2]["progress_at"]
    assert not any(j["stalled"] for i, j in jobs.items() if i != 2)


def test_the_board_says_why_a_request_waits(client: TestClient) -> None:
    board = client.get("/api/agents/board").json()
    waiting = {q["request_id"]: q["waiting_reason"] for q in board["queue"]}
    assert "held by session 4" in str(waiting[3])
    assert all(s["quiet_s"] is not None for s in board["slots"] if s["request_id"])
    assert not any(s["hung"] for s in board["slots"])


def test_nudge_a_campaign_or_a_session_with_your_own_words(client: TestClient) -> None:
    res = client.post("/api/campaigns/1/nudge", json={"text": "Use the second source"})
    assert res.status_code == 200
    sessions = client.get("/api/agents/sessions").json()
    campaign_session = next(s for s in sessions if s["role"] == "campaign")
    assert client.post(f"/api/agents/sessions/{campaign_session['id']}/nudge", json={}).status_code == 200
    director = next(s for s in sessions if s["role"] == "director")
    assert (
        client.post(f"/api/agents/sessions/{director['id']}/nudge", json={"text": "hello"}).status_code == 200
    )
    events = client.get("/api/events", params={"latest": "true", "types": "user.nudge", "limit": 10}).json()
    assert {e["payload"]["role"] for e in events} == {"campaign", "director"}
    assert {e["payload"]["text"] for e in events} >= {"Use the second source", "hello"}
    assert client.post("/api/campaigns/999/nudge", json={}).status_code == 400
    assert client.post("/api/campaigns/1/nudge", json={"text": "x" * 1001}).status_code == 422


def test_your_words_on_a_stuck_item_are_the_message_of_a_nudge(client: TestClient) -> None:
    # a job has no agent to nudge, so use the lease item's campaign: its stall offers run_now/release_lease, not nudge,
    # but the reply box nudges that campaign's agent whatever the stall's own actions are
    res = client.post("/api/needs-you/stuck-request_blocked-3/reply", json={"text": "Please carry on"})
    assert res.status_code == 200 and res.json()["routed_to"] == "campaign"
    events = client.get("/api/events", params={"latest": "true", "types": "user.nudge", "limit": 5}).json()
    assert events[-1]["payload"]["text"] == "Please carry on"
    assert events[-1]["payload"]["stall_key"] == "request_blocked:3"
