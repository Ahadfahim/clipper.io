"""The core and the Companion extension agree: protocol version, recipe names, recipe params,
and how scraped campaign rows are read."""

from __future__ import annotations

import json
import re
from pathlib import Path

from clipper.browser.protocol import PROTOCOL_VERSION
from clipper.marketplaces.browser import card_from_row
from clipper.publishing.base import RECIPES

EXT = Path(__file__).resolve().parents[1] / "apps" / "extension"


def _recipes() -> dict[str, dict[str, object]]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in (EXT / "recipes").glob("*.json")
        if p.name != "schema.json"
    }


def test_protocol_versions_match() -> None:
    ts = (EXT / "src" / "shared" / "protocol.ts").read_text(encoding="utf-8")
    m = re.search(r"PROTOCOL_VERSION = (\d+);", ts)
    assert m and int(m.group(1)) == PROTOCOL_VERSION


def test_every_recipe_the_core_calls_ships_with_the_extension() -> None:
    have = _recipes()
    needed = [RECIPES[p] for p in ("youtube", "tiktok", "instagram")]  # x.post_video arrives in phase 5
    needed += [
        f"{m}.{r}" for m in ("vyro", "whop") for r in ("list_campaigns", "submit_url", "session_check")
    ]
    missing = [n for n in needed if n not in have]
    assert not missing, missing
    for name, r in have.items():
        assert r["status"] == "UNVERIFIED", name  # nothing has been run against the real sites yet


def test_upload_recipes_take_the_params_the_publisher_sends() -> None:
    sent = {
        "file_url",
        "file_name",
        "title",
        "caption",
        "hashtags",
        "schedule_at",
        "handle",
    }  # publishing/browser.py
    for name in (RECIPES[p] for p in ("youtube", "tiktok", "instagram")):
        params = set(_recipes()[name]["params"])  # type: ignore[arg-type]
        assert sent <= params, (name, sent - params)


def test_scraped_rows_are_normalized() -> None:
    card = card_from_row(
        "whop",
        {
            "id": "abc",
            "title": "Podcast cuts",
            "cpm": "2.50",
            "budget_left": "7,200",
            "platforms": "YouTube, TikTok / Reels",
            "join": "Join free",
        },
    )
    assert card.allowed_platforms == ["youtube", "tiktok", "instagram"]
    assert card.join == "free" and card.cpm_usd == 2.5
    assert card_from_row("whop", {"id": "x", "join": "Joined"}).join == "joined"
    assert card_from_row("whop", {"id": "x", "join": "Join · $29"}).join == "paid"
    assert card_from_row("vyro", {"id": "x", "platforms": ["youtube", "myspace"]}).allowed_platforms == [
        "youtube"
    ]
