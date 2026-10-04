"""One real, private upload that checks an upload recipe end to end (HANDOFF §8 task 7).

This isn't campaign publishing, and it never posts anything public:
- the video is a synthetic test pattern made here with ffmpeg (no one's content);
- the recipe is told to upload it as Private, and only recipes that can do that are allowed;
- it runs only when you ask for it (the API route needs ``confirm: true``). Agents have no tool for it.
The kill switch and the platform's on/off switch still apply. The dry-run switch doesn't: that switch
is for campaign posts, and this route *is* the deliberate real run. The result is recorded as a
recipe run, so Publishing → Recipes shows when the recipe last worked for real.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from clipper.browser.protocol import RecipeResult, decode_screenshot
from clipper.db.models import Platform, RecipeRun
from clipper.services.base import ServiceError
from clipper.services.control import read_control

if TYPE_CHECKING:
    from clipper.core import Core

# recipe -> platform; each recipe here must take the `private` param
CHECK_UPLOADS: dict[str, str] = {"youtube.upload_short": "youtube"}
CLIP_NAME = "recipe_check.mp4"
TITLE = "Clipper recipe check (private, delete me)"
CAPTION = "Test upload by Clipper, checking its YouTube upload steps. Safe to delete."


def check_clip(core: Core) -> Path:
    """An 8-second 1080x1920 test pattern with a quiet tone (made once, then reused)."""
    out = core.dir("recipe_checks") / CLIP_NAME
    if out.is_file():
        return out
    tmp = out.with_suffix(".tmp.mp4")
    cmd = [
        core.settings.paths.ffmpeg("ffmpeg"),
        *("-y", "-hide_banner", "-loglevel", "error"),
        *("-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=8"),
        *("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=8"),
        *("-filter:a", "volume=0.05", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"),
        *("-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", str(tmp)),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServiceError(f"couldn't make the test clip with ffmpeg: {exc}") from exc
    tmp.replace(out)
    return out


async def run_check_upload(core: Core, recipe: str, profile: str = "main") -> RecipeResult:
    platform = CHECK_UPLOADS.get(recipe)
    if platform is None:
        raise ServiceError(f"{recipe} can't do a private check upload (only {', '.join(CHECK_UPLOADS)})")
    if read_control(core.db).kill_switch:
        raise ServiceError("the kill switch is on")
    with core.db.read() as s:
        row = s.get(Platform, platform)
    if row is not None and not row.enabled:
        raise ServiceError(f"{platform} is switched off")
    check_clip(core)
    api = f"http://{core.settings.api.host}:{core.settings.api.port}"
    params: dict[str, Any] = {
        "file_url": f"{api}/api/files/recipe-check/{CLIP_NAME}",
        "file_name": "clipper_recipe_check.mp4",
        "title": TITLE,
        "caption": CAPTION,
        "hashtags": [],
        "schedule_at": None,
        "handle": None,
        "private": True,
    }
    try:
        res = await core.adapters.browser.run_recipe(profile, recipe, params, dry_run=False)
    except Exception as exc:  # not connected, timed out
        res = RecipeResult(ok=False, error=str(exc))
    shot_path: str | None = None
    shot = decode_screenshot(res.screenshot)
    if shot is not None:
        raw, suffix = shot
        path = core.dir("screenshots") / f"recipe_check_{recipe}{suffix}"
        path.write_bytes(raw)
        shot_path = str(path)
    core.db.write(
        lambda tx: tx.add(
            RecipeRun(recipe=recipe, ok=res.ok, dry_run=False, error=res.error, screenshot_path=shot_path)
        )
    )
    return res
