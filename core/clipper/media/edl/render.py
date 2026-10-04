"""EDL -> ffmpeg filtergraph renderer (PLAN §18.1, §18.2).

One input, seeked once to the clip's source span (fast and frame-accurate when decoding), then per
segment: trim -> layout (eased-keyframe crop / stacked split-screen / blurred-background fit, punch-in
zoom) -> concat. After concat: ASS captions + hook/brand text, progress bar, then audio: denoise,
gain, loudness normalization (one pass for proxies, two passes for finals), clean fades at every cut.

Deterministic: the same EDL and profile always build the same command.
"""

from __future__ import annotations

import itertools
import json
import os
from dataclasses import dataclass
from pathlib import Path

from clipper.media.edl.captions import build_ass
from clipper.media.edl.schema import CameraKey, Edl, Segment
from clipper.media.edl.timeline import camera_keys_for_segment
from clipper.media.encode import Encoder, RenderProfile
from clipper.media.ffmpeg import parse_loudnorm_json, probe, run_ffmpeg
from clipper.settings import Settings

ASS_NAME = "captions.ass"


def _even(v: float) -> int:
    return max(2, round(v / 2) * 2)


def _num(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


def eased_expr(points: list[tuple[float, float]]) -> str:
    """Piecewise smoothstep interpolation through (t, value) points, as an ffmpeg expression in ``t``."""
    pts = sorted(points)
    if not pts:
        return "0"
    if len(pts) == 1 or all(abs(v - pts[0][1]) < 1e-9 for _, v in pts):
        return _num(pts[0][1])
    expr = _num(pts[-1][1])
    for (t0, v0), (t1, v1) in reversed(list(itertools.pairwise(pts))):
        if t1 - t0 < 1e-6:
            continue
        p = f"((t-{_num(t0)})/{_num(t1 - t0)})"
        seg = f"{_num(v0)}+({_num(v1 - v0)})*{p}*{p}*(3-2*{p})"
        expr = f"if(lt(t,{_num(t1)}),{seg},{expr})"
    return f"if(lt(t,{_num(pts[0][0])}),{_num(pts[0][1])},{expr})"


def crop_window(src_w: int, src_h: int, aspect: float) -> tuple[int, int]:
    """Largest window of ``aspect`` (w/h) inside the source."""
    if src_w / src_h > aspect:
        return _even(src_h * aspect), _even(src_h)
    return _even(src_w), _even(src_w / aspect)


def _local_keys(keys: list[CameraKey], seg: Segment) -> list[CameraKey]:
    return [k.model_copy(update={"t": max(0.0, k.t - seg.start)}) for k in keys]


def _crop_chain(
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    keys: list[CameraKey],
    attr: str = "focus_x",
    ease_s: float = 0.4,
) -> str:
    cw, ch = crop_window(src_w, src_h, out_w / out_h)
    # Each key is a target; the camera eases toward it over ``ease_s`` seconds (dead zone handled when keys are made).
    xs: list[tuple[float, float]] = []
    ys: list[tuple[float, float]] = []
    for i, k in enumerate(keys):
        fx = getattr(k, attr)
        fx = k.focus_x if fx is None else fx
        x = min(max(fx * src_w - cw / 2, 0), src_w - cw)
        y = min(max(k.focus_y * src_h - ch / 2, 0), src_h - ch)
        if i and xs:
            xs.append((k.t, xs[-1][1]))
            ys.append((k.t, ys[-1][1]))
            xs.append((k.t + ease_s, x))
            ys.append((k.t + ease_s, y))
        else:
            xs.append((k.t, x))
            ys.append((k.t, y))
    chain = f"crop=w={cw}:h={ch}:x='{eased_expr(xs)}':y='{eased_expr(ys)}',scale={out_w}:{out_h}:flags=lanczos,setsar=1"
    zooms = [(k.t, k.zoom) for k in keys]
    if any(abs(z - 1.0) > 1e-6 for _, z in zooms):
        z = eased_expr(zooms if len(zooms) > 1 else [(0.0, zooms[0][1])])
        chain += (
            f",scale=w='trunc({out_w}*({z})/2)*2':h='trunc({out_h}*({z})/2)*2':eval=frame:flags=bicubic"
            f",crop={out_w}:{out_h}:(in_w-{out_w})/2:(in_h-{out_h})/2,setsar=1"
        )
    return chain


def segment_video_chain(edl: Edl, seg: Segment, label_in: str, label_out: str, out_w: int, out_h: int) -> str:
    keys = _local_keys(camera_keys_for_segment(edl, seg), seg)
    layout = keys[0].layout
    sw, sh = edl.source.width, edl.source.height
    if layout == "split":
        half = _even(out_h / 2)
        top_keys = keys
        bot_keys = [
            k.model_copy(update={"focus_x": k.focus2_x if k.focus2_x is not None else 1 - k.focus_x})
            for k in keys
        ]
        return (
            f"[{label_in}]split=2[{label_out}t][{label_out}b];"
            f"[{label_out}t]{_crop_chain(sw, sh, out_w, half, top_keys)}[{label_out}tc];"
            f"[{label_out}b]{_crop_chain(sw, sh, out_w, out_h - half, bot_keys)}[{label_out}bc];"
            f"[{label_out}tc][{label_out}bc]vstack=inputs=2[{label_out}]"
        )
    if layout == "fit":
        return (
            f"[{label_in}]split=2[{label_out}bg][{label_out}fg];"
            f"[{label_out}bg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
            f"boxblur=luma_radius=24:luma_power=2,eq=brightness=-0.06[{label_out}bgb];"
            f"[{label_out}fg]scale={out_w}:-2:flags=lanczos[{label_out}fgs];"
            f"[{label_out}bgb][{label_out}fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[{label_out}]"
        )
    return f"[{label_in}]{_crop_chain(sw, sh, out_w, out_h, keys)}[{label_out}]"


@dataclass(frozen=True)
class RenderPlan:
    args: list[str]  # ffmpeg args without the binary
    ass_text: str
    base: float
    span: float
    duration: float


def _has_text_layer(edl: Edl) -> bool:
    return (edl.captions.enabled and bool(edl.captions.words)) or any(
        o.type in ("hook_text", "brand") for o in edl.overlays
    )


def build_render_plan(
    edl: Edl,
    profile: RenderProfile,
    encoder: Encoder,
    out_path: Path,
    *,
    loudnorm_measured: dict[str, str] | None = None,
    audio_only_measure: bool = False,
) -> RenderPlan:
    W, H, fps = profile.width, profile.height, profile.fps
    scaled = edl.model_copy(
        update={"output": edl.output.model_copy(update={"width": W, "height": H, "fps": fps})}
    )
    segs = edl.segments
    base = max(0.0, min(s.start for s in segs))
    span = max(s.end for s in segs) - base
    n = len(segs)
    duration = edl.duration
    parts: list[str] = []
    has_audio = edl.source.has_audio
    if not audio_only_measure:
        parts.append(
            f"[0:v]fps={fps},format=yuv420p,split={n}" + "".join(f"[sv{i}]" for i in range(n))
            if n > 1
            else f"[0:v]fps={fps},format=yuv420p[sv0]"
        )
    if has_audio:
        parts.append(
            f"[0:a]aresample=48000,aformat=channel_layouts=stereo,asplit={n}"
            + "".join(f"[sa{i}]" for i in range(n))
            if n > 1
            else "[0:a]aresample=48000,aformat=channel_layouts=stereo[sa0]"
        )
    fade = edl.audio.fade_ms / 1000
    for i, seg in enumerate(segs):
        a, b = seg.start - base, seg.end - base
        if not audio_only_measure:
            parts.append(f"[sv{i}]trim=start={_num(a)}:end={_num(b)},setpts=PTS-STARTPTS[tv{i}]")
            parts.append(segment_video_chain(scaled, seg, f"tv{i}", f"v{i}", W, H))
        if has_audio:
            d = seg.duration
            chain = f"[sa{i}]atrim=start={_num(a)}:end={_num(b)},asetpts=PTS-STARTPTS"
            if fade > 0 and d > 3 * fade:
                chain += f",afade=t=in:d={_num(fade)},afade=t=out:st={_num(d - fade)}:d={_num(fade)}"
            parts.append(chain + f"[a{i}]")
    if audio_only_measure:
        parts.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[ac]")
    elif has_audio:
        parts.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
    else:
        parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vc]")
        parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={_num(duration)}[ac]")

    ass_text = build_ass(scaled)
    vlabel = "vc"
    if not audio_only_measure:
        if _has_text_layer(edl):
            parts.append(f"[vc]ass={ASS_NAME}[vs]")
            vlabel = "vs"
        bars = [o for o in edl.overlays if o.type == "progress_bar"]
        if bars:
            bar_h = _even(H * 12 / 1920)
            parts.append(f"color=c=white@0.85:s={W}x{bar_h}:r={fps}:d={_num(duration)}[bar]")
            parts.append(f"[{vlabel}][bar]overlay=x='-w+w*t/{_num(duration)}':y=H-{bar_h}:shortest=1[vp]")
            vlabel = "vp"

    achain = "[ac]"
    filters: list[str] = []
    if edl.audio.denoise:
        filters.append("afftdn=nf=-25")
    if abs(edl.audio.gain_db) > 1e-6:
        filters.append(f"volume={_num(edl.audio.gain_db)}dB")
    target, tp = edl.audio.loudness, edl.audio.true_peak
    if audio_only_measure:
        filters.append(f"loudnorm=I={_num(target)}:TP={_num(tp)}:LRA=11:print_format=json")
    elif loudnorm_measured:
        m = loudnorm_measured
        filters.append(
            f"loudnorm=I={_num(target)}:TP={_num(tp)}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
            f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"
        )
    else:
        filters.append(f"loudnorm=I={_num(target)}:TP={_num(tp)}:LRA=11")
    filters.append("aresample=48000")
    parts.append(achain + ",".join(filters) + "[aout]")

    graph = ";".join(parts)
    args = ["-y", "-ss", _num(base), "-t", _num(span + 0.05), "-i", edl.source.path, "-filter_complex", graph]
    if audio_only_measure:
        args += ["-map", "[aout]", "-f", "null", "-"]
    else:
        args += ["-map", f"[{vlabel}]", "-map", "[aout]", "-r", str(fps), *encoder.video_args(profile)]
        args += ["-c:a", "aac", "-b:a", profile.audio_bitrate, "-ar", "48000", "-movflags", "+faststart"]
        args += ["-t", _num(duration), str(out_path)]
    return RenderPlan(args=args, ass_text=ass_text, base=base, span=span, duration=duration)


