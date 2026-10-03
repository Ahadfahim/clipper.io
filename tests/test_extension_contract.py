"""The core and the Companion extension agree: protocol version, recipe names, recipe params,
and how scraped campaign rows are read."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from clipper.browser.bridge import FakeBrowserBridge
from clipper.browser.protocol import PROTOCOL_VERSION, RecipeResult, decode_screenshot
from clipper.marketplaces.browser import RecipeMarketplace, card_from_row
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


def test_vyro_rows_as_the_real_site_gives_them() -> None:
    # what vyro.list_campaigns read on app.vyro.com (2026-10-03)
    card = card_from_row(
        "vyro",
        {
            "creator": "MrBeast",
            "card_title": "Eat Everything In A Grocery Store, Win $1,000,000",
            "opened_url": "https://app.vyro.com/campaigns?c=i-built-a-city-to-save-kids-inwLNld-",
            "id": "i-built-a-city-to-save-kids-inwLNld-",
            "title": "Eat Everything In A Grocery Store, Win $1,000,000",
            "deadline": "October 17, 2026, 09:10:00",
            "cpm": "1.00",
            "paid_out_pct": "7",
            "platforms": "TikTok, YouTube, Instagram",
            "join": "Join campaign",
        },
    )
    assert card.external_id == "i-built-a-city-to-save-kids-inwLNld-"
    assert card.url == "https://app.vyro.com/campaigns?c=i-built-a-city-to-save-kids-inwLNld-"
    assert card.creator == "MrBeast" and card.cpm_usd == 1.0 and card.join == "free"
    assert card.allowed_platforms == ["tiktok", "youtube", "instagram"]
    # shown in this PC's time zone
    assert card.deadline == datetime(2026, 10, 17, 9, 10).astimezone(UTC)
    assert card_from_row("vyro", {"id": "x", "join": "Submit post"}).join == "joined"


async def test_vyro_campaign_detail_drops_vyros_own_links() -> None:
    bridge = FakeBrowserBridge(
        recipes={
            "vyro.get_campaign": RecipeResult(
                ok=True,
                data={
                    "campaign": {"title": "Cinematic edits", "cpm": "1.50", "platforms": "TikTok"},
                    "rules_text": "Make cinematic edits. Required hashtags #ketoneiq",
                    "sources": ["https://f.io/abc", "https://www.vyro.com/content-requirements", 7],
                    "page_url": "https://app.vyro.com/campaigns?c=cinematic-edits-njQgl-gP",
                },
            )
        }
    )
    detail = await RecipeMarketplace("vyro", bridge).get_campaign("cinematic-edits-njQgl-gP")
    assert detail.sources == ["https://f.io/abc"]
    assert detail.card.external_id == "cinematic-edits-njQgl-gP" and detail.card.cpm_usd == 1.5
    assert detail.card.url == "https://app.vyro.com/campaigns?c=cinematic-edits-njQgl-gP"


def test_screenshots_decode_as_jpeg_or_png() -> None:
    import base64

    jpeg = b"\xff\xd8\xff\xe0jpeg"
    assert decode_screenshot("data:image/jpeg;base64," + base64.b64encode(jpeg).decode()) == (jpeg, ".jpg")
    assert decode_screenshot("data:image/png;base64," + base64.b64encode(b"png").decode()) == (b"png", ".png")
    for bad in (
        None,
        "",
        "data:image/png;base64,",
        "data:text/html;base64,PGI+",
        "data:image/png;base64,***",
    ):
        assert decode_screenshot(bad) is None
