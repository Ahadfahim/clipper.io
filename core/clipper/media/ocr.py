"""Text recognition on frames, to find burned-in captions/watermarks in a source (PLAN §16.1)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Protocol


class OcrEngine(Protocol):
    def read(self, image: Path) -> str: ...


class FakeOcr:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def read(self, image: Path) -> str:
        return self.text


class TesseractOcr:
    """Tesseract CLI (``winget install UB-Mannheim.TesseractOCR``). LOCAL-VERIFY."""

    def __init__(self, exe: str | None = None) -> None:
        self.exe = exe or shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    def read(self, image: Path) -> str:  # LOCAL-VERIFY
        proc = subprocess.run(
            [self.exe, str(image), "stdout", "--psm", "11"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip()[-300:])
        return " ".join(proc.stdout.split())
