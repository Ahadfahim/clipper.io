r"""The running core logs clipper.* to the console and to data\logs\core.log."""

from __future__ import annotations

import logging
from collections.abc import Generator

import pytest

from clipper.logs import setup_logging
from clipper.settings import Settings


@pytest.fixture
def clean_clipper_logger() -> Generator[logging.Logger]:
    root = logging.getLogger("clipper")
    before = (list(root.handlers), root.level, root.propagate)
    yield root
    for h in root.handlers:
        if h not in before[0]:
            h.close()
    root.handlers, root.level, root.propagate = before


def test_writes_core_log_once(settings: Settings, clean_clipper_logger: logging.Logger) -> None:
    setup_logging(settings)
    setup_logging(settings)  # idempotent
    assert len([h for h in clean_clipper_logger.handlers if (h.get_name() or "").startswith("clipper.")]) == 2
    logging.getLogger("clipper.browser.bridge").info("Companion main connected")
    for h in clean_clipper_logger.handlers:
        h.flush()
    log = (settings.paths.sub("logs") / "core.log").read_text(encoding="utf-8")
    assert "clipper.browser.bridge: Companion main connected" in log
