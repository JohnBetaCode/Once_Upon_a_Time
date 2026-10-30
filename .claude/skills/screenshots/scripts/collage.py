#!/usr/bin/env python3
"""Build the README banner and collages from generated images.

    python3 .claude/skills/screenshots/scripts/collage.py --out /tmp/collages   # preview
    python3 .claude/skills/screenshots/scripts/collage.py                        # writes docs/images/

Produces three JPEGs the README links to, plus one for GitHub:
  banner.jpg          hero: title + a staggered lineup of anchor portraits across styles
  cast-gallery.jpg    4x2 grid of captioned anchor portraits
  locations.jpg       three captioned establishing shots
  social-preview.jpg  the banner at 1280x640 for the repository's social preview setting
  page-to-portrait.jpg  researched details on paper cards, an arrow, and the anchor drawn from them

Sources are listed in SOURCES below (paths under projects/ or docs/images). Missing files
are skipped with a warning so the script still runs on a clone with different projects.
Needs Pillow on the host (stdlib otherwise). Everything is drawn at 1.5x and downscaled.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[4]
P = ROOT / "projects"
D = ROOT / "docs" / "images"

# (image path, caption name, caption subline) -----------------------------------------
BANNER_SOURCES = [
    P / "2001-una-odisea-espacial/characters/dr-david-bowman/anchor.png",
    P / "guia-del-autoestopista-galactico/characters/zaphod-beeblebrox/anchor.png",
    D / "sample-fox-anchor.jpg",
    P / "guia-del-autoestopista-galactico/characters/marvin-the-paranoid-android/anchor.png",
    P / "la-guerra-de-los-mundos/characters/the-martians/anchor.png",
    P / "suenan-los-androides-con-ovejas-electricas/characters/rachael-rosen/anchor.png",
    P / "2001-una-odisea-espacial/characters/moon-watcher/anchor.png",
]

CAST_SOURCES = [
    (P / "guia-del-autoestopista-galactico/characters/arthur-dent/anchor.png",
     "Arthur Dent", "The Hitchhiker's Guide to the Galaxy · realistic"),
    (P / "2001-una-odisea-espacial/characters/hal-9000/anchor.png",
     "HAL 9000", "2001: A Space Odyssey · comic"),
    ((D / "sample-little-prince-anchor.jpg", (0.30, 0.0, 0.90, 1.0)),  # wide canvas: keep figure + scarf
     "The Little Prince", "The Little Prince · cartoon"),
    (P / "suenan-los-androides-con-ovejas-electricas/characters/rick-deckard/anchor.png",
     "Rick Deckard", "Do Androids Dream of Electric Sheep? · realistic"),
    (P / "ubik/characters/glen-runciter/anchor.png",
     "Glen Runciter", "Ubik · comic"),
    (D / "sample-seldon-anchor.jpg",
     "Hari Seldon", "Foundation · realistic"),
    (P / "2001-una-odisea-espacial/characters/the-weaver-the-entity/anchor.png",
     "The Weaver", "2001: A Space Odyssey · comic"),
    (P / "guia-del-autoestopista-galactico/characters/ford-prefect/anchor.png",
     "Ford Prefect", "The Hitchhiker's Guide to the Galaxy · realistic"),
]

LOCATION_SOURCES = [
    (P / "guia-del-autoestopista-galactico/locations/the-vogon-flagship-interior.png",
     "The Vogon flagship", "The Hitchhiker's Guide to the Galaxy · realistic"),
    (P / "guia-del-autoestopista-galactico/locations/the-orbit-of-earth-the-vogon-demolition-fleet.png",
     "The Vogon demolition fleet", "The Hitchhiker's Guide to the Galaxy · realistic"),
    (P / "suenan-los-androides-con-ovejas-electricas/locations/deckard-s-apartment-building-roof-pasture.png",
     "Deckard's rooftop pasture", "Do Androids Dream of Electric Sheep? · realistic"),
]

# (anchor, name, book · author, illustration style, details condensed from the character's
# research in characters.json; keep them faithful to that data, never invent)
PAGE_SOURCES = [
    (P / "guia-del-autoestopista-galactico/characters/zaphod-beeblebrox/anchor.png",
     "Zaphod Beeblebrox", "The Hitchhiker's Guide to the Galaxy · Douglas Adams", "realistic",
     ["two heads, side by side",
      "three arms",
      "candy-striped crimson and purple jacket",
      "wild blond hair, stubble on both chins"]),
    (P / "la-guerra-de-los-mundos/characters/the-martians/anchor.png",
     "The Martians", "The War of the Worlds · H. G. Wells", "cartoon",
     ["“heads—merely heads”",
      "sixteen whip-like tentacles in two bunches",
      "huge dark eyes with no eyelids",
      "sagging into a mound under Earth's gravity"]),
    (P / "ubik/characters/glen-runciter/anchor.png",
     "Glen Runciter", "Ubik · Philip K. Dick", "comic",
     ["about eighty, shaggy iron-gray hair",
      "a ruddy flush from artificial organs",
      "iridescent pastel suit, knit cummerbund",
      "cheesecloth cravat, paper cigarettes"]),
    (P / "2001-una-odisea-espacial/characters/moon-watcher/anchor.png",
     "Moon-Watcher", "2001: A Space Odyssey · Arthur C. Clarke", "comic",
     ["a hominid, not yet human",
      "half-starved, all wiry muscle",
      "fur matted with red clay",
      "scars from a carnivore attack"]),
]

SCALE = 1.5  # supersampling factor; output width = canvas width / SCALE
BG_TOP, BG_BOTTOM = (24, 30, 48), (9, 12, 22)
INK, INK_SOFT, INK_MUTED = (245, 241, 232), (184, 192, 208), (138, 147, 166)
ACCENT = (255, 184, 92)

FONT_DIRS = [Path("/usr/share/fonts"), Path.home() / ".fonts", Path("/usr/local/share/fonts")]
BOLD_CANDIDATES = ["Ubuntu-B.ttf", "NotoSans-Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"]
REG_CANDIDATES = ["Ubuntu-R.ttf", "NotoSans-Regular.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"]
SERIF_BOLD = ["FreeSerifBold.ttf", "LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"]
SERIF_REG = ["FreeSerif.ttf", "LiberationSerif-Regular.ttf", "DejaVuSerif.ttf"]
SERIF_ITALIC = ["FreeSerifItalic.ttf", "LiberationSerif-Italic.ttf", "DejaVuSerif.ttf"]
PAPER, PAPER_INK, PAPER_MUTED = (244, 236, 220), (48, 37, 28), (128, 106, 84)
ACCENT_INK = (196, 112, 30)  # the accent, darkened to read on paper


_FONT_FILES: dict[str, Path | None] = {}


def _font_file(name: str) -> Path | None:
    if name not in _FONT_FILES:
        _FONT_FILES[name] = next((p for base in FONT_DIRS if base.exists() for p in base.rglob(name)), None)
    return _FONT_FILES[name]


def find_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in candidates:
        path = _font_file(name)
        if path:
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def load(source: Path | tuple[Path, tuple[float, float, float, float]]) -> Image.Image | None:
    """Load an image; ``source`` may be ``(path, (left, top, right, bottom))`` with a focus
    crop in relative coordinates for canvases much wider than the figure."""
    path, box = (source, None) if isinstance(source, Path) else source
    if not path.exists():
        print(f"warning: missing {path.relative_to(ROOT)}", file=sys.stderr)
        return None
    img = autocrop_letterbox(Image.open(path).convert("RGB"))
    if box:
        w, h = img.size
        img = img.crop((round(box[0] * w), round(box[1] * h), round(box[2] * w), round(box[3] * h)))
    return img


def autocrop_letterbox(img: Image.Image, threshold: int = 14) -> Image.Image:
    """Remove near-black horizontal bands some wide generations come with."""
    gray = img.convert("L")
    w, h = gray.size
    rows = list(gray.resize((1, h), Image.BOX).tobytes())  # mean brightness per row
    top, bottom = 0, h
    while top < h // 3 and rows[top] < threshold:
        top += 1
    while bottom > 2 * h // 3 and rows[bottom - 1] < threshold:
        bottom -= 1
    return img.crop((0, top, w, bottom)) if (top, bottom) != (0, h) else img


def gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    w, h = size
    strip = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        strip.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return strip.resize((w, h))


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def fit_tile(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale to fill the tile; when the aspect ratio differs, show the whole image over a
    blurred, darkened copy of itself instead of cropping the figure."""
    w, h = size
    src_ratio, dst_ratio = img.width / img.height, w / h
    if abs(src_ratio - dst_ratio) / dst_ratio < 0.03:
        return img.resize((w, h), Image.LANCZOS)
    # background: cover + blur
    scale = max(w / img.width, h / img.height)
    bg = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    bg = bg.crop(((bg.width - w) // 2, (bg.height - h) // 2, (bg.width - w) // 2 + w, (bg.height - h) // 2 + h))
    bg = bg.filter(ImageFilter.GaussianBlur(26))
    bg = Image.blend(bg, Image.new("RGB", (w, h), (0, 0, 0)), 0.35)
    # foreground: contain
    scale = min(w / img.width, h / img.height)
    fg = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
    return bg


def paste_card(canvas: Image.Image, tile: Image.Image, xy: tuple[int, int], radius: int) -> None:
    """Paste a rounded tile with a soft drop shadow."""
    x, y = xy
    w, h = tile.size
    pad = 60
    shadow = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + 14, pad + w, pad + h + 14), radius=radius, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    canvas.alpha_composite(shadow, (x - pad, y - pad))
    card = Image.new("RGBA", (w, h))
    card.paste(tile, (0, 0))
    card.putalpha(rounded_mask((w, h), radius))
    canvas.alpha_composite(card, (x, y))


def paste_rgba(canvas: Image.Image, layer: Image.Image, xy: tuple[int, int]) -> None:
    """Paste an RGBA layer (any shape, e.g. a rotated card) with a shadow taken from its alpha."""
    x, y = xy
    pad = 60
    shadow = Image.new("RGBA", (layer.width + 2 * pad, layer.height + 2 * pad), (0, 0, 0, 0))
    silhouette = Image.new("RGBA", layer.size, (0, 0, 0, 150))
    silhouette.putalpha(layer.getchannel("A").point(lambda a: a * 150 // 255))
    shadow.alpha_composite(silhouette, (pad, pad + 14))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)), (x - pad, y - pad))
    canvas.alpha_composite(layer, (x, y))


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line] if line else lines


