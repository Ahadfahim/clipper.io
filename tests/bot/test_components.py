"""Persistent components with mocked interactions (no Discord connection)."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord

from clipper_bot import ids
from clipper_bot.actions import NO_ROLE, Actions
from clipper_bot.components import (
    ApproveButton,
    CaptionButton,
    CaptionModal,
    ReasonSelect,
    RecutButton,
    RecutModal,
    RejectButton,
    ShipButton,
)
from tests.bot.conftest import CoreEnv


def interaction(actions: Actions, roles: list[str], data: dict[str, Any] | None = None) -> Any:
    response = SimpleNamespace(
        send_message=AsyncMock(),
        send_modal=AsyncMock(),
        edit_message=AsyncMock(),
        is_done=MagicMock(return_value=False),
    )
    user = SimpleNamespace(
        id=1,
        name="you",
        display_name="you",
        roles=[SimpleNamespace(id=i, name=n) for i, n in enumerate(roles)],
    )
    return SimpleNamespace(
        user=user,
        client=SimpleNamespace(actions=actions),
        response=response,
        followup=SimpleNamespace(send=AsyncMock()),
        data=data or {},
    )


async def _match(cls: Any, custom_id: str) -> Any:
    m = re.match(cls.__discord_ui_compiled_template__, custom_id)
    assert m, custom_id
    return await cls.from_custom_id(None, None, m)


async def _pending(env: CoreEnv) -> int:
    detail = await env.client.batch(env.ids["batch"])
    return next(c["clip"]["id"] for c in detail["clips"] if c["decision"] == "pending")


async def test_approve_button_rebuilds_from_custom_id_and_approves(
    actions: Actions, core_env: CoreEnv
) -> None:
    cid = await _pending(core_env)
    item = await _match(ApproveButton, ids.make(*ids.CLIP_APPROVE, cid))
    assert item.clip_id == cid
    i = interaction(actions, ["Clipper"])
    await item.callback(i)
    i.response.send_message.assert_awaited_once_with(f"Approved clip {cid}.", ephemeral=True)
    detail = await core_env.client.batch(core_env.ids["batch"])
    assert next(c for c in detail["clips"] if c["clip"]["id"] == cid)["decision"] == "approved"


async def test_buttons_refuse_members_without_the_role(actions: Actions, core_env: CoreEnv) -> None:
    cid = await _pending(core_env)
    for cls, custom in [
        (ApproveButton, ids.CLIP_APPROVE),
        (RejectButton, ids.CLIP_REJECT),
        (CaptionButton, ids.CLIP_CAPTION),
        (RecutButton, ids.CLIP_RECUT),
    ]:
        item = await _match(cls, ids.make(custom[0], custom[1], cid))
        i = interaction(actions, ["everyone"])
        await item.callback(i)
        i.response.send_message.assert_awaited_once_with(NO_ROLE, ephemeral=True)
        i.response.send_modal.assert_not_awaited()
    detail = await core_env.client.batch(core_env.ids["batch"])
    assert next(c for c in detail["clips"] if c["clip"]["id"] == cid)["decision"] == "pending"


async def test_reject_opens_reason_picker_then_select_rejects(actions: Actions, core_env: CoreEnv) -> None:
    cid = await _pending(core_env)
    i = interaction(actions, ["Clipper"])
    await (await _match(RejectButton, ids.make(*ids.CLIP_REJECT, cid))).callback(i)
    view = i.response.send_message.await_args.kwargs["view"]
    select = view.children[0]
    assert isinstance(select, discord.ui.Select) and select.custom_id == ids.make(*ids.CLIP_REASON, cid)
    assert i.response.send_message.await_args.kwargs["ephemeral"] is True

    j = interaction(actions, ["Clipper"], data={"values": ["boring"]})
    await (await _match(ReasonSelect, select.custom_id)).callback(j)
    j.response.edit_message.assert_awaited_once()
    assert j.response.edit_message.await_args.kwargs["content"].startswith(f"Rejected clip {cid}: boring")
    detail = await core_env.client.batch(core_env.ids["batch"])
    rc = next(c for c in detail["clips"] if c["clip"]["id"] == cid)
    assert rc["decision"] == "rejected" and rc["decision_reason"] == "boring"


async def test_caption_modal_prefills_and_saves_changes_only(actions: Actions, core_env: CoreEnv) -> None:
    cid = await _pending(core_env)
    i = interaction(actions, ["Clipper"])
    await (await _match(CaptionButton, ids.make(*ids.CLIP_CAPTION, cid))).callback(i)
    modal: CaptionModal = i.response.send_modal.await_args.args[0]
    assert isinstance(modal, CaptionModal) and "youtube" in modal.inputs
    original_tt = modal.inputs["tiktok"].default
    modal.inputs["youtube"]._value = "A better title"  # what the user typed
    for p, f in modal.inputs.items():
        if p != "youtube":
            f._value = f.default
    j = interaction(actions, ["Clipper"])
    await modal.on_submit(j)
    j.response.send_message.assert_awaited_once_with("Caption saved.", ephemeral=True)
    detail = await core_env.client.batch(core_env.ids["batch"])
    rc = next(c for c in detail["clips"] if c["clip"]["id"] == cid)
    assert rc["captions"]["youtube"] == "A better title" and rc["captions"]["tiktok"] == original_tt


async def test_recut_modal_sends_event(actions: Actions, core_env: CoreEnv) -> None:
    cid = await _pending(core_env)
    i = interaction(actions, ["Clipper"])
    await (await _match(RecutButton, ids.make(*ids.CLIP_RECUT, cid))).callback(i)
    modal: RecutModal = i.response.send_modal.await_args.args[0]
    modal.start._value, modal.end._value, modal.layout._value, modal.note._value = (
        "-2",
        "1",
        "fit",
        "keep the laugh",
    )
    j = interaction(actions, ["Clipper"])
    await modal.on_submit(j)
    assert j.response.send_message.await_args.args[0].startswith("Re-cut sent")
    ev = [e for e in core_env.core.bus.since(0, limit=1000) if e.type == "recut.requested"][-1]
    assert (
        ev.payload["clip_id"] == cid
        and ev.payload["end_delta"] == 1
        and ev.payload["note"] == "keep the laugh"
    )


async def test_ship_button(actions: Actions, core_env: CoreEnv) -> None:
    i = interaction(actions, ["clipper"])  # role names match case-insensitively
    await (await _match(ShipButton, ids.make(*ids.BATCH_SHIP, core_env.ids["batch"]))).callback(i)
    assert i.response.send_message.await_args.args[0].startswith("Shipped:")


# ---------------------------------------------------------------- answers in your own words, stuck things


async def _open_question(env: CoreEnv) -> int:
    return next(q["id"] for q in await env.client.questions() if q["status"] == "open")


async def test_other_opens_a_modal_and_the_answer_goes_in_as_your_own_words(
    actions: Actions, core_env: CoreEnv
) -> None:
    from clipper_bot.components import OtherButton, OtherModal

    qid = await _open_question(core_env)
    i = interaction(actions, ["Clipper"])
    await (await _match(OtherButton, ids.make(*ids.QUESTION_OTHER, qid))).callback(i)
    modal: OtherModal = i.response.send_modal.await_args.args[0]
    assert isinstance(modal, OtherModal) and modal.text.max_length == 500
    modal.text._value = "Use the trailer, but only the first minute"
    j = interaction(actions, ["Clipper"])
    await modal.on_submit(j)
    j.response.send_message.assert_awaited_once_with(
        "Answered in your own words. The agent picks it up from here.", ephemeral=True
    )
    q = await core_env.client.question(qid)
    assert (
        q is not None
        and q["status"] == "answered"
        and q["answer"] == "Use the trailer, but only the first minute"
    )
    again = interaction(actions, ["Clipper"])
    await modal.on_submit(again)
    again.response.send_message.assert_awaited_once_with(
        "That question was already answered.", ephemeral=True
    )


async def test_other_is_for_reviewers_only(actions: Actions, core_env: CoreEnv) -> None:
    from clipper_bot.components import OtherButton

    qid = await _open_question(core_env)
    i = interaction(actions, ["everyone"])
    await (await _match(OtherButton, ids.make(*ids.QUESTION_OTHER, qid))).callback(i)
    i.response.send_message.assert_awaited_once_with(NO_ROLE, ephemeral=True)
    i.response.send_modal.assert_not_awaited()


async def test_a_stall_button_rebuilds_from_its_id_and_runs_the_action(
    actions: Actions, core_env: CoreEnv
) -> None:
    from clipper_bot.components import StallButton

    # the demo has a job that stopped moving (job 2): cancel and retry it from the button
    stall = next(s for s in await core_env.client.stalls() if s["kind"] == "job_stalled")
    ident = stall["job_id"]
    item = await _match(StallButton, f"clipper:stall:cancel_retry:{ident}:job_stalled")
    assert (item.action, item.ident, item.kind) == ("cancel_retry", ident, "job_stalled")
    assert item.item.label == "Cancel and retry"
    i = interaction(actions, ["Clipper"])
    await item.callback(i)
    assert "queued it again as job" in i.response.send_message.await_args.args[0]
    assert not [s for s in await core_env.client.stalls() if s["kind"] == "job_stalled"]
    out = interaction(actions, ["everyone"])
    await item.callback(out)
    out.response.send_message.assert_awaited_once_with(NO_ROLE, ephemeral=True)
    gone = interaction(actions, ["Clipper"])
    await item.callback(gone)
    assert "isn't stuck any more" in gone.response.send_message.await_args.args[0]
