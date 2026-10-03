"""``edit`` server: EDL operations (PLAN §18.3). Each op is logged as an ``edit_op`` and broadcast live;
the Edit page shows a violet 'Claude is editing: ...' line while it runs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from clipper.media.edl.ops import OPS, EditError, OpSpec
from clipper.media.edl.schema import Edl
from clipper.tools.base import Handler, ToolContext, ToolFailure, tool

STATUS_TEXT = {
    "trim": "Trimming",
    "split": "Splitting",
    "delete_range": "Cutting a range",
    "remove_silences": "Removing silences",
    "remove_fillers": "Removing filler words",
    "set_layout": "Changing the layout",
    "set_camera_keyframes": "Moving the camera",
    "set_caption_style": "Styling captions",
    "edit_caption_words": "Fixing caption words",
    "emphasize": "Adding emphasis",
    "set_hook": "Reworking the hook",
    "add_overlay": "Adding an overlay",
    "set_audio": "Adjusting audio",
}


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


def edl_summary(edl: Edl, version: int, locked_by: str | None, words_from: int = 0) -> dict[str, Any]:
    words = edl.captions.words
    return {
        "version": version,
        "locked_by": locked_by,
        "duration": round(edl.duration, 2),
        "source_range": [edl.range.start, edl.range.end],
        "segments": [[round(s.start, 2), round(s.end, 2), s.kind] for s in edl.segments],
        "camera": [[round(k.t, 2), k.layout, k.focus_x, k.zoom] for k in edl.camera],
        "captions": {
            "style": edl.captions.style,
            "safe_zone": edl.captions.safe_zone,
            "words_total": len(words),
            "words": [[i, w.text, round(w.t, 2), w.emphasis] for i, w in enumerate(words)][
                words_from : words_from + 80
            ],
        },
        "overlays": [[o.type, o.t_in, o.t_out, o.props.get("text")] for o in edl.overlays],
        "hook": edl.hook.model_dump(),
        "audio": edl.audio.model_dump(),
    }


class GetEdl(_A):
    clip_id: int
    words_from: int = Field(default=0, ge=0, description="page caption words 80 at a time")


@tool(
    "edit",
    "get_edl",
    "The clip's timeline: segments, camera keys, caption words (paged), overlays, hook, audio.",
    GetEdl,
)
async def get_edl(ctx: ToolContext, a: GetEdl) -> dict[str, Any]:
    try:
        edl, version, locked = ctx.core.edl.get(a.clip_id)
    except EditError as exc:
        raise ToolFailure(str(exc)) from exc
    out = edl_summary(edl, version, locked, a.words_from)
    out["history"] = [
        {"op_id": o.id, "op": o.op, "actor": o.actor, "reason": o.reason, "undone": o.undone}
        for o in ctx.core.edl.history(a.clip_id)[-8:]
    ]
    return out


def _make_op_tool(spec: OpSpec) -> None:
    model: type[BaseModel] = create_model(  # type: ignore[call-overload]
        f"{spec.args.__name__}Tool",
        __base__=spec.args,
        clip_id=(int, Field(description="clip to edit")),
        reason=(str, Field(default="", max_length=200, description="one line for the history panel")),
    )

    async def handler(ctx: ToolContext, a: Any) -> dict[str, Any]:
        args = a.model_dump(exclude={"clip_id", "reason"})
        ctx.core.edl.status(a.clip_id, ctx.actor, f"{STATUS_TEXT.get(spec.name, spec.name)}…")
        try:
            applied = ctx.core.edl.apply(a.clip_id, spec.name, args, actor=ctx.actor, reason=a.reason)
        except EditError as exc:
            raise ToolFailure(str(exc)) from exc
        return {
            "op_id": applied.op_id,
            "version": applied.version,
            "summary": applied.summary,
            "duration": round(applied.edl.duration, 2),
            "segments": len(applied.edl.segments),
        }

    h: Handler = handler
    tool("edit", spec.name, spec.description + " Logged and shown live on the Edit page.", model)(h)


for _spec in OPS.values():
    _make_op_tool(_spec)


class Change(_A):
    op: str = Field(description="an edit op name, e.g. set_hook")
    args: dict[str, Any] = Field(default_factory=dict)


class Variant(_A):
    clip_id: int
    label: str = Field(min_length=2, max_length=60, description="e.g. 'cold open' or 'question hook'")
    changes: list[Change] = Field(min_length=1, max_length=6)


@tool(
    "edit",
    "make_variant",
    "Make a hook variant (copy + changes) to show side by side in review. Returns the new clip id.",
    Variant,
)
async def make_variant(ctx: ToolContext, a: Variant) -> dict[str, Any]:
    try:
        new_id = ctx.core.edl.make_variant(
            a.clip_id, [c.model_dump() for c in a.changes], label=a.label, actor=ctx.actor
        )
    except (EditError, KeyError) as exc:
        raise ToolFailure(str(exc)) from exc
    job_id = ctx.core.media.request_preview(new_id)
    return {"clip_id": new_id, "job_id": job_id}


class ClipArg(_A):
    clip_id: int


@tool("edit", "preview", "Render the review preview of the current EDL (QA runs on it).", ClipArg)
async def preview(ctx: ToolContext, a: ClipArg) -> dict[str, Any]:
    return {"clip_id": a.clip_id, "job_id": ctx.core.media.request_preview(a.clip_id)}


@tool("edit", "render_final", "Full-quality render for posting. Approved clips only.", ClipArg)
async def render_final(ctx: ToolContext, a: ClipArg) -> dict[str, Any]:
    return {"clip_id": a.clip_id, "job_id": ctx.core.media.request_final(a.clip_id)}


class Undo(_A):
    clip_id: int
    op_id: int = Field(description="from get_edl history; undoing an undone op redoes it")


@tool("edit", "undo", "Undo (or redo) one step; later steps are replayed on top.", Undo)
async def undo(ctx: ToolContext, a: Undo) -> dict[str, Any]:
    try:
        edl, skipped = ctx.core.edl.undo(a.clip_id, a.op_id, actor=ctx.actor)
    except EditError as exc:
        raise ToolFailure(str(exc)) from exc
    return {"duration": round(edl.duration, 2), "skipped": skipped}
