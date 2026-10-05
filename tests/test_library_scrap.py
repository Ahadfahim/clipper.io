"""Scrapping clips: the rules, the locks that keep a scrapped clip from ever being posted, restore, purge."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import col, select

from clipper.agents.access import fq
from clipper.agents.guard_context import DbGuardContext
from clipper.agents.hooks import Guard, ToolCall
from clipper.clock import FakeClock, utcnow
from clipper.core import Core
from clipper.db.engine import WriteTx
from clipper.db.models import Clip, Edl, Job, Moment, Post, Review, ReviewBatch
from clipper.events.bus import EventEnvelope
from clipper.media.edl.ops import EditError
from clipper.services.base import ServiceError
from clipper.supervisor.messages import describe
from clipper.supervisor.router import compact, route
from tests.conftest import tune
from tests.factories import approve, make_account, make_campaign, make_clip, make_source


@pytest.fixture
def core_t(settings: Any) -> Any:
    clock = FakeClock(utcnow())
    c = Core.create(settings, fakes=True, clock=clock)
    c.test_clock = clock  # type: ignore[attr-defined]
    yield c
    c.close()


def _clip(core: Core, camp_id: int, src_id: int, **kw: Any) -> int:
    clip = make_clip(core.db, camp_id, src_id, **kw)
    assert clip.id is not None
    return clip.id


def _files(core: Core, clip_id: int, version: int = 1) -> list[Path]:
    """The files a rendered clip leaves behind."""
    made: list[Path] = []
    for folder, name in (
        ("previews", f"clip_{clip_id}_v{version}.mp4"),
        ("previews", f"clip_{clip_id}_v{version}.jpg"),
        ("previews", f"clip_{clip_id}_v{version}_discord.mp4"),
        ("clips", f"clip_{clip_id}_v{version}_final.mp4"),
    ):
        path = core.dir(folder) / name
        path.write_bytes(b"x" * 1000)
        made.append(path)
    work = core.dir("work") / f"clip_{clip_id}_v{version}"
    work.mkdir(exist_ok=True)
    (work / "part.bin").write_bytes(b"y" * 500)
    made.append(work)
    return made


def _setup(core: Core) -> tuple[int, int]:
    camp = make_campaign(core.db, status="active")
    src = make_source(core.db, camp.id or 0)
    return camp.id or 0, src.id or 0


def _add(core: Core, obj: Any) -> int:
    def job(tx: WriteTx) -> int:
        tx.add(obj)
        tx.flush()
        return int(obj.id) if getattr(obj, "id", None) is not None else 0

    return core.db.write(job)


def _clip_row(core: Core, clip_id: int) -> Clip:
    with core.db.read() as s:
        c = s.get(Clip, clip_id)
        assert c is not None
        return c


# ---------------------------------------------------------------- the rules


def test_checks_say_what_can_and_cannot_be_scrapped(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    ready = _clip(core, camp, src, status="ready")
    posted = _clip(core, camp, src, status="posted")
    scheduled = _clip(core, camp, src, status="approved")
    posting = _clip(core, camp, src, status="approved")
    running = _clip(core, camp, src, status="rendering")
    acct = make_account(core.db)

    def posts(tx: WriteTx) -> None:
        now = core.clock.now()
        tx.add(
            Post(
                clip_id=posted,
                account_id=acct.id or 0,
                campaign_id=camp,
                platform="youtube",
                scheduled_at=now,
                status="live",
            )
        )
        tx.add(
            Post(
                clip_id=scheduled,
                account_id=acct.id or 0,
                campaign_id=camp,
                platform="youtube",
                scheduled_at=now,
                status="scheduled",
            )
        )
        tx.add(
            Post(
                clip_id=posting,
                account_id=acct.id or 0,
                campaign_id=camp,
                platform="youtube",
                scheduled_at=now,
                status="posting",
            )
        )
        tx.add(
            Job(kind="render_preview", input_json={"clip_id": running}, status="running", campaign_id=camp)
        )

    core.db.write(posts)
    by = {
        c.id: c
        for c in core.library.check([ready, posted, scheduled, posting, running], include_variants=False)
    }
    assert by[ready].can_scrap and by[ready].blocked_reason is None
    assert not by[posted].can_scrap and "Hide it instead" in (by[posted].blocked_reason or "")
    assert by[scheduled].can_scrap and len(by[scheduled].scheduled_posts) == 1
    assert not by[posting].can_scrap and "upload of this clip is running" in (
        by[posting].blocked_reason or ""
    )
    assert not by[running].can_scrap and "render of this clip is running" in (
        by[running].blocked_reason or ""
    )
    assert not core.library.check([999])[0].can_scrap


def test_scrapping_throws_a_clip_away_but_keeps_what_is_needed_to_bring_it_back(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    clip_id = _clip(core, camp, src, status="ready")
    seen: list[EventEnvelope] = []
    core.bus.add_listener(seen.append, types=["clip.scrapped"])

    res = core.library.scrap([clip_id], reason="weak hook")

    assert res["scrapped"] == [clip_id] and res["refused"] == []
    clip = _clip_row(core, clip_id)
    assert clip.status == "scrapped" and clip.scrap_reason == "weak hook" and clip.scrapped_at is not None
    assert clip.scrap_json["status"] == "ready"
    with core.db.read() as s:
        review = s.get(Review, clip_id)
        moment = s.get(Moment, clip.moment_id)
    assert review is not None and review.decision == "rejected" and review.reason == "scrapped: weak hook"
    assert review.via == "dashboard" and review.reviewer == "user"
    assert moment is not None and moment.scrapped
    assert seen[0].payload["clip_ids"] == [clip_id] and seen[0].payload["reason"] == "weak hook"
    # an agent that was editing it stops: the clip is locked
    assert core.library.scrap([clip_id])["refused"][0]["reason"] == "already scrapped"


def test_a_pending_clip_in_a_batch_no_longer_holds_the_batch_up(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    keep, drop = _clip(core, camp, src, status="in_review"), _clip(core, camp, src, status="in_review")
    batch = _add(core, ReviewBatch(campaign_id=camp))

    def reviews(tx: WriteTx) -> None:
        tx.add(Review(clip_id=keep, batch_id=batch, decision="approved", via="dashboard", reviewer="you"))
        tx.add(Review(clip_id=drop, batch_id=batch, decision="pending"))

    core.db.write(reviews)
    core.library.scrap([drop])
    with core.db.read() as s:
        assert [
            r.decision
            for r in s.exec(
                select(Review).where(Review.batch_id == batch).order_by(col(Review.clip_id))
            ).all()
        ] == ["approved", "rejected"]
    assert core.library.check([drop])[0].in_batch is None  # decided now


def test_scheduled_posts_are_cancelled_only_when_you_say_so(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    clip_id = _clip(core, camp, src, status="approved")
    approve(core.db, clip_id)
    acct = make_account(core.db)
    post_id = _add(
        core,
        Post(
            clip_id=clip_id,
            account_id=acct.id or 0,
            campaign_id=camp,
            platform="youtube",
            scheduled_at=core.clock.now() + timedelta(hours=2),
            status="scheduled",
        ),
    )
    refused = core.library.scrap([clip_id])
    assert refused["scrapped"] == [] and "scheduled post" in refused["refused"][0]["reason"]
    assert _clip_row(core, clip_id).status == "approved"
    done = core.library.scrap([clip_id], cancel_posts=True)
    assert done["scrapped"] == [clip_id]
    with core.db.read() as s:
        post = s.get(Post, post_id)
    assert post is not None and post.status == "cancelled"


def test_hook_variants_come_along_by_default(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    base = _clip(core, camp, src, status="ready")
    variant = _clip(core, camp, src, status="draft", variant_of=base)
    assert core.library.check([base])[0].variants == [variant]
    assert sorted(core.library.scrap([base])["scrapped"]) == sorted([base, variant])
    other = _clip(core, camp, src, status="ready")
    other_variant = _clip(core, camp, src, status="draft", variant_of=other)
    assert core.library.scrap([other], include_variants=False)["scrapped"] == [other]
    assert _clip_row(core, other_variant).status == "draft"


def test_queued_renders_of_a_scrapped_clip_are_cancelled(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    clip_id = _clip(core, camp, src, status="rendering")
    job_id = _add(
        core, Job(kind="render_preview", input_json={"clip_id": clip_id}, status="queued", campaign_id=camp)
    )
    core.library.scrap([clip_id])
    with core.db.read() as s:
        job = s.get(Job, job_id)
    assert job is not None and job.status == "cancelled"


# ---------------------------------------------------------------- it can never be published


def test_a_scrapped_clip_cannot_be_scheduled_edited_rendered_or_cut_again(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    clip_id = _clip(core, camp, src, status="approved", path="C:/fake.mp4")
    approve(core.db, clip_id)  # even a human approval can't revive a scrapped clip
    acct = make_account(core.db)
    core.library.scrap([clip_id])
    core.db.write(
        lambda tx: setattr(tx.session.get(Clip, clip_id), "status", "scrapped")
    )  # approve() didn't touch it
    # the guard
    guard = Guard(DbGuardContext(core.db, core.settings, core.clock))
    call = ToolCall(
        fq("publish", "schedule_post"),
        {
            "clip_id": clip_id,
            "account_id": acct.id,
            "scheduled_at": (core.clock.now() + timedelta(hours=1)).isoformat(),
        },
        role="campaign",
        session_id=None,
        campaign_id=camp,
    )
    verdict = guard.check(call)
    assert not verdict.allowed and verdict.rule == "approval" and "scrapped" in verdict.reason
    # the service and the atomic scheduler
    with pytest.raises(ServiceError, match="scrapped"):
        core.publishing.schedule(clip_id, acct.id or 0, "now")
    from clipper.services.posting import schedule_post_tx

    res = core.db.write(
        lambda tx: schedule_post_tx(
            tx,
            clip_id=clip_id,
            account_id=acct.id or 0,
            scheduled_at=core.clock.now(),
            settings=core.settings,
        )
    )
    assert not isinstance(res, Post) and "scrapped" in res.reason
    # edits, renders and re-cuts
    with pytest.raises(ServiceError, match="scrapped"):
        core.media.request_final(clip_id)
    with pytest.raises(ServiceError, match="scrapped"):
        core.media.request_preview(clip_id)
    with core.db.read() as s:
        moment_id = s.get(Clip, clip_id).moment_id  # type: ignore[union-attr]
    with pytest.raises(ServiceError, match="scrapped a clip of this moment"):
        core.media.render_moment(moment_id)


def test_a_post_scheduled_before_the_scrap_is_cancelled_instead_of_uploaded(core_t: Core) -> None:
    import asyncio

    core = core_t
    camp, src = _setup(core)
    clip_id = _clip(core, camp, src, status="approved", path="C:/fake.mp4")
    acct = make_account(core.db)
    post_id = _add(
        core,
        Post(
            clip_id=clip_id,
            account_id=acct.id or 0,
            campaign_id=camp,
            platform="youtube",
            scheduled_at=core.clock.now() - timedelta(minutes=1),
            status="scheduled",
        ),
    )
    core.db.write(
        lambda tx: setattr(tx.session.get(Clip, clip_id), "status", "scrapped")
    )  # scrapped by some other path
    asyncio.run(core.publishing.run_due())
    with core.db.read() as s:
        post = s.get(Post, post_id)
    assert post is not None and post.status == "cancelled" and post.error == "the clip was scrapped"


def test_editing_a_scrapped_clip_is_refused(core_t: Core) -> None:
    from clipper.media.edl.schema import new_edl
    from tests.media.conftest import talk_source

    core = core_t
    camp, src = _setup(core)
    clip_id = _clip(core, camp, src, status="ready")
    core.edl.init(clip_id, new_edl(talk_source(), 0.0, 8.0), actor="system")
    core.edl.apply(clip_id, "trim", {"start": 1.0, "end": 6.0}, actor="user")
    core.library.scrap([clip_id])
    with pytest.raises(EditError, match="scrapped"):
        core.edl.apply(clip_id, "trim", {"start": 0.0, "end": 5.0}, actor="session:1")
    with pytest.raises(EditError, match="scrapped"):
        core.edl.apply(clip_id, "trim", {"start": 0.0, "end": 5.0}, actor="user")
    with core.db.read() as s:
        assert s.get(Edl, clip_id).locked_by == "user"  # type: ignore[union-attr]
    core.library.restore([clip_id])
    with core.db.read() as s:
        assert s.get(Edl, clip_id).locked_by is None  # type: ignore[union-attr]
    core.edl.apply(clip_id, "trim", {"start": 0.0, "end": 5.0}, actor="user")


# ---------------------------------------------------------------- the agents learn from it


async def test_the_campaign_agent_hears_about_it_and_the_reason_counts_as_a_rejection(core_t: Core) -> None:
    import json

    from tests.conftest import call

    core = core_t
    camp, src = _setup(core)
    clip_id = _clip(core, camp, src, status="ready")
    seen: list[EventEnvelope] = []
    core.bus.add_listener(seen.append, types=["clip.scrapped"])
    core.library.scrap([clip_id], reason="bad framing")
    specs = route(seen[0], session_of=lambda _s: None, clip_campaign=lambda _c: None)
    assert [(s.priority, s.role, s.campaign_id) for s in specs] == [(2, "campaign", camp)]
    text = describe(compact(seen[0]))
    assert f"scrapped clips {clip_id}" in text and "bad framing" in text and "Don't re-cut" in text
    # the editor's learning examples include it, with the reason, as a rejected clip
    res = await call(core, "state", "get_learning_examples", {"campaign_id": camp})
    examples = json.loads(res.content[0]["text"])
    assert [e["reason"] for e in examples["rejected"]] == ["scrapped: bad framing"]


# ---------------------------------------------------------------- restore


def test_restore_puts_back_the_status_and_the_decision(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    approved = _clip(core, camp, src, status="approved")
    approve(core.db, approved, via="dashboard", reviewer="you")
    unreviewed = _clip(core, camp, src, status="ready")
    core.library.scrap([approved, unreviewed], reason="x", cancel_posts=True)
    res = core.library.restore([approved, unreviewed, 999])
    assert sorted(res["restored"]) == sorted([approved, unreviewed]) and res["refused"][0]["id"] == 999
    assert _clip_row(core, approved).status == "approved" and _clip_row(core, unreviewed).status == "ready"
    with core.db.read() as s:
        back = s.get(Review, approved)
        none = s.get(Review, unreviewed)
        moment = s.get(Moment, _clip_row(core, approved).moment_id)
    assert back is not None and back.decision == "approved" and back.via == "dashboard"
    assert none is None  # it had no review before the scrap
    assert moment is not None and not moment.scrapped
    assert _clip_row(core, approved).scrapped_at is None


# ---------------------------------------------------------------- purge


def test_purge_deletes_exactly_the_clips_files_and_keeps_the_thumbnail(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    gone = _clip(core, camp, src, status="ready")
    other = _clip(core, camp, src, status="ready")
    gone_files, other_files = _files(core, gone), _files(core, other)
    _files(core, gone, version=2)  # an old version's files go too
    thumb = core.dir("previews") / f"clip_{gone}_v1.jpg"
    core.db.write(lambda tx: setattr(tx.session.get(Clip, gone), "thumb_path", str(thumb)))
    decoy = core.dir("previews") / f"clip_{gone}0_v1.mp4"  # clip 10's file, not clip 1's
    decoy.write_bytes(b"z")
    source = core.dir("sources") / "campaign_1" / f"clip_{gone}_v1.mp4"  # a source video that looks the same
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"s")
    core.library.scrap([gone])
    seen: list[EventEnvelope] = []
    core.bus.add_listener(seen.append, types=["clip.purged"])

    res = core.library.purge([gone])

    assert res["clips"] == [gone] and res["bytes"] > 0
    assert thumb.exists()
    assert not any(p.exists() for p in gone_files if p != thumb)
    assert all(p.exists() for p in other_files) and decoy.exists() and source.exists()
    assert not (core.dir("work") / f"clip_{gone}_v2").exists()
    assert seen[0].payload["bytes_freed"] == res["bytes"]
    clip = _clip_row(core, gone)
    assert clip.files_purged_at is not None and clip.path is None and clip.preview_path is None
    assert core.library.purge([gone]) == {"clips": [], "bytes": 0}  # running it twice changes nothing
    refused = core.library.restore([gone])
    assert refused["restored"] == [] and refused["refused"][0]["reason"] == "This clip's files were deleted."


def test_files_wait_out_the_grace_period_and_the_daily_job_runs_once_a_day(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    clip_id = _clip(core, camp, src, status="ready")
    files = _files(core, clip_id)
    core.library.scrap([clip_id])
    assert core.library.purge(expired_only=True)["clips"] == []  # too soon
    assert all(p.exists() for p in files)
    core.test_clock.advance(timedelta(days=6, hours=23))  # type: ignore[attr-defined]
    assert core.library.purge_expired_daily() is not None
    assert all(p.exists() for p in files)  # run, but nothing was due
    assert core.library.purge_expired_daily() is None  # once per day
    core.test_clock.advance(timedelta(days=1))  # type: ignore[attr-defined]
    res = core.library.purge_expired_daily()
    assert res is not None and res["clips"] == [clip_id]
    assert not any(p.exists() for p in files if p.suffix != ".jpg")


def test_the_grace_period_is_a_setting(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    clip_id = _clip(core, camp, src, status="ready")
    files = _files(core, clip_id)
    tune(core, "retention", scrapped_clip_days=0)
    core.library.scrap([clip_id])
    assert core.library.purge(expired_only=True)["clips"] == [clip_id]
    assert not files[0].exists()


def test_purge_never_touches_a_path_outside_the_data_folders(core_t: Core, tmp_path: Path) -> None:
    core = core_t
    outside = tmp_path / "elsewhere" / "clip_1_v1.mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"precious")
    assert core.library._delete(outside) == 0  # pyright: ignore[reportPrivateUsage]
    assert outside.exists()
    assert core.library._delete(core.dir("previews")) == 0  # pyright: ignore[reportPrivateUsage]  # a root itself


def test_old_versions_lose_their_render_files_but_the_clip_stays(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    clip_id = _clip(core, camp, src, status="ready", version=3)
    v1, v3 = _files(core, clip_id, 1), _files(core, clip_id, 3)
    res = core.library.purge_old_versions([clip_id])
    assert res["clips"] == [clip_id] and res["bytes"] > 0
    assert not v1[0].exists() and v1[1].exists()  # the old version's thumbnail stays
    assert all(p.exists() for p in v3)
    assert _clip_row(core, clip_id).status == "ready"


# ---------------------------------------------------------------- hide and clean up


def test_posted_clips_are_hidden_not_scrapped(core_t: Core) -> None:
    core = core_t
    camp, src = _setup(core)
    posted = _clip(core, camp, src, status="posted")
    scrapped = _clip(core, camp, src, status="ready")
    core.library.scrap([scrapped])
    assert core.library.hide([posted, scrapped], True) == [posted]
    assert _clip_row(core, posted).hidden and not _clip_row(core, scrapped).hidden
    core.library.hide([posted], False)
    assert not _clip_row(core, posted).hidden


def test_cleanup_groups_what_is_worth_throwing_away_with_its_size(core_t: Core) -> None:
    core = core_t
    ended = make_campaign(core.db, status="skipped", external_id="e")
    live = make_campaign(core.db, status="active", external_id="l")
    s_end, s_live = make_source(core.db, ended.id or 0), make_source(core.db, live.id or 0)
    stale = [_clip(core, ended.id or 0, s_end.id or 0, status="ready") for _ in range(2)]
    approved = _clip(core, ended.id or 0, s_end.id or 0, status="approved")  # a decision was made: leave it
    failed = _clip(core, live.id or 0, s_live.id or 0, status="failed")
    versions = _clip(core, live.id or 0, s_live.id or 0, status="ready", version=2)
    old_reject = _clip(core, live.id or 0, s_live.id or 0, status="rejected")
    core.db.write(
        lambda tx: tx.add(
            Review(
                clip_id=old_reject,
                decision="rejected",
                decided_at=core.clock.now() - timedelta(days=20),
                via="dashboard",
                reviewer="you",
            )
        )
    )
    for cid in (*stale, approved, failed, old_reject):
        _files(core, cid)
    _files(core, versions, 1)
    _files(core, versions, 2)
    groups = {g.key: g for g in core.library.cleanup_groups()}
    assert groups["ended_unreviewed"].clip_ids == stale and groups["ended_unreviewed"].bytes > 3000
    assert approved not in groups["ended_unreviewed"].clip_ids
    assert groups["failed_renders"].clip_ids == [failed]
    assert groups["old_rejected"].clip_ids == [old_reject]
    assert groups["old_versions"].clip_ids == [versions] and groups["old_versions"].action == "delete_files"
    assert groups["ended_unreviewed"].action == "scrap"
    stale_bytes = groups["ended_unreviewed"].bytes
    core.library.scrap(stale)
    assert "ended_unreviewed" not in {g.key for g in core.library.cleanup_groups()}
    assert stale_bytes == sum(core.library.clip_bytes(c) for c in stale)
