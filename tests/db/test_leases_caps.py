from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from sqlmodel import col, select

from clipper.clock import FakeClock
from clipper.db.engine import Database
from clipper.db.models import Post
from clipper.leases import LeaseManager, campaign_resource
from clipper.rules.caps import AccountCaps, CapDecision, check_post_slot, effective_daily_cap
from clipper.services.posting import schedule_post_tx
from clipper.settings import PostingSettings, Settings
from tests.factories import make_account, make_campaign, make_clip, make_source

NOON = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)  # 12:00 in New York
TZ = "America/New_York"


# ------------------------------------------------------------------ leases


def test_lease_acquire_conflict_expiry_renew_release(db: Database, clock: FakeClock) -> None:
    leases = LeaseManager(db, clock)
    res = campaign_resource(1)
    assert leases.acquire(res, "session:1", ttl_s=60)
    assert leases.acquire(res, "session:1", ttl_s=60)  # re-entrant for the holder
    assert not leases.acquire(res, "session:2", ttl_s=60)
    assert leases.holder(res) == "session:1"
    clock.advance(seconds=30)
    assert leases.renew(res, "session:1", ttl_s=60)
    clock.advance(seconds=45)
    assert leases.holder(res) == "session:1"  # renewed, not expired yet
    clock.advance(seconds=20)
    assert leases.holder(res) is None
    assert not leases.renew(res, "session:1", ttl_s=60)  # expired leases can't be renewed
    assert leases.acquire(res, "session:2", ttl_s=60)  # expired -> anyone can take it
    assert not leases.release(res, "session:1")
    assert leases.release(res, "session:2")
    assert leases.holder(res) is None


def test_lease_race_has_exactly_one_winner(db: Database, clock: FakeClock) -> None:
    leases = LeaseManager(db, clock)
    winners: list[str] = []
    lock = threading.Lock()

    def contender(name: str) -> None:
        if leases.acquire("profile:main", name, ttl_s=300):
            with lock:
                winners.append(name)

    threads = [threading.Thread(target=contender, args=(f"session:{i}",)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1


def test_sweep_removes_expired(db: Database, clock: FakeClock) -> None:
    leases = LeaseManager(db, clock)
    leases.acquire("clip:1", "user", ttl_s=10)
    leases.acquire("clip:2", "user", ttl_s=1000)
    clock.advance(seconds=11)
    assert leases.sweep() == 1
    assert leases.holder("clip:2") == "user"


# ------------------------------------------------------------------ cap rules (pure)


def _acct(**kw: object) -> AccountCaps:
    base: dict[str, object] = {
        "account_id": 1,
        "daily_cap": None,
        "min_gap_min": None,
        "warmup_started": None,
    }
    base.update(kw)
    return AccountCaps(**base)  # type: ignore[arg-type]


def test_warmup_caps_by_week() -> None:
    posting = PostingSettings()
    start = NOON - timedelta(days=2)
    assert effective_daily_cap(_acct(warmup_started=start), NOON, posting) == 1
    assert effective_daily_cap(_acct(warmup_started=NOON - timedelta(days=9)), NOON, posting) == 2
    assert effective_daily_cap(_acct(warmup_started=NOON - timedelta(days=15)), NOON, posting) == 3
    assert effective_daily_cap(_acct(daily_cap=5), NOON, posting) == 5
    assert effective_daily_cap(_acct(daily_cap=5, warmup_started=start), NOON, posting) == 1


def test_daily_cap_counts_only_the_local_day() -> None:
    posting = PostingSettings()
    yesterday = [NOON - timedelta(days=1, hours=h) for h in (0, 3, 6)]
    assert check_post_slot(_acct(), yesterday, NOON, posting, TZ).ok
    today = [NOON - timedelta(hours=h) for h in (3, 6, 9)]  # 09:00, 06:00, 03:00 local
    decision = check_post_slot(_acct(), today, NOON, posting, TZ)
    assert not decision.ok
    assert "daily cap" in decision.reason
    assert (decision.used, decision.cap) == (3, 3)


def test_min_gap_between_posts() -> None:
    posting = PostingSettings()
    decision = check_post_slot(_acct(), [NOON - timedelta(minutes=90)], NOON, posting, TZ)
    assert not decision.ok
    assert "at least 120 min apart" in decision.reason
    assert check_post_slot(_acct(), [NOON - timedelta(minutes=120)], NOON, posting, TZ).ok
    assert check_post_slot(_acct(min_gap_min=60), [NOON - timedelta(minutes=90)], NOON, posting, TZ).ok


def test_warmup_reason_mentions_warmup() -> None:
    decision = check_post_slot(
        _acct(warmup_started=NOON - timedelta(days=1)),
        [NOON - timedelta(hours=3)],
        NOON,
        PostingSettings(),
        TZ,
    )
    assert not decision.ok
    assert "warm-up" in decision.reason


# ------------------------------------------------------------------ the cap race


def test_cap_race_two_agents_cannot_take_the_last_slot(db: Database, settings: Settings) -> None:
    camp = make_campaign(db)
    assert camp.id is not None
    src = make_source(db, camp.id)
    assert src.id is not None
    clip = make_clip(db, camp.id, src.id)
    acct = make_account(db, daily_cap=3, min_gap_min=0)
    assert clip.id is not None and acct.id is not None
    clip_id, acct_id = clip.id, acct.id

    results: list[Post | CapDecision] = []
    lock = threading.Lock()
    start = threading.Barrier(20)

    def agent(i: int) -> None:
        at = NOON + timedelta(minutes=i)
        start.wait()
        res = db.write(
            lambda tx: schedule_post_tx(
                tx, clip_id=clip_id, account_id=acct_id, scheduled_at=at, settings=settings
            )
        )
        with lock:
            results.append(res)

    threads = [threading.Thread(target=agent, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    posts = [r for r in results if isinstance(r, Post)]
    denied = [r for r in results if isinstance(r, CapDecision)]
    assert len(posts) == 3
    assert len(denied) == 17
    assert all("daily cap" in d.reason for d in denied)
    with db.read() as s:
        rows = s.exec(select(Post).where(col(Post.account_id) == acct_id)).all()
    assert len(rows) == 3


def test_cap_race_across_two_writer_processes(db: Database, settings: Settings) -> None:
    """Two Database objects on one file stand in for two processes (e.g. a stdio MCP server)."""
    camp = make_campaign(db)
    assert camp.id is not None
    src = make_source(db, camp.id)
    assert src.id is not None
    clip = make_clip(db, camp.id, src.id)
    acct = make_account(db, daily_cap=3, min_gap_min=0)
    assert clip.id is not None and acct.id is not None
    clip_id, acct_id = clip.id, acct.id
    other = Database(db.path)
    results: list[Post | CapDecision] = []
    lock = threading.Lock()
    start = threading.Barrier(16)

    def agent(i: int) -> None:
        target = db if i % 2 else other
        at = NOON + timedelta(minutes=i)
        start.wait()
        res = target.write(
            lambda tx: schedule_post_tx(
                tx, clip_id=clip_id, account_id=acct_id, scheduled_at=at, settings=settings
            )
        )
        with lock:
            results.append(res)

    try:
        threads = [threading.Thread(target=agent, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        other.close()
    assert sum(isinstance(r, Post) for r in results) == 3
