"""Persistent buttons, selects and modals. Each component is a ``DynamicItem`` whose template
matches the stable ``custom_id`` (ids.py), so clicks keep working across bot restarts without
storing views. Handlers only translate the interaction; the work happens in ``Actions``."""

from __future__ import annotations

import re
from typing import Any, Protocol, cast

import discord
from discord.ui import DynamicItem

from clipper_bot import ids
from clipper_bot.actions import NO_ROLE, PLATFORMS, Actions, Actor
from clipper_bot.render import PLATFORM_LABEL, reason_picker


class HasActions(Protocol):
    actions: Actions


def actor_of(interaction: discord.Interaction[Any]) -> Actor:
    user = interaction.user
    roles = list(getattr(user, "roles", []) or [])
    return Actor(
        id=user.id,
        name=str(getattr(user, "display_name", None) or user.name),
        role_ids=frozenset(r.id for r in roles),
        role_names=frozenset(r.name for r in roles),
    )


def actions_of(interaction: discord.Interaction[Any]) -> Actions:
    return cast(HasActions, interaction.client).actions


async def reply(interaction: discord.Interaction[Any], text: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


def _id(match: re.Match[str]) -> int:
    return int(match["id"])


# ---------------------------------------------------------------- campaigns


class TakeButton(DynamicItem[discord.ui.Button[Any]], template=ids.template(*ids.CAMPAIGN_TAKE)):
    def __init__(self, campaign_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Take",
                style=discord.ButtonStyle.success,
                custom_id=ids.make(*ids.CAMPAIGN_TAKE, campaign_id),
            )
        )
        self.campaign_id = campaign_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> TakeButton:
        return cls(_id(match))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await reply(interaction, await actions_of(interaction).take(actor_of(interaction), self.campaign_id))


class SkipButton(DynamicItem[discord.ui.Button[Any]], template=ids.template(*ids.CAMPAIGN_SKIP)):
    def __init__(self, campaign_id: int) -> None:
        super().__init__(discord.ui.Button(label="Skip", custom_id=ids.make(*ids.CAMPAIGN_SKIP, campaign_id)))
        self.campaign_id = campaign_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> SkipButton:
        return cls(_id(match))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await reply(interaction, await actions_of(interaction).skip(actor_of(interaction), self.campaign_id))


# ---------------------------------------------------------------- clips


class ApproveButton(DynamicItem[discord.ui.Button[Any]], template=ids.template(*ids.CLIP_APPROVE)):
    def __init__(self, clip_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.success,
                custom_id=ids.make(*ids.CLIP_APPROVE, clip_id),
            )
        )
        self.clip_id = clip_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> ApproveButton:
        return cls(_id(match))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await reply(interaction, await actions_of(interaction).approve(actor_of(interaction), self.clip_id))


class RejectButton(DynamicItem[discord.ui.Button[Any]], template=ids.template(*ids.CLIP_REJECT)):
    """Opens a private reason picker; the reasons feed the learning loop."""

    def __init__(self, clip_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Reject",
                style=discord.ButtonStyle.danger,
                custom_id=ids.make(*ids.CLIP_REJECT, clip_id),
            )
        )
        self.clip_id = clip_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> RejectButton:
        return cls(_id(match))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        if not actions_of(interaction).allowed(actor_of(interaction)):
            await reply(interaction, NO_ROLE)
            return
        await interaction.response.send_message(
            f"Reject clip {self.clip_id} because…", view=reason_picker(self.clip_id), ephemeral=True
        )


class ReasonSelect(DynamicItem[discord.ui.Select[Any]], template=ids.template(*ids.CLIP_REASON)):
    def __init__(self, clip_id: int) -> None:
        super().__init__(
            discord.ui.Select(
                custom_id=ids.make(*ids.CLIP_REASON, clip_id),
                options=[discord.SelectOption(label="x", value="x")],
            )
        )
        self.clip_id = clip_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> ReasonSelect:
        return cls(_id(match))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        values = list((interaction.data or {}).get("values", []))  # type: ignore[union-attr]
        text = await actions_of(interaction).reject(
            actor_of(interaction), self.clip_id, str(values[0]) if values else ""
        )
        await interaction.response.edit_message(content=text, view=None)


class PlatformsSelect(DynamicItem[discord.ui.Select[Any]], template=ids.template(*ids.CLIP_PLATFORMS)):
    def __init__(self, clip_id: int) -> None:
        super().__init__(
            discord.ui.Select(
                custom_id=ids.make(*ids.CLIP_PLATFORMS, clip_id),
                options=[discord.SelectOption(label="x", value="x")],
            )
        )
        self.clip_id = clip_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> PlatformsSelect:
        return cls(_id(match))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        values = [str(v) for v in (interaction.data or {}).get("values", [])]  # type: ignore[union-attr]
        await reply(
            interaction,
            await actions_of(interaction).set_platforms(actor_of(interaction), self.clip_id, values),
        )


class CaptionModal(discord.ui.Modal):
    def __init__(self, clip_id: int, captions: dict[str, str], platforms: list[str]) -> None:
        super().__init__(
            title=f"Edit captions · clip {clip_id}", custom_id=ids.make("modal", "caption", clip_id)
        )
        self.clip_id = clip_id
        self.original = captions
        self.inputs: dict[str, discord.ui.TextInput[Any]] = {}
        for p in platforms[:5]:
            field: discord.ui.TextInput[Any] = discord.ui.TextInput(
                label="YouTube title" if p == "youtube" else f"{PLATFORM_LABEL[p]} caption",
                style=discord.TextStyle.paragraph,
                default=captions.get(p, ""),
                required=False,
                max_length=100 if p == "youtube" else 2200,
                custom_id=f"cap-{p}",
            )
            self.inputs[p] = field
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        changes = {p: f.value for p, f in self.inputs.items() if f.value != self.original.get(p, "")}
        await reply(
            interaction, await actions_of(interaction).captions(actor_of(interaction), self.clip_id, changes)
        )


