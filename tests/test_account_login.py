"""Logging in to a social account in Clipper's browser: open the login page, check the result."""

from __future__ import annotations

from typing import Any

import pytest

from clipper.browser.bridge import FakeBrowserBridge
from clipper.browser.protocol import RecipeResult
from clipper.core import Core
from clipper.services.account_login import START_URLS, login_step
from clipper.services.base import ServiceError


def _bridge(core: Core) -> FakeBrowserBridge:
    bridge = core.adapters.browser
    assert isinstance(bridge, FakeBrowserBridge)
    return bridge


async def test_open_shows_the_browser_and_goes_to_the_platform(core: Core) -> None:
    res = await login_step(core, "youtube", "main", "open")
    assert res.logged_in is True  # the fake tab loads the page without a login wall
    assert _bridge(core).calls[-1][2] == {"action": "navigate", "url": START_URLS["youtube"]}
    assert any(s.name == "main" and s.visible for s in core.chrome.states())


async def test_a_login_wall_means_not_logged_in_and_a_captcha_means_your_turn(
    core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _bridge(core)
    answers = iter([RecipeResult(ok=False, challenge="login"), RecipeResult(ok=False, challenge="captcha")])

    async def action(profile: str, a: dict[str, Any]) -> RecipeResult:
        return next(answers)

    monkeypatch.setattr(bridge, "action", action)
    out = await login_step(core, "tiktok", "main", "check")
    assert out.logged_in is False and "not logged in" in out.detail
    out = await login_step(core, "tiktok", "main", "check")
    assert out.logged_in is None and "captcha" in out.detail


async def test_unknown_platform_and_unconnected_profile_are_explained(core: Core) -> None:
    with pytest.raises(ServiceError, match="unknown platform"):
        await login_step(core, "myspace", "main", "check")
    with pytest.raises(ServiceError, match="isn't connected"):
        await login_step(core, "youtube", "other", "check")
