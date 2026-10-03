"""Transcribers: WhisperX on CUDA (LOCAL-VERIFY, subprocess into the GPU env) and a fake for tests/CI."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from clipper.settings import Settings

GPU_SCRIPT = Path(__file__).parent / "gpu_scripts" / "whisperx_transcribe.py"


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    speaker: str | None = None


@dataclass(frozen=True)
class Transcript:
    language: str
    words: list[Word] = field(default_factory=lambda: [])

    def to_json(self) -> dict[str, object]:
        return {
            "language": self.language,
            "words": [
                {"text": w.text, "start": w.start, "end": w.end, "speaker": w.speaker} for w in self.words
            ],
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> Transcript:
        raw = data.get("words", [])
        assert isinstance(raw, list)
        words = [
            Word(str(w["text"]).strip(), float(w["start"]), float(w["end"]), w.get("speaker"))  # type: ignore[index,union-attr,arg-type]
            for w in raw  # type: ignore[union-attr]
        ]
        return cls(str(data.get("language") or "en"), words)


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio: Path, media: Path | None = None) -> Transcript: ...


class FakeTranscriber:
    """Returns ``<media>.words.json`` when it exists next to the media file, otherwise canned words."""

    name = "fake"

    def __init__(self, default_words: list[Word] | None = None) -> None:
        self.default_words = default_words or [Word("hello", 0.2, 0.5), Word("world", 0.6, 1.0)]

    def transcribe(self, audio: Path, media: Path | None = None) -> Transcript:
        for candidate in (media, audio):
            if candidate is None:
                continue
            sidecar = candidate.with_suffix(".words.json")
            if sidecar.exists():
                return Transcript.from_json(json.loads(sidecar.read_text(encoding="utf-8")))
        return Transcript("en", list(self.default_words))


class WhisperXTranscriber:
    """WhisperX large-v3 on the RTX 5080, run in the isolated CUDA env. LOCAL-VERIFY."""

    name = "whisperx"

    def __init__(self, settings: Settings, hf_token: str | None = None, diarize: bool = True) -> None:
        self.settings = settings
        self.hf_token = hf_token
        self.diarize = diarize

    def transcribe(self, audio: Path, media: Path | None = None) -> Transcript:  # LOCAL-VERIFY
        out = audio.with_suffix(".whisperx.json")
        cmd = [
            str(self.settings.paths.gpu_python),
            str(GPU_SCRIPT),
            str(audio),
            str(out),
            "--model",
            self.settings.media.whisper_model,
            "--models-dir",
            str(self.settings.paths.models_dir),
        ]
        if self.settings.media.whisper_language:
            cmd += ["--language", self.settings.media.whisper_language]
        env = dict(os.environ)
        if self.diarize and self.hf_token:
            cmd.append("--diarize")
            env["HF_TOKEN"] = self.hf_token
        if self.settings.paths.ffmpeg_bin:
            env["PATH"] = str(self.settings.paths.ffmpeg_bin) + os.pathsep + env.get("PATH", "")
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=3 * 3600, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"WhisperX failed ({proc.returncode}): {proc.stderr.strip()[-800:]}")
        return Transcript.from_json(json.loads(out.read_text(encoding="utf-8")))
