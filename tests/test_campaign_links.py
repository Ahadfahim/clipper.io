"""A working link for every campaign, built from the marketplace and the id, never from a scraped URL."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from clipper.core import Core
from clipper.fixtures.seed import seed_demo
from clipper.marketplaces.links import campaign_link
from clipper.settings import Settings
from tests.factories import make_campaign

WHOP_APP = "https://b4e0vdqv6zgqeqj4pfgm.apps.whop.com/c/exp_zeADOv9rOOKk2x"
UUID = "49013d93-5888-4cf2-9e20-b4ba54c983bc"


def test_a_vyro_campaign_opens_its_dialog(settings: Settings) -> None:
    link = campaign_link("vyro", "5-guys-face-their-crush-4cvTnrw6", None, settings)
    assert link.url == "https://app.vyro.com/campaigns?c=5-guys-face-their-crush-4cvTnrw6"
    assert (link.label, link.host, link.kind, link.exact) == (
        "Open on Vyro",
        "app.vyro.com",
        "marketplace",
        True,
    )


def test_a_whop_campaign_goes_through_the_launch_url(settings: Settings) -> None:
    link = campaign_link("whop", UUID, "https://anything.example/ignored", settings)
    assert link.url.startswith("https://whop.com/core/app/launch/?redirect=")
    redirect = parse_qs(urlsplit(link.url).query)["redirect"][0]
    assert redirect == f"{WHOP_APP}/campaigns/{UUID}"
    assert link.host == "whop.com" and link.exact and link.label == "Open on Whop"


@pytest.mark.parametrize(
    ("market", "ext"),
    [
        ("vyro", "bad slug/../etc"),
        ("vyro", "x" * 200),
        ("vyro", ""),
        ("whop", "not-a-uuid"),
        ("whop", UUID + "/../x"),
    ],
)
def test_a_bad_id_falls_back_to_the_marketplace_list(settings: Settings, market: str, ext: str) -> None:
    link = campaign_link(market, ext, "https://evil.example/", settings)
    assert not link.exact and "campaigns" in link.label
    assert link.host in {"app.vyro.com", "whop.com"} and "evil" not in link.url


def test_a_pasted_url_is_used_only_on_the_marketplaces_own_site(settings: Settings) -> None:
    ok = campaign_link("whop", "manual-abc", "https://whop.com/some-community/campaigns/abc", settings)
    assert ok.url == "https://whop.com/some-community/campaigns/abc" and ok.exact
    bad = campaign_link("whop", "manual-abc", "https://whop.com.evil.example/x", settings)
    assert not bad.exact and "evil" not in bad.url
    http = campaign_link("vyro", "manual-abc", "http://app.vyro.com/x", settings)
    assert http.url.startswith("https://")


def test_the_whop_app_address_comes_from_settings_and_must_be_on_whop(settings: Settings) -> None:
    mine = settings.model_copy(
        update={
            "marketplaces": settings.marketplaces.model_copy(
                update={
                    "whop": settings.marketplaces.whop.model_copy(
                        update={"app_url": "https://zzz.apps.whop.com/c/exp_other/"}
                    )
                }
            )
        }
    )
    assert unquote(campaign_link("whop", UUID, None, mine).url).endswith(
        f"https://zzz.apps.whop.com/c/exp_other/campaigns/{UUID}"
    )
    hostile = settings.model_copy(
        update={
            "marketplaces": settings.marketplaces.model_copy(
                update={
                    "whop": settings.marketplaces.whop.model_copy(
                        update={"app_url": "https://evil.example/c/x"}
                    )
                }
            )
        }
    )
    link = campaign_link("whop", UUID, None, hostile)
    assert not link.exact and link.url == "https://whop.com/"


def test_where_a_link_opens_follows_the_setting(settings: Settings) -> None:
    assert campaign_link("vyro", "abc", None, settings).open_in == "clipper"
    other = settings.model_copy(
        update={"ui": settings.ui.model_copy(update={"open_marketplace_links_in": "default"})}
    )
    assert campaign_link("vyro", "abc", None, other).open_in == "default"


def test_every_campaign_in_every_read_model_has_a_link(core: Core, settings: Settings) -> None:
    from clipper.api import needs_you, views

    seed_demo(core.db, settings)
    rows = views.campaign_rows(core)
    assert rows and all(r.link is not None and r.link.url.startswith("https://") for r in rows)
    assert all(a.link is not None for a in views.overview(core).active_campaigns)
    items = [i for i in needs_you.build(core) if i.campaign_id is not None]
    assert items and all(i.links and i.links[0].kind == "marketplace" for i in items)
    clip = views.clips(core)[0]
    detail = views.clip_detail(core, clip.id)
    assert detail is not None and detail.campaign_link is not None


def test_a_campaign_without_an_external_id_still_gets_a_link(core: Core) -> None:
    from clipper.api import views

    make_campaign(core.db, marketplace="whop", external_id="legacy-row")
    (row,) = views.campaign_rows(core)
    assert row.link is not None and row.link.host == "whop.com"
