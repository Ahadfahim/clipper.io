"""Mapping between output time and source time through an EDL's segments. Pure functions."""

from __future__ import annotations

from dataclasses import dataclass

from clipper.media.edl.schema import CameraKey, CaptionWord, Edl, Segment


@dataclass(frozen=True)
class Placed:
    """A segment with its position on the output timeline."""

    index: int
    segment: Segment
    out_start: float

    @property
    def out_end(self) -> float:
        return self.out_start + self.segment.duration


def placed_segments(edl: Edl) -> list[Placed]:
    out: list[Placed] = []
    t = 0.0
    for i, seg in enumerate(edl.segments):
        out.append(Placed(i, seg, t))
        t += seg.duration
    return out


def output_to_source(edl: Edl, t_out: float) -> tuple[int, float]:
    """Output time -> (segment index, source time). Clamps to the clip."""
    placed = placed_segments(edl)
    for p in placed:
        if t_out < p.out_end or p is placed[-1]:
            local = min(max(t_out - p.out_start, 0.0), p.segment.duration)
            return p.index, p.segment.start + local
    raise ValueError("empty EDL")  # pragma: no cover - EDL validation forbids it


def source_to_output(edl: Edl, t_src: float) -> list[float]:
    """Every output time at which source time ``t_src`` plays (0, 1 or 2 with a cold open)."""
    hits: list[float] = []
    for p in placed_segments(edl):
        if p.segment.start <= t_src < p.segment.end:
            hits.append(p.out_start + (t_src - p.segment.start))
    return hits


@dataclass(frozen=True)
class OutWord:
    text: str
    start: float  # output time
    end: float
    emphasis: bool
    segment: int
    source_index: int  # index in edl.captions.words


def output_words(edl: Edl) -> list[OutWord]:
    """Caption words placed on the output timeline, clipped to their segments."""
    words: list[OutWord] = []
    for p in placed_segments(edl):
        seg = p.segment
        for i, w in enumerate(edl.captions.words):
            if w.end <= seg.start or w.t >= seg.end:
                continue
            # keep a word only if most of it is inside the segment (never show half-cut words)
            inside = min(w.end, seg.end) - max(w.t, seg.start)
            if inside < 0.5 * max(w.end - w.t, 1e-3):
                continue
            start = p.out_start + max(w.t, seg.start) - seg.start
            end = p.out_start + min(w.end, seg.end) - seg.start
            words.append(OutWord(w.text, round(start, 3), round(end, 3), w.emphasis, p.index, i))
    words.sort(key=lambda w: (w.start, w.source_index))
    return words


def camera_keys_for_segment(edl: Edl, seg: Segment) -> list[CameraKey]:
    """Keys that apply inside ``seg``: the last key at or before its start, plus keys inside it."""
    keys = sorted(edl.camera, key=lambda k: k.t)
    before = [k for k in keys if k.t <= seg.start]
    inside = [k for k in keys if seg.start < k.t < seg.end]
    first = before[-1] if before else (inside[0] if inside else CameraKey(t=seg.start))
    return [first.model_copy(update={"t": seg.start}), *inside]


def segment_layout(edl: Edl, seg: Segment) -> str:
    """A segment renders with one layout: the layout in effect at its start."""
    return camera_keys_for_segment(edl, seg)[0].layout


def words_in(words: list[CaptionWord], start: float, end: float) -> list[int]:
    return [i for i, w in enumerate(words) if w.t < end and w.end > start]
