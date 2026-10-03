"""Publishing: schedule under the cap lock, run due uploads through the Companion extension, metrics.

On any login/CAPTCHA/verification challenge the account is paused and an alert goes out (PLAN §5).
In dry-run mode posts are marked ``simulated`` and nothing is uploaded.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlmodel import col, select

from clipper.agents.hooks import parse_when
from clipper.db.engine import WriteTx
from clipper.db.models import Account, Clip, Metric, Post, RecipeRun, Review
from clipper.db.types import CAP_COUNTED_POST_STATUSES, AccountStatus, ClipStatus, PostStatus
from clipper.events.types import AccountPaused, Alert, PostLive, PostStatusChanged
from clipper.leases import LeaseManager
from clipper.publishing.base import RECIPES, UploadRequest
from clipper.rules.caps import CapDecision, effective_daily_cap, local_day_bounds
from clipper.services.base import Service, ServiceError
from clipper.services.control import read_control
from clipper.services.posting import account_caps, schedule_post_tx


class PublishingService(Service):
    def list_accounts(self, platform: str | None = None) -> list[dict[str, Any]]:
        now = self.now()
        with self.db.read() as s:
            q = select(Account)
            if platform:
                q = q.where(Account.platform == platform)
            accounts = s.exec(q).all()
            day_start, day_end = local_day_bounds(now, self.settings.triggers.timezone)
            out: list[dict[str, Any]] = []
            for a in accounts:
                assert a.id is not None
                used = len(
                    s.exec(
                        select(Post.id).where(
                            Post.account_id == a.id,
                            col(Post.status).in_(list(CAP_COUNTED_POST_STATUSES)),
                            col(Post.scheduled_at) >= day_start,
                            col(Post.scheduled_at) < day_end,
                        )
                    ).all()
                )
                out.append(
                    {
                        "id": a.id,
                        "platform": a.platform,
                        "handle": a.handle,
                        "niche_tags": a.niche_tags,
                        "enabled": a.enabled,
                        "status": a.status,
                        "chrome_profile": a.chrome_profile,
                        "posts_today": used,
                        "cap_today": effective_daily_cap(account_caps(a), now, self.settings.posting),
                        "min_gap_min": a.min_gap_min
                        if a.min_gap_min is not None
                        else self.settings.posting.min_gap_min,
                    }
                )
        return out

    def schedule(
        self,
        clip_id: int,
        account_id: int,
        when: str | datetime | None,
        *,
        copy: dict[str, str] | None = None,
        created_by: str | None = None,
    ) -> Post:
        at = when if isinstance(when, datetime) else parse_when(when, self.now())
        if at is None:
            raise ServiceError("scheduled_at must be an ISO-8601 time or 'now'")
        at = max(at, self.now())
        with self.db.read() as s:
            clip = s.get(Clip, clip_id)
            if clip is None:
                raise ServiceError(f"clip {clip_id} not found")
            review = s.get(Review, clip_id)
            account = s.get(Account, account_id)
            if account is None:
                raise ServiceError(f"account {account_id} not found")
        if copy is None and review is not None:
            caption = review.captions_json.get(account.platform)
            copy = {"caption": caption} if isinstance(caption, str) else {}
        dry = read_control(self.db).dry_run
        res = self.db.write(
            lambda tx: schedule_post_tx(
                tx,
                clip_id=clip_id,
                account_id=account_id,
                scheduled_at=at,
                settings=self.settings,
                campaign_id=clip.campaign_id,
                copy=copy or {},
                dry_run=dry,
                created_by=created_by,
            )
        )
        if isinstance(res, CapDecision):
            raise ServiceError(res.reason)
        if not clip.path:
            self.core.media.request_final(clip_id)  # final render only for approved clips (PLAN §18.1)
        return res

    def cancel(self, post_id: int, *, by: str) -> None:
        def job(tx: WriteTx) -> None:
            post = tx.session.get(Post, post_id)
            if post is None:
                raise ServiceError(f"post {post_id} not found")
            if post.status not in (PostStatus.SCHEDULED, PostStatus.FAILED):
                raise ServiceError(f"post {post_id} is {post.status}; only scheduled posts can be cancelled")
            post.status = PostStatus.CANCELLED
            post.error = f"cancelled by {by}"
            tx.add(post)
            tx.publish(PostStatusChanged(post_id=post_id, status=post.status))

        self.db.write(job)

    # ------------------------------------------------------------ running uploads

    def due_posts(self) -> list[int]:
        with self.db.read() as s:
            rows = s.exec(
                select(Post.id)
                .where(Post.status == PostStatus.SCHEDULED, col(Post.scheduled_at) <= self.now())
                .order_by(col(Post.scheduled_at))
            ).all()
            return [r for r in rows if r is not None]

    def _set_post(self, post_id: int, **fields: Any) -> None:
        def job(tx: WriteTx) -> None:
            post = tx.session.get(Post, post_id)
            assert post is not None
            for k, v in fields.items():
                setattr(post, k, v)
            tx.add(post)
            tx.publish(PostStatusChanged(post_id=post_id, status=post.status, error=post.error))

        self.db.write(job)

    async def run_due(self) -> list[int]:
        """Upload every due post (one at a time per Chrome profile and account). Returns posts handled."""
        control = read_control(self.db)
        if control.kill_switch or control.paused:
            return []
        handled: list[int] = []
        leases = LeaseManager(self.db, self.core.clock)
        for post_id in self.due_posts():
            with self.db.read() as s:
                post = s.get(Post, post_id)
                assert post is not None
                account = s.get(Account, post.account_id)
                clip = s.get(Clip, post.clip_id)
            if account is None or clip is None:
                self._set_post(post_id, status=PostStatus.FAILED, error="account or clip missing")
                continue
            if not account.enabled or account.status != AccountStatus.ACTIVE:
                continue  # stays scheduled until the account is back (or the user cancels)
            if not clip.path and not (post.dry_run or control.dry_run):
                continue  # final render still running
            holder = f"post:{post_id}"
            if not leases.acquire(f"account:{account.id}", holder, ttl_s=900):
                continue
            try:
                await self._upload_one(post, account, clip, dry_run=post.dry_run or control.dry_run)
                handled.append(post_id)
            finally:
                leases.release(f"account:{account.id}", holder)
        return handled

    async def _upload_one(self, post: Post, account: Account, clip: Clip, *, dry_run: bool) -> None:
        assert post.id is not None and account.id is not None and clip.id is not None
        recipe = RECIPES.get(post.platform, f"{post.platform}.upload")
        if dry_run:
            url = f"https://dry-run.invalid/{post.platform}/{post.id}"
            self._finish_live(post, url, dry_run=True)
            self.db.write(
                lambda tx: tx.add(RecipeRun(recipe=recipe, account_id=account.id, ok=True, dry_run=True))
            )
            return
        self._set_post(post.id, status=PostStatus.POSTING)
        copy = dict(post.copy_json)
        req = UploadRequest(
            platform=post.platform,
            account_id=account.id,
            handle=account.handle,
            chrome_profile=account.chrome_profile,
            video=Path(clip.path or ""),
            title=copy.get("title", ""),
            caption=copy.get("caption", ""),
            hashtags=[t for t in copy.get("hashtags", "").split() if t.startswith("#")],
        )
        try:
            res = await self.core.adapters.publisher.upload(req)
        except Exception as exc:
            _ok, err, challenge, shot = False, f"{type(exc).__name__}: {exc}", None, None
        else:
            _ok, err, challenge, shot = res.ok, res.error, res.challenge, res.screenshot
            if res.ok and res.url:
                self.db.write(lambda tx: tx.add(RecipeRun(recipe=recipe, account_id=account.id, ok=True)))
                self._finish_live(post, res.url, dry_run=False)
                return
        shot_path = self._save_screenshot(shot, f"post_{post.id}") if shot else None
        self.db.write(
            lambda tx: tx.add(
                RecipeRun(
                    recipe=recipe, account_id=account.id, ok=False, error=err, screenshot_path=shot_path
                )
            )
        )
        if challenge:
            self.pause_account(account.id, f"{challenge} challenge during upload")
            self._set_post(post.id, status=PostStatus.SCHEDULED, error=f"paused: {challenge}")
        else:
            self._set_post(post.id, status=PostStatus.FAILED, error=err or "upload failed")
            self.core.notify.alert(
                "error", f"Upload failed on {account.handle} ({post.platform}): {err}", source="publish"
            )

    def _save_screenshot(self, data_url: str, name: str) -> str | None:
        import base64

        if not data_url.startswith("data:image/") or "," not in data_url:
            return None
        raw = base64.b64decode(data_url.split(",", 1)[1] or "")
        if not raw:
            return None
        path = self.core.dir("screenshots") / f"{name}_{int(self.now().timestamp())}.png"
        path.write_bytes(raw)
        return str(path)

    def _finish_live(self, post: Post, url: str, *, dry_run: bool) -> None:
        assert post.id is not None
        status = PostStatus.SIMULATED if dry_run else PostStatus.LIVE

        def job(tx: WriteTx) -> None:
            p = tx.session.get(Post, post.id)
            assert p is not None
            p.status = status
            p.url = url
            p.posted_at = self.now()
            p.dry_run = dry_run
            tx.add(p)
            clip = tx.session.get(Clip, p.clip_id)
            if clip is not None:
                clip.status = ClipStatus.POSTED
                tx.add(clip)
            tx.publish(PostStatusChanged(post_id=p.id or 0, status=status))
            tx.publish(
                PostLive(
                    post_id=p.id or 0,
                    clip_id=p.clip_id,
                    campaign_id=p.campaign_id,
                    platform=p.platform,
                    url=url,
                    dry_run=dry_run,
                )
            )

        self.db.write(job)

    def pause_account(self, account_id: int, reason: str) -> None:
        def job(tx: WriteTx) -> None:
            a = tx.session.get(Account, account_id)
            if a is None:
                return
            a.status = AccountStatus.PAUSED
            a.paused_reason = reason
            tx.add(a)
            tx.publish(AccountPaused(account_id=account_id, reason=reason))
            tx.publish(
                Alert(
                    level="warning",
                    text=f"{a.handle} ({a.platform}) paused: {reason}. Fix it in the Clipper Chrome window, then resume.",
                    source="publish",
                )
            )

        self.db.write(job)

    def resume_account(self, account_id: int) -> None:
        def job(tx: WriteTx) -> None:
            a = tx.session.get(Account, account_id)
            if a is None:
                raise ServiceError(f"account {account_id} not found")
            a.status = AccountStatus.ACTIVE
            a.paused_reason = None
            tx.add(a)

        self.db.write(job)

    # ------------------------------------------------------------ metrics

    async def refresh_metrics(self, post_id: int) -> dict[str, Any]:
        with self.db.read() as s:
            post = s.get(Post, post_id)
            if post is None or not post.url:
                raise ServiceError(f"post {post_id} has no URL yet")
            url, dry = post.url, post.dry_run
        if dry:
            return {"post_id": post_id, "views": 0, "dry_run": True}
        m = await self.core.adapters.publisher.metrics(url)
        now = self.now()
        self.db.write(
            lambda tx: tx.add(
                Metric(
                    post_id=post_id,
                    ts=now,
                    views=m.views,
                    likes=m.likes,
                    comments=m.comments,
                    shares=m.shares,
                )
            )
        )
        return {
            "post_id": post_id,
            "views": m.views,
            "likes": m.likes,
            "comments": m.comments,
            "shares": m.shares,
        }

    async def account_health(self, account_id: int) -> dict[str, Any]:
        with self.db.read() as s:
            a = s.get(Account, account_id)
            if a is None:
                raise ServiceError(f"account {account_id} not found")
            platform, handle = a.platform, a.handle
        h = await self.core.adapters.publisher.account_health(platform, handle)
        return {
            "account_id": account_id,
            "followers": h.followers,
            "recent_views": h.recent_views,
            "warnings": h.warnings,
        }

    def posts(self, *, since: datetime | None = None, until: datetime | None = None) -> list[Post]:
        since = since or self.now() - timedelta(days=1)
        until = until or self.now() + timedelta(days=7)
        with self.db.read() as s:
            return list(
                s.exec(
                    select(Post)
                    .where(col(Post.scheduled_at) >= since, col(Post.scheduled_at) < until)
                    .order_by(col(Post.scheduled_at))
                ).all()
            )
