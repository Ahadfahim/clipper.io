from __future__ import annotations

import pytest

from clipper.media.edl import ops
from clipper.media.edl.ops import EditError, apply_op, replay
from clipper.media.edl.schema import Edl
from clipper.media.edl.timeline import output_to_source, output_words, source_to_output
from tests.media.conftest import FIXTURE_SILENCES


def test_new_edl_basics(edl: Edl) -> None:
    assert edl.duration == pytest.approx(10.0)
    assert len(edl.segments) == 1
    assert edl.captions.words[0].text == "Nobody"


def test_trim_shrinks_and_extends(edl: Edl) -> None:
    short = ops.trim(edl, ops.TrimArgs(start=2.0, end=8.0)).edl
    assert short.duration == pytest.approx(6.0)
    assert all(w.end > 2.0 and w.t < 8.0 for w in short.captions.words)
    longer = ops.trim(short, ops.TrimArgs(start=1.0, end=9.5)).edl  # re-cut with more footage
    assert longer.duration == pytest.approx(8.5)
    with pytest.raises(EditError):
        ops.trim(edl, ops.TrimArgs(start=-1.0, end=5.0))
    with pytest.raises(EditError):
        ops.trim(edl, ops.TrimArgs(start=3.0, end=3.5))


def test_split_and_delete_range(edl: Edl) -> None:
    split = ops.split(edl, ops.SplitArgs(t=4.0)).edl
    assert [(s.start, s.end) for s in split.segments] == [(0.0, 4.0), (4.0, 10.0)]
    assert split.duration == pytest.approx(10.0)
    cut = ops.delete_range(split, ops.DeleteRangeArgs(start=3.0, end=5.0)).edl
    assert cut.duration == pytest.approx(8.0)
    assert [(s.start, s.end) for s in cut.segments] == [(0.0, 3.0), (5.0, 10.0)]
    assert output_to_source(cut, 3.5) == (1, 5.5)
    with pytest.raises(EditError):
        ops.delete_range(cut, ops.DeleteRangeArgs(start=0.0, end=8.0))  # nothing left
    with pytest.raises(EditError):
        ops.split(edl, ops.SplitArgs(t=0.01))


def test_remove_silences_levels(edl: Edl) -> None:
    low = ops.remove_silences(edl, ops.RemoveSilencesArgs(level="low", silences=FIXTURE_SILENCES))
    assert low.edl.duration == pytest.approx(10.0)  # 0.6 s gaps are below the low threshold
    med = ops.remove_silences(
        edl, ops.RemoveSilencesArgs(level="medium", silences=FIXTURE_SILENCES, pad=0.08)
    )
    assert med.edl.duration == pytest.approx(10.0 - 5 * (0.6 - 0.16), abs=1e-6)
    assert "5 gaps" in med.summary


def test_remove_fillers_and_false_starts(edl: Edl) -> None:
    res = ops.remove_fillers(edl, ops.RemoveFillersArgs())
    texts = [w.text for w in res.edl.captions.words]
    assert "um" not in texts
    assert texts.count("really") == 1  # "really really" false start
    assert res.edl.duration < edl.duration
    assert "2 words" in res.summary


def test_set_layout_splits_segments_and_restores(edl: Edl) -> None:
    res = ops.set_layout(
        edl, ops.SetLayoutArgs(start=2.0, end=4.0, layout="split", focus_x=0.3, focus2_x=0.7)
    ).edl
    assert [(s.start, s.end) for s in res.segments] == [(0.0, 2.0), (2.0, 4.0), (4.0, 10.0)]
    layouts = [(k.t, k.layout) for k in res.camera]
    assert (2.0, "split") in layouts
    assert (4.0, "crop") in layouts


def test_cold_open_duplicates_words(edl: Edl) -> None:
    res = ops.set_hook(edl, ops.SetHookArgs(type="cold_open", start=6.2, end=7.4)).edl
    assert res.segments[0].kind == "teaser"
    assert res.duration == pytest.approx(11.2)
    assert len(source_to_output(res, 6.5)) == 2
    first = output_words(res)[0]
    assert first.text == "really" and first.start == pytest.approx(0.0)
    none = ops.set_hook(res, ops.SetHookArgs(type="none")).edl
    assert none.duration == pytest.approx(10.0)
    with pytest.raises(EditError):
        ops.set_hook(edl, ops.SetHookArgs(type="cold_open", start=1.0, end=6.0))


def test_hook_text_caption_ops_overlay_audio(edl: Edl) -> None:
    e = ops.set_hook(edl, ops.SetHookArgs(type="text", text="Nobody tells you this")).edl
    assert e.overlays[0].type == "hook_text"
    e = ops.emphasize(e, ops.EmphasizeArgs(words=["money"])).edl
    assert any(w.emphasis for w in e.captions.words if w.text == "money")
    e = ops.edit_caption_words(
        e,
        ops.EditCaptionWordsArgs(
            edits=[ops.WordEdit(index=0, text="NOBODY"), ops.WordEdit(index=1, text="")]
        ),
    ).edl
    assert e.captions.words[0].text == "NOBODY" and e.captions.words[1].text == "you"
    e = ops.set_caption_style(e, ops.SetCaptionStyleArgs(style="boxed", safe_zone="reels")).edl
    assert (e.captions.style, e.captions.safe_zone) == ("boxed", "reels")
    with pytest.raises(EditError):
        ops.set_caption_style(e, ops.SetCaptionStyleArgs(style="comic-sans"))
    e = ops.add_overlay(e, ops.AddOverlayArgs(type="progress_bar")).edl
    assert e.overlays[-1].t_out == pytest.approx(e.duration)
    e = ops.set_audio(e, ops.SetAudioArgs(denoise=True, gain_db=2.0)).edl
    assert e.audio.denoise and e.audio.gain_db == 2.0


def test_camera_keyframes_replace_range(edl: Edl) -> None:
    keys = [ops.CameraKeyIn(t=1.0, focus_x=0.2), ops.CameraKeyIn(t=3.0, focus_x=0.8, zoom=1.08)]
    e = ops.set_camera_keyframes(edl, ops.SetCameraKeysArgs(keys=keys)).edl
    assert [k.t for k in e.camera] == [0.0, 1.0, 3.0]


def test_apply_op_and_replay(edl: Edl) -> None:
    res = apply_op(edl, "trim", {"start": 1.0, "end": 9.0})
    assert res.edl.duration == pytest.approx(8.0)
    with pytest.raises(EditError):
        apply_op(edl, "explode", {})
    final, skipped = replay(
        edl, [("trim", {"start": 1.0, "end": 9.0}), ("split", {"t": 0.0}), ("split", {"t": 4.0})]
    )
    assert len(final.segments) == 2
    assert skipped and skipped[0].startswith("split")


def test_ops_are_pure(edl: Edl) -> None:
    before = edl.model_dump()
    ops.remove_fillers(edl, ops.RemoveFillersArgs())
    ops.set_layout(edl, ops.SetLayoutArgs(start=1.0, end=3.0, layout="fit"))
    assert edl.model_dump() == before
