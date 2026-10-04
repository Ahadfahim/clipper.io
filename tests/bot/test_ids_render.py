from __future__ import annotations

import re

import discord
import pytest

from clipper_bot import ids, render
from clipper_bot.components import DYNAMIC_ITEMS


def test_ids_round_trip_and_length() -> None:
    cid = ids.make(*ids.QUESTION_ANSWER, 42, 3)
    assert cid == "clipper:question:answer:42:3"
    assert ids.parse(cid) == ids.ParsedId("question", "answer", 42, "3")
    assert ids.parse("something:else") is None
    with pytest.raises(ValueError, match="too long"):
        ids.make("clip", "approve", 1, "x" * 100)


def test_every_rendered_component_has_a_dynamic_handler() -> None:
    """Persistent buttons survive restarts only if a DynamicItem template matches their id."""
    templates = [item.__discord_ui_compiled_template__ for item in DYNAMIC_ITEMS]
    detail = {
        "batch": {
            "id": 3,
            "campaign_title": "MrBeast",
            "source_title": "S1",
            "status": "in_review",
            "approved": 1,
            "rejected": 0,
            "pending": 2,
            "total": 3,
            "timeout_at": None,
        },
        "clips": [],
        "approve_all_threshold": 80,
    }
    rc = {
        "clip": {
            "id": 7,
            "hook": "Hook",
            "score": 91.0,
            "duration": 42.0,
            "status": "in_review",
            "version": 2,
        },
        "decision": "pending",
        "platforms": ["youtube"],
        "platforms_allowed": ["youtube", "tiktok"],
        "captions": {"youtube": "Title"},
        "source_range": [120.0, 162.0],
        "reason": "Peak",
    }
    q = {"id": 5, "text": "Use the trailer?", "options": ["Yes", "No"], "status": "open"}
    camp = {
        "campaign": {
            "id": 9,
            "title": "C",
            "marketplace": "vyro",
            "status": "suggested",
            "score": 81.0,
            "cpm": 2.0,
            "budget_left": 5000.0,
            "deadline": None,
            "matching_accounts": [],
        },
        "url": "https://vyro.com/c/9",
    }
    views = [
        render.batch_summary(detail, 80)[1],
        render.clip_message(rc)[1],
        render.question_message(q)[1],
        render.campaign_card(camp)[1],
        render.reason_picker(7),
    ]
    custom_ids = [c.custom_id for v in views for c in v.children if getattr(c, "custom_id", None)]  # type: ignore[attr-defined]
    assert len(custom_ids) >= 12
    for cid in custom_ids:
        assert any(re.match(t, cid) for t in templates), cid


def test_clip_message_embed() -> None:
    rc = {
        "clip": {
            "id": 7,
            "hook": "Nobody tells you this",
            "score": 91.4,
            "duration": 42.0,
            "status": "in_review",
            "version": 2,
        },
        "decision": "rejected",
        "decision_reason": "bad_hook",
        "reviewer": "you",
        "via": "dashboard",
        "platforms": ["youtube"],
        "platforms_allowed": ["youtube", "tiktok"],
        "captions": {"youtube": "Title", "tiktok": "cap #tag"},
        "source_range": [120.0, 162.0],
        "reason": "Heatmap peak",
        "qa_ok": True,
    }
    e, v = render.clip_message(rc)
    fields = {f.name: f.value for f in e.fields}
    assert fields["Score"] == "91" and fields["Length"] == "0:42" and fields["Source"] == "2:00–2:42"
    assert fields["☑ YouTube"] == "Title" and fields["☐ TikTok"] == "cap #tag"
    assert e.footer.text and "Rejected by you via the app · Bad hook" in e.footer.text
    assert e.colour == render.RED
    select = next(c for c in v.children if isinstance(c, discord.ui.Select))
    assert [o.default for o in select.options] == [True, False]
    _, shipped = render.clip_message(rc, shipped=True)
    assert all(getattr(c, "disabled", False) for c in shipped.children)
