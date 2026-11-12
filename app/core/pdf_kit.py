"""Design toolkit for the PDF export: fonts, palette, image preparation, flowables.

``export.py`` lays the book out; this module holds what it is built from and knows
nothing about projects:

- fonts: the bundled faces, plus system fonts for the glyphs they lack
- colour: a ``Theme`` derived from the dominant hue of a piece of artwork
- images: ``Artwork`` crops, shades and re-encodes pictures as bounded JPEGs
- flowables: hand-painted pages, letter-spaced labels, rules, drop caps
"""

from __future__ import annotations

import colorsys
import math
import re
import statistics
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from PIL import ImageFilter
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Paragraph

# Images are re-encoded as JPEG at a bounded resolution so a 13-character project
# exports to a few MB instead of tens of MB of raw PNG.
IMAGE_JPEG_QUALITY = 85
# A portrait is cropped to its panel when that costs at most this share of its width;
# wider images are shown whole, with their studio backdrop extended above and below.
PANEL_MAX_CROP = 0.2

# --- Fonts --------------------------------------------------------------------------------
# Bundled open fonts (SIL OFL, licences next to the files): DM Serif Display for titles,
# Spectral for running text, Barlow for labels and data. Glyphs they lack come from the
# system fonts below when installed (the app image has them): DejaVu Sans for Cyrillic,
# Greek and symbols, WenQuanYi Micro Hei for Chinese, Japanese and Korean.
FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_FONT_FILES = {  # role: (bundled TrueType file, built-in PDF font used if it is missing)
    "display": ("DMSerifDisplay-Regular", "Times-Bold"),
    "display_italic": ("DMSerifDisplay-Italic", "Times-BoldItalic"),
    "text": ("Spectral-Regular", "Times-Roman"),
    "text_italic": ("Spectral-Italic", "Times-Italic"),
    "ui": ("Barlow-Regular", "Helvetica"),
    "ui_bold": ("Barlow-SemiBold", "Helvetica-Bold"),
}
_FALLBACK_FONTS = [  # (name, candidate files); a .ttc collection is read at index 0
    ("DejaVuSans", ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf"]),
    ("WenQuanYiMicroHei", ["/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "/usr/share/fonts/wenquanyi/wqy-microhei/wqy-microhei.ttc"]),
]
_INVISIBLE = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF))  # zero-width characters
# Straight quotes next to letters become curly ones; those after digits (5'11") are left alone.
_LETTER = r"[^\W\d_]"
_QUOTES = [
    (re.compile(rf"(?<={_LETTER})'(?={_LETTER})"), "’"),
    (re.compile(rf'"(?={_LETTER})'), "“"),
    (re.compile(rf'(?<={_LETTER})"|(?<=[.,!?…])"'), "”"),
]


def clean_text(value: Any) -> str:
    text = str(value).translate(_INVISIBLE).strip()
    for pattern, replacement in _QUOTES:
        text = pattern.sub(replacement, text)
    return text


@dataclass(frozen=True)
class Fonts:
    display: str
    display_italic: str
    text: str
    text_italic: str
    ui: str
    ui_bold: str
    fallbacks: tuple[str, ...]


@lru_cache(maxsize=1)
def load_fonts() -> Fonts:
    registered = pdfmetrics.getRegisteredFontNames()
    names = {}
    for role, (bundled, builtin) in _FONT_FILES.items():
        path = FONT_DIR / f"{bundled}.ttf"
        if path.exists():
            if bundled not in registered:
                pdfmetrics.registerFont(TTFont(bundled, str(path)))
            names[role] = bundled
        else:
            names[role] = builtin
    fallbacks = []
    for name, candidates in _FALLBACK_FONTS:
        path = next((candidate for candidate in candidates if Path(candidate).exists()), None)
        if path:
            if name not in registered:
                pdfmetrics.registerFont(TTFont(name, path))
            fallbacks.append(name)
    return Fonts(**names, fallbacks=tuple(fallbacks))


@lru_cache(maxsize=None)
def _glyphs(font: str) -> dict[int, int] | None:
    """Code points a TrueType font can draw; None for the built-in PDF fonts."""
    face = getattr(pdfmetrics.getFont(font), "face", None)
    return getattr(face, "charToGlyph", None)


def font_for(char: str, font: str) -> str:
    """``font`` if it can draw ``char``, else the first fallback font that can."""
    glyphs = _glyphs(font)
    if glyphs is None or char.isspace() or ord(char) in glyphs:
        return font
    for fallback in load_fonts().fallbacks:
        if ord(char) in (_glyphs(fallback) or ()):
            return fallback
    return font


def markup(value: Any, font: str) -> str:
    """Escape text for a Paragraph set in ``font``; glyphs it lacks use a fallback font."""
    parts: list[str] = []
    run, run_font = "", font
    for char in clean_text(value) + "\0":
        char_font = font_for(char, font)
        if run and (char == "\0" or char_font != run_font):
            piece = escape(run)
            parts.append(piece if run_font == font else f'<font name="{run_font}">{piece}</font>')
            run = ""
        run, run_font = run + char, char_font
    return "".join(parts).replace("\n", "<br/>")


def para_style(font: str, size: float, leading: float, color: Color, align: int = TA_LEFT, **extra: Any) -> ParagraphStyle:
    return ParagraphStyle(
        "s", fontName=font, fontSize=size, leading=leading, textColor=color, alignment=align, **extra
    )


def para(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(markup(value, style.fontName), style)


# --- Colour -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    paper: Color  # light pages
    ink: Color
    muted: Color
    hairline: Color
    accent: Color  # labels and rules on paper
    tint: Color  # soft panels on paper
    numeral: Color  # large page numerals on paper
    night: Color  # dark pages: cover, index pages, plates
    night_soft: Color
    on_night: Color
    on_night_muted: Color
    accent_night: Color


def _hls(hue: float, lightness: float, saturation: float) -> Color:
    return Color(*colorsys.hls_to_rgb(hue, lightness, saturation))


def hex_color(color: Color) -> str:
    return "#" + color.hexval()[2:]


def rgb255(color: Color) -> tuple[int, int, int]:
    return tuple(round(channel * 255) for channel in color.rgb())  # type: ignore[return-value]


def _luminance(color: Color) -> float:
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in color.rgb())
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(a: Color, b: Color) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _mix(base: Color, other: Color, amount: float) -> Color:
    return Color(*(b + (o - b) * amount for b, o in zip(base.rgb(), other.rgb())))


def theme_for_hue(hue: float | None) -> Theme:
    """Palette around the artwork's dominant hue (warm terracotta when it has none)."""
    saturation = 0.55
    if hue is None:
        hue, saturation = 0.045, 0.62
    paper = HexColor("#FAF7F1")
    lightness = 0.44
    accent = _hls(hue, lightness, saturation)
    while _contrast(accent, paper) < 4.6 and lightness > 0.2:  # legible as small labels
        lightness -= 0.02
        accent = _hls(hue, lightness, saturation)
    night = _hls(hue, 0.085, 0.24)
    lightness = 0.66
    accent_night = _hls(hue, lightness, saturation)
    while _contrast(accent_night, night) < 6.5 and lightness < 0.9:
        lightness += 0.02
        accent_night = _hls(hue, lightness, saturation)
    return Theme(
        paper=paper,
        ink=HexColor("#1F1C19"),
        muted=HexColor("#786F65"),
        hairline=HexColor("#DED7CB"),
        accent=accent,
        tint=_mix(paper, accent, 0.085),
        numeral=_mix(paper, accent, 0.17),
        night=night,
        night_soft=_hls(hue, 0.16, 0.2),
        on_night=HexColor("#F5F0E7"),
        on_night_muted=HexColor("#A9A195"),
        accent_night=accent_night,
    )


def sample_pixels(path: Path, size: int = 48) -> list[tuple[int, int, int]]:
    """A coarse grid of the image's pixels, enough to judge its colours."""
    try:
        with PILImage.open(path) as img:
            data = img.convert("RGB").resize((size, size), PILImage.Resampling.BILINEAR).tobytes()
    except OSError:
        return []
    return [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)]


