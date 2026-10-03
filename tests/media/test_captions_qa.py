from __future__ import annotations

import re

import pytest

from clipper.media.edl import ops
from clipper.media.edl.captions import SAFE_ZONES, STYLES, build_ass, caption_box, mask, phrase_lines
from clipper.media.edl.qa import (
    Measurements,
    check_black_frames,
    check_captions_face,
    check_captions_safe_zone,
    check_clipping,
    check_face_in_frame,
    check_frozen_frames,
    check_length,
    check_silence_ratio,
    check_speech_start,
    qa_report,
)
from clipper.media.edl.schema import Box, Edl
from clipper.media.edl.timeline import output_words
from clipper.media.reframe import auto_camera_keys


def _dialogues(ass: str, style: str = "Caption") -> list[str]:
    return [line for line in ass.splitlines() if line.startswith("Dialogue:") and f",{style}," in line]


def test_ass_header_and_word_by_word(edl: Edl) -> None:
    ass = build_ass(edl)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Style: Caption,Arial,84" in ass
    lines = _dialogues(ass)
    assert len(lines) == len(edl.captions.words)  # one event per highlighted word
    assert lines[0].startswith("Dialogue: 1,0:00:00.20,")
    assert r"{\c&H004DE1FF&}NOBODY{\r}" in lines[0]  # current word highlighted, uppercase style


def test_emphasis_profanity_and_hook(edl: Edl) -> None:
    e = ops.emphasize(edl, ops.EmphasizeArgs(words=["money"])).edl
    e = ops.set_hook(e, ops.SetHookArgs(type="text", text="Watch this")).edl
    e = ops.edit_caption_words(e, ops.EditCaptionWordsArgs(edits=[ops.WordEdit(index=0, text="Shit")])).edl
    e = ops.set_caption_style(e, ops.SetCaptionStyleArgs(profanity_mask=True)).edl
    ass = build_ass(e)
    assert r"\fscx115\fscy115" in ass
    assert "S***" in ass and "SHIT" not in ass
    hooks = _dialogues(ass, "Hook")
    assert (
        len(hooks) == 1
        and "Watch this" in hooks[0]
        and hooks[0].startswith("Dialogue: 2,0:00:00.00,0:00:02.00")
    )
    assert mask("damn!") == "d****"


def test_phrase_breaks_at_pauses_and_max_words(edl: Edl) -> None:
    lines = phrase_lines(output_words(edl), max_words=3)
    assert all(len(line.words) <= 3 for line in lines)
    # each 1.4 s burst is followed by a 0.6 s pause -> lines never span two bursts
    for line in lines:
        assert line.end - line.start < 1.5


@pytest.mark.parametrize("zone", ["tiktok", "shorts", "reels"])
def test_captions_inside_platform_safe_zone(edl: Edl, zone: str) -> None:
    e = ops.set_caption_style(edl, ops.SetCaptionStyleArgs(safe_zone=zone)).edl  # type: ignore[arg-type]
    assert check_captions_safe_zone(e).ok
    box = caption_box(e, STYLES[e.captions.style])
    area = SAFE_ZONES[zone]
    assert box.y + box.h <= 1920 - area.bottom
    assert box.x + box.w <= 1080 - area.right


def test_face_avoidance_moves_captions_up(edl: Edl) -> None:
    low_face = edl.model_copy(
        update={"captions": edl.captions.model_copy(update={"face_box": Box(x=0.2, y=0.55, w=0.6, h=0.35)})}
    )
    box = caption_box(low_face, STYLES["bold-pop"])
    assert box.align == 8  # top band
    assert check_captions_face(low_face).ok
    ass = build_ass(low_face)
    style = next(line for line in ass.splitlines() if line.startswith("Style: Caption"))
    assert style.split(",")[18] == "8"


def test_speech_start_and_length(edl: Edl) -> None:
    assert check_speech_start(edl).ok  # first word at 0.2 s
    late = ops.trim(edl, ops.TrimArgs(start=1.2, end=9.0)).edl  # starts in a pause
    res = check_speech_start(late)
    assert not res.ok and res.value is not None and float(res.value) > 0.5
    assert check_length(edl, 5, 60).ok
    assert not check_length(edl, 15, 60).ok


def test_face_in_frame() -> None:
    from clipper.media.edl.schema import new_edl
    from tests.media.conftest import talk_source, talk_words

    e = new_edl(talk_source(), 0.0, 10.0, words=talk_words(), focus_x=0.5)
    centered = [(t * 0.5, Box(x=0.45, y=0.3, w=0.1, h=0.2)) for t in range(21)]
    assert check_face_in_frame(e, centered).ok
    left = [(t * 0.5, Box(x=0.02, y=0.3, w=0.1, h=0.2)) for t in range(21)]
    res = check_face_in_frame(e, left)
    assert not res.ok and res.value == 0.0
    fit = ops.set_layout(e, ops.SetLayoutArgs(start=0.0, end=10.0, layout="fit")).edl
    assert check_face_in_frame(fit, left).ok


def test_measurement_checks() -> None:
    bad = Measurements(
        duration=4.0,
        width=320,
        height=180,
        black=[(1.0, 2.5)],
        frozen=[(2.5, 4.0)],
        silences=[(0.0, 4.0)],
        peak_db=0.0,
    )
    assert not check_black_frames(bad).ok
    assert not check_frozen_frames(bad).ok
    assert not check_clipping(bad).ok
    assert not check_silence_ratio(bad).ok
    good = Measurements(
        duration=10.0, width=1080, height=1920, black=[], frozen=[], silences=[(1.0, 1.5)], peak_db=-1.6
    )
    assert all(
        c(good).ok for c in (check_black_frames, check_frozen_frames, check_clipping, check_silence_ratio)
    )


def test_qa_report_shape(edl: Edl) -> None:
    rep = qa_report(edl, None, min_s=5, max_s=60)
    assert rep["ok"] is True
    assert {c["name"] for c in rep["checks"]} == {
        "speech_start",
        "length",
        "face_in_frame",
        "captions_safe_zone",
        "captions_face",
    }


def test_auto_camera_dead_zone() -> None:
    track = [(t * 0.25, Box(x=0.40 + (0.02 if t % 2 else 0), y=0.3, w=0.1, h=0.2)) for t in range(16)]
    keys = auto_camera_keys(track, 0.0, 4.0)
    assert len(keys) == 1  # jitter inside the dead zone doesn't move the camera
    moved = [*track, (4.5, Box(x=0.75, y=0.3, w=0.1, h=0.2))]
    keys = auto_camera_keys(moved, 0.0, 5.0)
    assert len(keys) == 2 and keys[1].focus_x == pytest.approx(0.8)
    assert auto_camera_keys([], 0.0, 5.0)[0].layout == "fit"


def test_ass_timestamps_are_monotonic(edl: Edl) -> None:
    starts = [re.match(r"Dialogue: \d,([\d:.]+),", line).group(1) for line in _dialogues(build_ass(edl))]  # type: ignore[union-attr]
    assert starts == sorted(starts)
