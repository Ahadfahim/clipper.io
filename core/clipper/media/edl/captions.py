"""ASS caption generator (PLAN §18.2): word-by-word highlight, emphasis, phrase line breaks,
platform safe zones and face avoidance. Pure: ``build_ass(edl) -> str``.

Layout is computed in output pixels (PlayResX/Y = the output size), so the same numbers drive the
QA check that captions stay inside the safe zone and off the face.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from clipper.media.edl.schema import Box, Edl
from clipper.media.edl.timeline import OutWord, output_words


@dataclass(frozen=True)
class SafeArea:
    """Unsafe margins in output pixels for a 1080x1920 frame (scaled for other sizes)."""

    top: int
    bottom: int
    left: int
    right: int


# Approximate UI overlays per platform at 1080x1920 (title/handle/caption bars and side buttons).
SAFE_ZONES: dict[str, SafeArea] = {
    "tiktok": SafeArea(top=160, bottom=420, left=60, right=150),
    "shorts": SafeArea(top=200, bottom=380, left=60, right=140),
    "reels": SafeArea(top=220, bottom=430, left=60, right=130),
    "none": SafeArea(top=60, bottom=60, left=40, right=40),
}


@dataclass(frozen=True)
class CaptionStyle:
    name: str
    font: str
    size: int
    primary: str  # &HAABBGGRR
    highlight: str  # current word
    emphasis: str
    outline: str
    outline_px: float
    shadow_px: float
    bold: bool = True
    box: bool = False  # opaque box behind text (BorderStyle 3)
    uppercase: bool = False


def _c(rgb: str, alpha: int = 0) -> str:
    """'#RRGGBB' -> ASS '&HAABBGGRR'."""
    r, g, b = rgb[1:3], rgb[3:5], rgb[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


STYLES: dict[str, CaptionStyle] = {
    "bold-pop": CaptionStyle(
        "bold-pop",
        "Arial",
        84,
        _c("#FFFFFF"),
        _c("#FFE14D"),
        _c("#FFE14D"),
        _c("#000000"),
        6,
        2,
        uppercase=True,
    ),
    "clean": CaptionStyle(
        "clean", "Arial", 72, _c("#FFFFFF"), _c("#9AE6FF"), _c("#9AE6FF"), _c("#000000"), 3, 1, bold=False
    ),
    "boxed": CaptionStyle(
        "boxed",
        "Arial",
        70,
        _c("#FFFFFF"),
        _c("#FFE14D"),
        _c("#FFE14D"),
        _c("#000000", 0x40),
        14,
        0,
        box=True,
    ),
    "karaoke": CaptionStyle(
        "karaoke",
        "Arial",
        80,
        _c("#C8C8C8"),
        _c("#FFFFFF"),
        _c("#7CFF6B"),
        _c("#000000"),
        5,
        2,
        uppercase=True,
    ),
}

PROFANITY = frozenset({"fuck", "fucking", "shit", "bitch", "asshole", "bastard", "dick", "cunt", "damn"})
_PUNCT_END = re.compile(r"[.!?;:,]$")


@dataclass(frozen=True)
class Line:
    words: list[OutWord]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


def phrase_lines(
    words: list[OutWord], max_words: int, pause: float = 0.35, max_chars: int = 22
) -> list[Line]:
    """Break at punctuation, at pauses, at segment changes and at ``max_words`` / ``max_chars``."""
    lines: list[Line] = []
    cur: list[OutWord] = []
    for w in words:
        if cur:
            prev = cur[-1]
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            if (
                len(cur) >= max_words
                or chars > max_chars
                or w.start - prev.end > pause
                or w.segment != prev.segment
                or _PUNCT_END.search(prev.text)
            ):
                lines.append(Line(cur))
                cur = []
        cur.append(w)
    if cur:
        lines.append(Line(cur))
    return lines


def mask(text: str) -> str:
    core = re.sub(r"[^\w]", "", text.lower())
    if core in PROFANITY and len(text) > 1:
        return text[0] + "*" * (len(text) - 1)
    return text


def _ts(t: float) -> str:
    t = max(t, 0.0)
    cs = round(t * 100)
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


@dataclass(frozen=True)
class CaptionBox:
    """Where the caption band sits, in output pixels."""

    x: int
    y: int
    w: int
    h: int
    align: int  # ASS \an
    margin_v: int

    def overlaps(self, other: tuple[int, int, int, int]) -> bool:
        ox, oy, ow, oh = other
        return not (self.x + self.w <= ox or ox + ow <= self.x or self.y + self.h <= oy or oy + oh <= self.y)


def _scale(area: SafeArea, width: int, height: int) -> SafeArea:
    sx, sy = width / 1080, height / 1920
    return SafeArea(
        round(area.top * sy), round(area.bottom * sy), round(area.left * sx), round(area.right * sx)
    )


def caption_box(edl: Edl, style: CaptionStyle, lines_per_event: int = 1) -> CaptionBox:
    """Pick the caption band: bottom of the safe area unless that covers the face, then the top."""
    W, H = edl.output.width, edl.output.height
    area = _scale(SAFE_ZONES[edl.captions.safe_zone], W, H)
    size = round(style.size * H / 1920)
    band_h = round(size * 1.35 * lines_per_event + 2 * style.outline_px)
    pad = round(24 * H / 1920)
    x, w = area.left, W - area.left - area.right
    bottom = CaptionBox(x, H - area.bottom - pad - band_h, w, band_h, 2, area.bottom + pad)
    top = CaptionBox(x, area.top + pad, w, band_h, 8, area.top + pad)
    middle = CaptionBox(x, round(H * 0.55), w, band_h, 2, H - round(H * 0.55) - band_h)
    pos = edl.captions.position
    if pos == "top":
        return top
    if pos == "bottom":
        return bottom
    if pos == "middle":
        return middle
    face = face_px(edl.captions.face_box, W, H)
    if face is None or not bottom.overlaps(face):
        # Lower third reads best on Shorts/TikTok/Reels; middle is the next choice.
        lower_third = CaptionBox(x, round(H * 0.62), w, band_h, 2, H - round(H * 0.62) - band_h)
        if face is None or not lower_third.overlaps(face):
            return lower_third if lower_third.y + band_h <= H - area.bottom - pad else bottom
        return bottom
    if not top.overlaps(face):
        return top
    return bottom


def face_px(box: Box | None, width: int, height: int) -> tuple[int, int, int, int] | None:
    if box is None:
        return None
    return round(box.x * width), round(box.y * height), round(box.w * width), round(box.h * height)


def _style_line(
    name: str, s: CaptionStyle, size: int, align: int, margin_v: int, margin_lr: tuple[int, int]
) -> str:
    border_style = 3 if s.box else 1
    back = s.outline if s.box else "&H80000000"
    return (
        f"Style: {name},{s.font},{size},{s.primary},{s.highlight},{s.outline},{back},"
        f"{-1 if s.bold else 0},0,0,0,100,100,0,0,{border_style},{s.outline_px},{s.shadow_px},"
        f"{align},{margin_lr[0]},{margin_lr[1]},{margin_v},1"
    )


def build_ass(edl: Edl) -> str:
    style = STYLES.get(edl.captions.style, STYLES["bold-pop"])
    W, H = edl.output.width, edl.output.height
    area = _scale(SAFE_ZONES[edl.captions.safe_zone], W, H)
    size = round(style.size * H / 1920)
    box = caption_box(edl, style)
    hook_size = round(78 * H / 1920)
    header = [
        "[Script Info]",
        "; Generated by Clipper.io from the clip EDL",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line("Caption", style, size, box.align, box.margin_v, (area.left, area.right)),
        _style_line(
            "Hook",
            CaptionStyle(
                "hook",
                style.font,
                hook_size,
                _c("#000000"),
                _c("#000000"),
                _c("#FFFFFF"),
                _c("#FFFFFF"),
                18,
                0,
                box=True,
            ),
            hook_size,
            8,
            area.top + round(40 * H / 1920),
            (area.left, area.right),
        ),
        _style_line(
            "Brand",
            CaptionStyle(
                "brand",
                style.font,
                round(44 * H / 1920),
                _c("#FFFFFF", 0x30),
                _c("#FFFFFF"),
                _c("#FFFFFF"),
                _c("#000000"),
                2,
                1,
                bold=False,
            ),
            round(44 * H / 1920),
            8,
            area.top + round(170 * H / 1920),
            (area.left, area.right),
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events: list[str] = []
    if edl.captions.enabled:
        words = output_words(edl)
        for line in phrase_lines(words, edl.captions.max_words_per_line):
            for i, current in enumerate(line.words):
                start = current.start if i else line.start
                end = line.words[i + 1].start if i + 1 < len(line.words) else line.end
                if end - start < 0.01:
                    continue
                parts: list[str] = []
                for w in line.words:
                    text = mask(w.text) if edl.captions.profanity_mask else w.text
                    text = _escape(text.upper() if style.uppercase else text)
                    if w is current:
                        tag = r"{\c" + (style.emphasis if w.emphasis else style.highlight) + "&"
                        tag += r"\fscx115\fscy115}" if w.emphasis else "}"
                        parts.append(tag + text + r"{\r}")
                    elif w.emphasis:
                        parts.append(r"{\c" + style.emphasis + "&}" + text + r"{\r}")
                    else:
                        parts.append(text)
                events.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{' '.join(parts)}")
    for ov in edl.overlays:
        if ov.type == "hook_text":
            text = _escape(str(ov.props.get("text", "")))
            if text:
                events.append(
                    f"Dialogue: 2,{_ts(ov.t_in)},{_ts(ov.t_out)},Hook,,0,0,0,,{{\\fad(80,120)}}{text}"
                )
        elif ov.type == "brand":
            text = _escape(str(ov.props.get("text", "")))
            if text:
                events.append(f"Dialogue: 2,{_ts(ov.t_in)},{_ts(ov.t_out)},Brand,,0,0,0,,{text}")
    return "\n".join(header + events) + "\n"


@dataclass(frozen=True)
class CaptionLayout:
    box: tuple[int, int, int, int]
    safe: tuple[int, int, int, int]
    face: tuple[int, int, int, int] | None


def caption_layout_report(edl: Edl) -> CaptionLayout:
    """Numbers the QA checks use: caption band, safe area and face box in output pixels."""
    style = STYLES.get(edl.captions.style, STYLES["bold-pop"])
    W, H = edl.output.width, edl.output.height
    area = _scale(SAFE_ZONES[edl.captions.safe_zone], W, H)
    box = caption_box(edl, style)
    return CaptionLayout(
        box=(box.x, box.y, box.w, box.h),
        safe=(area.left, area.top, W - area.left - area.right, H - area.top - area.bottom),
        face=face_px(edl.captions.face_box, W, H),
    )
