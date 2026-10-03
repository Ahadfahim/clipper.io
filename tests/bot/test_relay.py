"""Core events → Discord messages, with a fake gateway recording every call."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import discord

from clipper_bot.config import BotConfig
from clipper_bot.relay import Relay
from tests.bot.conftest import REVIEWER, CoreEnv


@dataclass
class Sent:
    channel: int
    id: int
    content: str | None
    embed: discord.Embed | None
    view: discord.ui.View | None
    file: Path | None


@dataclass
class FakeGateway:
    sent: list[Sent] = field(default_factory=list)
    posts: list[dict[str, Any]] = field(default_factory=list)
    edits: list[tuple[int, int, discord.Embed | None, discord.ui.View | None, Path | None]] = field(
        default_factory=list
    )
    pins: list[tuple[int, int]] = field(default_factory=list)
    tags: dict[int, str] = field(default_factory=dict)
    next_id: int = 1000

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    async def send(
        self,
        channel_id: int,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
        file: Path | None = None,
    ) -> int:
        mid = self._id()
        self.sent.append(Sent(channel_id, mid, content, embed, view, file))
        return mid

    async def create_forum_post(
        self, forum_id: int, *, name: str, embed: discord.Embed, view: discord.ui.View, tag: str
    ) -> tuple[int, int]:
        thread, starter = self._id(), self._id()
        self.posts.append(
            {
                "forum": forum_id,
                "name": name,
                "embed": embed,
                "view": view,
                "thread": thread,
                "starter": starter,
            }
        )
        self.tags[thread] = tag
        return thread, starter

    async def edit(
        self,
        channel_id: int,
        message_id: int,
        *,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
        file: Path | None = None,
    ) -> None:
        self.edits.append((channel_id, message_id, embed, view, file))

    async def pin(self, channel_id: int, message_id: int) -> None:
        self.pins.append((channel_id, message_id))

    async def set_tag(self, thread_id: int, tag: str) -> None:
        self.tags[thread_id] = tag


def ev(type_: str, **payload: Any) -> dict[str, Any]:
    return {"id": 1, "type": type_, "payload": payload}


async def test_batch_posted_creates_forum_post_with_one_message_per_clip(
    core_env: CoreEnv, cfg: BotConfig
) -> None:
    gw = FakeGateway()
    relay = Relay(core_env.client, gw, cfg)
    batch = core_env.ids["batch"]
    await relay.handle(ev("review.batch_posted", batch_id=batch, campaign_id=1, clip_ids=[]))
    assert len(gw.posts) == 1
    post = gw.posts[0]
    assert post["forum"] == cfg.channels.clip_review and "batch" in post["name"]
    assert post["embed"].description.startswith("Reviewed 7/12")
    assert gw.tags[post["thread"]] == "in review"
    assert gw.pins == [(post["thread"], post["starter"])]
    clips = [s for s in gw.sent if s.channel == post["thread"]]
    assert len(clips) == 12
    scores = [int(str(next(f.value for f in s.embed.fields if f.name == "Score"))) for s in clips if s.embed]
    assert scores == sorted(scores, reverse=True)
    assert any(s.file is not None for s in clips)  # the rendered preview is uploaded when present
    # idempotent: a replayed event doesn't post twice
    await relay.handle(ev("review.batch_posted", batch_id=batch, campaign_id=1, clip_ids=[]))
    assert len(gw.posts) == 1


async def test_dashboard_decision_updates_the_clip_message_and_summary(
    core_env: CoreEnv, cfg: BotConfig
) -> None:
    gw = FakeGateway()
    relay = Relay(core_env.client, gw, cfg)
    batch = core_env.ids["batch"]
    await relay.handle(ev("review.batch_posted", batch_id=batch, campaign_id=1, clip_ids=[]))
    detail = await core_env.client.batch(batch)
    cid = next(c["clip"]["id"] for c in detail["clips"] if c["decision"] == "pending")
    await core_env.client._req(
        "POST",
        f"/api/review/clips/{cid}/decision",
        json={"decision": "approved", "reviewer": "you", "via": "dashboard"},
    )
    await relay.handle(
        ev("review.decided", clip_id=cid, batch_id=batch, decision="approved", via="dashboard")
    )
    clip_msg = next(s for s in gw.sent if s.embed and s.embed.title and s.embed.title.startswith(f"#{cid} "))
    edited = [e for e in gw.edits if e[1] == clip_msg.id]
    assert (
        edited
        and edited[-1][2] is not None
        and "Approved by you via the app" in (edited[-1][2].footer.text or "")
    )
    summary = [e for e in gw.edits if e[1] == gw.posts[0]["starter"]]
    assert (
        summary
        and summary[-1][2] is not None
        and (summary[-1][2].description or "").startswith("Reviewed 8/12")
    )


async def test_shipped_disables_every_clip_and_tags_the_post(core_env: CoreEnv, cfg: BotConfig) -> None:
    gw = FakeGateway()
    relay = Relay(core_env.client, gw, cfg)
    batch = core_env.ids["batch"]
    await relay.handle(ev("review.batch_posted", batch_id=batch, campaign_id=1, clip_ids=[]))
    await core_env.client.ship(batch, reviewer=REVIEWER.name)
    await relay.handle(
        ev("review.shipped", batch_id=batch, campaign_id=1, approved=[], rejected=[], via="discord")
    )
    thread = gw.posts[0]["thread"]
    assert gw.tags[thread] == "shipped"
    clip_edits = [e for e in gw.edits if e[0] == thread and e[1] != gw.posts[0]["starter"]]
    assert len(clip_edits) == 12
    assert all(
        all(getattr(c, "disabled", False) for c in (e[3].children if e[3] else [])) for e in clip_edits
    )


async def test_campaign_card_question_alert_publish_and_director(core_env: CoreEnv, cfg: BotConfig) -> None:
    gw = FakeGateway()
    relay = Relay(core_env.client, gw, cfg)
    await relay.handle(ev("review.campaign_card", campaign_id=3, score=81, reasoning="Strong podcast fit"))
    card = gw.sent[-1]
    assert (
        card.channel == cfg.channels.campaigns
        and card.embed
        and card.embed.description == "Strong podcast fit"
    )
    assert card.view is not None
    assert [getattr(c, "custom_id", None) for c in card.view.children][:2] == [
        "clipper:campaign:take:3",
        "clipper:campaign:skip:3",
    ]  # type: ignore[union-attr]
    await core_env.client.take(3)
    await relay.handle(ev("campaign.taken", campaign_id=3, by="user", via="discord"))
    edited_view = gw.edits[-1][3]
    assert gw.edits[-1][1] == card.id and edited_view is not None
    assert all(c.disabled for c in edited_view.children if isinstance(c, discord.ui.Button) and c.custom_id)

    q = next(q for q in await core_env.client._req("GET", "/api/questions") if q["status"] == "open")
    await relay.handle(ev("question.asked", question_id=q["id"], text=q["text"], options=q["options"]))
    qmsg = gw.sent[-1]
    assert qmsg.channel == cfg.channels.control and len(qmsg.view.children) == len(q["options"])  # type: ignore[union-attr]

    await relay.handle(ev("alert", level="info", text="fyi", source="x"))
    await relay.handle(ev("alert", level="error", text="TikTok upload failed", source="publish"))
    assert (
        gw.sent[-1].channel == cfg.channels.alerts
        and gw.sent[-1].embed
        and "TikTok upload failed" in (gw.sent[-1].embed.description or "")
    )
    assert sum(1 for s in gw.sent if s.channel == cfg.channels.alerts) == 1  # info alerts stay in the app

    await relay.handle(
        ev(
            "post.live",
            post_id=99,
            clip_id=1,
            campaign_id=1,
            platform="youtube",
            url="https://youtube.com/shorts/x",
            dry_run=True,
        )
    )
    assert gw.sent[-1].channel == cfg.channels.published and (gw.sent[-1].embed.footer.text or "").startswith(
        "Dry run"
    )  # type: ignore[union-attr]

    # #control: the Director's reply goes to the thread the question came from
    await relay.handle(ev("user.chat", text="status?", via="discord", reply_to="4242"))
    director = next(
        s for s in (await core_env.client._req("GET", "/api/agents/sessions")) if s["role"] == "director"
    )
    await relay.handle(
        ev(
            "agent.event",
            session_id=director["id"],
            agent_event_id=1,
            kind="message",
            tool=None,
            summary="All good: 1 agent running.",
        )
    )
    assert gw.sent[-1].channel == 4242 and gw.sent[-1].content == "All good: 1 agent running."
    campaign_session = next(
        s for s in (await core_env.client._req("GET", "/api/agents/sessions")) if s["role"] == "campaign"
    )
    n = len(gw.sent)
    await relay.handle(
        ev(
            "agent.event",
            session_id=campaign_session["id"],
            agent_event_id=2,
            kind="message",
            tool=None,
            summary="internal",
        )
    )
    assert len(gw.sent) == n  # only the Director talks in #control
