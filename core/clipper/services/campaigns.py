"""Campaigns: upsert from marketplace cards, take/skip, spec, budget run-out prediction, summaries."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlmodel import col, func, select

from clipper.clock import ensure_utc
from clipper.db.engine import WriteTx
from clipper.db.models import (
    AgendaItem,
    Campaign,
    Clip,
    Event,
    Job,
    Marketplace,
    Moment,
    Platform,
    Review,
    Source,
)
from clipper.db.types import CampaignStatus
from clipper.events.types import CampaignFound, CampaignSkipped, CampaignTaken, CampaignUpdated, SpecUpdated
from clipper.marketplaces.base import CampaignCard
from clipper.rules.spec import ClipSpec
from clipper.services.base import Service, ServiceError

EDITABLE_FIELDS = {"status", "score", "score_reason"}
AGENT_STATUSES = {
    CampaignStatus.ACTIVE,
    CampaignStatus.PAUSED,
    CampaignStatus.ENDING,
    CampaignStatus.ENDED,
    CampaignStatus.NEEDS_USER,
    CampaignStatus.SUGGESTED,
}


def predict_run_out(samples: list[tuple[datetime, float]], now: datetime) -> datetime | None:
    """Linear fit of budget_left over time -> when it hits zero (None if not decreasing)."""
    pts = sorted((ensure_utc(t), v) for t, v in samples)
    if len(pts) < 2:
        return None
    t0 = pts[0][0]
    xs = [(t - t0).total_seconds() for t, _ in pts]
    ys = [v for _, v in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den
    if slope >= 0:
        return None
    last_t, last_v = pts[-1]
    seconds_left = last_v / -slope
    if seconds_left > 365 * 86400:
        return None
    return max(now, last_t + timedelta(seconds=seconds_left))


class CampaignService(Service):
    # ------------------------------------------------------------ scout

    def upsert_cards(self, cards: list[CampaignCard]) -> list[tuple[int, bool]]:
        """Insert new campaigns (status suggested) and refresh known ones. Returns (id, is_new)."""
        include_ugc = self.settings.marketplaces.whop.include_ugc
        now = self.now()

        def job(tx: WriteTx) -> list[tuple[int, bool]]:
            out: list[tuple[int, bool]] = []
            for card in cards:
                row = tx.session.exec(
                    select(Campaign).where(
                        Campaign.marketplace == card.marketplace, Campaign.external_id == card.external_id
                    )
                ).first()
                is_new = row is None
                if row is None:
                    status = CampaignStatus.SUGGESTED
                    if card.content_type == "ugc" and not include_ugc:
                        status = CampaignStatus.SKIPPED
                    row = Campaign(
                        marketplace=card.marketplace,
                        external_id=card.external_id,
                        title=card.title,
                        status=status,
                    )
                row.title = card.title
                row.brand = card.brand
                row.creator = card.creator
                row.url = card.url
                row.cpm = card.cpm_usd
                row.budget_total = card.budget_total
                row.budget_left = card.budget_left
                row.cap_per_clip = card.cap_per_post
                row.min_views_to_pay = card.min_views_to_pay
                row.platforms = list(card.allowed_platforms)
                row.deliverable = card.deliverable
                row.content_type = card.content_type
                row.tracking_window_days = card.tracking_window_days
                row.deadline = card.deadline
                row.updated_at = now
                tx.add(row)
                tx.flush()
                assert row.id is not None
                if is_new:
                    tx.publish(CampaignFound(campaign_id=row.id, marketplace=card.marketplace))
                if card.budget_left is not None:
                    tx.publish(
                        CampaignUpdated(
                            campaign_id=row.id, fields=["budget_left"], budget_left=card.budget_left
                        )
                    )
                out.append((row.id, is_new))
            return out

        result = self.db.write(job)
        for cid, _ in result:
            self.refresh_run_out(cid)
        return result

    def refresh_run_out(self, campaign_id: int) -> datetime | None:
        with self.db.read() as s:
            rows = s.exec(
                select(Event)
                .where(Event.type == "campaign.updated", Event.entity_id == str(campaign_id))
                .order_by(col(Event.id).desc())
                .limit(12)
            ).all()
        samples = [
            (r.ts, float(r.payload["budget_left"])) for r in rows if r.payload.get("budget_left") is not None
        ]
        when = predict_run_out(samples, self.now())

        def job(tx: WriteTx) -> None:
            row = tx.session.get(Campaign, campaign_id)
            if row is not None and row.budget_runs_out_at != when:
                row.budget_runs_out_at = when
                tx.add(row)

        self.db.write(job)
        return when

    # ------------------------------------------------------------ user / agent actions

    def take(self, campaign_id: int, *, by: str = "user", via: str = "dashboard") -> None:
        def job(tx: WriteTx) -> None:
            row = self._get(tx, campaign_id)
            if row.status not in (
                CampaignStatus.SUGGESTED,
                CampaignStatus.SKIPPED,
                CampaignStatus.NEEDS_USER,
            ):
                raise ServiceError(
                    f"campaign {campaign_id} is {row.status}; only suggested campaigns can be taken"
                )
            market = tx.session.get(Marketplace, row.marketplace)
            if market is None or not market.enabled:
                raise ServiceError(f"{row.marketplace} is switched off")
            row.status = CampaignStatus.ACTIVE
            row.taken_at = self.now()
            tx.add(row)
            tx.publish(CampaignTaken(campaign_id=campaign_id, by=by, via=via))

        self.db.write(job)

    def skip(self, campaign_id: int, *, by: str = "user", via: str = "dashboard") -> None:
        def job(tx: WriteTx) -> None:
            row = self._get(tx, campaign_id)
            row.status = CampaignStatus.SKIPPED
            tx.add(row)
            tx.publish(CampaignSkipped(campaign_id=campaign_id, by=by, via=via))

        self.db.write(job)

    def update(self, campaign_id: int, fields: dict[str, Any], *, by: str = "user") -> list[str]:
        """Agents (``by`` = "session:<id>" or a role) may only *take* a campaign in auto mode above the
        auto-take score (PLAN §3 Scout, §13 autonomy). Enforced here, not in the prompt."""
        bad = set(fields) - EDITABLE_FIELDS
        if bad:
            raise ServiceError(
                f"can't update {', '.join(sorted(bad))}; editable: {', '.join(sorted(EDITABLE_FIELDS))}"
            )
        if "status" in fields and fields["status"] not in AGENT_STATUSES:
            raise ServiceError(f"status must be one of {', '.join(sorted(AGENT_STATUSES))}")
        scout = self.settings.scout

        def job(tx: WriteTx) -> list[str]:
            row = self._get(tx, campaign_id)
            taking = fields.get("status") == CampaignStatus.ACTIVE and row.status == CampaignStatus.SUGGESTED
            if taking and by != "user":
                market = tx.session.get(Marketplace, row.marketplace)
                score = fields.get("score", row.score) or 0
                if scout.mode != "auto" or (market is not None and market.mode != "auto"):
                    raise ServiceError(
                        "Scout is in suggest mode: only the user can take a campaign (post a card instead)"
                    )
                if score < scout.auto_take_min_score:
                    raise ServiceError(f"auto-take needs a score of at least {scout.auto_take_min_score}")
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = self.now()
            if taking:
                row.taken_at = self.now()
            tx.add(row)
            tx.publish(CampaignUpdated(campaign_id=campaign_id, fields=sorted(fields)))
            if taking:
                tx.publish(
                    CampaignTaken(
                        campaign_id=campaign_id, by=by, via="agent" if by != "user" else "dashboard"
                    )
                )
            return sorted(fields)

        return self.db.write(job)

    def save_spec(self, campaign_id: int, spec: ClipSpec, *, by: str = "agent") -> ClipSpec:
        def job(tx: WriteTx) -> ClipSpec:
            row = self._get(tx, campaign_id)
            allowed = set(row.platforms or ["youtube", "tiktok", "instagram", "x"])
            platforms = [p for p in spec.platforms if p in allowed] or [
                p for p in ("youtube", "tiktok", "instagram") if p in allowed
            ]
            enabled = {p.id for p in tx.session.exec(select(Platform).where(col(Platform.enabled))).all()}
            cleaned = spec.model_copy(update={"platforms": platforms})
            row.spec_json = cleaned.model_dump(mode="json")
            if not any(p in enabled for p in platforms):
                row.status = CampaignStatus.NO_ENABLED_SOCIALS
            row.updated_at = self.now()
            tx.add(row)
            tx.publish(SpecUpdated(campaign_id=campaign_id, by=by))
            return cleaned

        return self.db.write(job)

    # ------------------------------------------------------------ reads

    def _get(self, tx: WriteTx, campaign_id: int) -> Campaign:
        row = tx.session.get(Campaign, campaign_id)
        if row is None:
            raise ServiceError(f"campaign {campaign_id} not found")
        return row

    def get(self, campaign_id: int) -> Campaign:
        with self.db.read() as s:
            row = s.get(Campaign, campaign_id)
            if row is None:
                raise ServiceError(f"campaign {campaign_id} not found")
            return row

    def spec(self, campaign_id: int) -> ClipSpec:
        return ClipSpec.model_validate(self.get(campaign_id).spec_json or {})

    def summary(self, campaign_id: int, *, clips_offset: int = 0, clips_limit: int = 30) -> dict[str, Any]:
        """Small, agent-friendly view: fields, spec, sources, moments/clip counts, a page of clips, jobs."""
        with self.db.read() as s:
            c = s.get(Campaign, campaign_id)
            if c is None:
                raise ServiceError(f"campaign {campaign_id} not found")
            sources = s.exec(select(Source).where(Source.campaign_id == campaign_id)).all()
            moments = s.exec(
                select(func.count()).select_from(Moment).where(Moment.campaign_id == campaign_id)
            ).one()
            clips = s.exec(
                select(Clip, Review)
                .join(Review, col(Review.clip_id) == col(Clip.id), isouter=True)
                .where(Clip.campaign_id == campaign_id)
                .order_by(col(Clip.id))
                .offset(clips_offset)
                .limit(clips_limit)
            ).all()
            jobs = s.exec(
                select(Job)
                .where(Job.campaign_id == campaign_id, col(Job.status).in_(["queued", "running"]))
                .limit(20)
            ).all()
            plan = s.exec(
                select(AgendaItem)
                .where(AgendaItem.scope == "campaign", AgendaItem.scope_id == str(campaign_id))
                .order_by(col(AgendaItem.ord))
            ).all()
        return {
            "id": c.id,
            "marketplace": c.marketplace,
            "title": c.title,
            "creator": c.creator,
            "status": c.status,
            "cpm": c.cpm,
            "budget_left": c.budget_left,
            "budget_runs_out_at": c.budget_runs_out_at.isoformat() if c.budget_runs_out_at else None,
            "deadline": c.deadline.isoformat() if c.deadline else None,
            "platforms": c.platforms,
            "score": c.score,
            "spec": c.spec_json or None,
            "sources": [
                {"id": x.id, "url": x.url, "status": x.status, "duration": x.duration} for x in sources
            ],
            "moments": moments,
            "clips": [
                {
                    "id": clip.id,
                    "status": clip.status,
                    "version": clip.version,
                    "decision": review.decision if review else None,
                }
                for clip, review in clips
            ],
            "clips_next_offset": clips_offset + clips_limit if len(clips) == clips_limit else None,
            "open_jobs": [
                {"id": j.id, "kind": j.kind, "status": j.status, "progress": j.progress} for j in jobs
            ],
            "plan": [{"id": p.id, "text": p.text, "status": p.status} for p in plan],
        }

    def list(
        self, *, status: str | None = None, market: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self.db.read() as s:
            q = select(Campaign).order_by(col(Campaign.id).desc()).limit(limit)
            if status:
                q = q.where(Campaign.status == status)
            if market:
                q = q.where(Campaign.marketplace == market)
            rows = s.exec(q).all()
        return [
            {
                "id": r.id,
                "marketplace": r.marketplace,
                "title": r.title,
                "status": r.status,
                "cpm": r.cpm,
                "budget_left": r.budget_left,
                "score": r.score,
                "deadline": r.deadline.isoformat() if r.deadline else None,
            }
            for r in rows
        ]