def dominant_hue(pixels: list[tuple[int, int, int]]) -> float | None:
    bins = [0.0] * 36
    for red, green, blue in pixels:
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        if saturation > 0.22 and value > 0.18:
            bins[int(hue * 36) % 36] += saturation * value
    if sum(bins) < len(pixels) * 0.02:  # greyscale artwork
        return None
    smooth = [bins[i - 1] + 2 * bins[i] + bins[(i + 1) % 36] for i in range(36)]
    return (max(range(36), key=smooth.__getitem__) + 0.5) / 36


def colorfulness(pixels: list[tuple[int, int, int]]) -> float:
    """Hasler-Suesstrunk colourfulness: how vivid an image looks."""
    if len(pixels) < 2:
        return 0.0
    red_green = [red - green for red, green, _ in pixels]
    yellow_blue = [(red + green) / 2 - blue for red, green, blue in pixels]
    spread = math.hypot(statistics.pstdev(red_green), statistics.pstdev(yellow_blue))
    return spread + 0.3 * math.hypot(statistics.fmean(red_green), statistics.fmean(yellow_blue))


# --- Image preparation --------------------------------------------------------------------


@dataclass(frozen=True)
class Picture:
    data: bytes  # JPEG
    width: int
    height: int

    def reader(self) -> ImageReader:
        return ImageReader(BytesIO(self.data))


