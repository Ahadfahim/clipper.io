"""A recipe check upload: a real run of an upload recipe with a synthetic clip, always Private."""

from __future__ import annotations

import pytest
from sqlmodel import select

from clipper.browser.bridge import FakeBrowserBridge
from clipper.browser.protocol import RecipeResult
from clipper.core import Core
from clipper.db.engine import WriteTx
from clipper.db.models import Platform, RecipeRun
from clipper.services.base import ServiceError
from clipper.services.recipe_check import CLIP_NAME, run_check_upload

pytestmark = pytest.mark.ffmpeg


def _bridge(core: Core) -> FakeBrowserBridge:
    bridge = core.adapters.browser
    assert isinstance(bridge, FakeBrowserBridge)
    return bridge


async def test_uploads_the_test_clip_as_private_for_real(core: Core) -> None:
    bridge = _bridge(core)
    bridge.recipes["youtube.upload_short"] = RecipeResult(
        ok=True, data={"post_url": "https://youtube.com/shorts/Abc123def45"}
    )
    res = await run_check_upload(core, "youtube.upload_short")
    assert res.ok and res.data["post_url"].endswith("Abc123def45")
    _profile, recipe, params = bridge.calls[-1]
    assert recipe == "youtube.upload_short" and params["private"] is True
    assert params["file_url"].endswith(f"/api/files/recipe-check/{CLIP_NAME}")
    assert (core.dir("recipe_checks") / CLIP_NAME).stat().st_size > 10_000  # a real video
    with core.db.read() as s:
        run = s.exec(select(RecipeRun)).one()
    assert run.ok and not run.dry_run


async def test_refuses_recipes_without_private_and_switched_off_platforms(core: Core) -> None:
    with pytest.raises(ServiceError, match="can't do a private check upload"):
        await run_check_upload(core, "tiktok.upload")

    def off(tx: WriteTx) -> None:
        row = tx.session.get(Platform, "youtube") or Platform(id="youtube", name="YouTube")
        row.enabled = False
        tx.add(row)

    core.db.write(off)
    with pytest.raises(ServiceError, match="switched off"):
        await run_check_upload(core, "youtube.upload_short")
    assert _bridge(core).calls == []
