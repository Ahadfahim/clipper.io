"""Column types and status constants shared by the models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from clipper.clock import ensure_utc


class UTCDateTime(TypeDecorator[datetime]):
    """Stores naive UTC in SQLite, always returns timezone-aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        assert isinstance(value, datetime)
        return ensure_utc(value)


class CampaignStatus(StrEnum):
    SUGGESTED = "suggested"
    TAKEN = "taken"
    ACTIVE = "active"
    PAUSED = "paused"
    SKIPPED = "skipped"
    ENDING = "ending"
    ENDED = "ended"
    NEEDS_USER = "needs_user"
    NO_ENABLED_SOCIALS = "no_enabled_socials"


class SourceStatus(StrEnum):
    LISTED = "listed"  # named by the marketplace page; on the whitelist, not downloaded
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    FAILED = "failed"
    DELETED = "deleted"


class ClipStatus(StrEnum):
    DRAFT = "draft"
    RENDERING = "rendering"
    READY = "ready"  # proxy rendered, QA done
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FINAL = "final"  # final render done
    POSTED = "posted"
    FAILED = "failed"


class Decision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewVia(StrEnum):
    DISCORD = "discord"
    DASHBOARD = "dashboard"
    AUTO = "auto"  # opt-in auto-approve tier (PLAN §14)


class BatchStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    SHIPPED = "shipped"


class PostStatus(StrEnum):
    SCHEDULED = "scheduled"
    POSTING = "posting"
    LIVE = "live"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SIMULATED = "simulated"  # dry-run


class AccountStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"  # login/CAPTCHA/verification challenge: the user handles it by hand


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionStatus(StrEnum):
    RUNNING = "running"
    WAITING = "waiting"  # finished its turn, waiting on an event
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RequestStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    TIMED_OUT = "timed_out"


class WakeupStatus(StrEnum):
    PENDING = "pending"
    FIRED = "fired"
    CANCELLED = "cancelled"


class AgendaStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"


# Posts that occupy a slot in an account's daily cap.
CAP_COUNTED_POST_STATUSES: frozenset[str] = frozenset(
    {PostStatus.SCHEDULED, PostStatus.POSTING, PostStatus.LIVE, PostStatus.SIMULATED}
)
