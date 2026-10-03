"""``media`` server: download, analysis outputs (paged), seeing the video (frames, contact sheet, OCR), renders."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clipper.tools.base import ToolContext, ToolOutput, tool


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DownloadArgs(_A):
    campaign_id: int
    url: str = Field(description="must be on the campaign's source whitelist")
    analyze: bool = Field(default=True, description="start analysis as soon as the download finishes")


@tool(
    "media",
    "download",
    "Queue a source download (and analysis). Returns a job id; you are resumed with job.done.",
    DownloadArgs,
)
async def download(ctx: ToolContext, a: DownloadArgs) -> dict[str, Any]:
    return ctx.core.media.request_download(a.campaign_id, a.url, analyze=a.analyze)


class SourceArg(_A):
    source_id: int


@tool(
    "media",
    "analyze",
    "Re-run analysis (transcript, scenes, energy, faces) on a downloaded source.",
    SourceArg,
)
async def analyze(ctx: ToolContext, a: SourceArg) -> dict[str, Any]:
    return {"source_id": a.source_id, "job_id": ctx.core.media.request_analyze(a.source_id)}


class TranscriptArgs(_A):
    source_id: int
    start: float = Field(alias="from", ge=0, description="source seconds")
    end: float = Field(alias="to", description="source seconds")
    max_words: int = Field(default=400, ge=5, le=400)


@tool(
    "media",
    "get_transcript",
    "Transcript words between from/to (source seconds), paged; [t] marks every 12 words.",
    TranscriptArgs,
)
async def get_transcript(ctx: ToolContext, a: TranscriptArgs) -> dict[str, Any]:
    return ctx.core.media.transcript(a.source_id, a.start, a.end, a.max_words)


@tool(
    "media",
    "get_signals",
    "Heatmap peaks (most replayed), energy spikes, scene cuts, silences, chapters.",
    SourceArg,
)
async def get_signals(ctx: ToolContext, a: SourceArg) -> dict[str, Any]:
    return ctx.core.media.signals(a.source_id)


class CommentsArgs(_A):
    source_id: int
    limit: int = Field(default=30, ge=1, le=100)


@tool(
    "media",
    "get_comments",
    "Top comments with the timestamps they mention (a strong virality signal).",
    CommentsArgs,
)
async def get_comments(ctx: ToolContext, a: CommentsArgs) -> dict[str, Any]:
    return {"source_id": a.source_id, "comments": ctx.core.media.comments(a.source_id, a.limit)}


class FramesArgs(_A):
    source_id: int | None = None
    clip_id: int | None = None
    times: list[float] = Field(
        min_length=1, max_length=8, description="seconds in the source (or in the clip)"
    )

    @model_validator(mode="after")
    def _one(self) -> FramesArgs:
        if (self.source_id is None) == (self.clip_id is None):
            raise ValueError("give exactly one of source_id or clip_id")
        return self


@tool(
    "media",
    "frames",
    "Look at frames (small JPEGs returned as images) from a source or a rendered clip.",
    FramesArgs,
)
async def frames(ctx: ToolContext, a: FramesArgs) -> ToolOutput:
    shots = ctx.core.media.frames(source_id=a.source_id, clip_id=a.clip_id, times=a.times)
    return ToolOutput({"frames": [{"t": t, "path": str(p)} for t, p in shots]}, [p for _, p in shots])


class ClipArg(_A):
    clip_id: int


@tool("media", "contact_sheet", "A 3x3 contact sheet of a rendered clip (one image).", ClipArg)
async def contact_sheet(ctx: ToolContext, a: ClipArg) -> ToolOutput:
    path = ctx.core.media.contact_sheet(a.clip_id)
    return ToolOutput({"clip_id": a.clip_id, "path": str(path)}, [path])


@tool("media", "ocr_frames", "Read burned-in text (captions, watermarks) at given times.", FramesArgs)
async def ocr_frames(ctx: ToolContext, a: FramesArgs) -> dict[str, Any]:
    return {"frames": ctx.core.media.ocr_frames(source_id=a.source_id, clip_id=a.clip_id, times=a.times)}


class RenderArgs(_A):
    moment_id: int
    layout: Literal["crop", "split", "fit"] | None = Field(
        default=None, description="default: follow the face track"
    )
    caption_style: Literal["bold-pop", "clean", "boxed", "karaoke"] | None = None
    platform: Literal["youtube", "tiktok", "instagram", "x"] | None = Field(
        default=None, description="safe zone to design for"
    )


@tool(
    "media",
    "render",
    "Make a clip from a moment: first-cut EDL + review preview render + QA. Returns clip and job ids.",
    RenderArgs,
)
async def render(ctx: ToolContext, a: RenderArgs) -> dict[str, Any]:
    return ctx.core.media.render_moment(
        a.moment_id, layout=a.layout, caption_style=a.caption_style, platform=a.platform
    )


class JobArg(_A):
    job_id: int


@tool("media", "job_status", "Status and progress of a background job.", JobArg)
async def job_status(ctx: ToolContext, a: JobArg) -> dict[str, Any]:
    return ctx.core.media.job_status(a.job_id)
