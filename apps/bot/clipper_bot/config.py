"""Bot configuration: the core's ``[discord]`` settings plus the token from Windows Credential
Manager. Nothing secret is read from files or the environment except ``CLIPPER_DISCORD_TOKEN``
for development."""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel

SERVICE = "clipper.io"  # same keyring service as core/clipper/secrets.py
TOKEN_NAME = "discord_bot_token"
CHANNEL_KEYS = ("control", "campaigns", "clip_review", "published", "alerts")


class Channels(BaseModel):
    control: int | None = None
    campaigns: int | None = None
    clip_review: int | None = None
    published: int | None = None
    alerts: int | None = None


class BotConfig(BaseModel):
    core_url: str = "http://127.0.0.1:8765"
    guild_id: int | None = None
    reviewer_role_id: int | None = None
    reviewer_role_name: str = "Clipper"
    channels: Channels = Channels()
    approve_all_threshold: int = 80
    enabled: bool = True

    @classmethod
    def from_settings(cls, settings: dict[str, Any], core_url: str) -> BotConfig:
        d = dict(settings.get("discord") or {})
        review = dict(settings.get("review") or {})
        return cls(
            core_url=core_url,
            guild_id=d.get("guild_id"),
            reviewer_role_id=d.get("reviewer_role_id"),
            reviewer_role_name=d.get("reviewer_role_name") or "Clipper",
            channels=Channels(**(d.get("channels") or {})),
            approve_all_threshold=int(review.get("approve_all_threshold") or 80),
            enabled=bool(d.get("enabled", True)),
        )


def core_url_from_env() -> str:
    return os.environ.get("CLIPPER_CORE_URL", "http://127.0.0.1:8765").rstrip("/")


def load_token() -> str | None:
    env = os.environ.get("CLIPPER_DISCORD_TOKEN")
    if env:
        return env
    import keyring

    return keyring.get_password(SERVICE, TOKEN_NAME)
