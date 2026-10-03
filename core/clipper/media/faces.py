# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""Face tracks per shot. ``FakeFaceDetector`` (centered face) for tests; MediaPipe for the real thing."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from clipper.media.edl.schema import Box
from clipper.settings import Settings


class FaceDetector(Protocol):
    def track(self, video: Path, duration: float, step: float = 0.5) -> list[tuple[float, Box]]: ...


class FakeFaceDetector:
    def __init__(self, box: Box | None = None) -> None:
        self.box = box or Box(x=0.42, y=0.25, w=0.16, h=0.3)

    def track(self, video: Path, duration: float, step: float = 0.5) -> list[tuple[float, Box]]:
        n = int(duration / step)
        return [(round(i * step, 3), self.box) for i in range(n + 1)]


FACE_MODEL = "blaze_face_short_range.tflite"
FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
)


def largest_box(detections: Iterable[Any], width: int, height: int) -> Box | None:
    """The widest detection as a normalized box (MediaPipe Tasks boxes are in pixels)."""
    best = max(detections, key=lambda d: d.bounding_box.width, default=None)
    if best is None or width <= 0 or height <= 0:
        return None
    bb = best.bounding_box
    x, y = max(0.0, bb.origin_x / width), max(0.0, bb.origin_y / height)
    w, h = min(bb.width / width, 1 - x), min(bb.height / height, 1 - y)
    return Box(x=x, y=y, w=w, h=h) if w > 0 and h > 0 else None


class MediaPipeFaceDetector:
    """Largest face per sampled frame via the MediaPipe Tasks face detector (BlazeFace short range).

    Install with ``uv sync --all-packages --all-extras`` (extra ``faces``) and put ``FACE_MODEL``
    (download ``FACE_MODEL_URL``) in ``paths.models_dir``. The calls follow the mediapipe 1.0.1
    sources, where the legacy ``mp.solutions`` API no longer exists.
    LOCAL-VERIFY: mediapipe isn't installed in CI. Active-speaker detection (PLAN §18.2) builds on
    these tracks.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def model_path(self) -> Path:
        return self.settings.paths.models_dir / FACE_MODEL

    def track(
        self, video: Path, duration: float, step: float = 0.5
    ) -> list[tuple[float, Box]]:  # LOCAL-VERIFY
        from mediapipe import Image  # type: ignore[import-not-found]
        from mediapipe.tasks.python import BaseOptions  # type: ignore[import-not-found]
        from mediapipe.tasks.python.vision import (  # type: ignore[import-not-found]
            FaceDetector as MpFaceDetector,
        )
        from mediapipe.tasks.python.vision import (  # type: ignore[import-not-found]
            FaceDetectorOptions,
        )

        if not self.model_path.exists():
            raise FileNotFoundError(f"face model missing: download {FACE_MODEL_URL} to {self.model_path}")
        out: list[tuple[float, Box]] = []
        with tempfile.TemporaryDirectory() as tmp:
            pattern = str(Path(tmp) / "f_%06d.jpg")
            subprocess.run(
                [self.settings.paths.ffmpeg("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(video),
                 "-vf", f"fps={1 / step},scale=640:-2", pattern],
                check=True,
            )  # fmt: skip
            options = FaceDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(self.model_path)),
                min_detection_confidence=0.5,
            )
            with MpFaceDetector.create_from_options(options) as detector:
                for i, frame in enumerate(sorted(Path(tmp).glob("f_*.jpg"))):
                    image = Image.create_from_file(str(frame))
                    box = largest_box(detector.detect(image).detections, image.width, image.height)
                    if box is not None:
                        out.append((round(i * step, 3), box))
        return out
