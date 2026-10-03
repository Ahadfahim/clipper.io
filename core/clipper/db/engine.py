"""Engine and writer queue (implemented in WP1)."""

from __future__ import annotations

from pathlib import Path


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def close(self) -> None:
        return None