def _bounded(img: PILImage.Image, max_px: int) -> PILImage.Image:
    if max(img.size) > max_px:
        img.thumbnail((max_px, max_px), PILImage.Resampling.LANCZOS)
    return img


def _shade(
    img: PILImage.Image, rgb: tuple[int, int, int], top: float, bottom: float, start: float, flat: float
) -> PILImage.Image:
    """Blend towards ``rgb`` so text stays legible: ``flat`` everywhere, ``top`` fading out
    below the top edge, and rising to ``bottom`` at the bottom edge from ``start`` down."""
    column = []
    for y in range(256):
        t = y / 255
        alpha = max(flat, top * max(0.0, 1 - t / 0.24))
        if t > start:
            alpha = max(alpha, flat + (bottom - flat) * ((t - start) / (1 - start)) ** 1.4)
        column.append(round(255 * min(alpha, 1.0)))
    mask = PILImage.new("L", (1, 256))
    mask.putdata(column)
    mask = mask.resize(img.size, PILImage.Resampling.BILINEAR)
    return PILImage.composite(PILImage.new("RGB", img.size, rgb), img, mask)


def _trim_bars(img: PILImage.Image) -> PILImage.Image:
    """Drop the black bars above and below a frame that was generated wider than its canvas."""
    width, height = img.size
    box = img.convert("L").point(lambda value: 255 if value > 24 else 0).getbbox()
    if not box:
        return img
    top, bottom = box[1], height - box[3]
    # Real bars are equal and modest; anything else is probably a dark scene.
    if min(top, bottom) < height * 0.02 or abs(top - bottom) > height * 0.03 or max(top, bottom) > height * 0.2:
        return img
    return img.crop((0, top, width, box[3]))


def _letterbox(img: PILImage.Image, aspect: float) -> PILImage.Image:
    """Grow the canvas to ``aspect`` by continuing the top and bottom edges (studio backdrops)."""
    width, height = img.size
    target_h = round(width / aspect)
    top = (target_h - height) // 2
    bottom = target_h - height - top
    canvas = PILImage.new("RGB", (width, target_h))
    blur = ImageFilter.GaussianBlur(width / 24)
    box = PILImage.Resampling.BOX
    if top > 0:
        edge = img.crop((0, 0, width, 6)).resize((width, 1), box)
        canvas.paste(edge.resize((width, top)).filter(blur), (0, 0))
    if bottom > 0:
        edge = img.crop((0, height - 6, width, height)).resize((width, 1), box)
        canvas.paste(edge.resize((width, bottom)).filter(blur), (0, top + height))
    canvas.paste(img, (0, top))
    return canvas


