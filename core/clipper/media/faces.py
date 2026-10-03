# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""Face tracks per shot. ``FakeFaceDetector`` (centered face) for tests; MediaPipe for the real thing."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

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


class MediaPipeFaceDetector:
    """Largest face per sampled frame via MediaPipe (``uv pip install mediapipe opencv-python-headless``).

    LOCAL-VERIFY: not installed in CI. Active-speaker detection (PLAN §18.2) builds on these tracks.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def track(
        self, video: Path, duration: float, step: float = 0.5
    ) -> list[tuple[float, Box]]:  # LOCAL-VERIFY
        import cv2  # type: ignore[import-not-found]
        import mediapipe as mp  # type: ignore[import-not-found]

        out: list[tuple[float, Box]] = []
        with tempfile.TemporaryDirectory() as tmp:
            pattern = str(Path(tmp) / "f_%06d.jpg")
            subprocess.run(
                [self.settings.paths.ffmpeg("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(video),
                 "-vf", f"fps={1 / step},scale=640:-2", pattern],
                check=True,
            )  # fmt: skip
            detector = mp.solutions.face_detection.FaceDetection(
                model_selection=1, min_detection_confidence=0.5
            )  # pyright: ignore
            for i, frame in enumerate(sorted(Path(tmp).glob("f_*.jpg"))):
                image = cv2.imread(str(frame))  # pyright: ignore
                res = detector.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))  # pyright: ignore
                dets = getattr(res, "detections", None) or []
                if not dets:
                    continue
                best = max(dets, key=lambda d: d.location_data.relative_bounding_box.width)  # pyright: ignore
                bb = best.location_data.relative_bounding_box  # pyright: ignore
                x, y = max(0.0, float(bb.xmin)), max(0.0, float(bb.ymin))  # pyright: ignore
                w, h = min(float(bb.width), 1 - x), min(float(bb.height), 1 - y)  # pyright: ignore
                if w > 0 and h > 0:
                    out.append((round(i * step, 3), Box(x=x, y=y, w=w, h=h)))
        return out
