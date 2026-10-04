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
