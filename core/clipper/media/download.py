"""Source downloaders: yt-dlp (real, network; LOCAL-VERIFY) and a fake that copies fixtures."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from clipper.rules.urls import canonical_source
from clipper.settings import Settings
from clipper.system import PROCESS_REGISTRAR, kill_tree, popen_flags


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
class Progress:
    downloaded: int
    total: int | None
    speed: float | None  # bytes per second

    @property
    def fraction(self) -> float | None:
        return min(self.downloaded / self.total, 1.0) if self.total else None

    def detail(self) -> str:
        """ "1.2 of 3.4 GB · 8 MB/s · 4 min left"."""
        parts = [
            f"{human_bytes(self.downloaded)} of {human_bytes(self.total)}"
            if self.total
            else human_bytes(self.downloaded)
        ]
        if self.speed:
            parts.append(f"{human_bytes(self.speed)}/s")
            if self.total and self.total > self.downloaded:
                mins = (self.total - self.downloaded) / self.speed / 60
                parts.append("under a minute left" if mins < 1 else f"{mins:.0f} min left")
        return " · ".join(parts)


def human_bytes(n: float | None) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


PROGRESS_TEMPLATE = (
    "download:[clipper] %(progress.downloaded_bytes)s %(progress.total_bytes)s "
    "%(progress.total_bytes_estimate)s %(progress.speed)s"
)


def parse_progress(line: str) -> Progress | None:
    """One ``[clipper] <downloaded> <total> <total estimate> <speed>`` line of yt-dlp's progress
    template (any of the numbers can be ``NA``). Anything else is not progress."""
    line = line.strip()
    if not line.startswith("[clipper]"):
        return None
    fields = line.removeprefix("[clipper]").split()
    if len(fields) != 4:
        return None

    def num(text: str) -> float | None:
        try:
            return float(text)
        except ValueError:
            return None

    downloaded, total, estimate, speed = (num(f) for f in fields)
    if downloaded is None:
        return None
    size = total or estimate
    return Progress(int(downloaded), int(size) if size else None, speed)


@dataclass
class DownloadHooks:
    """How a running download reports to the job that owns it, and how the job can stop it."""

    progress: Callable[[float | None, str], None] = lambda fraction, detail: None
    cancelled: Callable[[], bool] = lambda: False


def stream_process(
    cmd: list[str],
    *,
    on_line: Callable[[str], None],
    timeout: float,
) -> tuple[int, list[str], str]:
    """Run a command and hand every line it prints to ``on_line`` as it arrives (yt-dlp reports progress
    on the way). The process is told to the running job, so cancelling the job kills it and everything it
    started. Returns (exit code, stdout lines, stderr text)."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **popen_flags(),
    )
    register = PROCESS_REGISTRAR.get()
    if register is not None:
        register(proc)
    stderr_lines: list[str] = []

    def drain_stderr() -> None:
        assert proc.stderr is not None
        for ln in proc.stderr:
            stderr_lines.append(ln)
            on_line(ln)

    reader = threading.Thread(target=drain_stderr, daemon=True)
    reader.start()
    limit = threading.Timer(timeout, lambda: kill_tree(proc.pid))
    limit.start()
    out: list[str] = []
    try:
        assert proc.stdout is not None
        for ln in proc.stdout:
            out.append(ln.rstrip("\n"))
            on_line(ln)
        proc.wait()
    finally:
        limit.cancel()
    reader.join(timeout=5)
    return proc.returncode, out, "".join(stderr_lines)


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
    def download(self, url: str, dest_dir: Path, hooks: DownloadHooks | None = None) -> DownloadResult: ...
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

    def download(self, url: str, dest_dir: Path, hooks: DownloadHooks | None = None) -> DownloadResult:
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

    def _ffmpeg_args(self) -> list[str]:
        ffmpeg = self.settings.paths.ffmpeg("ffmpeg")
        return ["--ffmpeg-location", str(Path(ffmpeg).parent)] if Path(ffmpeg).is_absolute() else []

    def _base(self) -> list[str]:
        return [self.settings.paths.yt_dlp, "--no-progress", "--no-playlist", *self._ffmpeg_args()]

    def download(
        self, url: str, dest_dir: Path, hooks: DownloadHooks | None = None
    ) -> DownloadResult:  # LOCAL-VERIFY
        dest_dir.mkdir(parents=True, exist_ok=True)
        hooks = hooks or DownloadHooks()
        cmd = [
            self.settings.paths.yt_dlp, "--no-playlist", *self._ffmpeg_args(),
            "--progress", "--newline", "--progress-template", PROGRESS_TEMPLATE,
            "-f", "bv*[height<=1080]+ba/b[height<=1080]",
            "--merge-output-format", "mp4",
            "--write-info-json", "--write-subs", "--write-auto-subs", "--sub-langs", "en.*", "--convert-subs", "srt",
            "-o", str(dest_dir / "%(id)s.%(ext)s"),
            "--print", "after_move:filepath",
            url,
        ]  # fmt: skip

        def on_line(line: str) -> None:
            progress = parse_progress(line)
            if progress is not None:
                hooks.progress(progress.fraction, progress.detail())

        code, out, err = stream_process(cmd, on_line=on_line, timeout=6 * 3600)
        if hooks.cancelled():
            raise DownloadError("cancelled", err)
        if code != 0:
            reason, tail = clean_ytdlp_error(err)
            raise DownloadError(reason, tail)
        printed = [ln.strip() for ln in out if ln.strip() and not ln.startswith("[clipper]")]
        path = Path(printed[-1])
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
