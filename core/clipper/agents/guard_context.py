"""SQLite-backed ``GuardContext`` and the blocked-call logger."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlmodel import col, select

from clipper.agents.hooks import (
    AccountFacts,
    CampaignFacts,
    ClipFacts,
    PostFacts,
    ReviewFacts,
    ToolCall,
    Verdict,
)
from clipper.clock import Clock, SystemClock
from clipper.db.engine import Database, WriteTx
from clipper.db.models import (
    Account,
    AgentEvent,
    Campaign,
    Clip,
    Edl,
    Marketplace,
    Moment,
    Platform,
    Post,
    Review,
    Source,
    Submission,
)
from clipper.db.types import CAP_COUNTED_POST_STATUSES
from clipper.events.types import AgentEventLogged
from clipper.rules.caps import AccountCaps
from clipper.rules.spec import ClipSpec
from clipper.services.control import ControlState, read_control
from clipper.settings import Settings

BrowserUrlFn = Callable[[str | None], str | None]


def _no_browser(_profile: str | None) -> str | None:
    return None


def spec_of(campaign: Campaign) -> ClipSpec:
    try:
        return ClipSpec.model_validate(campaign.spec_json or {})
    except ValueError:
        return ClipSpec()


class DbGuardContext:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        clock: Clock | None = None,
        browser_url: BrowserUrlFn | None = None,
    ) -> None:
        self.db = db
        self._settings = settings
        self.clock = clock or SystemClock()
        self._browser_url: BrowserUrlFn = browser_url or _no_browser

    @property
    def settings(self) -> Settings:
        return self._settings

    def now(self) -> datetime:
        return self.clock.now()

    def control(self) -> ControlState:
        return read_control(self.db)

    def marketplace_enabled(self, market: str) -> bool:
        with self.db.read() as s:
            row = s.get(Marketplace, market)
            return bool(row and row.enabled)

    def platform_enabled(self, platform: str) -> bool:
        with self.db.read() as s:
            row = s.get(Platform, platform)
            return bool(row and row.enabled)

    def account(self, account_id: int) -> AccountFacts | None:
        with self.db.read() as s:
            a = s.get(Account, account_id)
            if a is None or a.id is None:
                return None
            return AccountFacts(
                id=a.id,
                platform=a.platform,
                enabled=a.enabled,
                status=a.status,
                chrome_profile=a.chrome_profile,
                caps=AccountCaps(a.id, a.daily_cap, a.min_gap_min, a.warmup_started),
            )

    def campaign(self, campaign_id: int) -> CampaignFacts | None:
        with self.db.read() as s:
            c = s.get(Campaign, campaign_id)
            if c is None or c.id is None:
                return None
            listed = s.exec(select(Source.url).where(Source.campaign_id == campaign_id)).all()
            return CampaignFacts(
                id=c.id,
                marketplace=c.marketplace,
                status=c.status,
                platforms=tuple(c.platforms or ()),
                spec=spec_of(c),
                listed_sources=tuple(listed),
            )

    def clip(self, clip_id: int) -> ClipFacts | None:
        with self.db.read() as s:
            c = s.get(Clip, clip_id)
            if c is None or c.id is None:
                return None
            edl = s.get(Edl, clip_id)
            moment = s.get(Moment, c.moment_id)
            return ClipFacts(
                id=c.id,
                campaign_id=c.campaign_id,
                locked_by=edl.locked_by if edl else None,
                score=moment.final_score if moment else None,
            )

    def review(self, clip_id: int) -> ReviewFacts | None:
        with self.db.read() as s:
            r = s.get(Review, clip_id)
            if r is None:
                return None
            return ReviewFacts(
                clip_id=r.clip_id,
                decision=r.decision,
                via=r.via,
                reviewer=r.reviewer,
                platforms=tuple(r.platforms or ()),
                score=r.score_at_decision,
            )

    def post(self, post_id: int) -> PostFacts | None:
        with self.db.read() as s:
            p = s.get(Post, post_id)
            if p is None or p.id is None:
                return None
            return PostFacts(
                id=p.id,
                clip_id=p.clip_id,
                account_id=p.account_id,
                platform=p.platform,
                status=p.status,
                url=p.url,
                campaign_id=p.campaign_id,
                dry_run=p.dry_run,
            )

    def submitted_campaigns(self, post_id: int) -> list[int]:
        with self.db.read() as s:
            return list(s.exec(select(Submission.campaign_id).where(Submission.post_id == post_id)).all())

    def counted_post_times(self, account_id: int, around: datetime) -> list[datetime]:
        with self.db.read() as s:
            rows = s.exec(
                select(Post.scheduled_at).where(
                    Post.account_id == account_id,
                    col(Post.status).in_(list(CAP_COUNTED_POST_STATUSES)),
                    col(Post.scheduled_at) >= around - timedelta(days=2),
                    col(Post.scheduled_at) < around + timedelta(days=2),
                )
            ).all()
            return list(rows)

    def browser_url(self, profile: str | None) -> str | None:
        return self._browser_url(profile)


def make_block_logger(db: Database) -> Callable[[ToolCall, Verdict], None]:
    """Writes each denial to ``agent_event`` (type ``blocked``) and mirrors it to the live console."""

    def on_block(call: ToolCall, verdict: Verdict) -> None:
        def job(tx: WriteTx) -> None:
            row = AgentEvent(
                session_id=call.session_id,
                type="blocked",
                tool=call.tool,
                input_json={"args": dict(call.args), "role": call.role},
                output_json={"rule": verdict.rule, "reason": verdict.reason},
            )
            tx.add(row)
            tx.flush()
            assert row.id is not None
            tx.publish(
                AgentEventLogged(
                    session_id=call.session_id,
                    agent_event_id=row.id,
                    kind="blocked",
                    tool=call.tool,
                    summary=verdict.message,
                )
            )

        db.write(job)

    return on_block
