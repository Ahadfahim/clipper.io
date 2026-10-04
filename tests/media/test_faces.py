"""The MediaPipe Tasks result → normalized face box conversion (the detector itself is LOCAL-VERIFY)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper.media.faces import FACE_MODEL, MediaPipeFaceDetector, largest_box
from clipper.settings import Settings


def det(x: int, y: int, w: int, h: int) -> SimpleNamespace:
    return SimpleNamespace(bounding_box=SimpleNamespace(origin_x=x, origin_y=y, width=w, height=h))


def test_largest_face_wins_and_is_normalized() -> None:
    box = largest_box([det(10, 10, 40, 40), det(320, 90, 128, 144)], 640, 360)
    assert box is not None
    assert (box.x, box.y, box.w, box.h) == pytest.approx((0.5, 0.25, 0.2, 0.4))


def test_boxes_are_clamped_to_the_frame() -> None:
    box = largest_box([det(-20, 300, 100, 100)], 640, 360)
    assert box is not None
    assert box.x == 0.0 and box.y == pytest.approx(300 / 360)
    assert box.y + box.h == pytest.approx(1.0)


def test_no_faces() -> None:
    assert largest_box([], 640, 360) is None
    assert largest_box([det(0, 0, 10, 10)], 0, 0) is None


def test_missing_model_names_the_download(settings: Settings, tmp_path: Path) -> None:
    detector = MediaPipeFaceDetector(settings)
    assert detector.model_path == settings.paths.models_dir / FACE_MODEL
    pytest.importorskip("mediapipe")
    with pytest.raises(FileNotFoundError, match="blaze_face_short_range"):
        detector.track(tmp_path / "x.mp4", 1.0)


def test_doctor_warns_until_the_face_model_is_in_place(settings: Settings) -> None:
    from clipper.doctor import check_face_model

    res = check_face_model(settings)
    assert res.status == "warn" and res.fix
