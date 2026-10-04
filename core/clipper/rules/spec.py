"""ClipSpec: the structured, trusted summary of an untrusted campaign brief (PLAN §3, §4).

The *brief-reader* subagent turns the raw campaign page into this shape; the Campaign agent works
from the spec, never from the raw brief. Guard hooks read ``source_whitelist`` and ``platforms``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PLATFORMS = ("youtube", "tiktok", "instagram", "x")


class Branding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handle_overlay: str | None = None  # e.g. "@creator" burned in
    watermark: str | None = None
    position: Literal["top", "bottom", "none"] = "none"


class ClipSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    source_whitelist: list[str] = Field(default_factory=list)  # exact source URLs we may download
    platforms: list[Literal["youtube", "tiktok", "instagram", "x"]] = Field(default_factory=lambda: [])
    duration_min_s: float = 15.0
    duration_max_s: float = 60.0
    required_text: list[str] = Field(default_factory=list)  # must appear in caption/description
    required_tags: list[str] = Field(default_factory=list)  # hashtags / @mentions
    banned: list[str] = Field(default_factory=list)  # words, topics, elements not allowed
    branding: Branding = Field(default_factory=Branding)
    allow_music: bool = False
    allow_cross_submit: bool = False  # may a post also be submitted to another campaign?
    profanity_mask: bool = False
    caption_style: str | None = None
    content_type: Literal["clipping", "ugc", "other"] = "clipping"
    deliverable: Literal["link", "upload"] = "link"
    min_views_to_pay: int | None = None
    unclear: list[str] = Field(default_factory=list)  # questions the agent should ask the user
    notes: str = ""
