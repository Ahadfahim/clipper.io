"""Needs you: the ranked list, stable keys, snooze and dismiss, the full story of one item, and replies."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlmodel import select

from clipper.api import needs_you
from clipper.clock import FakeClock, utcnow
from clipper.core import Core
from clipper.db.engine import WriteTx
from clipper.db.models import AgentEvent, AgentSession, Event, Job, Question, ReviewBatch
from clipper.events.bus import EventEnvelope
from clipper.services.base import ServiceError
from clipper.supervisor.router import compact, route
from tests.factories import make_account, make_campaign


@pytest.fixture
def fake_core(settings: Any) -> Any:
    from clipper.core import Core

    clock = FakeClock(utcnow())  # events are stamped by the real clock, so start there
    c = Core.create(settings, fakes=True, clock=clock)
    c.test_clock = clock  # type: ignore[attr-defined]
    yield c
    c.close()


def _alert(
    core: Core, text: str, *, level: str = "warning", source: str = "campaign", campaign_id: int | None = None
) -> None:
    core.notify.alert(level, text, source=source, campaign_id=campaign_id)


def _failed_job(
    core: Core, kind: str = "download", *, status: str = "failed", error: str = "boom", **inp: Any
) -> int:
    def job(tx: WriteTx) -> int:
        j = Job(
            kind=kind,
            input_json=inp,
            status=status,
            error=error if status == "failed" else None,
            campaign_id=inp.pop("campaign_id", None),
            created_at=core.clock.now(),
            finished_at=core.clock.now(),
        )
        tx.add(j)
        tx.flush()
        assert j.id is not None
        return j.id

    return core.db.write(job)


def _keys(core: Core) -> list[str]:
    return [i.key for i in needs_you.build(core)]


def test_items_are_ranked_and_keyed(fake_core: Core) -> None:
    core = fake_core
    camp = make_campaign(core.db, status="suggested", score=80.0, title="Diary of a CEO")
    acct = make_account(core.db, status="paused", paused_reason="verify it's you")
    qid = core.notify.ask_user("Use the trailer?", ["Yes", "No"], session_id=None, campaign_id=camp.id)
    _alert(core, "Campaign 1 needs the footage", campaign_id=camp.id)
    jid = _failed_job(core, source_id=4, url="https://f.io/x")
    assert _keys(core) == [
        f"challenge:{acct.id}",
        f"question:{qid}",
        f"campaign:{camp.id}",
        next(k for k in _keys(core) if k.startswith("alert:")),
        f"failure:job:{jid}",
    ]
    items = {i.key: i for i in needs_you.build(core)}
    q = items[f"question:{qid}"]
    assert q.options == ["Yes", "No"] and q.campaign_title == "Diary of a CEO" and q.since is not None
    assert [a.label for a in q.actions] == ["Yes", "No"]
    assert _keys(core) == _keys(core)  # stable between reads


def test_a_review_batch_that_times_out_soon_ranks_above_campaign_picks(fake_core: Core) -> None:
    core = fake_core
    camp = make_campaign(core.db, status="suggested", score=90.0)

    def job(tx: WriteTx) -> None:
        tx.add(ReviewBatch(campaign_id=camp.id or 0, timeout_at=core.clock.now() + timedelta(minutes=30)))

    core.db.write(job)
    assert [i.kind for i in needs_you.build(core)] == ["review", "campaign"]
    assert needs_you.build(core)[0].urgency < needs_you.build(core)[1].urgency


def test_a_failure_goes_away_when_a_later_job_for_the_same_input_succeeds_or_is_running(
    fake_core: Core,
) -> None:
    core = fake_core
    first = _failed_job(core, source_id=4)
    other = _failed_job(core, kind="analyze", source_id=9)
    assert {f"failure:job:{first}", f"failure:job:{other}"} <= set(_keys(core))
    _failed_job(core, status="queued", source_id=4)  # a retry is in flight
    assert f"failure:job:{first}" not in _keys(core) and f"failure:job:{other}" in _keys(core)
    _failed_job(core, kind="analyze", status="done", source_id=9)
    assert not [k for k in _keys(core) if k.startswith("failure:")]


def test_only_the_newest_failure_per_input_is_listed_and_old_ones_are_not(fake_core: Core) -> None:
    core = fake_core
    older = _failed_job(core, source_id=4)
    newer = _failed_job(core, source_id=4)
    assert [k for k in _keys(core) if k.startswith("failure:")] == [f"failure:job:{newer}"]
    assert f"failure:job:{older}" not in _keys(core)
    core.test_clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    assert not [k for k in _keys(core) if k.startswith("failure:")]


def test_alerts_merge_repeats_and_skip_what_is_shown_elsewhere_or_no_longer_true(fake_core: Core) -> None:
    core = fake_core
    make_account(core.db, status="paused", handle="@clipsdaily", paused_reason="challenge")
    for _ in range(3):
        _alert(core, "Campaign 2: clip 9 is approved but no accounts are connected")
        core.test_clock.advance(timedelta(minutes=5))  # type: ignore[attr-defined]
    _alert(
        core, "@clipsdaily (tiktok) paused: verification challenge during upload"
    )  # the account has its own row
    _alert(core, "Claude usage limit reached; agents paused, resuming at 16:10")  # not rate limited now
    _alert(core, "Uploaded fine", level="info")
    alerts = [i for i in needs_you.build(core) if i.kind == "alert"]
    assert [(a.title, a.count) for a in alerts] == [
        ("Campaign 2: clip 9 is approved but no accounts are connected", 3)
    ]
    assert "seen 3 times" in alerts[0].detail and alerts[0].dismissable
    core.test_clock.advance(timedelta(days=4))  # type: ignore[attr-defined]
    assert not [i for i in needs_you.build(core) if i.kind == "alert"]


def test_snooze_hides_until_the_time_and_dismiss_hides_until_something_new_happens(fake_core: Core) -> None:
    core = fake_core
    camp = make_campaign(core.db, status="suggested", score=80.0)
    qid = core.notify.ask_user("Which footage?", ["A", "B"], session_id=None, campaign_id=camp.id)
    key = f"question:{qid}"
    seen: list[EventEnvelope] = []
    core.bus.add_listener(seen.append, types=["attention.changed"])

    core.attention.snooze(key, 60)
    assert key not in _keys(core)
    core.test_clock.advance(timedelta(minutes=61))  # type: ignore[attr-defined]
    assert key in _keys(core)

    with pytest.raises(ServiceError, match="can only be snoozed"):
        core.attention.dismiss(key)

    _alert(core, "Something broke")
    alert_key = next(k for k in _keys(core) if k.startswith("alert:"))
    core.attention.dismiss(alert_key, note="seen")
    assert alert_key not in _keys(core)
    _alert(core, "Something broke")  # it happened again: new evidence, a new key
    again = next(k for k in _keys(core) if k.startswith("alert:"))
    assert again != alert_key
    core.attention.reopen(alert_key)
    assert [e.payload["state"] for e in seen] == ["snoozed", "dismissed", "open"]


def test_keys_are_checked(fake_core: Core) -> None:
    for bad in ("question:abc", "nonsense", "failure:6", "question:1; drop table", "campaign:1:2"):
        with pytest.raises(ServiceError, match="not a Needs you item"):
            fake_core.attention.snooze(bad, 5)
    with pytest.raises(ServiceError, match="between 1 minute"):
        fake_core.attention.snooze("question:1", 0)


def test_reply_to_a_question_is_its_answer_in_your_own_words(fake_core: Core) -> None:
    core = fake_core
    camp = make_campaign(core.db)
    qid = core.notify.ask_user("Which footage?", ["A", "B"], session_id=None, campaign_id=camp.id)
    seen: list[EventEnvelope] = []
    core.bus.add_listener(seen.append, types=["question.answered"])
    res = core.attention.reply(
        f"question:{qid}", "Use the Frame.io cut, not the trailer", about="Which footage?"
    )
    assert res == {"routed_to": "question", "id": qid}
    with core.db.read() as s:
        q = s.get(Question, qid)
    assert q is not None and q.status == "answered" and q.answer == "Use the Frame.io cut, not the trailer"
    assert seen[0].payload["custom"] is True
    from clipper.supervisor.messages import describe

    assert "own words" in describe(compact(seen[0]))


def test_reply_to_a_campaign_item_is_a_note_that_resumes_its_agent(fake_core: Core) -> None:
    core = fake_core
    camp = make_campaign(core.db, status="suggested", score=80.0)
    notes: list[EventEnvelope] = []
    core.bus.add_listener(notes.append, types=["note.added"])
    res = core.attention.reply(f"campaign:{camp.id}", "Take it, but only YouTube", about="New campaign: Test")
    assert res["routed_to"] == "campaign"
    assert notes[0].payload["text"].startswith("About: New campaign: Test. Take it")
    specs = route(notes[0], session_of=lambda _s: None, clip_campaign=lambda _c: None)
    assert [(s.priority, s.role, s.campaign_id) for s in specs] == [(0, "campaign", camp.id)]


def test_reply_to_a_failed_job_reaches_the_jobs_campaign_and_to_a_blocked_account_the_director(
    fake_core: Core,
) -> None:
    core = fake_core
    camp = make_campaign(core.db)
    jid = _failed_job(core, source_id=1, campaign_id=camp.id)
    assert (
        core.attention.reply(f"failure:job:{jid}", "skip that source", about="Download failed")["routed_to"]
        == "campaign"
    )
    acct = make_account(core.db, status="paused")
    chats: list[EventEnvelope] = []
    core.bus.add_listener(chats.append, types=["user.chat"])
    res = core.attention.reply(f"challenge:{acct.id}", "I'll log in tonight", about="TikTok paused")
    assert res["routed_to"] == "director" and "About: TikTok paused" in chats[0].payload["text"]


def test_reply_limits(fake_core: Core) -> None:
    core = fake_core
    camp = make_campaign(core.db, status="suggested", score=80.0)
    with pytest.raises(ServiceError, match="write something"):
        core.attention.reply(f"campaign:{camp.id}", "   ", about="x")
    with pytest.raises(ServiceError, match="characters for the campaign"):
        core.attention.reply(f"campaign:{camp.id}", "y" * 1200, about="x")
    long_answer = "z" * 1500
    qid = core.notify.ask_user("Q?", ["A"], session_id=None, campaign_id=camp.id)
    core.attention.reply(f"question:{qid}", long_answer, about="Q?")
    with core.db.read() as s:
        q = s.get(Question, qid)
    assert q is not None and q.answer == long_answer


def test_detail_tells_the_whole_story_of_a_question(fake_core: Core) -> None:
    core = fake_core
    camp = make_campaign(core.db, title="5 Guys Face Their Crush")

    def job(tx: WriteTx) -> int:
        sess = AgentSession(role="campaign", campaign_id=camp.id, status="waiting")
        tx.add(sess)
        tx.flush()
        assert sess.id is not None
        for text in ("Saved the spec.", "Source is too short, asking you."):
            tx.add(AgentEvent(session_id=sess.id, type="message", input_json={"text": text}))
        return sess.id

    sid = core.db.write(job)
    qid = core.notify.ask_user(
        "Is this the right source?", ["Yes", "No"], session_id=sid, campaign_id=camp.id
    )
    d = needs_you.detail(core, f"question:{qid}")
    assert d is not None
    assert d.body == "Is this the right source?" and d.reply_to == "question"
    assert d.item.options == ["Yes", "No"]
    assert d.agent is not None and d.agent.role == "campaign"
    assert [m.text for m in d.agent.messages] == ["Source is too short, asking you.", "Saved the spec."]
    assert {f.label for f in d.facts} >= {"Campaign", "Asked by", "Asked"}
    assert d.snooze_options == [60, 240, 1440]


def test_detail_of_a_failure_keeps_the_error_and_the_full_output(fake_core: Core) -> None:
    core = fake_core
    camp = make_campaign(core.db)

    def job(tx: WriteTx) -> int:
        j = Job(
            kind="download",
            input_json={"source_id": 5, "url": "https://f.io/DvtfTpUk"},
            status="failed",
            error="This site isn't supported by the downloader\n\nDownload it yourself and put the video in C:\\x",
            result_json={"raw_tail": "WARNING: old\nERROR: Unsupported URL"},
            campaign_id=camp.id,
            finished_at=core.clock.now(),
        )
        tx.add(j)
        tx.flush()
        assert j.id is not None
        return j.id

    jid = core.db.write(job)
    d = needs_you.detail(core, f"failure:job:{jid}")
    assert d is not None
    assert d.item.detail == "This site isn't supported by the downloader"
    assert d.evidence is not None and d.evidence.raw_tail == "WARNING: old\nERROR: Unsupported URL"
    assert d.evidence.error is not None and "Download it yourself" in d.evidence.error
    assert next(f.value for f in d.facts if f.label == "Input") == "https://f.io/DvtfTpUk"
    assert d.item.dismissable and d.reply_to == "campaign"


def test_detail_of_something_that_is_gone_is_none(fake_core: Core) -> None:
    assert needs_you.detail(fake_core, "question:999") is None
    qid = fake_core.notify.ask_user("Q?", ["A"], session_id=None, campaign_id=None)
    fake_core.notify.answer(qid, "A", by="you", via="dashboard")
    assert needs_you.detail(fake_core, f"question:{qid}") is None


def test_snoozed_items_are_still_found_by_key(fake_core: Core) -> None:
    core = fake_core
    qid = core.notify.ask_user("Q?", ["A"], session_id=None, campaign_id=None)
    core.attention.snooze(f"question:{qid}", 30)
    assert needs_you.find(core, f"question:{qid}") is not None  # the detail still opens from a deep link
    assert not [i for i in needs_you.build(core) if i.kind == "question"]
    with core.db.read() as s:
        assert (
            s.exec(select(Event).where(Event.type == "attention.changed")).one().payload["state"] == "snoozed"
        )


def test_a_campaign_you_took_but_must_join_on_the_site_is_a_join_item(fake_core: Core) -> None:
    core = fake_core
    camp = make_campaign(
        core.db,
        status="needs_user",
        taken_at=core.clock.now(),
        marketplace="vyro",
        title="5 Guys Face Their Crush",
    )
    other = make_campaign(core.db, status="needs_user", taken_at=None, title="Paid join ($29)", score=40.0)
    core.test_clock.advance(timedelta(seconds=1))  # type: ignore[attr-defined]
    _alert(
        core,
        "Campaign 5 Guys Face Their Crush needs you to join it (the user joins this campaign on the site)",
        source="marketplace",
        campaign_id=camp.id,
    )
    items = {i.key: i for i in needs_you.build(core)}
    join = items[f"join:{camp.id}"]
    assert join.kind == "join" and join.title == "Join 5 Guys Face Their Crush on Vyro"
    assert [a.action for a in join.actions] == ["open_link", "mark_joined", "skip"]
    assert join.links and join.links[0].host == "app.vyro.com"
    assert not [k for k in items if k.startswith("alert:")]  # the join item says it already
    assert f"campaign:{other.id}" in items  # a campaign you haven't taken is still just a pick
    d = needs_you.detail(core, f"join:{camp.id}")
    assert d is not None and "press I've joined" in d.body and d.reply_to == "campaign"


def test_joining_makes_the_campaign_active_and_wakes_its_agent(fake_core: Core) -> None:
    core = fake_core
    camp = make_campaign(core.db, status="needs_user")
    seen: list[EventEnvelope] = []
    core.bus.add_listener(seen.append, types=["campaign.joined"])
    core.campaigns.joined(camp.id or 0)
    assert core.campaigns.get(camp.id or 0).status == "active"
    assert f"join:{camp.id}" not in [i.key for i in needs_you.build(core)]
    specs = route(seen[0], session_of=lambda _s: None, clip_campaign=lambda _c: None)
    assert [(s.priority, s.role, s.campaign_id) for s in specs] == [(0, "campaign", camp.id)]
    from clipper.supervisor.messages import describe

    assert "joined campaign" in describe(compact(seen[0]))
    with pytest.raises(ServiceError, match="isn't waiting for you to join"):
        core.campaigns.joined(camp.id or 0)


def test_skipping_a_campaign_with_live_posts_to_submit_can_keep_submitting(fake_core: Core) -> None:
    from clipper.db.models import Post
    from clipper.db.types import CampaignStatus
    from tests.factories import make_account, make_clip, make_source

    core = fake_core
    camp = make_campaign(core.db)
    src = make_source(core.db, camp.id or 0)
    clip = make_clip(core.db, camp.id or 0, src.id or 0)
    acct = make_account(core.db)

    def add(tx: WriteTx) -> None:
        tx.add(
            Post(
                clip_id=clip.id or 0,
                account_id=acct.id or 0,
                campaign_id=camp.id,
                platform="youtube",
                scheduled_at=core.clock.now(),
                status="live",
                url="https://youtube.com/shorts/x",
            )
        )

    core.db.write(add)
    assert core.campaigns.unsubmitted_posts(camp.id or 0) == 1
    assert core.campaigns.skip(camp.id or 0, keep_submitting=True) == CampaignStatus.ENDING
    assert core.campaigns.get(camp.id or 0).status == "ending"
    assert core.campaigns.skip(camp.id or 0) == CampaignStatus.SKIPPED
    other = make_campaign(core.db, external_id="two")
    assert (
        core.campaigns.skip(other.id or 0, keep_submitting=True) == CampaignStatus.SKIPPED
    )  # nothing to finish


def test_link_status_follows_what_the_page_did_when_read(fake_core: Core) -> None:
    core = fake_core
    camp = make_campaign(core.db)
    assert core.campaigns.get(camp.id or 0).link_status == "unknown"
    core.campaigns.set_link_status(camp.id or 0, "unavailable")
    row = core.campaigns.get(camp.id or 0)
    assert row.link_status == "unavailable" and row.link_checked_at is not None
