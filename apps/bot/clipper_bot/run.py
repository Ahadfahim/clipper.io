"""``clipper-bot``: reads the bot settings from the core, the token from Credential Manager."""

from __future__ import annotations

import asyncio
import logging
import sys

from clipper_bot.config import BotConfig, core_url_from_env, load_token
from clipper_bot.core_client import CoreClient


async def _config() -> BotConfig:
    core = CoreClient(core_url_from_env())
    try:
        return BotConfig.from_settings(await core.settings(), core.base_url)
    finally:
        await core.close()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = load_token()
    if not token:
        sys.exit(
            "No Discord bot token. Add it in Clipper → Settings → Discord (stored in Windows Credential Manager)."
        )
    try:
        cfg = asyncio.run(_config())
    except OSError as exc:
        sys.exit(f"Can't reach the Clipper core at {core_url_from_env()}: {exc}")
    if not cfg.enabled:
        sys.exit("The Discord bot is turned off in Settings.")
    from clipper_bot.bot import ClipperBot

    bot = ClipperBot(CoreClient(cfg.core_url), cfg)
    bot.run(token, log_handler=None)  # LOCAL-VERIFY: live token, server and channels