def paper_note(size: tuple[int, int], name: str, book: str, details: list[str], angle: float) -> Image.Image:
    """A cream index card with the character's researched details, slightly rotated."""
    w, h = size
    card = Image.new("RGBA", (w, h), PAPER + (255,))
    grain = Image.effect_noise((w, h), 22).convert("RGBA")
    grain.putalpha(18)
    card.alpha_composite(grain)
    draw = ImageDraw.Draw(card)
    px, inner = 38, w - 76
    label = find_font(BOLD_CANDIDATES, 21)
    draw.text((px, 30), "R E S E A R C H   N O T E S", font=label, fill=PAPER_MUTED)
    y = 70
    for line in wrap(draw, name, find_font(SERIF_BOLD, 46), inner):
        draw.text((px, y), line, font=find_font(SERIF_BOLD, 46), fill=PAPER_INK)
        y += 50
    italic = find_font(SERIF_ITALIC, 28)
    for line in wrap(draw, book, italic, inner):
        draw.text((px, y + 2), line, font=italic, fill=PAPER_MUTED)
        y += 33
    y += 16
    draw.line((px, y, w - px, y), fill=PAPER_MUTED + (120,), width=2)
    y += 20
    body = find_font(SERIF_REG, 31)
    for detail in details:
        for i, line in enumerate(wrap(draw, detail, body, inner - 30)):
            if i == 0:
                draw.text((px, y), "–", font=body, fill=ACCENT_INK)
            draw.text((px + 30, y), line, font=body, fill=PAPER_INK)
            y += 37
        y += 7
    card.putalpha(rounded_mask((w, h), 10))
    return card.rotate(angle, resample=Image.BICUBIC, expand=True)


