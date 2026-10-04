"""Posting caps, warm-up caps and minimum gap between posts (PLAN §4, §14). Pure functions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from clipper.clock import ensure_utc
from clipper.settings import PostingSettings


@dataclass(frozen=True)
class AccountCaps:
    account_id: int
    daily_cap: int | None
    min_gap_min: int | None
    warmup_started: datetime | None


@dataclass(frozen=True)
class CapDecision:
    ok: bool
    reason: str
    cap: int
    used: int


def effective_daily_cap(account: AccountCaps, at: datetime, posting: PostingSettings) -> int:
    """Warm-up: week 1 -> week1 cap, week 2 -> week2 cap, then the account's (or default) cap.

    ``warmup_started is None`` means the account is established (warm-up not applicable).
    """
    normal = account.daily_cap if account.daily_cap is not None else posting.default_daily_cap
    if account.warmup_started is None:
        return normal
    age = ensure_utc(at) - ensure_utc(account.warmup_started)
    if age < timedelta(days=7):
        return min(normal, posting.warmup.week1_daily_cap)
    if age < timedelta(days=14):
        return min(normal, posting.warmup.week2_daily_cap)
    return normal


def local_day_bounds(at: datetime, tz: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(tz)
    local = ensure_utc(at).astimezone(zone)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return ensure_utc(start), ensure_utc(start + timedelta(days=1))


def check_daily_cap(
    account: AccountCaps,
    existing: Sequence[datetime],
    at: datetime,
    posting: PostingSettings,
    tz: str,
) -> CapDecision:
    cap = effective_daily_cap(account, at, posting)
    day_start, day_end = local_day_bounds(at, tz)
    used = sum(1 for t in existing if day_start <= ensure_utc(t) < day_end)
    if used >= cap:
        warm = " (warm-up)" if cap < (account.daily_cap or posting.default_daily_cap) else ""
        return CapDecision(
            False, f"daily cap reached for account {account.account_id}: {used}/{cap}{warm}", cap, used
        )
    return CapDecision(True, "ok", cap, used)


def check_min_gap(
    account: AccountCaps,
    existing: Sequence[datetime],
    at: datetime,
    posting: PostingSettings,
) -> CapDecision:
    gap = timedelta(minutes=account.min_gap_min if account.min_gap_min is not None else posting.min_gap_min)
    target = ensure_utc(at)
    for t in existing:
        if abs(ensure_utc(t) - target) < gap:
            minutes = int(gap.total_seconds() // 60)
            return CapDecision(
                False,
                f"posts on account {account.account_id} must be at least {minutes} min apart "
                f"(conflicts with {ensure_utc(t).isoformat()})",
                0,
                0,
            )
    return CapDecision(True, "ok", 0, 0)


def check_post_slot(
    account: AccountCaps,
    existing: Sequence[datetime],
    at: datetime,
    posting: PostingSettings,
    tz: str,
) -> CapDecision:
    """Can one more post go out on ``account`` at ``at``, given the already-counted post times?"""
    daily = check_daily_cap(account, existing, at, posting, tz)
    if not daily.ok:
        return daily
    gap = check_min_gap(account, existing, at, posting)
    if not gap.ok:
        return CapDecision(False, gap.reason, daily.cap, daily.used)
    return daily
