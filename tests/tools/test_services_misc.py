"""Switches (PLAN §15.2), read-only insights, ask_user plumbing, umbrella stdio server."""

from __future__ import annotations

import json
import os
import sqlite3
import sys

import pytest
from sqlmodel import select

from clipper.core import Core
from clipper.db.engine import WriteTx
from clipper.db.models import Campaign, Marketplace, Post, Question
from clipper.events.bus import EventEnvelope
from clipper.services.base import ServiceError
from tests.conftest import call
from tests.factories import approve, make_account, make_campaign, make_clip, make_source


def _session_ok(core: Core, market: str, ok: bool) -> None:
    def job(tx: WriteTx) -> None:
        m = tx.session.get(Marketplace, market)
        assert m is not None
        m.session_ok = ok
        tx.add(m)

    core.db.write(job)


def test_marketplace_switch_off_finish_or_pause(core: Core) -> None:
    a = make_campaign(core.db, marketplace="whop", external_id="a", status="active")
    b = make_campaign(core.db, marketplace="whop", external_id="b", status="active")
    events: list[EventEnvelope] = []
    core.bus.add_listener(events.append, types=["toggles.changed"])
    assert core.toggles.preview_off("marketplace", "whop") == {"active_campaigns": 2}
    res = core.toggles.set("marketplace", "whop", False, by="ahad", via="ctrl+k")
    assert res["effects"]["campaign_status"] == "ending"
    with core.db.read() as s:
        assert {s.get(Campaign, a.id).status, s.get(Campaign, b.id).status} == {"ending"}  # type: ignore[union-attr]
    assert events[0].payload["via"] == "ctrl+k" and events[0].payload["by"] == "ahad"
    # switching back on needs a valid login
    assert core.toggles.set("marketplace", "whop", True)["ok"] is False
    _session_ok(core, "whop", True)
    assert core.toggles.set("marketplace", "whop", True)["ok"] is True
    c = make_campaign(core.db, marketplace="whop", external_id="c", status="active")
    core.toggles.set("marketplace", "whop", False, on_active="pause")
    with core.db.read() as s:
        assert s.get(Campaign, c.id).status == "paused"  # type: ignore[union-attr]


def test_social_switch_cancels_or_keeps_posts(core: Core) -> None:
    camp = make_campaign(core.db, platforms=["tiktok"])
    assert camp.id is not None
    src = make_source(core.db, camp.id)
    assert src.id is not None
    clip = make_clip(core.db, camp.id, src.id, status="approved")
    assert clip.id is not None
    approve(core.db, clip.id)
    acct = make_account(core.db, "tiktok", min_gap_min=0)
    assert acct.id is not None
    p1 = core.publishing.schedule(clip.id, acct.id, "now")
    assert core.toggles.preview_off("social", "tiktok") == {"scheduled_posts": 1}
    res = core.toggles.set("social", "tiktok", False, on_scheduled="cancel")
    assert res["effects"]["scheduled_posts"] == [p1.id]
    with core.db.read() as s:
        assert s.get(Post, p1.id).status == "cancelled"  # type: ignore[union-attr]
        assert s.get(Campaign, camp.id).status == "no_enabled_socials"  # type: ignore[union-attr]
    assert core.toggles.set("social", "tiktok", True)["ok"] is True  # an active tiktok account exists
    with core.db.read() as s:
        assert s.get(Campaign, camp.id).status == "active"  # type: ignore[union-attr]
    assert core.toggles.set("social", "x", True)["ok"] is False  # no X account: needs setup


async def test_insights_is_read_only(core: Core) -> None:
    make_campaign(core.db)
    ok = await call(core, "insights", "query", {"sql": "select count(*) n from campaign"})
    assert json.loads(ok.content[0]["text"])["rows"] == [{"n": 1}]
    for sql in (
        "delete from campaign",
        "select 1; delete from campaign",
        "with x as (select 1) insert into kv(key, value_json, updated_at) select 'k', '1', '2026-01-01' from x",
        "update campaign set title = 'x'",
    ):
        res = await call(core, "insights", "query", {"sql": sql})
        assert res.is_error, sql
    with pytest.raises(sqlite3.OperationalError):
        core.db.readonly().execute("delete from campaign")
    with core.db.read() as s:
        assert len(s.exec(select(Campaign)).all()) == 1
    rows = core.insights.performance_by("marketplace")
    assert rows == []
    with pytest.raises(ServiceError):
        core.insights.performance_by("1; drop table post")


async def test_ask_user_creates_question_and_answer_event(core: Core) -> None:
    seen: list[EventEnvelope] = []
    core.bus.add_listener(seen.append, types=["question.*"])
    res = await call(
        core,
        "notify",
        "ask_user",
        {"question": "Can we use the trailer footage?", "options": ["Yes", "No", "Skip campaign"]},
        role="campaign",
        session_id=None,
        campaign_id=None,
    )
    qid = json.loads(res.content[0]["text"])["question_id"]
    with core.db.read() as s:
        q = s.get(Question, qid)
        assert q is not None and q.options_json == ["Yes", "No", "Skip campaign"]
    core.notify.answer(qid, "No", by="ahad", via="discord")
    assert [e.type for e in seen] == ["question.asked", "question.answered"]
    assert seen[1].payload["answer"] == "No"
    with pytest.raises(ServiceError):
        core.notify.answer(qid, "Yes", by="ahad", via="dashboard")


async def test_umbrella_stdio_server(tmp_path: object) -> None:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    env = {**os.environ, "CLIPPER_FAKES": "1", "CLIPPER_DATA_DIR": str(tmp_path)}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "clipper.cli", "mcp", "clipper"], env=env
    )
    async with Client(params) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        assert {"status", "set_switch", "set_paused", "review_queue"} <= names
        ro = {t.name: t.annotations.read_only_hint if t.annotations else None for t in tools.tools}  # type: ignore[union-attr]
        assert ro["status"] is True and ro["set_paused"] is False
        res = await client.call_tool("status", {})
        payload = json.loads(res.content[0].text)  # type: ignore[union-attr]
        assert payload["dry_run"] is True and payload["kill_switch"] is False
        res = await client.call_tool("set_paused", {"paused": True})
        assert json.loads(res.content[0].text) == {"paused": True}  # type: ignore[union-attr]
