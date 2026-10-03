"""Shared bits for services."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clipper.core import Core
    from clipper.db.engine import Database
    from clipper.settings import Settings


class ServiceError(RuntimeError):
    """A domain error with a message that is safe to show to an agent or a user."""


class Service:
    def __init__(self, core: Core) -> None:
        self.core = core

    @property
    def db(self) -> Database:
        return self.core.db

    @property
    def settings(self) -> Settings:
        return self.core.settings

    def now(self) -> datetime:
        return self.core.clock.now()
