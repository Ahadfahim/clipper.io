"""Bot actions against the real core API (fixture data): role gating and every review action."""

from __future__ import annotations

from typing import Any

from clipper.events.types import EVENT_TYPES  # noqa: F401  (registry import keeps payloads typed)
from clipper_bot.actions import NO_ROLE, Actions
from tests.bot.conftest import OUTSIDER, REVIEWER, CoreEnv


async def _rc(env: CoreEnv, batch: int, clip: int) -> dict[str, Any]:
    detail = await env.client.batch(batch)
    return next(c for c in detail["clips"] if c["clip"]["id"] == clip)


async def test_outsiders_cannot_act_and_nothing_changes(actions: Actions, core_env: CoreEnv) -> None:
    batch = core_env.ids["batch"]
    pending = next(c for c in (await core_env.client.batch(batch))["clips"] if c["decision"] == "pending")
    cid = pending["clip"]["id"]
    for result in [
        await actions.approve(OUTSIDER, cid),
        await actions.reject(OUTSIDER, cid, "boring"),
        await actions.ship(OUTSIDER, batch),
        await actions.take(OUTSIDER, 3),
        await actions.toggle(OUTSIDER, "whop", False),
        await actions.chat(OUTSIDER, "hi", None),
    ]:
        assert result == NO_ROLE
    assert (await _rc(core_env, batch, cid))["decision"] == "pending"


async def test_role_by_id_beats_name(actions: Actions) -> None:
    actions.cfg = actions.cfg.model_copy(update={"reviewer_role_id": 500})
    assert actions.allowed(REVIEWER)
    actions.cfg = actions.cfg.model_copy(update={"reviewer_role_id": 999})
    assert not actions.allowed(REVIEWER)


async def test_review_flow_approve_reject_platforms_caption_recut(
    actions: Actions, core_env: CoreEnv
) -> None:
    batch = core_env.ids["batch"]
    pending = [c for c in (await core_env.client.batch(batch))["clips"] if c["decision"] == "pending"]
    a, b = pending[0]["clip"]["id"], pending[1]["clip"]["id"]

    assert await actions.approve(REVIEWER, a) == f"Approved clip {a}."
    rc = await _rc(core_env, batch, a)
    assert rc["decision"] == "approved" and rc["via"] == "discord" and rc["reviewer"] == "you"

    assert (await actions.reject(REVIEWER, b, "bad_hook")).startswith(f"Rejected clip {b}")
    rc = await _rc(core_env, batch, b)
    assert rc["decision"] == "rejected" and rc["decision_reason"] == "bad_hook"
    assert await actions.reject(REVIEWER, b, "nonsense") == "Pick one of the reasons."

    assert "youtube" in await actions.set_platforms(REVIEWER, a, ["youtube"])
    rc = await _rc(core_env, batch, a)
    assert rc["platforms"] == ["youtube"] and rc["decision"] == "approved"

    assert await actions.captions(REVIEWER, a, {"youtube": "New title"}) == "Caption saved."
    assert (await _rc(core_env, batch, a))["captions"]["youtube"] == "New title"

    assert (await actions.recut(REVIEWER, a, "x", "0", "", "")).startswith("Start and end must be numbers")
    assert (
        await actions.recut(REVIEWER, a, "-9", "0", "", "") == "Re-cuts can move each end by up to 5 seconds."
    )
    assert (
        await actions.recut(REVIEWER, a, "0", "0", "zoom", "") == "Layout must be crop, split, fit or empty."
    )
    assert (await actions.recut(REVIEWER, a, "-1.5", "2", "split", "tighter")).startswith("Re-cut sent")
    ev = [e for e in core_env.core.bus.since(0, limit=1000) if e.type == "recut.requested"][-1]
    assert (
        ev.payload["start_delta"] == -1.5
        and ev.payload["layout"] == "split"
        and ev.payload["via"] == "discord"
    )


async def test_batch_actions_and_ship(actions: Actions, core_env: CoreEnv) -> None:
    batch = core_env.ids["batch"]
    assert (await actions.approve_all(REVIEWER, batch)).startswith("Approved")
    assert (await actions.reject_rest(REVIEWER, batch)).startswith("Rejected the")
    detail = await core_env.client.batch(batch)
    assert detail["batch"]["pending"] == 0
    assert (await actions.ship(REVIEWER, batch)).startswith("Shipped:")
    assert (await core_env.client.batch(batch))["batch"]["status"] == "shipped"
    shipped = [e for e in core_env.core.bus.since(0, limit=1000) if e.type == "review.shipped"]
    assert shipped and shipped[-1].payload["via"] == "discord"


async def test_campaign_question_toggle_and_chat(actions: Actions, core_env: CoreEnv) -> None:
    assert await actions.take(REVIEWER, 3) == "Taken. The Campaign agent starts on it."
    assert (await core_env.client.campaign(3))["campaign"]["status"] == "active"
    assert await actions.skip(REVIEWER, 4) == "Skipped."

    q = next(q for q in await core_env.client._req("GET", "/api/questions") if q["status"] == "open")
    assert (await actions.answer(REVIEWER, q["id"], 1)).startswith(f"Answered: {q['options'][1]}")
    assert await actions.answer(REVIEWER, q["id"], 0) == "That question was already answered."

    assert (await actions.toggle(REVIEWER, "whop", False)).startswith("whop is off")
    assert (await core_env.client.switches())["marketplaces"]["whop"]["enabled"] is False
    assert (await actions.toggle(REVIEWER, "myspace", True)).startswith("Unknown switch")
    changed = [e for e in core_env.core.bus.since(0, limit=1000) if e.type == "toggles.changed"][-1]
    assert changed.payload["via"] == "discord"

    assert await actions.chat(REVIEWER, "how are we doing?", 777) is None
    chat = [e for e in core_env.core.bus.since(0, limit=1000) if e.type == "user.chat"][-1]
    assert chat.payload == {"text": "how are we doing?", "via": "discord", "reply_to": "777"}
