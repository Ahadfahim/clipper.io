"""What counts as stuck: one case per kind, and the things that look stuck but aren't."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from clipper.settings import StallSettings
from clipper.supervisor.stalls import (
    CampaignView,
    EventView,
    JobView,
    PostView,
    RequestView,
    SessionView,
    Snapshot,
    Stall,
    detect_stalls,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
CFG = StallSettings()


def ago(minutes: float) -> datetime:
    return NOW - timedelta(minutes=minutes)


def snap(**kw: object) -> Snapshot:
    return Snapshot(now=NOW, **kw)  # type: ignore[arg-type]


def kinds(stalls: list[Stall]) -> list[str]:
    return [s.kind for s in stalls]


def running_request(started: float = 60, campaign: int | None = 1, session: int = 3) -> RequestView:
    return RequestView(
        9, "campaign", campaign, "running", ago(started), ago(started), 2, "job.done", None, session
    )


def campaign(status: str = "active", session: int | None = 3) -> dict[int, CampaignView]:
    return {1: CampaignView(1, "MrBeast #42", status, session)}


def session(status: str = "waiting", idle: float = 120) -> dict[int, SessionView]:
    return {3: SessionView(3, "campaign", 1, status, ago(idle), "claude-opus-5-5")}


def job(**kw: object) -> JobView:
    base: dict[str, object] = dict(
        id=4, kind="download", status="running", progress=0.3, progress_at=ago(1), created_at=ago(30),
        started_at=ago(29), detail="1 GB of 3 GB", campaign_id=1, label="Download of source 2", resource="download",
    )  # fmt: skip
    base.update(kw)
    return JobView(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------- session_hung


def test_a_running_session_with_no_events_for_ten_minutes_is_hung() -> None:
    s = snap(
        requests=[running_request(started=40)],
        sessions=session("running"),
        last_event={3: EventView(ago(25), None, "")},
        last_tool={3: EventView(ago(25), "mcp__marketplace__join_campaign", '{"campaign_id": 1}')},
    )
    (stall,) = detect_stalls(s, CFG)
    assert stall.kind == "session_hung" and stall.key == "session_hung:3" and stall.session_id == 3
    assert stall.actions == ["restart_turn", "nudge"] and stall.since == ago(25)
    assert any("join_campaign" in line for line in stall.evidence) and "25 min" in stall.summary


def test_a_session_that_is_still_producing_events_is_not_hung() -> None:
    s = snap(
        requests=[running_request(started=90)],
        sessions=session("running"),
        last_event={3: EventView(ago(2), "x", "")},
    )
    assert detect_stalls(s, CFG) == []


def test_a_run_that_just_started_is_given_the_full_quiet_time() -> None:
    s = snap(requests=[running_request(started=3)], sessions=session("running"))
    assert detect_stalls(s, CFG) == []
    long_run = snap(requests=[running_request(started=14)], sessions=session("running"))
    assert kinds(detect_stalls(long_run, CFG)) == ["session_hung"]


# ---------------------------------------------------------------- waiting_on_nothing


def test_a_campaign_waiting_on_nothing_is_flagged_with_what_the_agent_last_said() -> None:
    s = snap(
        campaigns=campaign(),
        sessions=session("waiting", idle=45),
        last_message={3: EventView(ago(45), None, "Waiting for the brief-reader to finish.")},
    )
    (stall,) = detect_stalls(s, CFG)
    assert (
        stall.kind == "waiting_on_nothing"
        and stall.key == "waiting_on_nothing:1"
        and stall.actions == ["nudge"]
    )
    assert any("brief-reader" in line for line in stall.evidence)


def test_waiting_on_something_is_not_waiting_on_nothing() -> None:
    base = dict(campaigns=campaign(), sessions=session("waiting", idle=300))
    assert kinds(detect_stalls(snap(**base), CFG)) == ["waiting_on_nothing"]
    for extra in (
        {"waiting_on_you": {1}},  # a question, a review batch or footage
        {"pending_wakeups": {1}},
        {"tracking": {1}},  # live posts still being tracked for payouts
        {"jobs": [job(progress_at=ago(1))]},
        {"requests": [RequestView(1, "campaign", 1, "queued", ago(1), None, 2, "x", None, None)]},
        {"posts": [PostView(5, 1, 2, "youtube", NOW + timedelta(hours=3), "scheduled", False)]},
    ):
        assert detect_stalls(snap(**base, **extra), CFG) == [], extra
    assert detect_stalls(snap(**{**base, "campaigns": campaign("paused")}), CFG) == []
    assert detect_stalls(snap(**base, paused=True), CFG) == []  # paused on purpose
    assert detect_stalls(snap(**{**base, "sessions": session("waiting", idle=10)}), CFG) == []


# ---------------------------------------------------------------- request_blocked


def test_a_queued_request_that_cannot_start_says_why_and_offers_run_now() -> None:
    queued = RequestView(
        7,
        "campaign",
        1,
        "queued",
        ago(12),
        None,
        2,
        "job.done",
        "Usage is high: only P0 and P1 requests start",
        None,
    )
    (stall,) = detect_stalls(snap(requests=[queued]), CFG)
    assert stall.kind == "request_blocked" and stall.request_id == 7
    assert stall.evidence[0] == "Usage is high: only P0 and P1 requests start"
    assert stall.actions == ["run_now"]
    fresh = RequestView(8, "campaign", 1, "queued", ago(2), None, 2, "job.done", None, None)
    assert detect_stalls(snap(requests=[fresh]), CFG) == []


def test_a_lease_held_by_a_session_that_is_not_running_can_be_released() -> None:
    queued = RequestView(7, "campaign", 1, "queued", ago(12), None, 2, "job.done", "Campaign 1 is busy", None)
    dead = snap(requests=[queued], leases={"campaign:1": ("session:3", NOW + timedelta(hours=2))})
    assert detect_stalls(dead, CFG)[0].actions == ["run_now", "release_lease"]
    alive = snap(
        requests=[queued, running_request(started=1)],
        sessions=session("running"),
        leases={"campaign:1": ("session:3", NOW + timedelta(hours=2))},
        last_event={3: EventView(ago(0.5), None, "")},
    )
    assert next(s for s in detect_stalls(alive, CFG) if s.kind == "request_blocked").actions == ["run_now"]
    p0 = RequestView(7, "director", None, "queued", ago(12), None, 0, "user.chat", None, None)
    assert detect_stalls(snap(requests=[p0]), CFG)[0].actions == ["show_agents"]  # already first in line


# ---------------------------------------------------------------- jobs


def test_a_job_that_stopped_moving_is_stalled_and_analysis_gets_twice_the_time() -> None:
    quiet = job(progress_at=ago(20))
    (stall,) = detect_stalls(snap(jobs=[quiet]), CFG)
    assert (
        stall.kind == "job_stalled" and stall.job_id == 4 and stall.actions == ["cancel_retry", "show_jobs"]
    )
    assert "30%" in stall.evidence[0] and "1 GB of 3 GB" in stall.evidence[1]
    assert detect_stalls(snap(jobs=[job(progress_at=ago(5))]), CFG) == []  # fresh progress
    assert detect_stalls(snap(jobs=[job(kind="analyze", progress_at=ago(20))]), CFG) == []
    assert kinds(detect_stalls(snap(jobs=[job(kind="analyze", progress_at=ago(40))]), CFG)) == ["job_stalled"]


def test_a_queued_job_waits_a_while_before_it_is_flagged_and_names_what_holds_its_slot() -> None:
    queued = job(
        id=5,
        status="queued",
        progress_at=None,
        started_at=None,
        created_at=ago(15),
        label="Download of source 3",
    )
    holder = job(id=4)
    (stall,) = detect_stalls(snap(jobs=[holder, queued]), CFG)
    assert stall.kind == "job_waiting" and "job 4" in stall.evidence[0]
    assert detect_stalls(snap(jobs=[job(id=5, status="queued", created_at=ago(3))]), CFG) == []
    assert "kill switch" in detect_stalls(snap(jobs=[queued], kill_switch=True), CFG)[0].evidence[0]


# ---------------------------------------------------------------- posts


def test_posts_that_are_late_or_stuck_uploading() -> None:
    late = PostView(5, 1, 2, "youtube", ago(40), "scheduled", False)
    stuck = PostView(6, 1, 2, "tiktok", ago(25), "posting", False)
    fine = PostView(7, 1, 2, "instagram", ago(5), "scheduled", False)
    found = {s.kind: s for s in detect_stalls(snap(posts=[late, stuck, fine], paused_accounts={2}), CFG)}
    assert set(found) == {"post_overdue", "recipe_stuck"}
    assert "account is paused" in found["post_overdue"].evidence[0]
    assert found["recipe_stuck"].actions == ["show_browser", "nudge"] and found["post_overdue"].post_id == 5
    assert "Clipper is paused" in detect_stalls(snap(posts=[late], paused=True), CFG)[0].evidence[0]


def test_stalls_come_oldest_first() -> None:
    s = snap(
        jobs=[job(id=1, progress_at=ago(40)), job(id=2, progress_at=ago(25))],
        posts=[PostView(5, 1, 2, "youtube", ago(60), "scheduled", False)],
    )
    assert [x.key for x in detect_stalls(s, CFG)] == ["post_overdue:5", "job_stalled:1", "job_stalled:2"]
