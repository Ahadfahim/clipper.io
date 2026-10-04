"""Source downloaders: yt-dlp (real, network; LOCAL-VERIFY) and a fake that copies fixtures."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from clipper.rules.urls import canonical_source
from clipper.settings import Settings


class DownloadError(RuntimeError):
    """A download failed. ``reason`` is one plain sentence; ``raw_tail`` is the tool's last output."""

    def __init__(self, reason: str, raw_tail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.raw_tail = raw_tail


_KNOWN_ERRORS: tuple[tuple[str, str], ...] = (
    ("unsupported url", "This site isn't supported by the downloader"),
    ("http error 403", "The host refused the download (403)"),
    ("http error 404", "The link doesn't exist any more (404)"),
    ("sign in to confirm", "YouTube asked for a sign-in check"),
    ("private video", "The video is private"),
    ("video unavailable", "The video isn't available"),
    ("this video is not available", "The video isn't available"),
)


def clean_ytdlp_error(stderr: str) -> tuple[str, str]:
    """Reduce yt-dlp's stderr to one sentence. Its warnings come first (an out-of-date notice, for
    one) and used to be all anyone saw; the reason is the last ``ERROR:`` line."""
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    tail = "\n".join(lines)[-4000:]
    errors = [ln for ln in lines if ln.startswith("ERROR:")]
    pool = errors or [ln for ln in lines if not ln.startswith("WARNING:")]
    if not pool:
        return "yt-dlp failed without saying why", tail
    reason = pool[-1].removeprefix("ERROR:").strip()
    low = reason.lower()
    for needle, friendly in _KNOWN_ERRORS:
        if needle in low:
            return friendly, tail
    return reason[:300], tail


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    title: str
    duration: float
    heatmap: list[dict[str, float]] = field(default_factory=lambda: [])  # [{start_time, end_time, value}]
    chapters: list[dict[str, Any]] = field(default_factory=lambda: [])
    subtitles: Path | None = None
    uploader: str | None = None


@dataclass(frozen=True)
class Comment:
    text: str
    likes: int
    timestamps: list[float]  # "3:45" style mentions, in seconds


class Downloader(Protocol):
    def download(self, url: str, dest_dir: Path) -> DownloadResult: ...
    def comments(self, url: str, limit: int = 100) -> list[Comment]: ...


_TS = re.compile(r"\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b")


def comment_timestamps(text: str) -> list[float]:
    out: list[float] = []
    for h, m, s in _TS.findall(text):
        out.append(int(h or 0) * 3600 + int(m) * 60 + int(s))
    return out


def file_hash(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


class FakeDownloader:
    """Maps every URL to a fixture video (copied, so later steps can't touch the original)."""

    def __init__(self, fixture: Path, duration: float = 10.0, comments: list[Comment] | None = None) -> None:
        self.fixture = fixture
        self.duration = duration
        self._comments = comments or [
            Comment("the part at 0:04 is insane", 120, [4.0]),
            Comment("lol", 3, []),
        ]
        self.calls: list[str] = []

    def download(self, url: str, dest_dir: Path) -> DownloadResult:
        self.calls.append(url)
        dest_dir.mkdir(parents=True, exist_ok=True)
        key = re.sub(r"[^\w.-]+", "_", canonical_source(url))[:80]
        dest = dest_dir / f"{key}{self.fixture.suffix}"
        shutil.copyfile(self.fixture, dest)
        sidecar = self.fixture.with_suffix(".words.json")
        if sidecar.exists():
            shutil.copyfile(sidecar, dest.with_suffix(".words.json"))
        heat = [
            {"start_time": float(i), "end_time": float(i + 1), "value": 0.2 + (0.7 if i in (4, 5) else 0.0)}
            for i in range(int(self.duration))
        ]
        return DownloadResult(dest, f"Fixture for {url}", self.duration, heat, [], None, "Fixture Creator")

    def comments(self, url: str, limit: int = 100) -> list[Comment]:
        return self._comments[:limit]


class YtDlpDownloader:
    """yt-dlp best <=1080p + subtitles + the "most replayed" heatmap. LOCAL-VERIFY (network)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _base(self) -> list[str]:
        cmd = [self.settings.paths.yt_dlp, "--no-progress", "--no-playlist"]
        ffmpeg = self.settings.paths.ffmpeg("ffmpeg")
        if Path(ffmpeg).is_absolute():
            cmd += ["--ffmpeg-location", str(Path(ffmpeg).parent)]
        return cmd

    def download(self, url: str, dest_dir: Path) -> DownloadResult:  # LOCAL-VERIFY
        dest_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            *self._base(),
            "-f", "bv*[height<=1080]+ba/b[height<=1080]",
            "--merge-output-format", "mp4",
            "--write-info-json", "--write-subs", "--write-auto-subs", "--sub-langs", "en.*", "--convert-subs", "srt",
            "-o", str(dest_dir / "%(id)s.%(ext)s"),
            "--print", "after_move:filepath",
            url,
        ]  # fmt: skip
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6 * 3600, check=False)
        if proc.returncode != 0:
            reason, tail = clean_ytdlp_error(proc.stderr)
            raise DownloadError(reason, tail)
        path = Path(proc.stdout.strip().splitlines()[-1])
        info_path = path.with_suffix(".info.json")
        info: dict[str, Any] = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
        subs = next(iter(sorted(dest_dir.glob(f"{path.stem}*.srt"))), None)
        return DownloadResult(
            path=path,
            title=str(info.get("title") or path.stem),
            duration=float(info.get("duration") or 0.0),
            heatmap=list(info.get("heatmap") or []),
            chapters=list(info.get("chapters") or []),
            subtitles=subs,
            uploader=info.get("uploader"),
        )

    def comments(self, url: str, limit: int = 100) -> list[Comment]:  # LOCAL-VERIFY
        cmd = [*self._base(), "--skip-download", "--write-comments", "--dump-single-json",
               "--extractor-args", f"youtube:max_comments={limit},all,0;comment_sort=top", url]  # fmt: skip
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        if proc.returncode != 0:
            reason, tail = clean_ytdlp_error(proc.stderr)
            raise DownloadError(f"couldn't read comments: {reason}", tail)
        data: dict[str, Any] = json.loads(proc.stdout or "{}")
        raw: list[dict[str, Any]] = list(data.get("comments") or [])
        out = [
            Comment(
                str(c.get("text", "")),
                int(c.get("like_count") or 0),
                comment_timestamps(str(c.get("text", ""))),
            )
            for c in raw
        ]
        return sorted(out, key=lambda c: -c.likes)[:limit]
