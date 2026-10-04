"""EDL operations (PLAN §18.3). Every operation is a pure function ``(edl, args) -> OpResult``.

``EdlService`` (``clipper.media.edl.service``) records each applied op as an ``edit_op`` row and
broadcasts it; undo replays the non-undone ops from the initial EDL, which works because ops are pure.

Times: ``trim`` and silence ranges use source time; ``split``, ``delete_range``, ``set_layout`` and
overlays use output time (what the user sees on the Edit page timeline).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clipper.media.edl.schema import (
    Audio,
    CameraKey,
    Captions,
    Edl,
    Hook,
    Layout,
    Overlay,
    SafeZone,
    Segment,
    TimeRange,
)
from clipper.media.edl.timeline import output_to_source, placed_segments

MIN_SEGMENT = 0.04  # one frame at 25 fps
MIN_CLIP = 1.0


class EditError(ValueError):
    """An operation that can't apply to this EDL (bad range, nothing left, ...)."""


@dataclass(frozen=True)
class OpResult:
    edl: Edl
    summary: str  # one line for the history panel
    out_range: tuple[float, float] | None = None  # where on the output timeline it happened


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- segment helpers


def _subtract(seg: Segment, start: float, end: float) -> list[Segment]:
    if end <= seg.start or start >= seg.end:
        return [seg]
    pieces: list[Segment] = []
    if start - seg.start >= MIN_SEGMENT:
        pieces.append(Segment(start=seg.start, end=start, kind=seg.kind))
    if seg.end - end >= MIN_SEGMENT:
        pieces.append(Segment(start=end, end=seg.end, kind=seg.kind))
    return pieces


def remove_source_range(
    segments: list[Segment], start: float, end: float, kinds: frozenset[str] = frozenset({"main"})
) -> list[Segment]:
    out: list[Segment] = []
    for seg in segments:
        out.extend(_subtract(seg, start, end) if seg.kind in kinds else [seg])
    return out


def _finish(edl: Edl, segments: list[Segment], **updates: Any) -> Edl:
    if not segments:
        raise EditError("that edit would remove the whole clip")
    total = sum(s.duration for s in segments)
    if total < MIN_CLIP:
        raise EditError(f"that edit would leave {total:.2f}s; clips need at least {MIN_CLIP:.0f}s")
    data = edl.model_dump()
    data["segments"] = [s.model_dump() for s in segments]
    for key, value in updates.items():
        data[key] = value.model_dump() if isinstance(value, BaseModel) else value
    return Edl.model_validate(data)


def _check_out_range(edl: Edl, start: float, end: float) -> None:
    if not (0 <= start < end <= edl.duration + 1e-6):
        raise EditError(f"range {start:.2f}-{end:.2f}s is outside the clip (0-{edl.duration:.2f}s)")


# ---------------------------------------------------------------- operations


class TrimArgs(_A):
    start: float = Field(description="new start of the main material, source seconds")
    end: float = Field(description="new end of the main material, source seconds")


def trim(edl: Edl, a: TrimArgs) -> OpResult:
    if a.end - a.start < MIN_CLIP:
        raise EditError("trim range is shorter than 1s")
    if a.start < 0 or a.end > edl.source.duration + 1e-6:
        raise EditError(f"trim range must be inside the source (0-{edl.source.duration:.2f}s)")
    mains = [i for i, s in enumerate(edl.segments) if s.kind == "main"]
    segments: list[Segment] = []
    for i, seg in enumerate(edl.segments):
        if seg.kind != "main":
            segments.append(seg)
            continue
        start, end = seg.start, seg.end
        if i == mains[0]:
            start = a.start  # extend or shrink the first main segment
        if i == mains[-1]:
            end = a.end
        start, end = max(start, a.start), min(end, a.end)
        if end - start >= MIN_SEGMENT:
            segments.append(Segment(start=start, end=end, kind="main"))
    words = [w for w in edl.captions.words if w.end > a.start and w.t < a.end]
    result = _finish(
        edl,
        segments,
        range=TimeRange(start=a.start, end=a.end),
        captions=edl.captions.model_copy(update={"words": words}),
    )
    return OpResult(result, f"trim to {a.start:.2f}-{a.end:.2f}s of the source", (0.0, result.duration))


