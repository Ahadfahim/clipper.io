"""Virtual camera from a face track: dead zone + minimum hold, so the crop only moves when the speaker
really moves (PLAN §18.2). Pure: produces EDL camera keys; the renderer eases between them."""

from __future__ import annotations

from clipper.media.edl.schema import Box, CameraKey, Layout


def auto_camera_keys(
    face_track: list[tuple[float, Box]],
    start: float,
    end: float,
    *,
    dead_zone: float = 0.08,
    min_hold: float = 1.0,
    layout: Layout = "crop",
) -> list[CameraKey]:
    """Keys (source time) following the face center. No faces -> one centered 'fit' key (wide shot)."""
    samples = sorted((t, b) for t, b in face_track if start - 0.5 <= t <= end + 0.5)
    if not samples:
        return [CameraKey(t=start, layout="fit")]
    keys = [
        CameraKey(
            t=start, layout=layout, focus_x=round(samples[0][1].cx, 4), focus_y=round(samples[0][1].cy, 4)
        )
    ]
    for t, box in samples[1:]:
        last = keys[-1]
        if t - last.t < min_hold:
            continue
        if abs(box.cx - last.focus_x) > dead_zone:
            keys.append(
                CameraKey(t=round(t, 3), layout=layout, focus_x=round(box.cx, 4), focus_y=round(box.cy, 4))
            )
    return keys
