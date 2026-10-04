"""On/off switches for marketplaces, socials and accounts (PLAN §15.2), with their side effects.

Switching off:
- marketplace: its active campaigns become ``ending`` ("Finish them", default: live posts still get
  submitted) or ``paused`` ("Pause them now"); its tools are denied by the guard.
- social / account: already-scheduled posts are cancelled ("Cancel N posts") or kept ("Let them post");
  campaigns whose allowed socials are all off become ``no_enabled_socials``.
Switching on runs a check first (marketplace login valid / at least one connected account).
Every change is a ``toggles.changed`` event with who made it and from where.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlmodel import col, select

from clipper.db.engine import WriteTx
from clipper.db.models import Account, Campaign, Marketplace, Platform, Post
from clipper.db.types import AccountStatus, CampaignStatus, PostStatus
from clipper.events.types import TogglesChanged
from clipper.rules.spec import ClipSpec
from clipper.services.base import Service, ServiceError

Level = Literal["marketplace", "social", "account"]
LIVE_CAMPAIGN = (CampaignStatus.ACTIVE, CampaignStatus.TAKEN)


class ToggleService(Service):
    def state(self) -> dict[str, Any]:
        with self.db.read() as s:
            markets = {
                m.id: {"enabled": m.enabled, "session_ok": m.session_ok}
                for m in s.exec(select(Marketplace)).all()
            }
            socials = {p.id: {"enabled": p.enabled} for p in s.exec(select(Platform)).all()}
            accounts = {
                str(a.id): {
                    "enabled": a.enabled,
                    "status": a.status,
                    "platform": a.platform,
                    "handle": a.handle,
                }
                for a in s.exec(select(Account)).all()
            }
        return {"marketplaces": markets, "socials": socials, "accounts": accounts}

    def preview_off(self, level: Level, name: str) -> dict[str, int]:
        """Counts for the switch-off dialog."""
        with self.db.read() as s:
            if level == "marketplace":
                n = len(
                    s.exec(
                        select(Campaign.id).where(
                            Campaign.marketplace == name, col(Campaign.status).in_(LIVE_CAMPAIGN)
                        )
                    ).all()
                )
                return {"active_campaigns": n}
            q = select(Post.id).where(Post.status == PostStatus.SCHEDULED)
            q = q.where(Post.platform == name) if level == "social" else q.where(Post.account_id == int(name))
            return {"scheduled_posts": len(s.exec(q).all())}

    def set(
        self,
        level: Level,
        name: str,
        enabled: bool,
        *,
        by: str = "user",
        via: str = "app",
        on_active: Literal["finish", "pause"] = "finish",
        on_scheduled: Literal["cancel", "keep"] = "keep",
    ) -> dict[str, Any]:
        def job(tx: WriteTx) -> dict[str, Any]:
            effects: dict[str, Any] = {}
            s = tx.session
            if level == "marketplace":
                row = s.get(Marketplace, name)
                if row is None:
                    raise ServiceError(f"unknown marketplace {name}")
                if enabled and not row.session_ok:
                    return {
                        "ok": False,
                        "needs_setup": f"log in to {row.name} in the Clipper Chrome window first",
                    }
                row.enabled = enabled
                tx.add(row)
                if not enabled:
                    camps = s.exec(
                        select(Campaign).where(
                            Campaign.marketplace == name, col(Campaign.status).in_(LIVE_CAMPAIGN)
                        )
                    ).all()
                    new_status = CampaignStatus.PAUSED if on_active == "pause" else CampaignStatus.ENDING
                    for c in camps:
                        c.status = new_status
                        tx.add(c)
                    effects = {"campaigns": [c.id for c in camps], "campaign_status": new_status}
            elif level == "social":
                row = s.get(Platform, name)
                if row is None:
                    raise ServiceError(f"unknown social {name}")
                if enabled:
                    usable = s.exec(
                        select(Account.id).where(
                            Account.platform == name,
                            col(Account.enabled),
                            Account.status == AccountStatus.ACTIVE,
                        )
                    ).first()
                    if usable is None:
                        return {"ok": False, "needs_setup": f"connect an active {row.name} account first"}
                row.enabled = enabled
                tx.add(row)
                if not enabled:
                    effects = self._posts_off(tx, Post.platform == name, on_scheduled)
                    effects["campaigns_without_socials"] = self._mark_no_socials(tx)
                else:
                    effects["campaigns_reenabled"] = self._unmark_no_socials(tx)
            else:
                row = s.get(Account, int(name))
                if row is None:
                    raise ServiceError(f"unknown account {name}")
                row.enabled = enabled
                tx.add(row)
                if not enabled:
                    effects = self._posts_off(tx, Post.account_id == int(name), on_scheduled)
            tx.publish(
                TogglesChanged(level=level, name=name, enabled=enabled, by=by, via=via, effects=effects)
            )
            return {"ok": True, "effects": effects}

        return self.db.write(job)

    def _posts_off(self, tx: WriteTx, cond: Any, on_scheduled: str) -> dict[str, Any]:
        posts = tx.session.exec(select(Post).where(Post.status == PostStatus.SCHEDULED, cond)).all()
        if on_scheduled == "cancel":
            for p in posts:
                p.status = PostStatus.CANCELLED
                p.error = "switched off"
                tx.add(p)
        return {"scheduled_posts": [p.id for p in posts], "action": on_scheduled}

    def _enabled_socials(self, tx: WriteTx) -> set[str]:
        return {p.id for p in tx.session.exec(select(Platform).where(col(Platform.enabled))).all()}

    def _allowed(self, c: Campaign) -> set[str]:
        spec = ClipSpec.model_validate(c.spec_json or {})
        allowed = set(c.platforms or ["youtube", "tiktok", "instagram", "x"])
        return allowed & set(spec.platforms) if spec.platforms else allowed

    def _mark_no_socials(self, tx: WriteTx) -> list[int]:
        enabled = self._enabled_socials(tx)
        hit: list[int] = []
        for c in tx.session.exec(
            select(Campaign).where(col(Campaign.status).in_([*LIVE_CAMPAIGN, CampaignStatus.SUGGESTED]))
        ).all():
            if not (self._allowed(c) & enabled) and c.id is not None:
                c.status = CampaignStatus.NO_ENABLED_SOCIALS
                tx.add(c)
                hit.append(c.id)
        return hit

    def _unmark_no_socials(self, tx: WriteTx) -> list[int]:
        enabled = self._enabled_socials(tx)
        hit: list[int] = []
        for c in tx.session.exec(
            select(Campaign).where(Campaign.status == CampaignStatus.NO_ENABLED_SOCIALS)
        ).all():
            if self._allowed(c) & enabled and c.id is not None:
                c.status = CampaignStatus.ACTIVE if c.taken_at else CampaignStatus.SUGGESTED
                tx.add(c)
                hit.append(c.id)
        return hit