@dataclass(frozen=True)
class RenderResult:
    path: Path
    ass_path: Path
    duration: float
    width: int
    height: int
    plan_args: list[str]
    loudnorm_measured: dict[str, str] | None


def render_edl(
    edl: Edl,
    out_path: Path,
    profile: RenderProfile,
    encoder: Encoder,
    settings: Settings,
    work_dir: Path,
) -> RenderResult:
    """Render ``edl`` to ``out_path``. Runs ffmpeg with ``cwd=work_dir`` so the ASS path needs no escaping."""
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    measured: dict[str, str] | None = None
    if profile.two_pass_loudnorm and edl.source.has_audio:
        plan = build_render_plan(edl, profile, encoder, out_path, audio_only_measure=True)
        measured = parse_loudnorm_json(run_ffmpeg(plan.args, settings=settings, cwd=work_dir))
        if float(measured.get("input_i", "-70")) < -60:  # silence: nothing to normalize
            measured = None
    plan = build_render_plan(edl, profile, encoder, out_path, loudnorm_measured=measured)
    ass_path = work_dir / ASS_NAME
    ass_path.write_text(plan.ass_text, encoding="utf-8")
    (work_dir / "edl.json").write_text(json.dumps(edl.model_dump(mode="json"), indent=1), encoding="utf-8")
    run_ffmpeg(plan.args, settings=settings, cwd=work_dir)
    info = probe(out_path, settings)
    return RenderResult(out_path, ass_path, info.duration, info.width, info.height, plan.args, measured)


