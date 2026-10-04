"""Text recognition on frames, to find burned-in captions/watermarks in a source (PLAN §16.1)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol


class OcrEngine(Protocol):
    def read(self, image: Path) -> str: ...


class FakeOcr:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def read(self, image: Path) -> str:
        return self.text


BRIGHT_TEXT_FILTER = "format=gray,scale=iw*2:ih*2:flags=lanczos,lut=y='if(gt(val\\,170)\\,0\\,255)'"


class TesseractOcr:
    """Tesseract CLI (``winget install UB-Mannheim.TesseractOCR``). LOCAL-VERIFY.

    Burned-in captions and watermarks are usually white text over busy video, which Tesseract misses on
    the raw frame. With ``ffmpeg`` given, a second pass reads a 2x grayscale copy where only bright pixels
    survive (as black on white); the words of both passes are merged in order.
    """

    def __init__(self, exe: str | None = None, ffmpeg: str | None = None) -> None:
        self.exe = exe or shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        self.ffmpeg = ffmpeg

    def read(self, image: Path) -> str:  # LOCAL-VERIFY
        words = self._tesseract(image).split()
        if self.ffmpeg:
            with tempfile.TemporaryDirectory(prefix="clipper-ocr-") as tmp:
                bright = Path(tmp) / "bright.png"
                proc = subprocess.run(
                    [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(image),
                     "-vf", BRIGHT_TEXT_FILTER, str(bright)],
                    capture_output=True, check=False, timeout=60,
                )  # fmt: skip
                if proc.returncode == 0:
                    words = self._tesseract(bright).split() + words
        return " ".join(dict.fromkeys(words))

    def _tesseract(self, image: Path) -> str:
        proc = subprocess.run(
            [self.exe, str(image), "stdout", "--psm", "11"],
            capture_output=True,
            encoding="utf-8",  # Tesseract writes UTF-8; the Windows default code page can't decode it
            errors="replace",
            check=False,
            timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip()[-300:])
        return " ".join(proc.stdout.split())
