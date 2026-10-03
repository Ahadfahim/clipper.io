"""Automatic QA on every EDL / render (PLAN §18.3). Checks are pure functions over the EDL and
measurements; ``measure()`` runs the ffmpeg measurement filters on a rendered file."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from clipper.media.edl.captions import caption_layout_report
from clipper.media.edl.render import crop_window
from clipper.media.edl.schema import Box, Edl
from clipper.media.edl.timeline import camera_keys_for_segment, output_to_source, output_words
from clipper.media.ffmpeg import audio_peak_db, detect_black, detect_freeze, detect_silences, probe
from clipper.settings import Settings


@dataclass(frozen=True)
class QaCheck:
    name: str
    ok: bool
    value: float | str | None
    limit: float | str | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Measurements:
    duration: float
    width: int
    height: int
    black: list[tuple[float, float]]
    frozen: list[tuple[float, float]]
    silences: list[tuple[float, float]]
    peak_db: float


def check_speech_start(edl: Edl, limit: float = 0.5) -> QaCheck:
    words = output_words(edl)
    if not words:
        return QaCheck(
            "speech_start", False, None, limit, "no caption words: can't confirm speech in the opening"
        )
    first = words[0].start
    return QaCheck("speech_start", first <= limit, round(first, 2), limit, f"first word at {first:.2f}s")


def check_length(edl: Edl, min_s: float, max_s: float) -> QaCheck:
    d = edl.duration
    ok = min_s <= d <= max_s
    return QaCheck("length", ok, round(d, 2), f"{min_s:g}-{max_s:g}", f"{d:.1f}s (spec {min_s:g}-{max_s:g}s)")


def _window_contains(edl: Edl, t_src: float, seg_index: int, face: Box) -> bool:
    seg = edl.segments[seg_index]
    keys = camera_keys_for_segment(edl, seg)
    key = [k for k in keys if k.t <= max(t_src, seg.start)][-1]
    if key.layout == "fit":
        return True
    W, H = edl.source.width, edl.source.height
    aspect = edl.output.width / (edl.output.height / (2 if key.layout == "split" else 1))
    cw, _ = crop_window(W, H, aspect)
    cx = face.cx * W
    centers = [key.focus_x] + (
        [key.focus2_x if key.focus2_x is not None else 1 - key.focus_x] if key.layout == "split" else []
    )
    for c in centers:
        x0 = min(max(c * W - cw / 2, 0), W - cw)
        if x0 <= cx <= x0 + cw:
            return True
    return False


def check_face_in_frame(
    edl: Edl, face_track: list[tuple[float, Box]], threshold: float = 0.9, step: float = 0.5
) -> QaCheck:
    if not face_track:
        return QaCheck(
            "face_in_frame", True, None, threshold, "no face track (wide shot or no faces): skipped"
        )
    track = sorted(face_track, key=lambda p: p[0])
    total = hits = 0
    t = 0.0
    while t < edl.duration:
        idx, src = output_to_source(edl, t)
        nearest = min(track, key=lambda p: abs(p[0] - src))
        if abs(nearest[0] - src) <= 1.0:
            total += 1
            hits += _window_contains(edl, src, idx, nearest[1])
        t += step
    if total == 0:
        return QaCheck("face_in_frame", True, None, threshold, "no face samples inside the clip")
    ratio = hits / total
    return QaCheck(
        "face_in_frame",
        ratio >= threshold,
        round(ratio, 3),
        threshold,
        f"face in frame {ratio:.0%} of the time",
    )


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def check_captions_safe_zone(edl: Edl) -> QaCheck:
    rep = caption_layout_report(edl)
    bx, by, bw, bh = rep.box
    sx, sy, sw, sh = rep.safe
    inside = bx >= sx and by >= sy and bx + bw <= sx + sw and by + bh <= sy + sh
    return QaCheck(
        "captions_safe_zone",
        inside,
        f"{bx},{by},{bw}x{bh}",
        f"{sx},{sy},{sw}x{sh}",
        f"captions inside the {edl.captions.safe_zone} safe area",
    )


def check_captions_face(edl: Edl) -> QaCheck:
    rep = caption_layout_report(edl)
    face = rep.face
    if face is None:
        return QaCheck("captions_face", True, None, None, "no face box: skipped")
    clash = _overlap(rep.box, face)
    return QaCheck(
        "captions_face",
        not clash,
        None,
        None,
        "captions cover the face" if clash else "captions clear of the face",
    )


def check_black_frames(m: Measurements, max_total: float = 0.2) -> QaCheck:
    total = sum(e - s for s, e in m.black)
    return QaCheck("black_frames", total <= max_total, round(total, 2), max_total, f"{total:.2f}s of black")


def check_frozen_frames(m: Measurements, max_total: float = 1.0) -> QaCheck:
    total = sum(min(e, m.duration) - s for s, e in m.frozen)
    return QaCheck("frozen_frames", total < max_total, round(total, 2), max_total, f"{total:.2f}s frozen")


def check_clipping(m: Measurements, limit_db: float = -0.1) -> QaCheck:
    ok = m.peak_db < limit_db
    return QaCheck("audio_clipping", ok, round(m.peak_db, 2), limit_db, f"peak {m.peak_db:.2f} dBFS")


def check_silence_ratio(m: Measurements, max_ratio: float = 0.25) -> QaCheck:
    total = sum(min(e, m.duration) - s for s, e in m.silences)
    ratio = total / m.duration if m.duration else 1.0
    return QaCheck("silence_ratio", ratio <= max_ratio, round(ratio, 3), max_ratio, f"{ratio:.0%} silent")


def measure(path: Path, settings: Settings) -> Measurements:
    info = probe(path, settings)
    return Measurements(
        duration=info.duration,
        width=info.width,
        height=info.height,
        black=detect_black(path, settings),
        frozen=detect_freeze(path, settings),
        silences=detect_silences(path, settings, noise_db=settings.media.silence_threshold_db, min_s=0.5)
        if info.has_audio
        else [],
        peak_db=audio_peak_db(path, settings) if info.has_audio else float("-inf"),
    )


def qa_report(
    edl: Edl,
    m: Measurements | None,
    *,
    min_s: float = 15.0,
    max_s: float = 60.0,
    face_track: list[tuple[float, Box]] | None = None,
) -> dict[str, Any]:
    checks = [
        check_speech_start(edl),
        check_length(edl, min_s, max_s),
        check_face_in_frame(edl, face_track or []),
        check_captions_safe_zone(edl),
        check_captions_face(edl),
    ]
    if m is not None:
        checks += [check_black_frames(m), check_frozen_frames(m), check_clipping(m), check_silence_ratio(m)]
    return {"ok": all(c.ok for c in checks), "checks": [c.as_dict() for c in checks]}