def arrow_down(draw: ImageDraw.ImageDraw, x: int, y0: int, y1: int) -> None:
    """Dashed accent arrow from y0 down to y1."""
    y = y0
    while y < y1 - 34:
        draw.line((x, y, x, min(y + 14, y1 - 34)), fill=ACCENT, width=6)
        y += 26
    draw.polygon([(x - 18, y1 - 34), (x + 18, y1 - 34), (x, y1)], fill=ACCENT)


def pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
    font = find_font(BOLD_CANDIDATES, 24)
    x, y = xy
    tw = draw.textlength(text, font=font)
    draw.rounded_rectangle((x, y, x + tw + 32, y + 42), radius=21, fill=(12, 16, 28, 200))
    draw.text((x + 16, y + 7), text, font=font, fill=INK)


def caption(draw: ImageDraw.ImageDraw, xy: tuple[int, int], name: str, sub: str, width: int) -> None:
    x, y = xy
    draw.text((x, y), name, font=find_font(BOLD_CANDIDATES, 34), fill=INK)
    draw.text((x, y + 44), sub, font=find_font(REG_CANDIDATES, 26), fill=INK_MUTED)


def finish(canvas: Image.Image, out: Path, out_width: int | None = None) -> None:
    factor = canvas.width / out_width if out_width else SCALE
    final = canvas.convert("RGB").resize((round(canvas.width / factor), round(canvas.height / factor)), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    final.save(out, "JPEG", quality=86, optimize=True, progressive=True)
    print(f"wrote {out} ({final.width}x{final.height}, {out.stat().st_size // 1024} KB)")


# ----------------------------------------------------------------------------------------

def build_banner(
    out: Path,
    size: tuple[int, int] = (2400, 900),
    title_top: int = 62,
    tile_size: tuple[int, int] = (300, 450),
    tiles_top: int = 388,
    out_width: int | None = None,
    text_scale: float = 1.0,
) -> None:
    """Title block plus a staggered lineup of anchor portraits. The defaults give the README
    hero (1600x600); ``build_social`` reuses it for GitHub's 2:1 social preview."""
    W, H = size
    canvas = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    # warm glow behind the title
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-300, title_top - 560, 1300, title_top + 440), fill=ACCENT + (46,))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(160)))

    draw = ImageDraw.Draw(canvas)
    s = text_scale
    draw.text((92, title_top), "Once Upon a Time", font=find_font(BOLD_CANDIDATES, round(118 * s)), fill=INK,
              stroke_width=3, stroke_fill=INK)
    draw.text((98, title_top + round(150 * s)), "Turn any story into a consistent, illustrated cast.",
              font=find_font(REG_CANDIDATES, round(44 * s)), fill=INK_SOFT)
    draw.text((98, title_top + round(210 * s)), "Book title  ·  researched cast  ·  anchor portraits  ·  presentation sheets  ·  eight styles",
              font=find_font(REG_CANDIDATES, round(29 * s)), fill=INK_MUTED)

    tiles = [t for t in (load(p) for p in BANNER_SOURCES) if t is not None]
    (tw, th), gap = tile_size, 28
    total = len(tiles) * tw + (len(tiles) - 1) * gap
    x = (W - total) // 2
    for i, img in enumerate(tiles):
        y = tiles_top + (-22 if i % 2 == 0 else 22)
        paste_card(canvas, fit_tile(img, (tw, th)), (x, y), radius=26)
        x += tw + gap
    finish(canvas, out, out_width)


