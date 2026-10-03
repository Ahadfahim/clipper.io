"""Core events → Discord. Posts campaign cards, review batches (forum post + one message per
clip + pinned summary), questions, alerts and the publish log, and re-renders a message
whenever its state changes, so Discord and the dashboard never disagree.

The relay talks to Discord through ``Gateway`` so it can be tested with a fake.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Protocol

import discord

from clipper_bot import render
from clipper_bot.config import BotConfig
from clipper_bot.core_client import CoreClient, CoreError

log = logging.getLogger(__name__)

EVENT_TYPES = [
    "review.campaign_card",
    "campaign.taken",
    "campaign.skipped",
    "campaign.updated",
    "review.batch_posted",
    "review.decided",
    "review.shipped",
    "review.preview_replaced",
    "caption.edited",
    "recut.requested",
    "clip.updated",
    "question.asked",
    "question.answered",
    "post.live",
    "alert",
    "account.paused",
    "agent.event",
    "user.chat",
]

DISCORD_UPLOAD_LIMIT = 10 * 1024 * 1024  # bot uploads; previews are encoded to ~9.5 MB


class Gateway(Protocol):
    async def send(
        self,
        channel_id: int,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
        file: Path | None = None,
    ) -> int: ...
    async def create_forum_post(
        self, forum_id: int, *, name: str, embed: discord.Embed, view: discord.ui.View, tag: str
    ) -> tuple[int, int]: ...
    async def edit(
        self,
        channel_id: int,
        message_id: int,
        *,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
        file: Path | None = None,
    ) -> None: ...
    async def pin(self, channel_id: int, message_id: int) -> None: ...
    async def set_tag(self, thread_id: int, tag: str) -> None: ...


class Relay:
    def __init__(self, core: CoreClient, gateway: Gateway, cfg: BotConfig) -> None:
        self.core = core
        self.gw = gateway
        self.cfg = cfg
        self.roles: dict[int, str] = {}  # agent session id → role (to spot the Director)
        self.last_chat_thread: int | None = None

    async def handle(self, ev: dict[str, Any]) -> None:
        t = str(ev.get("type"))
        p: dict[str, Any] = dict(ev.get("payload") or {})
        try:
            if t == "review.campaign_card":
                await self.campaign_card(int(p["campaign_id"]), p.get("reasoning"))
            elif t in ("campaign.taken", "campaign.skipped", "campaign.updated"):
                await self.refresh_campaign(int(p["campaign_id"]))
            elif t == "review.batch_posted":
                await self.batch_posted(int(p["batch_id"]))
            elif t in ("review.decided", "caption.edited", "recut.requested", "clip.updated"):
                await self.refresh_clip(int(p["clip_id"]), p.get("batch_id"))
            elif t == "review.preview_replaced":
                await self.refresh_clip(int(p["clip_id"]), p.get("batch_id"), new_file=True)
            elif t == "review.shipped":
                await self.refresh_batch(int(p["batch_id"]), all_clips=True)
            elif t == "question.asked":
                await self.question(int(p["question_id"]))
            elif t == "question.answered":
                await self.refresh_question(int(p["question_id"]))
            elif t == "post.live":
                await self.published(p)
            elif t == "alert":
                if p.get("level") in ("warning", "error"):
                    await self.alert(
                        str(p.get("level")), str(p.get("text", "")), str(p.get("source", "alert"))
                    )
            elif t == "account.paused":
                await self.alert(
                    "warning",
                    f"Account {p.get('account_id')} paused: {p.get('reason')}. Fix it in its Chrome window, then press Resume.",
                    "publish",
                )
            elif t == "user.chat":
                rt = p.get("reply_to")
                if p.get("via") == "discord" and rt and str(rt).isdigit():
                    self.last_chat_thread = int(rt)
            elif t == "agent.event":
                await self.director_reply(p)
        except CoreError as e:
            log.warning("relay %s failed: %s", t, e.detail)

    async def catch_up(self) -> None:
        """After a (re)start: post whatever is waiting and isn't in Discord yet. Every post is
        idempotent (message refs live in the core), so nothing is posted twice and old alerts
        are not replayed."""
        for b in await self.core.batches():
            if b.get("status") != "shipped":
                await self.batch_posted(int(b["id"]))
        for c in await self.core.campaigns():
            if c.get("status") in ("suggested", "needs_user"):
                await self.campaign_card(int(c["id"]), None)
        for q in await self.core.questions():
            if q.get("status") == "open":
                await self.question(int(q["id"]))

    # ------------------------------------------------------------ campaigns
    async def campaign_card(self, campaign_id: int, reasoning: str | None) -> None:
        if not self.cfg.channels.campaigns or await self.core.ref("campaign_card", campaign_id):
            return
        detail = await self.core.campaign(campaign_id)
        embed, view = render.campaign_card(detail, reasoning)
        mid = await self.gw.send(self.cfg.channels.campaigns, embed=embed, view=view)
        await self.core.put_ref("campaign_card", campaign_id, self.cfg.channels.campaigns, mid)

    async def refresh_campaign(self, campaign_id: int) -> None:
        ref = await self.core.ref("campaign_card", campaign_id)
        if not ref or not ref.get("message_id"):
            return
        detail = await self.core.campaign(campaign_id)
        embed, view = render.campaign_card(detail)
        await self.gw.edit(int(ref["channel_id"]), int(ref["message_id"]), embed=embed, view=view)

    # ------------------------------------------------------------ review batches
    async def batch_posted(self, batch_id: int) -> None:
        forum = self.cfg.channels.clip_review
        if not forum or await self.core.ref("batch", batch_id):
            return
        detail = await self.core.batch(batch_id)
        b = detail["batch"]
        embed, view = render.batch_summary(detail, self.cfg.approve_all_threshold)
        name = f"{b['campaign_title']} · {b.get('source_title') or 'source'} · batch {b['id']}"[:100]
        thread_id, starter_id = await self.gw.create_forum_post(
            forum, name=name, embed=embed, view=view, tag=render.batch_tag(detail)
        )
        await self.gw.pin(thread_id, starter_id)
        await self.core.put_ref("batch", batch_id, forum, starter_id, thread_id)
        for rc in sorted(detail["clips"], key=lambda c: -c["clip"]["score"]):
            cid = rc["clip"]["id"]
            embed, view = render.clip_message(rc)
            mid = await self.gw.send(thread_id, embed=embed, view=view, file=await self._preview(cid))
            await self.core.put_ref("clip", cid, thread_id, mid, thread_id)

    async def _preview(self, clip_id: int) -> Path | None:
        info = await self.core.preview_path(clip_id)
        path = info.get("path")
        if not path:
            return None
        f = Path(path)
        ok = await asyncio.to_thread(lambda: f.is_file() and f.stat().st_size <= DISCORD_UPLOAD_LIMIT)
        return f if ok else None

    async def refresh_clip(self, clip_id: int, batch_id: int | None, new_file: bool = False) -> None:
        ref = await self.core.ref("clip", clip_id)
        if not ref or not ref.get("message_id"):
            return
        if batch_id is None:
            clip = await self.core.clip(clip_id)
            review = clip.get("review") or {}
            batch_id = review.get("batch_id")
        if batch_id is None:
            return
        detail = await self.core.batch(int(batch_id))
        rc = next((c for c in detail["clips"] if c["clip"]["id"] == clip_id), None)
        if rc is None:
            return
        embed, view = render.clip_message(rc, shipped=detail["batch"].get("status") == "shipped")
        await self.gw.edit(
            int(ref["channel_id"]),
            int(ref["message_id"]),
            embed=embed,
            view=view,
            file=await self._preview(clip_id) if new_file else None,
        )
        await self.refresh_batch(int(batch_id), detail=detail)

    async def refresh_batch(
        self, batch_id: int, detail: dict[str, Any] | None = None, all_clips: bool = False
    ) -> None:
        ref = await self.core.ref("batch", batch_id)
        if not ref or not ref.get("message_id"):
            return
        detail = detail or await self.core.batch(batch_id)
        embed, view = render.batch_summary(detail, self.cfg.approve_all_threshold)
        thread_id = int(ref.get("thread_id") or ref["channel_id"])
        await self.gw.edit(thread_id, int(ref["message_id"]), embed=embed, view=view)
        await self.gw.set_tag(thread_id, render.batch_tag(detail))
        if all_clips:
            shipped = detail["batch"].get("status") == "shipped"
            for rc in detail["clips"]:
                cref = await self.core.ref("clip", rc["clip"]["id"])
                if cref and cref.get("message_id"):
                    e, v = render.clip_message(rc, shipped=shipped)
                    await self.gw.edit(int(cref["channel_id"]), int(cref["message_id"]), embed=e, view=v)

    # ------------------------------------------------------------ questions, alerts, log, Director
    async def question(self, question_id: int) -> None:
        ch = self.cfg.channels.control or self.cfg.channels.alerts
        if not ch or await self.core.ref("question", question_id):
            return
        q = await self.core.question(question_id)
        if q is None:
            return
        embed, view = render.question_message(q)
        mid = await self.gw.send(ch, embed=embed, view=view)
        await self.core.put_ref("question", question_id, ch, mid)

    async def refresh_question(self, question_id: int) -> None:
        ref = await self.core.ref("question", question_id)
        q = await self.core.question(question_id)
        if not ref or not ref.get("message_id") or q is None:
            return
        embed, view = render.question_message(q)
        await self.gw.edit(int(ref["channel_id"]), int(ref["message_id"]), embed=embed, view=view)

    async def alert(self, level: str, text: str, source: str) -> None:
        if self.cfg.channels.alerts:
            await self.gw.send(self.cfg.channels.alerts, embed=render.alert_message(level, text, source))

    async def published(self, p: dict[str, Any]) -> None:
        if not self.cfg.channels.published or await self.core.ref("post", p["post_id"]):
            return
        mid = await self.gw.send(self.cfg.channels.published, embed=render.published_message(p))
        await self.core.put_ref("post", p["post_id"], self.cfg.channels.published, mid)

    async def director_reply(self, p: dict[str, Any]) -> None:
        if p.get("kind") != "message" or p.get("session_id") is None:
            return
        sid = int(p["session_id"])
        if sid not in self.roles:
            self.roles[sid] = str((await self.core.session(sid))["session"]["role"])
        if self.roles[sid] != "director":
            return
        target = self.last_chat_thread or self.cfg.channels.control
        if target and p.get("summary"):
            await self.gw.send(target, content=str(p["summary"])[:2000])
