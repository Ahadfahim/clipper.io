"""Questions stay in step with their campaign: closed when it ends, short options only."""

from __future__ import annotations

import pytest
from sqlmodel import select

from clipper.core import Core
from clipper.db.models import Question
from clipper.events.bus import EventEnvelope
from clipper.services.base import ServiceError
from clipper.supervisor.router import compact, route
from tests.conftest import call
from tests.factories import make_campaign


def _ask(core: Core, campaign_id: int, text: str = "Which footage should I use?") -> int:
    return core.notify.ask_user(text, ["Yes", "No"], session_id=None, campaign_id=campaign_id)


def _status(core: Core, qid: int) -> tuple[str, str | None, str | None]:
    with core.db.read() as s:
        q = s.get(Question, qid)
        assert q is not None
        return q.status, q.answer, q.via


def test_skipping_a_campaign_closes_its_open_questions(core: Core) -> None:
    c = make_campaign(core.db, status="active")
    other = make_campaign(core.db, status="active", external_id="other")
    mine, theirs = _ask(core, c.id or 0), _ask(core, other.id or 0)
    seen: list[EventEnvelope] = []
    core.bus.add_listener(seen.append, types=["question.answered"])

    core.campaigns.skip(c.id or 0)

    assert _status(core, mine) == ("closed", "(campaign skipped)", "campaign_closed")
    assert _status(core, theirs)[0] == "open"
    assert [e.payload["question_id"] for e in seen] == [mine]
    assert seen[0].payload["via"] == "campaign_closed"


def test_ending_a_campaign_closes_its_open_questions(core: Core) -> None:
    c = make_campaign(core.db, status="active")
    qid = _ask(core, c.id or 0)
    core.campaigns.update(c.id or 0, {"status": "ended"}, by="session:1")
    assert _status(core, qid)[:2] == ("closed", "(campaign ended)")


def test_other_status_changes_leave_questions_open(core: Core) -> None:
    c = make_campaign(core.db, status="active")
    qid = _ask(core, c.id or 0)
    core.campaigns.update(c.id or 0, {"status": "paused"}, by="session:1")
    assert _status(core, qid)[0] == "open"


def test_closed_questions_are_not_listed_as_open(core: Core) -> None:
    c = make_campaign(core.db, status="active")
    _ask(core, c.id or 0)
    core.campaigns.skip(c.id or 0)
    assert core.notify.open_questions() == []
    with core.db.read() as s:
        assert s.exec(select(Question).where(Question.status == "open")).all() == []


def test_a_closed_question_does_not_resume_the_campaign_agent(core: Core) -> None:
    c = make_campaign(core.db, status="active")
    seen: list[EventEnvelope] = []
    core.bus.add_listener(seen.append, types=["question.answered"])
    qid = core.notify.ask_user("Use it?", ["Yes", "No"], session_id=None, campaign_id=c.id)
    core.campaigns.skip(c.id or 0)
    closed = seen[-1]
    assert closed.payload["question_id"] == qid
    assert route(closed, session_of=lambda _sid: None, clip_campaign=lambda _cid: None) == []
    # a real answer still routes
    answered = EventEnvelope(
        id=99,
        type="question.answered",
        entity="question",
        entity_id=str(qid),
        payload={**closed.payload, "via": "dashboard"},
        ts=closed.ts,
    )
    assert route(answered, session_of=lambda _sid: None, clip_campaign=lambda _cid: None)
    assert compact(answered)["payload"]["via"] == "dashboard"


async def test_long_answer_options_are_refused_not_cut(core: Core) -> None:
    long_option = "I'll join the campaign on Vyro myself and give you the correct URL; then retry the submit"
    res = await call(
        core,
        "notify",
        "ask_user",
        {"question": "How should I proceed with this one?", "options": [long_option, "Stop"]},
        role="campaign",
        session_id=None,
        campaign_id=None,
    )
    assert res.is_error
    assert "60 characters" in res.content[0]["text"]
    assert core.notify.open_questions() == []


def test_service_refuses_options_over_the_limit(core: Core) -> None:
    with pytest.raises(ServiceError, match="60 characters"):
        core.notify.ask_user("Pick one", ["x" * 61], session_id=None, campaign_id=None)
    qid = core.notify.ask_user("Pick one", ["x" * 60], session_id=None, campaign_id=None)
    assert _status(core, qid)[0] == "open"
