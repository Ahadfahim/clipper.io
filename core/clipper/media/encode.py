"""Pluggable video encoders. ``X264Encoder`` runs anywhere (tested in CI); ``NvencEncoder`` targets the
RTX 5080 (verified settings in docs/LOCAL_CHECKS.md)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from clipper.settings import MediaSettings

ProfileName = Literal["proxy", "review", "final"]


@dataclass(frozen=True)
class RenderProfile:
    name: ProfileName
    width: int
    height: int
    fps: int
    audio_bitrate: str = "160k"
    two_pass_loudnorm: bool = False


def proxy_profile(media: MediaSettings) -> RenderProfile:
    height = media.proxy_height
    width = round(height * media.final_width / media.final_height / 2) * 2
    return RenderProfile("proxy", width, height, media.fps, audio_bitrate="96k")


def review_profile(media: MediaSettings) -> RenderProfile:
    """Review preview for Discord and the Review page (720x1280, sized to fit Discord's limit)."""
    width = round(1280 * media.final_width / media.final_height / 2) * 2
    return RenderProfile("review", width, 1280, media.fps, audio_bitrate="128k")


def final_profile(media: MediaSettings) -> RenderProfile:
    return RenderProfile("final", media.final_width, media.final_height, media.fps, two_pass_loudnorm=True)


class Encoder(Protocol):
    name: str

    def video_args(self, profile: RenderProfile) -> list[str]: ...


class X264Encoder:
    """CPU encoder (libx264)."""

    name = "x264"

    def video_args(self, profile: RenderProfile) -> list[str]:
        if profile.name == "review":
            return [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-maxrate",
                "6M",
                "-bufsize",
                "12M",
            ]
        if profile.name == "proxy":
            return [
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "30",
                "-pix_fmt",
                "yuv420p",
                "-g",
                str(profile.fps),
            ]
        return [
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-maxrate", "16M", "-bufsize", "32M",
            "-pix_fmt", "yuv420p", "-profile:v", "high",
        ]  # fmt: skip


class NvencEncoder:
    """NVIDIA NVENC (h264_nvenc). LOCAL-VERIFY: needs the RTX 5080 + an NVENC ffmpeg build."""

    name = "nvenc"

    def __init__(self, preset: str = "p5", bitrate: str = "14M") -> None:
        self.preset = preset
        self.bitrate = bitrate

    def video_args(self, profile: RenderProfile) -> list[str]:  # LOCAL-VERIFY
        if profile.name == "review":
            return [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p3",
                "-rc",
                "vbr",
                "-cq",
                "23",
                "-maxrate",
                "6M",
                "-bufsize",
                "12M",
                "-pix_fmt",
                "yuv420p",
            ]
        if profile.name == "proxy":
            return ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "32", "-pix_fmt", "yuv420p"]
        return [
            "-c:v", "h264_nvenc", "-preset", self.preset, "-rc", "vbr", "-cq", "19", "-b:v", self.bitrate,
            "-maxrate", "16M", "-bufsize", "28M", "-pix_fmt", "yuv420p", "-profile:v", "high",
        ]  # fmt: skip


def make_encoder(media: MediaSettings) -> Encoder:
    if media.encoder == "nvenc":
        return NvencEncoder(media.nvenc_preset, media.final_bitrate)
    return X264Encoder()
