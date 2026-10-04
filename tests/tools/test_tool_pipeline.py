"""Tools end to end on fakes: download -> analysis -> moments -> render -> edit -> review -> schedule -> post -> submit."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from sqlmodel import select

from clipper.core import Core
from clipper.db.models import Account, AgentEvent, Campaign, Post, Submission
from clipper.services.control import set_control
from tests.conftest import call
from tests.factories import make_account

pytestmark = pytest.mark.ffmpeg

YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def data(res: Any) -> dict[str, Any]:
    assert not res.is_error, res.content[0]["text"]
    return json.loads(res.content[0]["text"])


async def _campaign(core: Core) -> int:
    cards = await core.market.list_campaigns("vyro")
    cid = cards["campaigns"][0]["id"]
    core.campaigns.take(cid)
    from clipper.rules.spec import ClipSpec

    core.campaigns.save_spec(
        cid,
        ClipSpec(source_whitelist=[YT], platforms=["youtube", "tiktok"], duration_min_s=5, duration_max_s=60),
    )
    return cid


async def test_media_edit_review_publish_flow(core: Core) -> None:
    cid = await _campaign(core)

    # download is whitelisted and chains analysis
    res = data(
        await call(core, "media", "download", {"campaign_id": cid, "url": "https://youtu.be/dQw4w9WgXcQ"})
    )
    assert res["job_id"]
    blocked = await call(
        core, "media", "download", {"campaign_id": cid, "url": "https://youtu.be/notonlist00"}
    )
    assert blocked.is_error and "source_whitelist" in blocked.content[0]["text"]
    await core.jobs.drain()
    sid = res["source_id"]

    tr = data(
        await call(core, "media", "get_transcript", {"source_id": sid, "from": 0, "to": 10, "max_words": 10})
    )
    assert tr["words"] == 10 and tr["next_from"] is not None and tr["text"].startswith("[0.2]Nobody")
    sig = data(await call(core, "media", "get_signals", {"source_id": sid}))
    assert sig["silences"] >= 4 and sig["heatmap_peaks"][0]["start"] in (4.0, 5.0)
    assert data(await call(core, "media", "get_comments", {"source_id": sid}))["comments"][0][
        "timestamps"
    ] == [4.0]

    frames = await call(core, "media", "frames", {"source_id": sid, "times": [1.0, 5.0]})
    assert not frames.is_error and [c["type"] for c in frames.content] == ["text", "image", "image"]
    ocr = data(await call(core, "media", "ocr_frames", {"source_id": sid, "times": [2.0]}))
    assert "WATERMARK" in ocr["frames"][0]["text"]

    moments = data(
        await call(
            core,
            "state",
            "save_moments",
            {
                "campaign_id": cid,
                "source_id": sid,
                "moments": [{"start": 0.0, "end": 9.5, "hook": "Nobody tells you this", "final_score": 88}],
            },
        )
    )
    rend = data(
        await call(core, "media", "render", {"moment_id": moments["moment_ids"][0], "platform": "tiktok"})
    )
    clip_id = rend["clip_id"]
    await core.jobs.drain()
    clip = data(await call(core, "state", "get_clip", {"clip_id": clip_id}))
    assert (
        clip["status"] == "ready"
        and clip["qa_ok"] is not None
        and clip["duration"] == pytest.approx(9.5, abs=0.1)
    )

    # the cutter edits; every op is logged and broadcast
    seen: list[str] = []
    core.bus.add_listener(
        lambda env: seen.append(str(env.payload.get("text") or env.payload.get("op"))),
        types=["edit.op", "edit.status"],
    )
    data(await call(core, "edit", "remove_fillers", {"clip_id": clip_id, "reason": "tighter"}))
    trimmed = data(await call(core, "edit", "trim", {"clip_id": clip_id, "start": 0.0, "end": 8.0}))
    assert trimmed["duration"] < 8.0
    edl = data(await call(core, "edit", "get_edl", {"clip_id": clip_id}))
    assert [h["op"] for h in edl["history"]] == ["init", "remove_fillers", "trim"]
    undone = data(await call(core, "edit", "undo", {"clip_id": clip_id, "op_id": edl["history"][1]["op_id"]}))
    assert undone["duration"] == pytest.approx(8.0)
    assert "Removing filler words…" in seen and "trim" in seen
    data(await call(core, "edit", "preview", {"clip_id": clip_id}))
    await core.jobs.drain()
    sheet = await call(core, "media", "contact_sheet", {"clip_id": clip_id})
    assert sheet.content[1]["type"] == "image"

    # review batch, human decisions, ship
    batch = data(
        await call(
            core,
            "review",
            "post_batch",
            {
                "campaign_id": cid,
                "clip_ids": [clip_id],
                "copy_by_clip": {str(clip_id): {"tiktok": "watch this #clips"}},
            },
        )
    )
    core.review.decide(clip_id, "approved", via="discord", reviewer="ahad")
    core.review.ship(batch["batch_id"], via="discord", reviewer="ahad")
    dec = data(await call(core, "review", "get_decisions", {"batch_id": batch["batch_id"]}))
    assert dec["decisions"][0]["decision"] == "approved" and dec["decisions"][0]["captions"] == {
        "tiktok": "watch this #clips"
    }

    # publishing: approval + caps + switches in the guard; dry-run simulates
    acct = make_account(core.db, "tiktok", handle="@clipsdaily")
    assert acct.id is not None
    when = (core.clock.now() + timedelta(seconds=1)).isoformat()
    sched = data(
        await call(
            core,
            "publish",
            "schedule_post",
            {"clip_id": clip_id, "account_id": acct.id, "scheduled_at": "now"},
            role="campaign",
            campaign_id=cid,
        )
    )
    assert sched["dry_run"] is True  # new installs start in dry-run
    second = await call(
        core,
        "publish",
        "schedule_post",
        {"clip_id": clip_id, "account_id": acct.id, "scheduled_at": when},
        role="campaign",
        campaign_id=cid,
    )
    assert second.is_error and "min_gap" in second.content[0]["text"]
    await core.jobs.drain()  # final render requested on schedule
    handled = await core.publishing.run_due()
    assert handled == [sched["post_id"]]
    with core.db.read() as s:
        post = s.get(Post, sched["post_id"])
        assert (
            post is not None
            and post.status == "simulated"
            and post.url
            and post.url.startswith("https://dry-run.invalid/")
        )

    sub = data(
        await call(
            core,
            "marketplace",
            "submit_post_url",
            {"post_id": sched["post_id"], "campaign_id": cid},
            role="campaign",
            campaign_id=cid,
        )
    )
    assert sub["status"] == "simulated" and sub["dry_run"] is True
    with core.db.read() as s:
        assert s.exec(select(Submission)).one().dry_run is True
        events = s.exec(select(AgentEvent).where(AgentEvent.type == "blocked")).all()
    assert {e.output_json["rule"] for e in events} >= {"source_whitelist", "min_gap"}


async def test_live_upload_and_challenge_pause(core: Core) -> None:
    from tests.factories import approve, make_clip, make_source

    set_control(core.db, "dry_run", False)
    camp = await _campaign(core)
    src = make_source(core.db, camp)
    assert src.id is not None
    clip = make_clip(core.db, camp, src.id, status="final", path="/tmp/does-not-matter.mp4")
    assert clip.id is not None
    approve(core.db, clip.id)
    ok_acct = make_account(core.db, "youtube", handle="@good", min_gap_min=0)
    bad_acct = make_account(core.db, "youtube", handle="@challenged", min_gap_min=0)
    assert ok_acct.id is not None and bad_acct.id is not None
    core.adapters.publisher.challenge_for.add("@challenged")  # type: ignore[attr-defined]
    good = core.publishing.schedule(clip.id, ok_acct.id, "now")
    bad = core.publishing.schedule(clip.id, bad_acct.id, "now")
    alerts: list[str] = []
    core.bus.add_listener(lambda env: alerts.append(env.payload["text"]), types=["alert"])
    await core.publishing.run_due()
    with core.db.read() as s:
        g, b = s.get(Post, good.id), s.get(Post, bad.id)
        acct = s.get(Account, bad_acct.id)
    assert g is not None and g.status == "live" and g.url and "youtube.com/shorts/" in g.url
    assert b is not None and b.status == "scheduled" and "verification" in (b.error or "")
    assert acct is not None and acct.status == "paused"
    assert any("@challenged" in a and "paused" in a for a in alerts)
    # submit for real through the fake marketplace
    res = await core.market.submit_post_url(good.id or 0, camp)
    assert res["status"] == "pending" and res["dry_run"] is False


async def test_marketplace_page_is_fenced_and_lists_sources(core: Core) -> None:
    cid = await _campaign(core)
    page = data(await call(core, "marketplace", "get_campaign_page", {"campaign_id": cid}))
    assert page["rules"].startswith("<<<UNTRUSTED")
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in page["rules"]  # the text is there, fenced, as data
    assert page["listed_sources"]
    with core.db.read() as s:
        c = s.get(Campaign, cid)
        assert c is not None and "IGNORE" in c.rules_raw
