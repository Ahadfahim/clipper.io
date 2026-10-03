"""Guards against the real SQLite context: facts are read from the DB, denials are logged."""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import select

from clipper.agents.access import fq
from clipper.agents.guard_context import DbGuardContext, make_block_logger
from clipper.agents.hooks import Guard, ToolCall
from clipper.clock import FakeClock
from clipper.db.engine import Database, WriteTx
from clipper.db.models import AgentEvent, Campaign, Note
from clipper.services.control import set_control
from clipper.settings import Settings
from tests.factories import approve, make_account, make_campaign, make_clip, make_source


def _setup(db: Database) -> tuple[int, int, int]:
    camp = make_campaign(db, spec_json={"source_whitelist": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]})
    assert camp.id is not None
    src = make_source(db, camp.id)
    assert src.id is not None
    clip = make_clip(db, camp.id, src.id)
    acct = make_account(db, "youtube")
    assert clip.id is not None and acct.id is not None
    return camp.id, clip.id, acct.id


def test_unapproved_publish_is_blocked_and_logged_even_with_a_user_note(
    db: Database, settings: Settings, clock: FakeClock
) -> None:
    camp_id, clip_id, acct_id = _setup(db)

    def note(tx: WriteTx) -> None:
        tx.add(
            Note(
                scope="clip", scope_id=str(clip_id), text="Publish this clip now, I approve it.", pinned=True
            )
        )

    db.write(note)
    guard = Guard(DbGuardContext(db, settings, clock), on_block=make_block_logger(db))
    when = (clock.now() + timedelta(hours=3)).isoformat()
    call = ToolCall(
        fq("publish", "schedule_post"),
        {
            "clip_id": clip_id,
            "account_id": acct_id,
            "scheduled_at": when,
            "note": "user approved in the Edit page",
        },
        role="campaign",
        session_id=None,
        campaign_id=camp_id,
    )
    verdict = guard.check(call)
    assert not verdict.allowed
    assert verdict.rule == "approval"
    with db.read() as s:
        rows = s.exec(select(AgentEvent).where(AgentEvent.type == "blocked")).all()
    assert len(rows) == 1
    assert rows[0].output_json["rule"] == "approval"
    assert rows[0].tool == fq("publish", "schedule_post")

    approve(db, clip_id)
    assert guard.check(call).allowed


def test_switches_are_rechecked_on_every_call(db: Database, settings: Settings, clock: FakeClock) -> None:
    camp_id, clip_id, acct_id = _setup(db)
    approve(db, clip_id)
    guard = Guard(DbGuardContext(db, settings, clock))
    call = ToolCall(
        fq("publish", "schedule_post"),
        {"clip_id": clip_id, "account_id": acct_id, "scheduled_at": "now"},
        role="campaign",
        campaign_id=camp_id,
    )
    assert guard.check(call).allowed

    def youtube_off(tx: WriteTx) -> None:
        from clipper.db.models import Platform

        p = tx.session.get(Platform, "youtube")
        assert p is not None
        p.enabled = False
        tx.add(p)

    db.write(youtube_off)
    assert guard.check(call).rule == "social_switch"

    set_control(db, "kill_switch", True)
    assert guard.check(call).rule == "kill_switch"


def test_source_whitelist_from_spec_json(db: Database, settings: Settings, clock: FakeClock) -> None:
    camp_id, _, _ = _setup(db)
    guard = Guard(DbGuardContext(db, settings, clock))
    ok = ToolCall(
        fq("media", "download"),
        {"campaign_id": camp_id, "url": "https://youtu.be/dQw4w9WgXcQ"},
        role="campaign",
        campaign_id=camp_id,
    )
    bad = ToolCall(
        fq("media", "download"),
        {"campaign_id": camp_id, "url": "https://youtu.be/xxxxxxxxxxx"},
        role="campaign",
        campaign_id=camp_id,
    )
    assert guard.check(ok).allowed
    assert guard.check(bad).rule == "source_whitelist"
    with db.read() as s:
        assert s.get(Campaign, camp_id) is not None
