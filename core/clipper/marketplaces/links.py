"""The address of a campaign's page on its marketplace, built from what Clipper knows for sure.

A campaign's stored ``url`` came from a page we read, and pages are untrusted (PLAN §4), so a link is
never taken from it as it is. It is built from the marketplace and the campaign's id, with fixed
templates; the stored URL is only used for campaigns you added by hand, and only on the marketplace's
own domain. Every campaign gets some link: when the exact page can't be built, the marketplace's list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

from clipper.rules.urls import domain_allowed, host_of
from clipper.settings import Settings

VYRO_BASE = "https://app.vyro.com/campaigns"
WHOP_LAUNCH = "https://whop.com/core/app/launch/?redirect="
VYRO_SLUG = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
MARKET_LABEL = {"vyro": "Vyro", "whop": "Whop"}


@dataclass(frozen=True)
class CampaignLink:
    label: str
    url: str
    kind: Literal["marketplace", "source", "post", "platform", "doc"]
    host: str
    open_in: Literal["clipper", "default"]
    exact: bool  # False: the marketplace's list, because the campaign's own page couldn't be built


def _whop_app(settings: Settings) -> str | None:
    """Whop runs Content Rewards as an app inside a community; its address is a setting."""
    app = settings.marketplaces.whop.app_url.rstrip("/")
    return app if domain_allowed(app, ["whop.com"]) and app.startswith("https://") else None


def page_url(
    marketplace: str, external_id: str, stored_url: str | None, settings: Settings
) -> tuple[str, bool]:
    """(address, exact). ``exact`` is False when it is the marketplace's list."""
    if external_id.startswith("manual-") and stored_url:
        allowed = settings.browser.domain_allowlist.get(marketplace, [])
        if stored_url.startswith("https://") and domain_allowed(stored_url, allowed):
            return stored_url, True
    if marketplace == "vyro":
        if VYRO_SLUG.match(external_id):
            return f"{VYRO_BASE}?c={quote(external_id, safe='')}", True
        return VYRO_BASE, False
    if marketplace == "whop":
        app = _whop_app(settings)
        if app is None:
            return "https://whop.com/", False
        if UUID.match(external_id):
            return WHOP_LAUNCH + quote(f"{app}/campaigns/{external_id.lower()}", safe=""), True
        return WHOP_LAUNCH + quote(app, safe=""), False
    return "https://whop.com/", False  # a marketplace we have no template for


def campaign_link(
    marketplace: str, external_id: str, stored_url: str | None, settings: Settings
) -> CampaignLink:
    url, exact = page_url(marketplace, external_id, stored_url, settings)
    name = MARKET_LABEL.get(marketplace, marketplace.capitalize())
    return CampaignLink(
        label=f"Open on {name}" if exact else f"Open {name}'s campaigns",
        url=url,
        kind="marketplace",
        host=host_of(url),
        open_in=settings.ui.open_marketplace_links_in,
        exact=exact,
    )