class SplitArgs(_A):
    t: float = Field(description="output time to split at, seconds")


def split(edl: Edl, a: SplitArgs) -> OpResult:
    for p in placed_segments(edl):
        if p.out_start + MIN_SEGMENT < a.t < p.out_end - MIN_SEGMENT:
            cut = p.segment.start + (a.t - p.out_start)
            segs = list(edl.segments)
            segs[p.index : p.index + 1] = [
                Segment(start=p.segment.start, end=cut, kind=p.segment.kind),
                Segment(start=cut, end=p.segment.end, kind=p.segment.kind),
            ]
            return OpResult(_finish(edl, segs), f"split at {a.t:.2f}s", (a.t, a.t))
    raise EditError(f"no segment to split at {a.t:.2f}s (too close to a cut or outside the clip)")


class DeleteRangeArgs(_A):
    start: float = Field(description="output seconds")
    end: float = Field(description="output seconds")


def delete_range(edl: Edl, a: DeleteRangeArgs) -> OpResult:
    _check_out_range(edl, a.start, a.end)
    segments: list[Segment] = []
    for p in placed_segments(edl):
        lo, hi = max(a.start, p.out_start), min(a.end, p.out_end)
        if hi <= lo:
            segments.append(p.segment)
            continue
        src_lo = p.segment.start + (lo - p.out_start)
        src_hi = p.segment.start + (hi - p.out_start)
        segments.extend(_subtract(p.segment, src_lo, src_hi))
    return OpResult(_finish(edl, segments), f"delete {a.start:.2f}-{a.end:.2f}s", (a.start, a.end))


SILENCE_LEVELS: dict[str, float] = {"low": 0.9, "medium": 0.6, "high": 0.35}


class RemoveSilencesArgs(_A):
    level: Literal["low", "medium", "high"] = "medium"
    silences: list[tuple[float, float]] = Field(
        default_factory=lambda: [],
        description="silent ranges in source seconds (filled in from the analysis)",
    )
    pad: float = Field(default=0.08, ge=0, le=0.3, description="keep this much air around speech")


def remove_silences(edl: Edl, a: RemoveSilencesArgs) -> OpResult:
    min_len = SILENCE_LEVELS[a.level]
    segments = list(edl.segments)
    removed = 0.0
    count = 0
    for s, e in sorted(a.silences):
        if e - s < min_len - 1e-6:
            continue
        lo, hi = s + a.pad, e - a.pad
        if hi - lo < MIN_SEGMENT:
            continue
        before = sum(x.duration for x in segments)
        segments = remove_source_range(segments, lo, hi)
        delta = before - sum(x.duration for x in segments)
        if delta > 0:
            removed += delta
            count += 1
    if count == 0:
        return OpResult(edl, f"remove silences ({a.level}): nothing to remove")
    return OpResult(
        _finish(edl, segments), f"remove silences ({a.level}): {count} gaps, {removed:.1f}s", None
    )


FILLERS = frozenset({"um", "umm", "uh", "uhh", "er", "erm", "ah", "hmm", "mm", "uh-huh"})
_WORD = re.compile(r"[^\w'-]+")


def _norm(word: str) -> str:
    return _WORD.sub("", word.lower())


class RemoveFillersArgs(_A):
    extra_words: list[str] = Field(default_factory=list, description="more filler words to cut, e.g. 'like'")
    false_starts: bool = Field(
        default=True, description="also cut an immediately repeated word ('I I think')"
    )


def remove_fillers(edl: Edl, a: RemoveFillersArgs) -> OpResult:
    fillers = FILLERS | {_norm(w) for w in a.extra_words}
    words = edl.captions.words
    drop: set[int] = set()
    for i, w in enumerate(words):
        n = _norm(w.text)
        if n in fillers:
            drop.add(i)
        elif a.false_starts and i + 1 < len(words) and n and n == _norm(words[i + 1].text):
            gap = words[i + 1].t - w.end
            if gap < 0.6:
                drop.add(i)
    if not drop:
        return OpResult(edl, "remove fillers: none found")
    segments = list(edl.segments)
    for i in sorted(drop):
        w = words[i]
        segments = remove_source_range(segments, w.t - 0.02, w.end + 0.02, frozenset({"main", "teaser"}))
    kept = [w for i, w in enumerate(words) if i not in drop]
    result = _finish(edl, segments, captions=edl.captions.model_copy(update={"words": kept}))
    return OpResult(result, f"remove fillers: {len(drop)} words", None)