class Artwork:
    """Crops and re-encodes images, cached so the second layout pass costs nothing."""

    def __init__(self) -> None:
        self._cache: dict[tuple, Picture | None] = {}

    @staticmethod
    def _open(path: Path) -> PILImage.Image | None:
        try:
            with PILImage.open(path) as img:
                img.load()
                if img.mode in ("RGBA", "LA", "P"):
                    rgba = img.convert("RGBA")
                    flat = PILImage.new("RGB", rgba.size, "white")
                    flat.paste(rgba, mask=rgba.split()[-1])
                    return flat
                return img.convert("RGB")
        except OSError:
            return None

    def _cached(self, key: tuple, build: Callable[[PILImage.Image], PILImage.Image]) -> Picture | None:
        if key not in self._cache:
            img = self._open(Path(key[1]))
            pic = None
            if img is not None:
                img = build(img)
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
                pic = Picture(buffer.getvalue(), *img.size)
            self._cache[key] = pic
        return self._cache[key]

    def whole(self, path: Path, max_px: int) -> Picture | None:
        return self._cached(("whole", str(path), max_px), lambda img: _bounded(img, max_px))

    def crop(
        self,
        path: Path,
        aspect: float,
        max_px: int,
        focus: tuple[float, float] = (0.5, 0.5),
        zoom: float = 1.0,
        shade: tuple | None = None,
        trim_bars: bool = False,
    ) -> Picture | None:
        """Largest ``aspect`` (width / height) window, tightened by ``zoom`` and placed at
        ``focus`` (0 = left/top, 1 = right/bottom of the room left over)."""

        def build(img: PILImage.Image) -> PILImage.Image:
            if trim_bars:
                img = _trim_bars(img)
            width, height = img.size
            box_w, box_h = (width, width / aspect) if width / height <= aspect else (height * aspect, height)
            box_w, box_h = box_w / zoom, box_h / zoom
            left, top = (width - box_w) * focus[0], (height - box_h) * focus[1]
            img = _bounded(img.crop((round(left), round(top), round(left + box_w), round(top + box_h))), max_px)
            return _shade(img, *shade) if shade else img

        return self._cached(("crop", str(path), round(aspect, 4), max_px, focus, zoom, shade, trim_bars), build)

    def panel(self, path: Path, aspect: float, max_px: int) -> Picture | None:
        """A portrait for the full-height panel: cropped when little is lost, else shown
        whole with its backdrop extended."""

        def build(img: PILImage.Image) -> PILImage.Image:
            width, height = img.size
            if width / height > aspect and 1 - aspect / (width / height) > PANEL_MAX_CROP:
                return _bounded(_letterbox(img, aspect), max_px)
            box_w, box_h = (width, width / aspect) if width / height <= aspect else (height * aspect, height)
            left, top = (width - box_w) / 2, (height - box_h) * 0.4
            return _bounded(img.crop((round(left), round(top), round(left + box_w), round(top + box_h))), max_px)

        return self._cached(("panel", str(path), round(aspect, 4), max_px), build)


# --- Flowables ----------------------------------------------------------------------------


class Paint(Flowable):
    """Runs ``painter(canvas)`` with the origin at the page corner.

    Zero-sized by default: a backdrop drawn behind whatever follows it in the frame.
    Given a size, it claims that much of the frame (a page painted by hand).
    """

    def __init__(self, painter: Callable[[Any], None], width: float = 0, height: float = 0) -> None:
        super().__init__()
        self.painter, self.width, self.height = painter, width, height

    def wrap(self, avail_w: float, avail_h: float) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        canvas = self.canv
        canvas.saveState()
        x, y = canvas.absolutePosition(0, 0)
        canvas.translate(-x, -y)
        self.painter(canvas)
        canvas.restoreState()


def draw_tracked(
    canvas: Any,
    x: float,
    y: float,
    text: str,
    font: str,
    size: float,
    color: Color,
    tracking: float,
    align: str = "left",
    max_width: float | None = None,
) -> float:
    """Draw one line of letter-spaced capitals; returns its width."""
    text = clean_text(text).upper()
    # One font for the whole line: the first one any of its characters falls back to.
    font = next((other for other in (font_for(char, font) for char in text) if other != font), font)
    width = pdfmetrics.stringWidth(text, font, size) + tracking * max(len(text) - 1, 0)
    if max_width and width > max_width:
        shrink = max_width / width
        size, tracking, width = size * shrink, tracking * shrink, max_width
    canvas.setFont(font, size)
    canvas.setFillColor(color)
    canvas.drawString(x - width if align == "right" else x, y, text, charSpace=tracking)
    return width


