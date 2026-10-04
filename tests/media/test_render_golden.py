"""Golden renders: synthetic fixtures through the CPU (libx264) path."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipper.media.edl import ops
from clipper.media.edl.qa import measure, qa_report
from clipper.media.edl.render import build_render_plan, encode_to_size, render_edl, thumbnail
from clipper.media.edl.schema import Edl
from clipper.media.encode import NvencEncoder, X264Encoder, final_profile, proxy_profile
from clipper.media.ffmpeg import measure_loudness, probe
from clipper.settings import Settings
from tests.media.conftest import FIXTURE_SILENCES, QA_BAD

pytestmark = pytest.mark.ffmpeg


def _edited(edl: Edl) -> Edl:
    e = ops.set_hook(edl, ops.SetHookArgs(type="text", text="Nobody tells you this")).edl
    e = ops.remove_silences(e, ops.RemoveSilencesArgs(level="medium", silences=FIXTURE_SILENCES)).edl
    e = ops.remove_fillers(e, ops.RemoveFillersArgs()).edl
    e = ops.set_layout(
        e, ops.SetLayoutArgs(start=2.0, end=3.5, layout="split", focus_x=0.3, focus2_x=0.7)
    ).edl
    e = ops.set_layout(e, ops.SetLayoutArgs(start=5.0, end=6.0, layout="fit")).edl
    e = ops.set_camera_keyframes(
        e, ops.SetCameraKeysArgs(keys=[ops.CameraKeyIn(t=8.2, focus_x=0.6, zoom=1.08)])
    ).edl
    e = ops.emphasize(e, ops.EmphasizeArgs(words=["money"])).edl
    return ops.add_overlay(e, ops.AddOverlayArgs(type="progress_bar")).edl


def test_proxy_render_matches_edl(edl: Edl, settings: Settings, tmp_path: Path) -> None:
    e = _edited(edl)
    res = render_edl(
        e, tmp_path / "proxy.mp4", proxy_profile(settings.media), X264Encoder(), settings, tmp_path / "work"
    )
    assert (res.width, res.height) == (360, 640)
    assert res.duration == pytest.approx(e.duration, abs=0.07)
    ass = res.ass_path.read_text(encoding="utf-8")
    assert "PlayResX: 360" in ass and "Dialogue:" in ass
    assert (tmp_path / "work" / "edl.json").exists()
    thumb = thumbnail(res.path, tmp_path / "thumb.jpg", settings)
    assert thumb.stat().st_size > 1000


def test_final_render_dimensions_and_loudness(edl: Edl, settings: Settings, tmp_path: Path) -> None:
    e = _edited(edl)
    res = render_edl(
        e, tmp_path / "final.mp4", final_profile(settings.media), X264Encoder(), settings, tmp_path / "work"
    )
    assert (res.width, res.height) == (1080, 1920)
    assert res.duration == pytest.approx(e.duration, abs=0.07)
    assert res.loudnorm_measured is not None  # two-pass loudness for finals
    loud = measure_loudness(res.path, settings)
    assert loud.integrated == pytest.approx(-14.0, abs=1.0)
    assert loud.true_peak <= -1.0
    info = probe(res.path, settings)
    assert info.video_codec == "h264" and info.audio_codec == "aac" and info.fps == pytest.approx(30.0)
    m = measure(res.path, settings)
    report = qa_report(e, m, min_s=5, max_s=60)
    by_name = {c["name"]: c for c in report["checks"]}
    for name in ("speech_start", "black_frames", "frozen_frames", "audio_clipping", "captions_safe_zone"):
        assert by_name[name]["ok"], by_name[name]


def test_render_is_deterministic(edl: Edl, settings: Settings, tmp_path: Path) -> None:
    e = _edited(edl)
    a = build_render_plan(e, final_profile(settings.media), X264Encoder(), tmp_path / "x.mp4")
    b = build_render_plan(
        Edl.model_validate(e.model_dump()), final_profile(settings.media), X264Encoder(), tmp_path / "x.mp4"
    )
    assert a.args == b.args and a.ass_text == b.ass_text


def test_qa_measurements_catch_a_bad_file(settings: Settings) -> None:
    m = measure(QA_BAD, settings)
    assert sum(e - s for s, e in m.black) == pytest.approx(1.5, abs=0.2)
    assert m.frozen, "the solid-color tail is frozen"
    assert m.peak_db > -0.5  # clipped square wave


def test_discord_preview_fits_target(edl: Edl, settings: Settings, tmp_path: Path) -> None:
    res = render_edl(
        edl, tmp_path / "p.mp4", proxy_profile(settings.media), X264Encoder(), settings, tmp_path / "w"
    )
    out = encode_to_size(res.path, tmp_path / "discord.mp4", 0.5, settings, tmp_path / "w2", height=640)
    assert out.stat().st_size < 0.5 * 1_000_000 * 1.1


def test_nvenc_args_are_the_verified_ones(settings: Settings) -> None:
    # LOCAL-VERIFY executes these on the RTX 5080; here we only pin the arguments.
    args = NvencEncoder("p5", "14M").video_args(final_profile(settings.media))
    assert args[:4] == ["-c:v", "h264_nvenc", "-preset", "p5"]
    assert "14M" in args