class SetLayoutArgs(_A):
    start: float = Field(description="output seconds")
    end: float = Field(description="output seconds")
    layout: Layout
    focus_x: float | None = Field(default=None, ge=0, le=1, description="crop center, 0=left 1=right")
    focus2_x: float | None = Field(default=None, ge=0, le=1, description="second speaker center (split)")


def _key_at(edl: Edl, t_src: float) -> CameraKey:
    keys = [k for k in edl.camera if k.t <= t_src]
    return keys[-1] if keys else (edl.camera[0] if edl.camera else CameraKey(t=t_src))


def _split_at_out(edl: Edl, t_out: float) -> Edl:
    try:
        return split(edl, SplitArgs(t=t_out)).edl
    except EditError:
        return edl  # already at a cut


def set_layout(edl: Edl, a: SetLayoutArgs) -> OpResult:
    _check_out_range(edl, a.start, a.end)
    work = _split_at_out(_split_at_out(edl, a.start), a.end)
    placed = placed_segments(work)
    affected = [p for p in placed if p.out_start >= a.start - 1e-6 and p.out_end <= a.end + 1e-6]
    if not affected:
        raise EditError("no whole segment inside that range")
    keys = list(work.camera)
    for p in affected:
        prev = _key_at(work, p.segment.start)
        keys = [k for k in keys if not (p.segment.start <= k.t < p.segment.end)]
        keys.append(
            prev.model_copy(
                update={
                    "t": p.segment.start,
                    "layout": a.layout,
                    "focus_x": a.focus_x if a.focus_x is not None else prev.focus_x,
                    "focus2_x": a.focus2_x if a.focus2_x is not None else prev.focus2_x,
                }
            )
        )
        nxt = p.segment.end
        if not any(abs(k.t - nxt) < 1e-6 for k in keys):
            keys.append(prev.model_copy(update={"t": nxt}))
    keys.sort(key=lambda k: k.t)
    result = _finish(work, list(work.segments), camera=[k.model_dump() for k in keys])
    return OpResult(result, f"{a.layout} layout {a.start:.2f}-{a.end:.2f}s", (a.start, a.end))


class CameraKeyIn(_A):
    t: float = Field(description="source seconds")
    layout: Layout = "crop"
    focus_x: float = Field(default=0.5, ge=0, le=1)
    focus_y: float = Field(default=0.5, ge=0, le=1)
    focus2_x: float | None = None
    zoom: float = Field(default=1.0, ge=1.0, le=1.5)


class SetCameraKeysArgs(_A):
    keys: list[CameraKeyIn]
    replace_from: float | None = Field(default=None, description="drop existing keys from this source second")
    replace_to: float | None = Field(default=None, description="... up to this source second")


def set_camera_keyframes(edl: Edl, a: SetCameraKeysArgs) -> OpResult:
    if not a.keys:
        raise EditError("no keys given")
    lo = a.replace_from if a.replace_from is not None else min(k.t for k in a.keys)
    hi = a.replace_to if a.replace_to is not None else max(k.t for k in a.keys)
    keep = [k for k in edl.camera if not (lo <= k.t <= hi)]
    keys = sorted([*keep, *(CameraKey(**k.model_dump()) for k in a.keys)], key=lambda k: k.t)
    result = _finish(edl, list(edl.segments), camera=[k.model_dump() for k in keys])
    return OpResult(result, f"camera keys {lo:.2f}-{hi:.2f}s ({len(a.keys)})", None)


class SetCaptionStyleArgs(_A):
    style: str | None = None
    position: Literal["auto", "top", "middle", "bottom"] | None = None
    safe_zone: SafeZone | None = None
    max_words_per_line: int | None = Field(default=None, ge=1, le=8)
    enabled: bool | None = None
    profanity_mask: bool | None = None


