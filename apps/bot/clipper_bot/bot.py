"""The Clipper Discord bot: persistent review components, campaign cards, ask_user questions,
`/clipper toggle`, and the #control relay to the Director. It holds no state of its own; the
core is the source of truth (review state lives in SQLite)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import discord
from discord import app_commands

from clipper_bot.actions import Actions, Actor
from clipper_bot.components import DYNAMIC_ITEMS, actor_of
from clipper_bot.config import CHANNEL_KEYS, BotConfig
from clipper_bot.core_client import CoreClient, CoreError
from clipper_bot.gateway import DiscordGateway, ensure_channels
from clipper_bot.relay import EVENT_TYPES, Relay

log = logging.getLogger(__name__)

SWITCH_CHOICES = [
    app_commands.Choice(name=n, value=n) for n in ("vyro", "whop", "youtube", "tiktok", "instagram", "x")
]


def actor_of_member(member: Any) -> Actor:
    roles = list(getattr(member, "roles", []) or [])
    return Actor(
        id=member.id,
        name=str(getattr(member, "display_name", None) or member.name),
        role_ids=frozenset(r.id for r in roles),
        role_names=frozenset(r.name for r in roles),
    )


class ClipperBot(discord.Client):
    def __init__(self, core: CoreClient, cfg: BotConfig) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # #control relay (enable "Message Content" in the Developer Portal)
        super().__init__(intents=intents)
        self.core = core
        self.cfg = cfg
        self.actions = Actions(core, cfg)
        self.tree = app_commands.CommandTree(self)
        self.relay = Relay(core, DiscordGateway(self), cfg)
        self._tasks: list[asyncio.Task[None]] = []
        self._register_commands()

    def _register_commands(self) -> None:
        group = app_commands.Group(name="clipper", description="Clipper controls")

        @group.command(name="toggle", description="Turn a marketplace or social on or off")
        @app_commands.describe(name="vyro, whop, youtube, tiktok, instagram or x", state="on or off")
        @app_commands.choices(
            name=SWITCH_CHOICES,
            state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")],
        )
        async def toggle(
            interaction: discord.Interaction[Any],
            name: app_commands.Choice[str],
            state: app_commands.Choice[str],
        ) -> None:
            text = await self.actions.toggle(actor_of(interaction), name.value, state.value == "on")
            await interaction.response.send_message(text, ephemeral=True)

        @group.command(name="status", description="What the agents are doing")
        async def status(interaction: discord.Interaction[Any]) -> None:
            s = await self.core.status()
            c = s["control"]
            text = (
                f"{'Paused' if c['paused'] else 'Running'}{' · dry run' if c['dry_run'] else ''} · agents {s['agents_running']}/{s['agents_capacity']}"
                f" · {s['review_pending']} clips to review · today ${s['earned_today']:.2f}"
            )
            await interaction.response.send_message(text, ephemeral=True)

        self.tree.add_command(group)

    async def setup_hook(self) -> None:
        self.add_dynamic_items(*DYNAMIC_ITEMS)
        if self.cfg.guild_id:
            guild = discord.Object(id=self.cfg.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        self._tasks.append(asyncio.create_task(self._heartbeat()))
        self._tasks.append(asyncio.create_task(self._events()))

    async def on_ready(self) -> None:
        log.info("logged in as %s", self.user)
        if self.cfg.guild_id:
            guild = self.get_guild(self.cfg.guild_id)
            if guild is not None:
                current = self.cfg.channels.model_dump()
                if not all(current.get(k) for k in CHANNEL_KEYS):
                    created = await ensure_channels(guild, current)
                    if created:
                        await self.core.patch_settings(
                            {f"discord.channels.{k}": v for k, v in created.items()}
                        )
                        self.cfg.channels = self.cfg.channels.model_copy(update=created)

    async def on_message(self, message: discord.Message) -> None:
        """#control: a message starts (or continues) a thread with the Director."""
        if message.author.bot or not self.cfg.channels.control:
            return
        ch = message.channel
        in_control = ch.id == self.cfg.channels.control
        in_thread = isinstance(ch, discord.Thread) and ch.parent_id == self.cfg.channels.control
        if not (in_control or in_thread):
            return
        actor = actor_of_member(message.author)
        thread_id: int | None = ch.id if in_thread else None
        if in_control:
            if not self.actions.allowed(actor):
                return
            thread = await message.create_thread(name=f"Director · {message.content[:40] or 'chat'}")
            thread_id = thread.id
        err = await self.actions.chat(actor, message.content, thread_id)
        if err:
            await message.reply(err, mention_author=False)

    async def _heartbeat(self) -> None:
        while not self.is_closed():
            with contextlib.suppress(CoreError, OSError):
                await self.core.heartbeat()
            await asyncio.sleep(60)

    async def _events(self) -> None:
        await self.wait_until_ready()
        async for ev in self.core.events(after=0, types=EVENT_TYPES):
            await self.relay.handle(ev)

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        await self.core.close()
        await super().close()