class Tracked(Flowable):
    """One line of letter-spaced capitals: kickers and field labels."""

    def __init__(self, text: str, font: str, size: float, color: Color, tracking: float, space_after: float = 0) -> None:
        super().__init__()
        self.text, self.font, self.size, self.color = text, font, size, color
        self.tracking, self.space_after = tracking, space_after
        self.height = size * 1.25 + space_after

    def wrap(self, avail_w: float, avail_h: float) -> tuple[float, float]:
        self.width = avail_w
        return avail_w, self.height

    def draw(self) -> None:
        baseline = self.space_after + self.size * 0.24
        draw_tracked(self.canv, 0, baseline, self.text, self.font, self.size, self.color, self.tracking, max_width=self.width)


class Rule(Flowable):
    """A short horizontal rule."""

    def __init__(self, width: float, thickness: float, color: Color) -> None:
        super().__init__()
        self.width, self.height, self.color = width, thickness, color

    def wrap(self, avail_w: float, avail_h: float) -> tuple[float, float]:
        return min(self.width, avail_w), self.height

    def draw(self) -> None:
        self.canv.setFillColor(self.color)
        self.canv.rect(0, 0, self.width, self.height, stroke=0, fill=1)


class DropCap(Flowable):
    """The enlarged first letter of a paragraph, three lines tall."""

    def __init__(self, letter: str, font: str, size: float, color: Color, height: float, baseline: float) -> None:
        super().__init__()
        self.letter, self.font, self.size, self.color, self.baseline = letter, font, size, color, baseline
        self.width, self.height = pdfmetrics.stringWidth(letter, font, size), height

    def wrap(self, avail_w: float, avail_h: float) -> tuple[float, float]:
        return self.width, self.height

    # ImageAndFlowables, which wraps the paragraph around the letter, expects an Image.
    def _restrictSize(self, avail_w: float, avail_h: float) -> tuple[float, float]:
        return self.width, self.height

    def _unRestrictSize(self) -> None:
        pass

    def draw(self) -> None:
        self.canv.setFont(self.font, self.size)
        self.canv.setFillColor(self.color)
        self.canv.drawString(0, self.baseline, self.letter)


def stack_height(flowables: list[Flowable], width: float, canvas: Any = None) -> float:
    if canvas is None:
        return sum(flowable.wrap(width, 1e5)[1] for flowable in flowables)
    return sum(flowable.wrapOn(canvas, width, 1e5)[1] for flowable in flowables)


def draw_stack(canvas: Any, flowables: list[Flowable], x: float, top: float, width: float) -> float:
    """Draw flowables downwards from ``top``; returns the y under the last one."""
    for flowable in flowables:
        _, height = flowable.wrapOn(canvas, width, 1e5)
        top -= height
        flowable.drawOn(canvas, x, top)
    return top


def balanced_runs(heights: list[float], groups: int) -> list[tuple[int, int]]:
    """Split a sequence into ``groups`` consecutive runs, keeping the tallest run shortest."""
    count = len(heights)
    groups = max(1, min(groups, count))
    prefix = [0.0]
    for height in heights:
        prefix.append(prefix[-1] + height)
    best = [[math.inf] * (count + 1) for _ in range(groups + 1)]
    cut = [[0] * (count + 1) for _ in range(groups + 1)]
    best[0][0] = 0.0
    for group in range(1, groups + 1):
        for end in range(1, count + 1):
            for start in range(group - 1, end):
                tallest = max(best[group - 1][start], prefix[end] - prefix[start])
                if tallest < best[group][end]:
                    best[group][end], cut[group][end] = tallest, start
    runs, end = [], count
    for group in range(groups, 0, -1):
        runs.append((cut[group][end], end))
        end = cut[group][end]
    return runs[::-1]
