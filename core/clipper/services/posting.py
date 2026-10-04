"""Atomic post scheduling: cap check + insert inside one writer job (PLAN §17.3)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import col, select

from clipper.db.engine import WriteTx
from clipper.db.models import Account, Post
from clipper.db.types import CAP_COUNTED_POST_STATUSES, PostStatus
from clipper.events.types import PostScheduled
from clipper.rules.caps import AccountCaps, CapDecision, check_post_slot
from clipper.settings import Settings


def account_caps(account: Account) -> AccountCaps:
    assert account.id is not None
    return AccountCaps(account.id, account.daily_cap, account.min_gap_min, account.warmup_started)


def counted_post_times(tx: WriteTx, account_id: int, around: datetime) -> list[datetime]:
    window_start, window_end = around - timedelta(days=2), around + timedelta(days=2)
    rows = tx.session.exec(
        select(Post.scheduled_at).where(
            Post.account_id == account_id,
            col(Post.status).in_(list(CAP_COUNTED_POST_STATUSES)),
            col(Post.scheduled_at) >= window_start,
            col(Post.scheduled_at) < window_end,
        )
    ).all()
    return list(rows)


def schedule_post_tx(
    tx: WriteTx,
    *,
    clip_id: int,
    account_id: int,
    scheduled_at: datetime,
    settings: Settings,
    campaign_id: int | None = None,
    copy: dict[str, str] | None = None,
    dry_run: bool = False,
    created_by: str | None = None,
) -> Post | CapDecision:
    """Runs on the writer thread: nothing else can insert a post between the check and the insert."""
    account = tx.session.get(Account, account_id)
    if account is None:
        return CapDecision(False, f"account {account_id} not found", 0, 0)
    decision = check_post_slot(
        account_caps(account),
        counted_post_times(tx, account_id, scheduled_at),
        scheduled_at,
        settings.posting,
        settings.triggers.timezone,
    )
    if not decision.ok:
        return decision
    post = Post(
        clip_id=clip_id,
        account_id=account_id,
        campaign_id=campaign_id,
        platform=account.platform,
        scheduled_at=scheduled_at,
        status=PostStatus.SCHEDULED,
        copy_json=dict(copy or {}),
        dry_run=dry_run,
        created_by=created_by,
    )
    tx.add(post)
    tx.flush()
    assert post.id is not None
    tx.publish(
        PostScheduled(
            post_id=post.id,
            clip_id=clip_id,
            account_id=account_id,
            platform=account.platform,
            scheduled_at=scheduled_at.isoformat(),
            dry_run=dry_run,
        )
    )
    return post
