"""Logging in to a social account in Clipper's own Chrome: open its login page, check the result.

You log in by hand (password, 2-step, CAPTCHA are yours; Clipper never types them and never solves a
challenge). Both calls only navigate to the platform's own page: logged out, the site sends the tab
to its login screen, which the extension reports as a login challenge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from clipper.services.base import ServiceError

if TYPE_CHECKING:
    from clipper.core import Core

# an address on the platform that needs a login (the site redirects a logged-out tab to sign-in)
START_URLS: dict[str, str] = {
    "youtube": "https://studio.youtube.com/",
    "tiktok": "https://www.tiktok.com/tiktokstudio/upload",
    "instagram": "https://www.instagram.com/",
    "x": "https://x.com/home",
}


@dataclass(frozen=True)
class LoginResult:
    logged_in: bool | None  # None: a CAPTCHA or "verify it's you" screen is up (yours to handle)
    url: str | None
    detail: str


async def login_step(
    core: Core, platform: str, profile: str, action: Literal["open", "check"]
) -> LoginResult:
    url = START_URLS.get(platform)
    if url is None:
        raise ServiceError(f"unknown platform {platform}")
    if action == "open":
        core.chrome.show(profile)  # the window you log in with; starts Chrome if needed
    if profile not in core.adapters.browser.connected_profiles():
        raise ServiceError(
            f"the Clipper browser profile {profile!r} isn't connected yet: wait a few seconds after it opens "
            "(Clipper Companion must be installed in it)"
        )
    res = await core.adapters.browser.action(profile, {"action": "navigate", "url": url})
    where = str(res.data.get("url") or "") or None
    if res.challenge == "login":
        word = (
            "login page opened: log in there, then press Check" if action == "open" else "not logged in yet"
        )
        return LoginResult(False, where, word)
    if res.challenge in ("captcha", "verification"):
        return LoginResult(
            None, where, f"the site is asking you to verify ({res.challenge}): do it in the browser window"
        )
    if not res.ok:
        return LoginResult(None, where, res.error or "couldn't load the page")
    return LoginResult(True, where, "logged in")
