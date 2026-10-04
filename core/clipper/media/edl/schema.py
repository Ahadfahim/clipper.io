"""The EDL document (PLAN §18.1).

Time bases:
- ``segments``, ``camera`` keyframes and caption ``words`` use **source time** (seconds in the
  source video). A word inside a removed range simply disappears; a teaser segment (cold open) shows
  its words twice, as it should.
- ``overlays`` use **output time** (seconds from the start of the rendered clip).

Same EDL + same source -> same render (the renderer is deterministic).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Layout = Literal["crop", "split", "fit"]
SafeZone = Literal["tiktok", "shorts", "reels", "none"]
CaptionPosition = Literal["auto", "top", "middle", "bottom"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeRange(_M):
    start: float
    end: float

    @model_validator(mode="after")
    def _ordered(self) -> TimeRange:
        if self.end <= self.start:
            raise ValueError(f"range end {self.end} must be after start {self.start}")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class Segment(_M):
    """A piece of the source played in order. ``teaser`` is the cold-open copy of the payoff."""

    start: float
    end: float
    kind: Literal["main", "teaser"] = "main"

    @model_validator(mode="after")
    def _ordered(self) -> Segment:
        if self.end - self.start < 0.04:
            raise ValueError(f"segment {self.start}-{self.end} is shorter than one frame")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class Box(_M):
    """Normalized rectangle (0..1) in source-frame coordinates."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


class CameraKey(_M):
    """Virtual camera at source time ``t``. ``focus`` is where to center the 9:16 window."""

    t: float
    layout: Layout = "crop"
    focus_x: float = Field(default=0.5, ge=0, le=1)  # horizontal center of the crop window
    focus_y: float = Field(default=0.5, ge=0, le=1)
    focus2_x: float | None = Field(default=None, ge=0, le=1)  # second speaker (split layout)
    zoom: float = Field(default=1.0, ge=1.0, le=1.5)


class CaptionWord(_M):
    t: float  # source time
    end: float
    text: str
    emphasis: bool = False
    speaker: str | None = None


class Captions(_M):
    style: str = "bold-pop"
    words: list[CaptionWord] = Field(default_factory=lambda: [])
    position: CaptionPosition = "auto"
    safe_zone: SafeZone = "tiktok"
    max_words_per_line: int = Field(default=3, ge=1, le=8)
    profanity_mask: bool = False
    face_box: Box | None = None  # in output-frame normalized coordinates, for face avoidance
    enabled: bool = True


class Overlay(_M):
    id: str
    type: Literal["hook_text", "progress_bar", "brand"]
    t_in: float = 0.0  # output time
    t_out: float = 2.0
    props: dict[str, Any] = Field(default_factory=dict)


class Audio(_M):
    loudness: float = -14.0
    true_peak: float = -1.5
    denoise: bool = False
    duck_music: bool = False
    fade_ms: int = 30
    gain_db: float = 0.0


class Hook(_M):
    type: Literal["cold_open", "text", "none"] = "none"
    range: TimeRange | None = None
    text: str | None = None


class OutputSpec(_M):
    width: int = 1080
    height: int = 1920
    fps: int = 30


class SourceInfo(_M):
    source_id: int | None = None
    path: str
    duration: float
    width: int
    height: int
    fps: float = 30.0
    has_audio: bool = True


class Edl(_M):
    schema_version: Literal[1] = 1
    source: SourceInfo
    range: TimeRange  # the moment's window in the source
    segments: list[Segment]
    camera: list[CameraKey] = Field(default_factory=lambda: [CameraKey(t=0.0)])
    captions: Captions = Field(default_factory=Captions)
    overlays: list[Overlay] = Field(default_factory=lambda: [])
    audio: Audio = Field(default_factory=Audio)
    hook: Hook = Field(default_factory=Hook)
    output: OutputSpec = Field(default_factory=OutputSpec)
    variant: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Edl:
        if not self.segments:
            raise ValueError("an EDL needs at least one segment")
        for seg in self.segments:
            if seg.start < 0 or seg.end > self.source.duration + 1e-3:
                raise ValueError(
                    f"segment {seg.start}-{seg.end} is outside the source (0-{self.source.duration})"
                )
        self.camera.sort(key=lambda k: k.t)
        return self

    @property
    def duration(self) -> float:
        return round(sum(s.duration for s in self.segments), 6)


def new_edl(
    source: SourceInfo,
    start: float,
    end: float,
    *,
    words: list[CaptionWord] | None = None,
    caption_style: str = "bold-pop",
    safe_zone: SafeZone = "tiktok",
    layout: Layout = "crop",
    focus_x: float = 0.5,
) -> Edl:
    """The first EDL for a moment: one main segment, one camera key, captions from the transcript."""
    end = min(end, source.duration)
    in_range = [w for w in (words or []) if w.end > start and w.t < end]
    return Edl(
        source=source,
        range=TimeRange(start=start, end=end),
        segments=[Segment(start=start, end=end)],
        camera=[CameraKey(t=start, layout=layout, focus_x=focus_x)],
        captions=Captions(style=caption_style, words=in_range, safe_zone=safe_zone),
    )
