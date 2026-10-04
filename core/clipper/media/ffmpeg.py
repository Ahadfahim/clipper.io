"""ffmpeg/ffprobe helpers: run, probe, and measurement filters parsed into numbers."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clipper.settings import Settings, get_settings


class FfmpegError(RuntimeError):
    def __init__(self, cmd: list[str], code: int, stderr: str) -> None:
        tail = "\n".join(stderr.strip().splitlines()[-12:])
        super().__init__(f"ffmpeg exited {code}: {tail}")
        self.cmd = cmd
        self.code = code
        self.stderr = stderr


def ffmpeg_bin(settings: Settings | None = None) -> str:
    return (settings or get_settings()).paths.ffmpeg("ffmpeg")


def ffprobe_bin(settings: Settings | None = None) -> str:
    return (settings or get_settings()).paths.ffmpeg("ffprobe")


def run_ffmpeg(
    args: list[str], *, settings: Settings | None = None, cwd: Path | None = None, timeout: float = 1800
) -> str:
    """Run ffmpeg with ``args`` (without the binary). Returns stderr (where ffmpeg logs)."""
    cmd = [ffmpeg_bin(settings), "-hide_banner", "-nostdin", *args]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise FfmpegError(cmd, proc.returncode, proc.stderr)
    return proc.stderr


@dataclass(frozen=True)
class ProbeInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str | None
    audio_codec: str | None
    sample_rate: int | None


def _fps(rate: str | None) -> float:
    if not rate or rate == "0/0":
        return 0.0
    num, _, den = rate.partition("/")
    return float(num) / float(den or 1)


def probe(path: Path, settings: Settings | None = None) -> ProbeInfo:
    cmd = [
        ffprobe_bin(settings),
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,sample_rate",
        "-of",
        "json",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    if proc.returncode != 0:
        raise FfmpegError(cmd, proc.returncode, proc.stderr)
    data: dict[str, Any] = json.loads(proc.stdout)
    streams: list[dict[str, Any]] = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or 0.0)
    return ProbeInfo(
        duration=duration,
        width=int(video["width"]) if video else 0,
        height=int(video["height"]) if video else 0,
        fps=_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")) if video else 0.0,
        has_audio=audio is not None,
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
    )


# ---------------------------------------------------------------- measurements


@dataclass(frozen=True)
class Loudness:
    integrated: float  # LUFS
    true_peak: float  # dBTP
    lra: float
    threshold: float


def parse_loudnorm_json(stderr: str) -> dict[str, str]:
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not m:
        raise ValueError("no loudnorm JSON in ffmpeg output")
    return json.loads(m.group(0))


def measure_loudness(
    path: Path, settings: Settings | None = None, target: float = -14.0, tp: float = -1.5
) -> Loudness:
    err = run_ffmpeg(
        [
            "-i",
            str(path),
            "-vn",
            "-af",
            f"loudnorm=I={target}:TP={tp}:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        settings=settings,
    )
    j = parse_loudnorm_json(err)
    return Loudness(
        float(j["input_i"]), float(j["input_tp"]), float(j["input_lra"]), float(j["input_thresh"])
    )


def parse_intervals(stderr: str, kind: str) -> list[tuple[float, float]]:
    """Parse ``blackdetect``/``silencedetect``/``freezedetect`` logs into (start, end) intervals."""
    out: list[tuple[float, float]] = []
    if kind == "black":
        for m in re.finditer(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)", stderr):
            out.append((float(m.group(1)), float(m.group(2))))
        return out
    key = {"silence": "silence", "freeze": "lavfi.freezedetect.freeze"}[kind]
    starts = [float(x) for x in re.findall(rf"{re.escape(key)}_start:\s*(-?[\d.]+)", stderr)]
    ends = [float(x) for x in re.findall(rf"{re.escape(key)}_end:\s*(-?[\d.]+)", stderr)]
    for i, s in enumerate(starts):
        out.append((max(s, 0.0), ends[i] if i < len(ends) else float("inf")))
    return out


def detect_silences(
    path: Path, settings: Settings | None = None, noise_db: float = -35.0, min_s: float = 0.3
) -> list[tuple[float, float]]:
    err = run_ffmpeg(
        ["-i", str(path), "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-"],
        settings=settings,
    )
    info = None
    spans = parse_intervals(err, "silence")
    if spans and spans[-1][1] == float("inf"):
        info = probe(path, settings)
        spans[-1] = (spans[-1][0], info.duration)
    return spans


def detect_black(
    path: Path, settings: Settings | None = None, min_s: float = 0.25
) -> list[tuple[float, float]]:
    err = run_ffmpeg(
        ["-i", str(path), "-an", "-vf", f"blackdetect=d={min_s}:pix_th=0.10", "-f", "null", "-"],
        settings=settings,
    )
    return parse_intervals(err, "black")


def detect_freeze(
    path: Path, settings: Settings | None = None, min_s: float = 1.0
) -> list[tuple[float, float]]:
    err = run_ffmpeg(
        ["-i", str(path), "-an", "-vf", f"freezedetect=n=0.001:d={min_s}", "-f", "null", "-"],
        settings=settings,
    )
    return parse_intervals(err, "freeze")


def audio_peak_db(path: Path, settings: Settings | None = None) -> float:
    err = run_ffmpeg(
        [
            "-i",
            str(path),
            "-vn",
            "-af",
            "astats=measure_overall=Peak_level:measure_perchannel=0",
            "-f",
            "null",
            "-",
        ],
        settings=settings,
    )
    vals = re.findall(r"Peak level dB:\s*(-?[\d.]+|-inf)", err)
    if not vals:
        return float("-inf")
    last = vals[-1]
    return float("-inf") if last == "-inf" else float(last)


def scene_cuts(path: Path, settings: Settings | None = None, threshold: float = 0.3) -> list[float]:
    err = run_ffmpeg(
        ["-i", str(path), "-an", "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        settings=settings,
    )
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", err)]


def energy_curve(
    path: Path, settings: Settings | None = None, window: float = 0.5
) -> list[tuple[float, float]]:
    """Momentary loudness (LUFS) per ~100 ms from ebur128, averaged into ``window``-second bins."""
    err = run_ffmpeg(
        ["-i", str(path), "-vn", "-af", "ebur128=peak=none", "-f", "null", "-"], settings=settings
    )
    points = [(float(t), float(m)) for t, m in re.findall(r"t:\s*([\d.]+)\s+TARGET:.*?M:\s*(-?[\d.]+)", err)]
    bins: dict[int, list[float]] = {}
    for t, m in points:
        bins.setdefault(int(t / window), []).append(m)
    return [(k * window, sum(v) / len(v)) for k, v in sorted(bins.items())]
