"""Time source. Everything that reads "now" takes a ``Clock`` so tests can drive time."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Protocol


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC (SQLite stores naive UTC)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return utcnow()


class FakeClock:
    """Manually advanced clock for tests."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = ensure_utc(start) if start else datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, delta: timedelta | None = None, **kwargs: float) -> datetime:
        step = delta if delta is not None else timedelta(**kwargs)
        with self._lock:
            self._now += step
            return self._now

    def set(self, value: datetime) -> None:
        with self._lock:
            self._now = ensure_utc(value)
