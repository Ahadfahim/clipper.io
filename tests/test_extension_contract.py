"""The core and the Companion extension agree: protocol version, recipe names, recipe params,
and how scraped campaign rows are read."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clipper.browser.bridge import FakeBrowserBridge
from clipper.browser.protocol import PROTOCOL_VERSION, RecipeResult, decode_screenshot
from clipper.marketplaces.browser import RecipeMarketplace, card_from_row
from clipper.marketplaces.docs import fetch_doc_text
from clipper.publishing.base import RECIPES, UploadRequest
from clipper.publishing.browser import BrowserPublisher
from clipper.settings import Settings

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
        assert r["status"] in ("UNVERIFIED", "verified"), name  # verified = run against the real site


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


def test_whop_rows_as_the_real_site_gives_them() -> None:
    # what whop.list_campaigns read in Content Rewards (2026-10-03)
    card = card_from_row(
        "whop",
        {
            "id": "abe41f6d-61e4-497d-b2d1-ee64c3bd1713",
            "title": "bbno$ - Minecraft Concert Clips",
            "creator": "Clipping Culture",
            "platforms": "Instagram | TikTok",
            "cpm": "1.50",
            "budget_used": "671.68",
            "budget_total": "1k",
            "cap_per_post": "100.00",
            "join": "Submit clip",
        },
    )
    assert card.allowed_platforms == ["instagram", "tiktok"]
    assert card.budget_total == 1000 and card.budget_left == pytest.approx(328.32)
    assert card.cap_per_post == 100 and card.cpm_usd == 1.5 and card.join == "joined"


async def test_whop_campaign_detail_reads_the_linked_rules_doc() -> None:
    doc = "https://docs.google.com/document/d/1F2slKMDX7pYrXgXNcH_U-KncgjukrBdZ75vCmR5GZqg/edit"
    bridge = FakeBrowserBridge(
        recipes={
            "whop.get_campaign": RecipeResult(
                ok=True,
                data={
                    "campaign": {"title": "bbno$ - Minecraft Concert Clips", "budget_left": "328"},
                    "rules_text": "Please refer to Google Doc for requirements.",
                    "rules_doc": doc,
                    "sources": [doc, "https://whop.com/clippingculture/"],
                },
            )
        }
    )
    fetched: list[str] = []

    async def fake_fetch(url: str) -> str | None:
        fetched.append(url)
        return "Content file: https://f.io/TjTVviUl"

    detail = await RecipeMarketplace("whop", bridge, fetch_text=fake_fetch).get_campaign("abe41f6d")
    assert fetched == [doc]
    assert "Content file: https://f.io/TjTVviUl" in detail.rules_raw
    assert detail.sources == []  # the doc is the rules, whop.com is the marketplace itself

    async def private(_url: str) -> str | None:
        return None

    detail = await RecipeMarketplace("whop", bridge, fetch_text=private).get_campaign("abe41f6d")
    assert "couldn't be read here" in detail.rules_raw


async def test_only_google_docs_are_fetched() -> None:
    assert await fetch_doc_text("https://example.com/rules") is None
    assert await fetch_doc_text("https://docs.google.com/spreadsheets/d/abc") is None


async def test_the_publisher_sends_the_posts_own_clip_url(settings: Settings) -> None:
    bridge = FakeBrowserBridge(
        recipes={
            "youtube.upload_short": RecipeResult(ok=True, data={"post_url": "https://youtube.com/shorts/abc"})
        }
    )
    pub = BrowserPublisher(bridge, settings, file_url="http://127.0.0.1:8765/api/files/upload/{post_id}")
    req = UploadRequest(
        platform="youtube",
        account_id=1,
        handle="@me",
        chrome_profile="main",
        video=Path("clip_7.mp4"),
        post_id=42,
    )
    assert (await pub.upload(req)).url == "https://youtube.com/shorts/abc"
    assert bridge.calls[-1][2]["file_url"] == "http://127.0.0.1:8765/api/files/upload/42"
    missing = await pub.upload(UploadRequest("youtube", 1, "@me", "main", Path("x.mp4")))
    assert not missing.ok and "post id" in (missing.error or "")


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


async def test_joining_without_a_join_recipe_is_an_answer_not_a_crash() -> None:
    bridge = FakeBrowserBridge()  # no recipes scripted: "no scripted result" != unknown recipe
    bridge.recipes["vyro.join_campaign"] = RecipeResult(ok=False, error="unknown recipe vyro.join_campaign")
    vyro = await RecipeMarketplace("vyro", bridge).join_campaign("abc")
    assert vyro.status == "needs_user" and "user joins" in vyro.detail
    whop = await RecipeMarketplace("whop", bridge).join_campaign("abc")
    assert whop.status == "already"
    assert not any(c[1] == "whop.join_campaign" for c in bridge.calls)
