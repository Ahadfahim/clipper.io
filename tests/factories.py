"""Row factories for tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from clipper.db.engine import Database, WriteTx
from clipper.db.models import Account, Campaign, Clip, Moment, Review, Source


def make_campaign(db: Database, **kw: Any) -> Campaign:
    def job(tx: WriteTx) -> Campaign:
        c = Campaign(
            marketplace=kw.pop("marketplace", "vyro"),
            external_id=kw.pop("external_id", f"ext-{datetime.now().timestamp()}"),
            title=kw.pop("title", "Test campaign"),
            cpm=kw.pop("cpm", 3.0),
            platforms=kw.pop("platforms", ["youtube", "tiktok", "instagram"]),
            status=kw.pop("status", "active"),
            **kw,
        )
        if c.status == "active" and c.taken_at is None:
            c.taken_at = datetime.now(UTC)
        tx.add(c)
        tx.flush()
        return c

    return db.write(job)


def make_source(db: Database, campaign_id: int, **kw: Any) -> Source:
    def job(tx: WriteTx) -> Source:
        s = Source(campaign_id=campaign_id, url=kw.pop("url", "https://www.youtube.com/watch?v=abc123"), **kw)
        tx.add(s)
        tx.flush()
        return s

    return db.write(job)


def make_clip(db: Database, campaign_id: int, source_id: int, **kw: Any) -> Clip:
    def job(tx: WriteTx) -> Clip:
        m = Moment(
            source_id=source_id,
            campaign_id=campaign_id,
            start=10.0,
            end=40.0,
            final_score=kw.pop("score", 85.0),
        )
        tx.add(m)
        tx.flush()
        assert m.id is not None
        c = Clip(moment_id=m.id, campaign_id=campaign_id, status=kw.pop("status", "ready"), **kw)
        tx.add(c)
        tx.flush()
        return c

    return db.write(job)


def make_account(db: Database, platform: str = "youtube", **kw: Any) -> Account:
    def job(tx: WriteTx) -> Account:
        a = Account(
            platform=platform,
            handle=kw.pop("handle", "@clips"),
            chrome_profile=kw.pop("chrome_profile", "main"),
            **kw,
        )
        tx.add(a)
        tx.flush()
        return a

    return db.write(job)


def approve(db: Database, clip_id: int, via: str = "discord", reviewer: str = "ahad", **kw: Any) -> None:
    def job(tx: WriteTx) -> None:
        tx.add(Review(clip_id=clip_id, decision="approved", via=via, reviewer=reviewer, **kw))

    db.write(job)