def set_caption_style(edl: Edl, a: SetCaptionStyleArgs) -> OpResult:
    from clipper.media.edl.captions import STYLES

    if a.style is not None and a.style not in STYLES:
        raise EditError(f"unknown caption style {a.style!r}; choose one of {', '.join(STYLES)}")
    changes = {k: v for k, v in a.model_dump().items() if v is not None}
    if not changes:
        raise EditError("nothing to change")
    caps = Captions.model_validate({**edl.captions.model_dump(), **changes})
    result = _finish(edl, list(edl.segments), captions=caps)
    return OpResult(result, "captions: " + ", ".join(f"{k}={v}" for k, v in changes.items()), None)


class WordEdit(_A):
    index: int = Field(ge=0)
    text: str = Field(description="new text; empty string hides the word")


class EditCaptionWordsArgs(_A):
    edits: list[WordEdit]


def edit_caption_words(edl: Edl, a: EditCaptionWordsArgs) -> OpResult:
    words = list(edl.captions.words)
    drop: set[int] = set()
    for e in a.edits:
        if e.index >= len(words):
            raise EditError(f"no caption word {e.index} (there are {len(words)})")
        if e.text.strip():
            words[e.index] = words[e.index].model_copy(update={"text": e.text.strip()})
        else:
            drop.add(e.index)
    kept = [w for i, w in enumerate(words) if i not in drop]
    result = _finish(edl, list(edl.segments), captions=edl.captions.model_copy(update={"words": kept}))
    return OpResult(result, f"edit {len(a.edits)} caption words", None)


class EmphasizeArgs(_A):
    indices: list[int] = Field(default_factory=list[int], description="caption word indices")
    words: list[str] = Field(default_factory=list, description="or match these words (case-insensitive)")
    on: bool = True


def emphasize(edl: Edl, a: EmphasizeArgs) -> OpResult:
    targets = {_norm(w) for w in a.words}
    words = list(edl.captions.words)
    hit = 0
    for i, w in enumerate(words):
        if i in a.indices or (targets and _norm(w.text) in targets):
            words[i] = w.model_copy(update={"emphasis": a.on})
            hit += 1
    if hit == 0:
        raise EditError("no caption words matched")
    result = _finish(edl, list(edl.segments), captions=edl.captions.model_copy(update={"words": words}))
    return OpResult(result, f"{'emphasize' if a.on else 'un-emphasize'} {hit} words", None)


class SetHookArgs(_A):
    type: Literal["cold_open", "text", "none"]
    start: float | None = Field(default=None, description="cold open: teaser start, source seconds")
    end: float | None = Field(default=None, description="cold open: teaser end, source seconds")
    text: str | None = Field(default=None, description="hook text for the first ~2s")
    seconds: float = Field(default=2.0, ge=0.5, le=5.0, description="how long the hook text shows")


def set_hook(edl: Edl, a: SetHookArgs) -> OpResult:
    segments = [s for s in edl.segments if s.kind != "teaser"]
    overlays = [o for o in edl.overlays if o.type != "hook_text"]
    hook = edl.hook
    if a.type == "cold_open":
        if a.start is None or a.end is None:
            raise EditError("cold open needs start and end (source seconds)")
        length = a.end - a.start
        if not (0.5 <= length <= 3.0):
            raise EditError("a cold-open teaser should be 0.5-3s long")
        segments = [Segment(start=a.start, end=a.end, kind="teaser"), *segments]
        hook = Hook(type="cold_open", range=TimeRange(start=a.start, end=a.end), text=hook.text)
        summary = f"cold open from {a.start:.2f}s ({length:.1f}s)"
        overlays = list(edl.overlays)  # keep hook text if any
    elif a.type == "text":
        if not a.text or not a.text.strip():
            raise EditError("hook text is empty")
        segments = list(edl.segments)
        overlays.append(
            Overlay(
                id="hook_text", type="hook_text", t_in=0.0, t_out=a.seconds, props={"text": a.text.strip()}
            )
        )
        hook = Hook(
            type=edl.hook.type if edl.hook.type == "cold_open" else "text",
            range=edl.hook.range,
            text=a.text.strip(),
        )
        summary = f'hook text "{a.text.strip()}"'
    else:
        hook = Hook()
        summary = "remove hook"
    result = _finish(edl, segments, overlays=[o.model_dump() for o in overlays], hook=hook)
    return OpResult(result, summary, (0.0, min(2.0, result.duration)))


