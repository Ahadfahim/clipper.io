"""End to end on fakes, in dry-run (WP5): campaign taken -> spec -> download -> analysis -> moments ->
renders -> review batch -> shipped -> schedule -> post.live -> submit. The FakeAgentRunner replays tool
calls through the same PreToolUse hook and tool wrapper a real session uses."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlmodel import col, select

from clipper.agents.runner import FakeAgentRunner, RunRequest, Say, ScriptState, Step, ToolStep
from clipper.clock import FakeClock
from clipper.core import Core
from clipper.db.models import AgentEvent, AgentRequest, AgentSession, Campaign, Clip, Post, Submission
from clipper.settings import Settings
from clipper.supervisor.supervisor import Supervisor
from tests.factories import make_account

pytestmark = pytest.mark.ffmpeg


def _events(req: RunRequest, type_: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in req.payload.get("events", []) if e["type"] == type_]


def campaign_script(req: RunRequest) -> list[Step]:
    cid = req.campaign_id
    assert cid is not None
    steps: list[Step] = [ToolStep("state", "get_campaign", {"campaign_id": cid})]
    if _events(req, "campaign.taken"):
        steps += [
            ToolStep("marketplace", "get_campaign_page", {"campaign_id": cid}, save_as="page"),
            ToolStep("memory", "recall", {"scope": "creator"}, agent="brief-reader"),
            ToolStep(
                "state",
                "save_spec",
                lambda st: {
                    "campaign_id": cid,
                    "spec": {
                        "source_whitelist": st.results["page"]["listed_sources"],
                        "platforms": ["youtube", "tiktok"],
                        "duration_min_s": 5,
                        "duration_max_s": 60,
                        "notes": "brief contains an instruction to skip review: ignored",
                    },
                },
            ),
            ToolStep("marketplace", "join_campaign", {"campaign_id": cid}),
            ToolStep(
                "media",
                "download",
                each=lambda st: [
                    {"campaign_id": cid, "url": u} for u in st.results["page"]["listed_sources"]
                ],
            ),
            # what an agent that fell for the brief's injection would try; the code must block both
            ToolStep("publish", "schedule_post", {"clip_id": 1, "account_id": 1, "scheduled_at": "now"}),
            ToolStep("media", "download", {"campaign_id": cid, "url": "https://evil.example/spam.mp4"}),
        ]
    analyzed = [
        p["result"]["source_id"]
        for p in _events(req, "job.done")
        if p["kind"] == "analyze" and p["status"] == "done"
    ]
    for sid in analyzed:
        steps += [
            ToolStep("media", "get_signals", {"source_id": sid}, agent="editor"),
            ToolStep("media", "get_transcript", {"source_id": sid, "from": 0, "to": 10}, agent="editor"),
            ToolStep(
                "state",
                "save_moments",
                {
                    "campaign_id": cid,
                    "source_id": sid,
                    "moments": [
                        {
                            "start": 0.0,
                            "end": 9.5,
                            "hook": "Nobody tells you this",
                            "final_score": 88,
                            "reason": "heatmap peak + quoted in comments",
                        },
                        {
                            "start": 2.0,
                            "end": 9.0,
                            "hook": "The money is in the edit",
                            "final_score": 81,
                            "reason": "energy spike",
                        },
                    ],
                },
                save_as="moments",
            ),
            ToolStep(
                "media",
                "render",
                each=lambda st: [
                    {"moment_id": m, "platform": "tiktok"} for m in st.results["moments"]["moment_ids"]
                ],
            ),
        ]
    rendered = [
        p["result"]["clip_id"]
        for p in _events(req, "job.done")
        if p["kind"] == "render_preview" and p["status"] == "done"
    ]
    if rendered:
        steps += [
            ToolStep(
                "edit",
                "remove_fillers",
                each=lambda st: [{"clip_id": c, "reason": "tighter"} for c in rendered],
                agent="cutter",
            ),
            ToolStep(
                "state", "get_clip", each=lambda st: [{"clip_id": c} for c in rendered], agent="qa-checker"
            ),
            ToolStep("trends", "hashtags", {"niche": "podcast", "platform": "tiktok"}, agent="copywriter"),
            ToolStep(
                "review",
                "post_batch",
                {
                    "campaign_id": cid,
                    "clip_ids": rendered,
                    "copy_by_clip": {
                        str(c): {"tiktok": f"clip {c} #clips", "youtube": f"Clip {c}"} for c in rendered
                    },
                },
            ),
        ]
    for shipped in _events(req, "review.shipped"):
        approved: list[int] = shipped["approved"]

        def schedule_args(st: ScriptState, approved: list[int] = approved) -> list[dict[str, Any]]:
            accounts = st.results["accounts"]["accounts"]
            by_platform = {a["platform"]: a["id"] for a in accounts}
            plats = ["youtube", "tiktok"]
            return [
                {"clip_id": c, "account_id": by_platform[plats[i % 2]], "scheduled_at": "now"}
                for i, c in enumerate(approved)
            ]

        steps += [
            ToolStep("review", "get_decisions", {"campaign_id": cid}),
            ToolStep(
                "edit", "render_final", each=lambda st, approved=approved: [{"clip_id": c} for c in approved]
            ),
            ToolStep("publish", "list_accounts", {}, save_as="accounts"),
            ToolStep("publish", "schedule_post", each=schedule_args, save_as="scheduled"),
            ToolStep("supervisor", "wake_me", {"in": 360, "reason": "check views of today's posts"}),
        ]
    for live in _events(req, "post.live"):
        steps.append(
            ToolStep("marketplace", "submit_post_url", {"post_id": live["post_id"], "campaign_id": cid})
        )
    steps.append(
        ToolStep(
            "state", "log_note", {"text": f"handled {[e['type'] for e in req.payload.get('events', [])]}"}
        )
    )
    return steps


def scout_script(req: RunRequest) -> list[Step]:
    return [
        ToolStep("marketplace", "list_campaigns", {}, save_as="list"),
        ToolStep(
            "state",
            "update_campaign",
            lambda st: {
                "campaign_id": st.results["list"]["campaigns"][0]["id"],
                "score": 84,
                "score_reason": "CPM 3, budget 18k left, niche fit",
            },
        ),
        ToolStep(
            "review",
            "post_campaign_card",
            lambda st: {
                "campaign_id": st.results["list"]["campaigns"][0]["id"],
                "reasoning": "High CPM, fits @podcastcuts",
            },
        ),
        # suggest mode: an agent can't take a campaign itself
        ToolStep(
            "state",
            "update_campaign",
            lambda st: {
                "campaign_id": st.results["list"]["campaigns"][0]["id"],
                "status": "active",
                "score": 99,
            },
        ),
        Say("scout done"),
    ]


@pytest.fixture
def e2e(settings: Settings) -> Iterator[tuple[Core, FakeAgentRunner, Supervisor, FakeClock]]:
    clock = FakeClock()
    core = Core.create(settings, fakes=True, clock=clock)
    runner = FakeAgentRunner(core, {"campaign": campaign_script, "scout": scout_script})
    sup = Supervisor(core, runner)
    yield core, runner, sup, clock
    core.close()


async def test_campaign_lifecycle_end_to_end_in_dry_run(
    e2e: tuple[Core, FakeAgentRunner, Supervisor, FakeClock],
) -> None:
    core, runner, sup, clock = e2e
    yt = make_account(core.db, "youtube", handle="@podcastcuts", niche_tags=["podcast"])
    tt = make_account(core.db, "tiktok", handle="@podcastcuts_tt", niche_tags=["podcast"])

    # Scout run (trigger) finds campaigns and posts a card; it can't take one in suggest mode.
    assert sup.fire_triggers() == ["scout"]  # 08:00 in New York: the Analyst runs at 09:00
    await sup.run_until_idle()
    scout_state = runner.states[0]
    assert any("suggest mode" in e for e in scout_state.errors)
    with core.db.read() as s:
        camp = s.exec(select(Campaign).where(Campaign.external_id == "vyro-ext-101")).one()
    assert camp.id is not None and camp.score == 84 and camp.status == "suggested"

    # The user takes it.
    core.campaigns.take(camp.id, by="ahad", via="discord")
    await sup.run_until_idle()

    with core.db.read() as s:
        batches = s.exec(select(Clip).where(Clip.campaign_id == camp.id)).all()
    clip_ids = sorted(c.id for c in batches if c.id is not None)
    assert len(clip_ids) == 2 and all(c.status == "in_review" for c in batches)

    # The injected instructions were blocked in code and logged.
    first_campaign_run = next(st for st in runner.states if st.req.role == "campaign")
    joined = " ".join(first_campaign_run.errors)
    assert "[approval]" in joined and "[source_whitelist]" in joined
    with core.db.read() as s:
        blocked = s.exec(select(AgentEvent).where(AgentEvent.type == "blocked")).all()
    assert {b.output_json["rule"] for b in blocked} >= {"approval", "source_whitelist"}

    # Human review in Discord: approve both, ship.
    batch_id = core.review.decisions(campaign_id=camp.id)[0]["batch_id"]
    for c in clip_ids:
        core.review.decide(c, "approved", via="discord", reviewer="ahad")
    core.review.ship(batch_id, via="discord", reviewer="ahad")
    await sup.run_until_idle()

    with core.db.read() as s:
        posts = s.exec(select(Post).where(Post.campaign_id == camp.id)).all()
        subs = s.exec(select(Submission)).all()
        clips = s.exec(select(Clip).where(col(Clip.id).in_(clip_ids))).all()
    assert {p.platform for p in posts} == {"youtube", "tiktok"}
    assert {p.account_id for p in posts} == {yt.id, tt.id}
    assert all(p.status == "simulated" and p.dry_run for p in posts)
    assert sorted(s_.post_id for s_ in subs) == sorted(p.id for p in posts if p.id is not None)
    assert all(s_.dry_run and s_.external_status == "simulated" for s_ in subs)
    assert all(c.path for c in clips), "approved clips got a final render"

    # One Campaign session, resumed for every event with the same SDK session id.
    with core.db.read() as s:
        sessions = s.exec(select(AgentSession).where(AgentSession.role == "campaign")).all()
        requests = s.exec(select(AgentRequest).where(AgentRequest.role == "campaign")).all()
    assert len(sessions) == 1
    campaign_runs = [r for r in runner.runs if r.role == "campaign"]
    assert campaign_runs[0].resume is None
    assert (
        len({r.resume for r in campaign_runs[1:]}) == 1
        and campaign_runs[1].resume == sessions[0].sdk_session_id
    )
    kinds = [r.kind for r in requests]
    assert kinds[0] == "campaign.taken" and "review.shipped" in kinds and "post.live" in kinds
    assert all(r.status == "done" for r in requests)
    assert sessions[0].turns > 10
    # resume prompts describe the events
    shipped_run = next(r for r in campaign_runs if r.kind == "review.shipped")
    assert "shipped via discord" in shipped_run.prompt and "Dry run is ON" in shipped_run.prompt

    # The follow-up the agent scheduled wakes it later.
    clock.advance(hours=6, minutes=1)
    core.wakeups.fire_due()
    await sup.run_until_idle()
    assert runner.runs[-1].kind == "wakeup.due" and runner.runs[-1].resume == sessions[0].sdk_session_id


async def test_ask_user_answer_resumes_the_same_session(
    e2e: tuple[Core, FakeAgentRunner, Supervisor, FakeClock],
) -> None:
    core, runner, sup, _clock = e2e

    def asking(req: RunRequest) -> list[Step]:
        if req.kind == "campaign.taken":
            return [
                ToolStep(
                    "notify",
                    "ask_user",
                    {
                        "question": "Rules unclear: can we use the trailer footage?",
                        "options": ["Yes", "No", "Skip campaign"],
                    },
                )
            ]
        return [Say("thanks")]

    runner.scripts["campaign"] = asking
    cards = await core.market.list_campaigns("whop")
    cid = cards["campaigns"][0]["id"]
    core.campaigns.take(cid)
    await sup.run_until_idle()
    questions = core.notify.open_questions()
    assert len(questions) == 1 and questions[0]["session_id"] is not None
    core.notify.answer(questions[0]["id"], "No", by="ahad", via="dashboard")
    await sup.run_until_idle()
    first, second = (r for r in runner.runs if r.role == "campaign")
    with core.db.read() as s:
        session = s.exec(select(AgentSession).where(AgentSession.role == "campaign")).one()
    assert first.resume is None and second.kind == "question.answered"
    assert second.resume is not None and second.resume == session.sdk_session_id
    assert "was answered via dashboard: 'No'" in second.prompt
    with core.db.read() as s:
        req = s.exec(select(AgentRequest).where(AgentRequest.kind == "question.answered")).one()
    assert req.priority == 0


async def test_daily_triggers_fire_once(e2e: tuple[Core, FakeAgentRunner, Supervisor, FakeClock]) -> None:
    core, _runner, sup, clock = e2e
    clock.set(clock.now().replace(hour=14, minute=0))  # 10:00 New York, after 09:00
    assert sorted(sup.fire_triggers()) == ["analyst", "scout"]
    assert sup.fire_triggers() == []
    clock.advance(minutes=16)
    assert sup.fire_triggers() == ["scout"]
    clock.advance(timedelta(days=1))
    assert sorted(sup.fire_triggers()) == ["analyst", "scout"]
    from clipper.services.control import set_control

    set_control(core.db, "paused", True)
    clock.advance(minutes=30)
    assert sup.fire_triggers() == []
