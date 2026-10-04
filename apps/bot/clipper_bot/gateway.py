"""The real ``Gateway``: discord.py calls behind the relay's small interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import discord


class DiscordGateway:
    def __init__(self, client: discord.Client) -> None:
        self.client = client

    async def _channel(self, channel_id: int) -> Any:
        ch = self.client.get_channel(channel_id)
        return ch if ch is not None else await self.client.fetch_channel(channel_id)

    async def send(
        self,
        channel_id: int,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
        file: Path | None = None,
    ) -> int:
        ch = await self._channel(channel_id)
        kw: dict[str, Any] = {"content": content}
        if embed is not None:
            kw["embed"] = embed
        if view is not None:
            kw["view"] = view
        if file is not None:
            kw["file"] = discord.File(file)
        msg = await ch.send(**kw)
        return int(msg.id)

    async def create_forum_post(
        self, forum_id: int, *, name: str, embed: discord.Embed, view: discord.ui.View, tag: str
    ) -> tuple[int, int]:
        forum = await self._channel(forum_id)
        if not isinstance(forum, discord.ForumChannel):
            raise TypeError("#clip-review must be a forum channel")
        tags = [t for t in forum.available_tags if t.name.lower() == tag.lower()]
        created = await forum.create_thread(name=name, embed=embed, view=view, applied_tags=tags)
        return int(created.thread.id), int(created.message.id)

    async def edit(
        self,
        channel_id: int,
        message_id: int,
        *,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
        file: Path | None = None,
    ) -> None:
        ch = await self._channel(channel_id)
        msg = ch.get_partial_message(message_id)
        kw: dict[str, Any] = {}
        if embed is not None:
            kw["embed"] = embed
        if view is not None:
            kw["view"] = view
        if file is not None:
            kw["attachments"] = [discord.File(file)]
        await msg.edit(**kw)

    async def pin(self, channel_id: int, message_id: int) -> None:
        ch = await self._channel(channel_id)
        await ch.get_partial_message(message_id).pin()

    async def set_tag(self, thread_id: int, tag: str) -> None:
        thread = await self._channel(thread_id)
        if not isinstance(thread, discord.Thread) or not isinstance(thread.parent, discord.ForumChannel):
            return
        tags = [t for t in thread.parent.available_tags if t.name.lower() == tag.lower()]
        if tags and [t.id for t in thread.applied_tags] != [t.id for t in tags]:
            await thread.edit(applied_tags=tags)


FORUM_TAGS = ("pending", "in review", "shipped")
TEXT_CHANNELS = {
    "control": "Talk to the Director. It replies in a thread.",
    "campaigns": "Campaign cards: Take / Skip.",
    "published": "Every post with its link.",
    "alerts": "Logins, challenges, quotas, failures.",
}


async def ensure_channels(guild: discord.Guild, current: dict[str, int | None]) -> dict[str, int]:
    """Creates the Clipper category and channels that don't exist yet (first run)."""
    created: dict[str, int] = {}
    category = discord.utils.get(guild.categories, name="Clipper") or await guild.create_category("Clipper")
    for key, topic in TEXT_CHANNELS.items():
        if current.get(key):
            continue
        name = key.replace("_", "-")
        ch = discord.utils.get(guild.text_channels, name=name) or await guild.create_text_channel(
            name, category=category, topic=topic
        )
        created[key] = ch.id
    if not current.get("clip_review"):
        forum = discord.utils.get(guild.forums, name="clip-review") or await guild.create_forum(
            "clip-review",
            category=category,
            topic="One post per campaign × source batch. Approve, reject, edit captions, re-cut.",
            available_tags=[discord.ForumTag(name=t) for t in FORUM_TAGS],
        )
        created["clip_review"] = forum.id
    return created