class AddOverlayArgs(_A):
    type: Literal["hook_text", "progress_bar", "brand"]
    t_in: float = 0.0
    t_out: float | None = Field(default=None, description="output seconds; default = end of clip")
    props: dict[str, Any] = Field(default_factory=dict, description="e.g. {'text': '@creator'}")


def add_overlay(edl: Edl, a: AddOverlayArgs) -> OpResult:
    t_out = a.t_out if a.t_out is not None else edl.duration
    _check_out_range(edl, a.t_in, t_out)
    n = sum(1 for o in edl.overlays if o.type == a.type)
    overlay = Overlay(id=f"{a.type}-{n + 1}", type=a.type, t_in=a.t_in, t_out=t_out, props=a.props)
    result = _finish(
        edl, list(edl.segments), overlays=[*(o.model_dump() for o in edl.overlays), overlay.model_dump()]
    )
    return OpResult(result, f"add {a.type} {a.t_in:.2f}-{t_out:.2f}s", (a.t_in, t_out))


class SetAudioArgs(_A):
    loudness: float | None = Field(default=None, ge=-24, le=-9)
    denoise: bool | None = None
    duck_music: bool | None = None
    gain_db: float | None = Field(default=None, ge=-12, le=12)
    fade_ms: int | None = Field(default=None, ge=0, le=500)


def set_audio(edl: Edl, a: SetAudioArgs) -> OpResult:
    changes = {k: v for k, v in a.model_dump().items() if v is not None}
    if not changes:
        raise EditError("nothing to change")
    audio = Audio.model_validate({**edl.audio.model_dump(), **changes})
    result = _finish(edl, list(edl.segments), audio=audio)
    return OpResult(result, "audio: " + ", ".join(f"{k}={v}" for k, v in changes.items()), None)


# ---------------------------------------------------------------- registry


@dataclass(frozen=True)
class OpSpec:
    name: str
    args: type[BaseModel]
    fn: Callable[[Edl, Any], OpResult]
    description: str


OPS: dict[str, OpSpec] = {
    spec.name: spec
    for spec in (
        OpSpec("trim", TrimArgs, trim, "Set the start/end of the clip's main material (source seconds)."),
        OpSpec("split", SplitArgs, split, "Split the segment at an output time."),
        OpSpec("delete_range", DeleteRangeArgs, delete_range, "Cut out an output-time range."),
        OpSpec("remove_silences", RemoveSilencesArgs, remove_silences, "Remove dead air (low/medium/high)."),
        OpSpec("remove_fillers", RemoveFillersArgs, remove_fillers, "Cut filler words and false starts."),
        OpSpec("set_layout", SetLayoutArgs, set_layout, "Layout for an output range: crop, split or fit."),
        OpSpec("set_camera_keyframes", SetCameraKeysArgs, set_camera_keyframes, "Place virtual-camera keys."),
        OpSpec(
            "set_caption_style", SetCaptionStyleArgs, set_caption_style, "Caption style, position, safe zone."
        ),
        OpSpec("edit_caption_words", EditCaptionWordsArgs, edit_caption_words, "Fix or hide caption words."),
        OpSpec("emphasize", EmphasizeArgs, emphasize, "Mark caption words for emphasis."),
        OpSpec("set_hook", SetHookArgs, set_hook, "Cold open teaser, hook text, or none."),
        OpSpec("add_overlay", AddOverlayArgs, add_overlay, "Add hook text, progress bar or brand overlay."),
        OpSpec("set_audio", SetAudioArgs, set_audio, "Loudness, denoise, ducking, gain, fades."),
    )
}


def apply_op(edl: Edl, op: str, args: dict[str, Any]) -> OpResult:
    spec = OPS.get(op)
    if spec is None:
        raise EditError(f"unknown edit op {op!r}")
    return spec.fn(edl, spec.args.model_validate(args))


def replay(base: Edl, ops: list[tuple[str, dict[str, Any]]]) -> tuple[Edl, list[str]]:
    """Apply ops in order to ``base``; ops that no longer apply are skipped and reported."""
    edl = base
    skipped: list[str] = []
    for op, args in ops:
        try:
            edl = apply_op(edl, op, args).edl
        except EditError as exc:
            skipped.append(f"{op}: {exc}")
    return edl, skipped


def source_time(edl: Edl, t_out: float) -> float:
    return output_to_source(edl, t_out)[1]