def thumbnail(video: Path, out: Path, settings: Settings, at: float | None = None) -> Path:
    info = probe(video, settings)
    t = at if at is not None else min(1.5, info.duration / 2)
    run_ffmpeg(
        ["-y", "-ss", _num(t), "-i", str(video), "-frames:v", "1", "-q:v", "3", str(out)], settings=settings
    )
    return out


def encode_to_size(
    src: Path, out: Path, target_mb: float, settings: Settings, work_dir: Path, height: int = 1280
) -> Path:
    """Two-pass x264 to fit Discord's upload limit (PLAN §12)."""
    info = probe(src, settings)
    audio_kbps = 96
    total_kbits = target_mb * 8 * 1000 * 0.97
    video_kbps = max(200, int(total_kbits / max(info.duration, 1) - audio_kbps))
    width = _even(height * 9 / 16)
    common = [
        "-vf",
        f"scale={width}:{height}",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-b:v",
        f"{video_kbps}k",
    ]
    log = str(work_dir / "x264pass")
    work_dir.mkdir(parents=True, exist_ok=True)
    null = os.devnull
    run_ffmpeg(
        ["-y", "-i", str(src), *common, "-pass", "1", "-passlogfile", log, "-an", "-f", "mp4", null],
        settings=settings,
        cwd=work_dir,
    )
    run_ffmpeg(
        [
            "-y",
            "-i",
            str(src),
            *common,
            "-pass",
            "2",
            "-passlogfile",
            log,
            "-c:a",
            "aac",
            "-b:a",
            f"{audio_kbps}k",
            "-movflags",
            "+faststart",
            str(out),
        ],
        settings=settings,
        cwd=work_dir,
    )
    return out