class CaptionButton(DynamicItem[discord.ui.Button[Any]], template=ids.template(*ids.CLIP_CAPTION)):
    def __init__(self, clip_id: int) -> None:
        super().__init__(
            discord.ui.Button(label="Edit caption", custom_id=ids.make(*ids.CLIP_CAPTION, clip_id))
        )
        self.clip_id = clip_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> CaptionButton:
        return cls(_id(match))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        actions = actions_of(interaction)
        if not actions.allowed(actor_of(interaction)):
            await reply(interaction, NO_ROLE)
            return
        clip = await actions.core.clip(self.clip_id)
        review = clip.get("review") or {}
        captions = {str(k): str(v) for k, v in (review.get("captions") or {}).items()}
        platforms = [p for p in PLATFORMS if p in captions or p in (review.get("platforms") or [])] or [
            "youtube",
            "tiktok",
            "instagram",
        ]
        await interaction.response.send_modal(CaptionModal(self.clip_id, captions, platforms))


class RecutModal(discord.ui.Modal):
    def __init__(self, clip_id: int) -> None:
        super().__init__(title=f"Re-cut clip {clip_id}", custom_id=ids.make("modal", "recut", clip_id))
        self.clip_id = clip_id
        self.start: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Move start (seconds, ±5)",
            placeholder="-1.5 starts earlier",
            required=False,
            max_length=6,
            custom_id="start",
        )
        self.end: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Move end (seconds, ±5)",
            placeholder="2 ends later",
            required=False,
            max_length=6,
            custom_id="end",
        )
        self.layout: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Layout: crop, split, fit (empty = keep)", required=False, max_length=5, custom_id="layout"
        )
        self.note: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Note for the agent",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            custom_id="note",
        )
        for f in (self.start, self.end, self.layout, self.note):
            self.add_item(f)

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        text = await actions_of(interaction).recut(
            actor_of(interaction),
            self.clip_id,
            self.start.value,
            self.end.value,
            self.layout.value,
            self.note.value,
        )
        await reply(interaction, text)


class RecutButton(DynamicItem[discord.ui.Button[Any]], template=ids.template(*ids.CLIP_RECUT)):
    def __init__(self, clip_id: int) -> None:
        super().__init__(discord.ui.Button(label="Re-cut", custom_id=ids.make(*ids.CLIP_RECUT, clip_id)))
        self.clip_id = clip_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> RecutButton:
        return cls(_id(match))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        if not actions_of(interaction).allowed(actor_of(interaction)):
            await reply(interaction, NO_ROLE)
            return
        await interaction.response.send_modal(RecutModal(self.clip_id))


# ---------------------------------------------------------------- batch summary


class ShipButton(DynamicItem[discord.ui.Button[Any]], template=ids.template(*ids.BATCH_SHIP)):
    def __init__(self, batch_id: int) -> None:
        super().__init__(
            discord.ui.Button(label="Ship approved", custom_id=ids.make(*ids.BATCH_SHIP, batch_id))
        )
        self.batch_id = batch_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> ShipButton:
        return cls(_id(match))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await reply(interaction, await actions_of(interaction).ship(actor_of(interaction), self.batch_id))


class ApproveAllButton(DynamicItem[discord.ui.Button[Any]], template=ids.template(*ids.BATCH_APPROVE_ALL)):
    def __init__(self, batch_id: int) -> None:
        super().__init__(
            discord.ui.Button(label="Approve all", custom_id=ids.make(*ids.BATCH_APPROVE_ALL, batch_id))
        )
        self.batch_id = batch_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> ApproveAllButton:
        return cls(_id(match))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await reply(
            interaction, await actions_of(interaction).approve_all(actor_of(interaction), self.batch_id)
        )


class RejectRestButton(DynamicItem[discord.ui.Button[Any]], template=ids.template(*ids.BATCH_REJECT_REST)):
    def __init__(self, batch_id: int) -> None:
        super().__init__(
            discord.ui.Button(label="Reject rest", custom_id=ids.make(*ids.BATCH_REJECT_REST, batch_id))
        )
        self.batch_id = batch_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> RejectRestButton:
        return cls(_id(match))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await reply(
            interaction, await actions_of(interaction).reject_rest(actor_of(interaction), self.batch_id)
        )


# ---------------------------------------------------------------- ask_user


class AnswerButton(
    DynamicItem[discord.ui.Button[Any]], template=ids.template(*ids.QUESTION_ANSWER, extra=True)
):
    def __init__(self, question_id: int, option: int) -> None:
        super().__init__(
            discord.ui.Button(label="Answer", custom_id=ids.make(*ids.QUESTION_ANSWER, question_id, option))
        )
        self.question_id = question_id
        self.option = option

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction[Any], item: discord.ui.Item[Any], match: re.Match[str], /
    ) -> AnswerButton:
        return cls(_id(match), int(match["extra"]))

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await reply(
            interaction,
            await actions_of(interaction).answer(actor_of(interaction), self.question_id, self.option),
        )


DYNAMIC_ITEMS: tuple[type[DynamicItem[Any]], ...] = (
    TakeButton,
    SkipButton,
    ApproveButton,
    RejectButton,
    ReasonSelect,
    PlatformsSelect,
    CaptionButton,
    RecutButton,
    ShipButton,
    ApproveAllButton,
    RejectRestButton,
    AnswerButton,
)
