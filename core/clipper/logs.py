"""Logging for the running core: ``clipper.*`` at INFO to the console and to ``<data>\\logs\\core.log``
(rotated at midnight, ``retention.logs_days`` files kept). Tests don't call this."""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

from clipper.settings import Settings

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(settings: Settings) -> None:
    root = logging.getLogger("clipper")
    if any((h.get_name() or "").startswith("clipper.") for h in root.handlers):
        return  # already set up (the API restarted in-process)
    root.setLevel(logging.INFO)
    root.propagate = False
    fmt = logging.Formatter(FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    logs = settings.paths.sub("logs")
    logs.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        TimedRotatingFileHandler(
            logs / "core.log",
            when="midnight",
            backupCount=settings.retention.logs_days,
            encoding="utf-8",
            delay=True,
        ),
    ]
    for i, h in enumerate(handlers):
        h.set_name(f"clipper.{i}")
        h.setFormatter(fmt)
        root.addHandler(h)