def build_social(out: Path) -> None:
    """GitHub social preview (repository Settings > Social preview): 1280x640, 2:1."""
    build_banner(out, size=(2560, 1280), title_top=130, tile_size=(320, 480), tiles_top=600,
                 out_width=1280, text_scale=1.25)


def build_cast_gallery(out: Path) -> None:
    cols, margin, gap = 4, 48, 32
    W = 2400
    tw = (W - 2 * margin - (cols - 1) * gap) // cols
    th = round(tw * 1.5)
    band = 100
    rows = -(-len(CAST_SOURCES) // cols)
    H = 2 * margin + rows * (th + band) + (rows - 1) * gap
    canvas = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    for i, (path, name, sub) in enumerate(CAST_SOURCES):
        img = load(path)
        if img is None:
            continue
        x = margin + (i % cols) * (tw + gap)
        y = margin + (i // cols) * (th + band + gap)
        paste_card(canvas, fit_tile(img, (tw, th)), (x, y), radius=24)
        caption(draw, (x + 6, y + th + 18), name, sub, tw)
    finish(canvas, out)


def build_locations(out: Path) -> None:
    margin, gap = 48, 32
    W = 2400
    tw = (W - 2 * margin - 2 * gap) // 3
    th = round(tw * 9 / 16)
    band = 100
    H = 2 * margin + th + band
    canvas = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    for i, (path, name, sub) in enumerate(LOCATION_SOURCES):
        img = load(path)
        if img is None:
            continue
        # cover-crop wide shots to 16:9 (they are generated close to it)
        scale = max(tw / img.width, th / img.height)
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        img = img.crop(((img.width - tw) // 2, (img.height - th) // 2, (img.width - tw) // 2 + tw, (img.height - th) // 2 + th))
        x = margin + i * (tw + gap)
        paste_card(canvas, img, (x, margin), radius=24)
        caption(draw, (x + 6, margin + th + 18), name, sub, tw)
    finish(canvas, out)


def build_page_to_portrait(out: Path) -> None:
    """Researched details on paper, an arrow, and the anchor portrait drawn from them."""
    cols, margin, gap, W = len(PAGE_SOURCES), 56, 44, 2400
    cw = (W - 2 * margin - (cols - 1) * gap) // cols
    header_h, paper_h, arrow_h = 170, 520, 120
    ph = round(cw * 1.5)
    H = margin + header_h + paper_h + arrow_h + ph + margin
    canvas = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, margin - 4), "From the notes to the portrait", font=find_font(BOLD_CANDIDATES, 60),
              fill=INK, stroke_width=1, stroke_fill=INK)
    draw.text((margin + 2, margin + 80), "What the app's research found about each character, and the anchor portrait it drew from those notes.",
              font=find_font(REG_CANDIDATES, 30), fill=INK_MUTED)
    angles = [-1.6, 1.2, -0.9, 1.5]
    top = margin + header_h
    for i, (path, name, book, style, details) in enumerate(PAGE_SOURCES):
        img = load(path)
        if img is None:
            continue
        x = margin + i * (cw + gap)
        note = paper_note((cw, paper_h), name, book, details, angles[i % len(angles)])
        paste_rgba(canvas, note, (x + (cw - note.width) // 2, top + (paper_h - note.height) // 2))
        arrow_down(draw, x + cw // 2, top + paper_h + 18, top + paper_h + arrow_h - 14)
        py = top + paper_h + arrow_h
        paste_card(canvas, fit_tile(img, (cw, ph)), (x, py), radius=24)
        pill(draw, (x + 18, py + ph - 62), style)
    finish(canvas, out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=D, help="output directory (default docs/images)")
    parser.add_argument("--only", default="banner,cast,locations,social,page", help="comma list of pieces to build")
    args = parser.parse_args()
    pieces = set(args.only.split(","))
    if "page" in pieces:
        build_page_to_portrait(args.out / "page-to-portrait.jpg")
    if "banner" in pieces:
        build_banner(args.out / "banner.jpg")
    if "social" in pieces:
        build_social(args.out / "social-preview.jpg")
    if "cast" in pieces:
        build_cast_gallery(args.out / "cast-gallery.jpg")
    if "locations" in pieces:
        build_locations(args.out / "locations.jpg")


if __name__ == "__main__":
    main()
