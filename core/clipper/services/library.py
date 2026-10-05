"""The Library: scrap clips you don't want, restore them, and delete their files later.

To **scrap** a clip is to throw it away. It leaves the Library, it can never be posted, the agents learn
from it (it counts as a rejection with your reason), and its files are deleted after a grace period.
Until then it can be restored. Clips that are posted can't be scrapped: their records feed submissions
and earnings. They can be hidden from the Library instead.

Every rule here is enforced in code. The guard (agents/hooks.py), ``schedule_post_tx``, the due-post
runner, the EDL service and ``render_moment`` all refuse a scrapped clip, so none of them depends on
the Library screen being used.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlmodel import col, select

from clipper.clock import ensure_utc
from clipper.db.engine import WriteTx
from clipper.db.models import Campaign, Clip, Edl, Job, Moment, Post, Review
from clipper.db.types import ClipStatus
from clipper.events.types import ClipPurged, ClipRestored, ClipScrapped, ClipUpdated
from clipper.services.base import Service, ServiceError
from clipper.services.control import kv_get, kv_set_tx

MAX_BATCH = 500
OLD_REJECT_DAYS = 14
PURGE_KEY = "library.purge.date"
SCRAPPABLE = {
    ClipStatus.DRAFT,
    ClipStatus.RENDERING,
    ClipStatus.READY,
    ClipStatus.IN_REVIEW,
    ClipStatus.APPROVED,
    ClipStatus.REJECTED,
    ClipStatus.FINAL,
    ClipStatus.FAILED,
}
_VERSION = re.compile(r"_v(\d+)")


@dataclass
class ScrapCheck:
    id: int
    can_scrap: bool
    blocked_reason: str | None = None
    status: str = ""
    hook: str = ""
    scheduled_posts: list[int] = field(default_factory=list[int])
    in_batch: int | None = None
    editing_by: str | None = None
    variants: list[int] = field(default_factory=list[int])
    bytes: int = 0


@dataclass
class CleanupGroup:
    key: str
    label: str
    clip_ids: list[int]
    bytes: int
    action: str  # scrap | delete_files


def _size(path: Path) -> int:
    try:
        if path.is_dir():
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return path.stat().st_size
    except OSError:
        return 0


class LibraryService(Service):
    # ------------------------------------------------------------ the files a clip owns

    def _roots(self) -> dict[str, Path]:
        return {name: self.core.dir(name) for name in ("previews", "clips", "work")}

    def clip_paths(self, clip_id: int) -> list[Path]:
        """Every file and folder that belongs to a clip, built from its id under the data folders (never
        from a path stored in the database). All versions."""
        roots = self._roots()
        found: list[Path] = []
        found += sorted(roots["previews"].glob(f"clip_{clip_id}_v*"))
        found += sorted(roots["clips"].glob(f"clip_{clip_id}_v*"))
        found += sorted(roots["work"].glob(f"clip_{clip_id}_v*"))
        for extra in (f"frames_clip{clip_id}", f"sheet_clip{clip_id}"):
            if (roots["work"] / extra).exists():
                found.append(roots["work"] / extra)
        return found

    def _version_of(self, path: Path) -> int | None:
        m = _VERSION.search(path.name)
        return int(m.group(1)) if m else None

    def clip_bytes(self, clip_id: int) -> int:
        return sum(_size(p) for p in self.clip_paths(clip_id))

    def _delete(self, path: Path) -> int:
        """Delete one path, only if it is inside the data folders. Returns the bytes freed."""
        resolved = path.resolve()
        if not any(
            resolved.is_relative_to(root.resolve()) and resolved != root.resolve()
            for root in self._roots().values()
        ):
            return 0
        size = _size(path)
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        return size

    # ------------------------------------------------------------ checks

    def check(self, clip_ids: list[int], *, include_variants: bool = True) -> list[ScrapCheck]:
        """What scrapping these clips would do, clip by clip (the confirm dialog is built from this)."""
        ids = self._expand(clip_ids, include_variants)
        out: list[ScrapCheck] = []
        with self.db.read() as s:
            for cid in ids:
                clip = s.get(Clip, cid)
                if clip is None:
                    out.append(ScrapCheck(cid, False, "no such clip"))
                    continue
                moment = s.get(Moment, clip.moment_id)
                review = s.get(Review, cid)
                edl = s.get(Edl, cid)
                posts = s.exec(select(Post).where(Post.clip_id == cid)).all()
                variants = s.exec(select(Clip.id).where(Clip.variant_of == cid)).all()
                running = [
                    j
                    for j in s.exec(
                        select(Job).where(
                            Job.status == "running", col(Job.kind).in_(["render_preview", "render_final"])
                        )
                    ).all()
                    if j.input_json.get("clip_id") == cid
                ]
                check = ScrapCheck(
                    id=cid,
                    can_scrap=True,
                    status=clip.status,
                    hook=moment.hook if moment else "",
                    scheduled_posts=[p.id for p in posts if p.status == "scheduled" and p.id is not None],
                    in_batch=review.batch_id if review and review.decision == "pending" else None,
                    editing_by=edl.locked_by if edl and edl.locked_by and edl.locked_by != "user" else None,
                    variants=[v for v in variants if v is not None],
                    bytes=self.clip_bytes(cid),
                )
                if clip.status == ClipStatus.SCRAPPED:
                    check.can_scrap, check.blocked_reason = False, "already scrapped"
                elif clip.status == ClipStatus.POSTED or any(
                    p.status in ("live", "simulated") for p in posts
                ):
                    check.can_scrap = False
                    check.blocked_reason = (
                        "Can't scrap a posted clip: its post counts toward earnings. Hide it instead."
                    )
                elif any(p.status == "posting" for p in posts):
                    check.can_scrap, check.blocked_reason = (
                        False,
                        "An upload of this clip is running. Try again when it finishes.",
                    )
                elif running:
                    check.can_scrap, check.blocked_reason = (
                        False,
                        "A render of this clip is running. Try again when it finishes.",
                    )
                elif clip.status not in SCRAPPABLE:
                    check.can_scrap, check.blocked_reason = False, f"a {clip.status} clip can't be scrapped"
                out.append(check)
        return out

    def _expand(self, clip_ids: list[int], include_variants: bool) -> list[int]:
        if len(clip_ids) > MAX_BATCH:
            raise ServiceError(f"scrap at most {MAX_BATCH} clips at once")
        ids = list(dict.fromkeys(clip_ids))
        if include_variants and ids:
            with self.db.read() as s:
                more = s.exec(select(Clip.id).where(col(Clip.variant_of).in_(ids))).all()
            ids += [m for m in more if m is not None and m not in ids]
        return ids

    # ------------------------------------------------------------ scrap

    def scrap(
        self,
        clip_ids: list[int],
        *,
        reason: str | None = None,
        include_variants: bool = True,
        cancel_posts: bool = False,
        by: str = "user",
        via: str = "dashboard",
    ) -> dict[str, Any]:
        checks = self.check(clip_ids, include_variants=include_variants)
        refused: list[dict[str, Any]] = []
        todo: list[ScrapCheck] = []
        for c in checks:
            if not c.can_scrap:
                refused.append({"id": c.id, "reason": c.blocked_reason or "can't be scrapped"})
            elif c.scheduled_posts and not cancel_posts:
                refused.append(
                    {
                        "id": c.id,
                        "reason": f"{len(c.scheduled_posts)} scheduled post(s): scrap with Cancel its posts",
                    }
                )
            else:
                todo.append(c)
        if not todo:
            return {"scrapped": [], "refused": refused, "bytes": 0}
        for c in todo:
            for post_id in c.scheduled_posts:
                self.core.publishing.cancel(post_id, by=by)
            self._cancel_queued_renders(c.id)
        now = self.now()
        why = (reason or "").strip()[:200] or None

        def job(tx: WriteTx) -> list[int]:
            done: list[int] = []
            by_campaign: dict[int | None, list[int]] = {}
            for c in todo:
                clip = tx.session.get(Clip, c.id)
                if clip is None or clip.status == ClipStatus.SCRAPPED:
                    continue
                review = tx.session.get(Review, c.id)
                clip.scrap_json = {
                    "status": clip.status,
                    "decision": review.decision if review else None,
                    "reason": review.reason if review else None,
                    "via": review.via if review else None,
                    "reviewer": review.reviewer if review else None,
                }
                clip.status = ClipStatus.SCRAPPED
                clip.scrapped_at, clip.scrapped_by, clip.scrap_reason = now, by, why
                clip.updated_at = now
                tx.add(clip)
                # it counts as a rejection with your reason: the agents learn from it, and a pending clip
                # no longer holds its review batch up
                if review is None:
                    review = Review(clip_id=c.id)
                review.decision = "rejected"
                review.reason = f"scrapped: {why}" if why else "scrapped"
                review.reviewer, review.via, review.decided_at = by, via, now
                tx.add(review)
                moment = tx.session.get(Moment, clip.moment_id)
                if moment is not None:
                    moment.scrapped = True
                    tx.add(moment)
                edl = tx.session.get(Edl, c.id)
                if edl is not None:
                    edl.locked_by = "user"  # an agent in the middle of an edit stops
                    tx.add(edl)
                by_campaign.setdefault(clip.campaign_id, []).append(c.id)
                tx.publish(
                    ClipUpdated(
                        clip_id=c.id,
                        status=ClipStatus.SCRAPPED,
                        campaign_id=clip.campaign_id,
                        version=clip.version,
                    )
                )
                done.append(c.id)
            for campaign_id, ids in by_campaign.items():
                tx.publish(ClipScrapped(clip_ids=ids, campaign_id=campaign_id, reason=why, by=by, via=via))
            return done

        done = self.db.write(job)
        return {"scrapped": done, "refused": refused, "bytes": sum(c.bytes for c in todo if c.id in done)}

    def _cancel_queued_renders(self, clip_id: int) -> None:
        with self.db.read() as s:
            queued = [
                j.id
                for j in s.exec(
                    select(Job).where(
                        Job.status == "queued", col(Job.kind).in_(["render_preview", "render_final"])
                    )
                ).all()
                if j.id is not None and j.input_json.get("clip_id") == clip_id
            ]
        for job_id in queued:
            self.core.jobs.cancel(job_id)

    # ------------------------------------------------------------ restore

    def restore(self, clip_ids: list[int], *, by: str = "user") -> dict[str, Any]:
        restored: list[int] = []
        refused: list[dict[str, Any]] = []

        def job(tx: WriteTx) -> None:
            campaigns: dict[int | None, list[int]] = {}
            for cid in dict.fromkeys(clip_ids):
                clip = tx.session.get(Clip, cid)
                if clip is None or clip.status != ClipStatus.SCRAPPED:
                    refused.append({"id": cid, "reason": "isn't scrapped"})
                    continue
                if clip.files_purged_at is not None:
                    refused.append({"id": cid, "reason": "This clip's files were deleted."})
                    continue
                before = dict(clip.scrap_json or {})
                clip.status = str(before.get("status") or ClipStatus.READY)
                clip.scrapped_at = clip.scrapped_by = clip.scrap_reason = None
                clip.scrap_json = {}
                clip.updated_at = self.now()
                tx.add(clip)
                review = tx.session.get(Review, cid)
                if review is not None:
                    if before.get("decision") is None:
                        tx.session.delete(review)
                    else:
                        review.decision = str(before["decision"])
                        review.reason = before.get("reason")
                        review.via, review.reviewer = before.get("via"), before.get("reviewer")
                        tx.add(review)
                moment = tx.session.get(Moment, clip.moment_id)
                if moment is not None:
                    others = tx.session.exec(
                        select(Clip).where(
                            Clip.moment_id == moment.id, Clip.status == ClipStatus.SCRAPPED, Clip.id != cid
                        )
                    ).first()
                    moment.scrapped = others is not None
                    tx.add(moment)
                edl = tx.session.get(Edl, cid)
                if edl is not None and edl.locked_by == "user":
                    edl.locked_by = None
                    tx.add(edl)
                tx.publish(
                    ClipUpdated(
                        clip_id=cid, status=clip.status, campaign_id=clip.campaign_id, version=clip.version
                    )
                )
                campaigns.setdefault(clip.campaign_id, []).append(cid)
                restored.append(cid)
            for campaign_id, ids in campaigns.items():
                tx.publish(ClipRestored(clip_ids=ids, campaign_id=campaign_id, by=by))

        self.db.write(job)
        return {"restored": restored, "refused": refused}

    # ------------------------------------------------------------ purge

    def purge(self, clip_ids: list[int] | None = None, *, expired_only: bool = False) -> dict[str, Any]:
        """Delete the files of scrapped clips (everything but the thumbnail). The rows stay."""
        now = self.now()
        days = self.settings.retention.scrapped_clip_days
        with self.db.read() as s:
            q = select(Clip).where(Clip.status == ClipStatus.SCRAPPED, col(Clip.files_purged_at).is_(None))
            if clip_ids is not None:
                q = q.where(col(Clip.id).in_(clip_ids))
            rows = list(s.exec(q).all())
        if expired_only:
            rows = [
                c
                for c in rows
                if c.scrapped_at is not None and ensure_utc(c.scrapped_at) + timedelta(days=days) <= now
            ]
        freed = 0
        purged: list[int] = []
        for clip in rows:
            assert clip.id is not None
            keep: set[Path] = {Path(clip.thumb_path).resolve()} if clip.thumb_path else set()
            for path in self.clip_paths(clip.id):
                if path.resolve() in keep:
                    continue
                freed += self._delete(path)
            purged.append(clip.id)
        if purged:

            def job(tx: WriteTx) -> None:
                for cid in purged:
                    row = tx.session.get(Clip, cid)
                    if row is not None:
                        row.files_purged_at = now
                        row.preview_path = row.path = None  # the files are gone
                        tx.add(row)
                tx.publish(ClipPurged(clip_ids=purged, bytes_freed=freed))

            self.db.write(job)
        return {"clips": purged, "bytes": freed}

    def purge_expired_daily(self) -> dict[str, Any] | None:
        """Once per local day (called by the supervisor's tick): delete files whose grace period is over."""
        from clipper.rules.caps import local_day_bounds

        today = local_day_bounds(self.now(), self.settings.triggers.timezone)[0].date().isoformat()
        if kv_get(self.db, PURGE_KEY) == today:
            return None
        self.db.write(lambda tx: kv_set_tx(tx, PURGE_KEY, today))
        return self.purge(expired_only=True)

    def purge_old_versions(self, clip_ids: list[int]) -> dict[str, Any]:
        """Delete the render files of versions that aren't a clip's current one. The clips stay, and so
        does the edit history: Edit renders a version again when it is needed."""
        freed = 0
        touched: list[int] = []
        with self.db.read() as s:
            clips = [s.get(Clip, c) for c in clip_ids]
        for clip in clips:
            if clip is None or clip.id is None or clip.version <= 1:
                continue
            for path in self.clip_paths(clip.id):
                v = self._version_of(path)
                if v is not None and v < clip.version and path.suffix != ".jpg":
                    freed += self._delete(path)
            touched.append(clip.id)
        return {"clips": touched, "bytes": freed}

    # ------------------------------------------------------------ hide

    def hide(self, clip_ids: list[int], hidden: bool) -> list[int]:
        def job(tx: WriteTx) -> list[int]:
            done: list[int] = []
            for cid in dict.fromkeys(clip_ids):
                clip = tx.session.get(Clip, cid)
                if clip is not None and clip.status != ClipStatus.SCRAPPED:
                    clip.hidden = hidden
                    tx.add(clip)
                    done.append(cid)
            return done

        return self.db.write(job)

    # ------------------------------------------------------------ clean up

    def cleanup_groups(self) -> list[CleanupGroup]:
        """Things worth throwing away, grouped, each with the space it would free."""
        now = self.now()
        with self.db.read() as s:
            clips = [c for c in s.exec(select(Clip)).all() if c.status != ClipStatus.SCRAPPED]
            camps = {c.id: c for c in s.exec(select(Campaign)).all()}
            reviews = {r.clip_id: r for r in s.exec(select(Review)).all()}
            posted = {
                p.clip_id
                for p in s.exec(select(Post)).all()
                if p.status in ("live", "simulated", "scheduled", "posting")
            }
        groups: list[CleanupGroup] = []

        def add(key: str, label: str, ids: list[int], action: str = "scrap") -> None:
            if ids:
                groups.append(CleanupGroup(key, label, ids, sum(self.clip_bytes(i) for i in ids), action))

        def safe(c: Clip) -> bool:
            return (
                c.id is not None
                and c.id not in posted
                and c.status
                not in (ClipStatus.POSTED, ClipStatus.APPROVED, ClipStatus.FINAL, ClipStatus.RENDERING)
            )

        add(
            "ended_unreviewed",
            "Unreviewed clips of ended or skipped campaigns",
            [
                c.id
                for c in clips
                if c.id is not None
                and safe(c)
                and camps.get(c.campaign_id) is not None
                and camps[c.campaign_id].status in ("ended", "skipped")
                and (c.id not in reviews or reviews[c.id].decision == "pending")
            ],
        )
        add(
            "old_rejected",
            f"Rejected more than {OLD_REJECT_DAYS} days ago",
            [
                c.id
                for c in clips
                if c.id is not None
                and safe(c)
                and c.id in reviews
                and reviews[c.id].decision == "rejected"
                and reviews[c.id].decided_at is not None
                and now - ensure_utc(reviews[c.id].decided_at) > timedelta(days=OLD_REJECT_DAYS)  # type: ignore[arg-type]
            ],
        )
        add(
            "failed_renders",
            "Failed renders",
            [c.id for c in clips if c.id is not None and c.status == ClipStatus.FAILED and safe(c)],
        )
        old: list[int] = []
        old_bytes = 0
        for c in clips:
            if c.id is None or c.version <= 1:
                continue
            size = sum(
                _size(p)
                for p in self.clip_paths(c.id)
                if (self._version_of(p) or c.version) < c.version and p.suffix != ".jpg"
            )
            if size:
                old.append(c.id)
                old_bytes += size
        if old:
            groups.append(
                CleanupGroup(
                    "old_versions",
                    "Render files of old versions (the clips stay)",
                    old,
                    old_bytes,
                    "delete_files",
                )
            )
        return groups
