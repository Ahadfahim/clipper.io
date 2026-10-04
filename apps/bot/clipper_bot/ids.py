"""Stable ``custom_id``s for every persistent component.

Buttons keep working after a bot restart because the id carries everything the handler needs
(``clipper:<scope>:<action>:<entity id>``) and the bot registers ``DynamicItem`` templates for
each pattern on start (components.py). Ids stay short: Discord allows 100 characters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PREFIX = "clipper"


@dataclass(frozen=True)
class ParsedId:
    scope: str
    action: str
    entity: int
    extra: str | None = None


def make(scope: str, action: str, entity: int, extra: str | int | None = None) -> str:
    cid = f"{PREFIX}:{scope}:{action}:{entity}"
    if extra is not None:
        cid += f":{extra}"
    if len(cid) > 100:
        raise ValueError("custom_id too long")
    return cid


ID_RE = re.compile(
    rf"^{PREFIX}:(?P<scope>[a-z]+):(?P<action>[a-z_]+):(?P<entity>\d+)(?::(?P<extra>[\w-]+))?$"
)


def parse(custom_id: str) -> ParsedId | None:
    m = ID_RE.match(custom_id)
    if not m:
        return None
    return ParsedId(m["scope"], m["action"], int(m["entity"]), m["extra"])


def template(scope: str, action: str, extra: bool = False) -> str:
    """Regex for a DynamicItem; named groups ``id`` (and ``extra``)."""
    base = rf"{PREFIX}:{scope}:{action}:(?P<id>\d+)"
    return base + (r":(?P<extra>[\w-]+)" if extra else "") + "$"


# the persistent components
CAMPAIGN_TAKE = ("campaign", "take")
CAMPAIGN_SKIP = ("campaign", "skip")
CLIP_APPROVE = ("clip", "approve")
CLIP_REJECT = ("clip", "reject")  # opens the reason picker
CLIP_REASON = ("clip", "reason")  # select with the reasons
CLIP_CAPTION = ("clip", "caption")  # opens the caption modal
CLIP_RECUT = ("clip", "recut")  # opens the re-cut modal
CLIP_PLATFORMS = ("clip", "platforms")  # select
BATCH_SHIP = ("batch", "ship")
BATCH_APPROVE_ALL = ("batch", "approveall")
BATCH_REJECT_REST = ("batch", "rejectrest")
QUESTION_ANSWER = ("question", "answer")  # extra = option index
