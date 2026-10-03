"""Review flow (PLAN §7, UI §3.5): batches per campaign x source, decisions from Discord or the dashboard,
ship, re-cut and caption edits. Review state lives here; Discord and the dashboard show the same data."""

from __future__ import annotations

from typing import Any

from sqlmodel import col, select

from clipper.db.engine import WriteTx
from clipper.db.models import Campaign, Clip, Moment, Platform, Review, ReviewBatch
from clipper.db.types import BatchStatus, ClipStatus, Decision
from clipper.events.types import (
    CampaignCardRequested,
    CaptionEdited,
    ReviewBatchPosted,
    ReviewDecided,
    ReviewShipped,
)
from clipper.events.types import RecutRequested as RecutEvent
from clipper.rules.spec import ClipSpec
from clipper.services.base import Service, ServiceError

REJECT_REASONS = ("bad hook", "boring", "broken", "off-brief", "other")


class ReviewService(Service):
    def post_batch(
        self,
        campaign_id: int,
        clip_ids: list[int],
        *,
        copy: dict[int, dict[str, str]] | None = None,
        source_id: int | None = None,
    ) -> int:
        if not clip_ids:
            raise ServiceError("a batch needs at least one clip")
        copy = copy or {}
        settings = self.settings

        def job(tx: WriteTx) -> int:
            campaign = tx.session.get(Campaign, campaign_id)
            if campaign is None:
                raise ServiceError(f"campaign {campaign_id} not found")
            spec = ClipSpec.model_validate(campaign.spec_json or {})
            enabled = {p.id for p in tx.session.exec(select(Platform).where(col(Platform.enabled))).all()}
            platforms = [p for p in (spec.platforms or campaign.platforms) if p in enabled]
            clips: list[Clip] = []
            for cid in clip_ids:
                clip = tx.session.get(Clip, cid)
                if clip is None or clip.campaign_id != campaign_id:
                    raise ServiceError(f"clip {cid} is not part of campaign {campaign_id}")
                if clip.status not in (ClipStatus.READY, ClipStatus.IN_REVIEW):
                    raise ServiceError(f"clip {cid} is {clip.status}; only rendered clips can be reviewed")
                clips.append(clip)
            timeout = None
            if settings.review.timeout_hours > 0:
                from datetime import timedelta

                timeout = self.now() + timedelta(hours=settings.review.timeout_hours)
            batch = ReviewBatch(
                campaign_id=campaign_id, source_id=source_id, status=BatchStatus.PENDING, timeout_at=timeout
            )
            tx.add(batch)
            tx.flush()
            assert batch.id is not None
            for clip in clips:
                assert clip.id is not None
                moment = tx.session.get(Moment, clip.moment_id)
                review = tx.session.get(Review, clip.id) or Review(clip_id=clip.id)
                review.batch_id = batch.id
                review.decision = Decision.PENDING
                review.platforms = platforms
                review.captions_json = {k: v for k, v in (copy.get(clip.id) or {}).items() if k in platforms}
                review.score_at_decision = moment.final_score if moment else None
                tx.add(review)
                clip.status = ClipStatus.IN_REVIEW
                tx.add(clip)
            tx.publish(
                ReviewBatchPosted(
                    batch_id=batch.id,
                    campaign_id=campaign_id,
                    clip_ids=[c.id for c in clips if c.id is not None],
                )
            )
            return batch.id

        return self.db.write(job)

    def decide(
        self,
        clip_id: int,
        decision: str,
        *,
        via: str,
        reviewer: str,
        reason: str | None = None,
        platforms: list[str] | None = None,
    ) -> None:
        if decision not in (Decision.APPROVED, Decision.REJECTED, Decision.PENDING):
            raise ServiceError("decision must be approved, rejected or pending")
        if via not in ("discord", "dashboard", "auto"):
            raise ServiceError("decisions come from discord, the dashboard, or the opt-in auto tier")
        if not reviewer:
            raise ServiceError("a decision needs a reviewer")

        def job(tx: WriteTx) -> None:
            review = tx.session.get(Review, clip_id)
            clip = tx.session.get(Clip, clip_id)
            if review is None or clip is None:
                raise ServiceError(f"clip {clip_id} is not in review")
            batch = tx.session.get(ReviewBatch, review.batch_id) if review.batch_id else None
            if batch is not None and batch.status == BatchStatus.SHIPPED:
                raise ServiceError(f"batch {batch.id} was already shipped")
            review.decision = decision
            review.reason = reason
            review.via = via
            review.reviewer = reviewer
            review.decided_at = self.now()
            if platforms is not None:
                review.platforms = [p for p in platforms if p in review.platforms or not review.platforms]
            tx.add(review)
            clip.status = {
                Decision.APPROVED: ClipStatus.APPROVED,
                Decision.REJECTED: ClipStatus.REJECTED,
            }.get(decision, ClipStatus.IN_REVIEW)
            tx.add(clip)
            if batch is not None and batch.status == BatchStatus.PENDING:
                batch.status = BatchStatus.IN_REVIEW
                tx.add(batch)
            tx.publish(
                ReviewDecided(
                    clip_id=clip_id,
                    batch_id=review.batch_id,
                    decision=str(decision),
                    reason=reason,
                    via=via,
                    reviewer=reviewer,
                )  # type: ignore[arg-type]
            )

        self.db.write(job)

    def batch_reviews(self, batch_id: int) -> list[tuple[Review, Clip]]:
        with self.db.read() as s:
            rows = s.exec(
                select(Review, Clip)
                .join(Clip, col(Clip.id) == col(Review.clip_id))
                .where(Review.batch_id == batch_id)
            ).all()
            return [(r, c) for r, c in rows]

    def approve_all_at_least(self, batch_id: int, threshold: float, *, via: str, reviewer: str) -> list[int]:
        done: list[int] = []
        for review, _clip in self.batch_reviews(batch_id):
            if review.decision == Decision.PENDING and (review.score_at_decision or 0) >= threshold:
                self.decide(
                    review.clip_id,
                    Decision.APPROVED,
                    via=via,
                    reviewer=reviewer,
                    reason=f"approve all >= {threshold:g}",
                )
                done.append(review.clip_id)
        return done

    def reject_rest(self, batch_id: int, *, via: str, reviewer: str, reason: str = "other") -> list[int]:
        done: list[int] = []
        for review, _clip in self.batch_reviews(batch_id):
            if review.decision == Decision.PENDING:
                self.decide(review.clip_id, Decision.REJECTED, via=via, reviewer=reviewer, reason=reason)
                done.append(review.clip_id)
        return done

    def ship(self, batch_id: int, *, via: str, reviewer: str) -> dict[str, list[int]]:
        def job(tx: WriteTx) -> dict[str, list[int]]:
            batch = tx.session.get(ReviewBatch, batch_id)
            if batch is None:
                raise ServiceError(f"batch {batch_id} not found")
            if batch.status == BatchStatus.SHIPPED:
                raise ServiceError(f"batch {batch_id} was already shipped")
            reviews = tx.session.exec(select(Review).where(Review.batch_id == batch_id)).all()
            approved = [r.clip_id for r in reviews if r.decision == Decision.APPROVED]
            rejected = [r.clip_id for r in reviews if r.decision == Decision.REJECTED]
            if not approved and not rejected:
                raise ServiceError("nothing was decided in this batch yet")
            batch.status = BatchStatus.SHIPPED
            batch.shipped_at = self.now()
            tx.add(batch)
            tx.publish(
                ReviewShipped(
                    batch_id=batch_id,
                    campaign_id=batch.campaign_id,
                    approved=approved,
                    rejected=rejected,
                    via=via,
                )
            )
            return {"approved": approved, "rejected": rejected}

        return self.db.write(job)

    def edit_caption(self, clip_id: int, platform: str, text: str, *, via: str) -> None:
        def job(tx: WriteTx) -> None:
            review = tx.session.get(Review, clip_id)
            if review is None:
                raise ServiceError(f"clip {clip_id} is not in review")
            captions = dict(review.captions_json)
            captions[platform] = text[:2200]
            review.captions_json = captions
            tx.add(review)
            tx.publish(CaptionEdited(clip_id=clip_id, platform=platform, text=text[:2200], via=via))

        self.db.write(job)

    def request_recut(
        self,
        clip_id: int,
        *,
        start_delta: float = 0.0,
        end_delta: float = 0.0,
        layout: str | None = None,
        note: str | None = None,
        via: str,
    ) -> None:
        with self.db.read() as s:
            clip = s.get(Clip, clip_id)
            if clip is None:
                raise ServiceError(f"clip {clip_id} not found")
            campaign_id = clip.campaign_id
        self.db.write(
            lambda tx: tx.publish(
                RecutEvent(
                    clip_id=clip_id,
                    campaign_id=campaign_id,
                    start_delta=start_delta,
                    end_delta=end_delta,
                    layout=layout,
                    note=note,
                    via=via,
                )
            )
        )

    def post_campaign_card(self, campaign_id: int, reasoning: str) -> None:
        with self.db.read() as s:
            c = s.get(Campaign, campaign_id)
            if c is None:
                raise ServiceError(f"campaign {campaign_id} not found")
            score = c.score
        self.db.write(
            lambda tx: tx.publish(
                CampaignCardRequested(campaign_id=campaign_id, score=score, reasoning=reasoning[:1500])
            )
        )

    # ------------------------------------------------------------ reads

    def batch_status(self, batch_id: int) -> dict[str, Any]:
        with self.db.read() as s:
            batch = s.get(ReviewBatch, batch_id)
            if batch is None:
                raise ServiceError(f"batch {batch_id} not found")
        rows = self.batch_reviews(batch_id)
        counts = {d: sum(1 for r, _ in rows if r.decision == d) for d in ("pending", "approved", "rejected")}
        return {
            "batch_id": batch_id,
            "campaign_id": batch.campaign_id,
            "status": batch.status,
            "total": len(rows),
            **counts,
        }

    def decisions(
        self, *, batch_id: int | None = None, campaign_id: int | None = None
    ) -> list[dict[str, Any]]:
        with self.db.read() as s:
            q = select(Review, Clip).join(Clip, col(Clip.id) == col(Review.clip_id))
            if batch_id is not None:
                q = q.where(Review.batch_id == batch_id)
            if campaign_id is not None:
                q = q.where(Clip.campaign_id == campaign_id)
            rows = s.exec(q.order_by(col(Review.clip_id))).all()
        return [
            {
                "clip_id": r.clip_id,
                "batch_id": r.batch_id,
                "decision": r.decision,
                "reason": r.reason,
                "platforms": r.platforms,
                "captions": r.captions_json,
                "via": r.via,
                "clip_status": c.status,
            }
            for r, c in rows
        ]

    def auto_approve_offer(self) -> dict[str, Any]:
        """PLAN §14: offer auto-approve for tier T when > 95% of >= 100 decisions at >= T were approvals."""
        cfg = self.settings.review
        with self.db.read() as s:
            rows = s.exec(
                select(Review).where(col(Review.decision).in_(["approved", "rejected"]), Review.via != "auto")
            ).all()
        offers: list[dict[str, Any]] = []
        for tier in (95, 90, 85, 80):
            sample = [r for r in rows if (r.score_at_decision or 0) >= tier]
            if len(sample) < cfg.auto_approve_offer_min_decisions:
                continue
            rate = sum(1 for r in sample if r.decision == "approved") / len(sample)
            if rate > cfg.auto_approve_offer_min_rate:
                offers.append({"tier": tier, "decisions": len(sample), "approval_rate": round(rate, 3)})
        return {"eligible": bool(offers), "offers": offers, "current_tier": None}
