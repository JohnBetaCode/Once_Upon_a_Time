#!/usr/bin/env python3
"""Side-by-side comparison of Gemini images and the local backend's POC images.

Runs on the host (Pillow only) after compare.py has filled data/poc-local/:

    python3 local_image/side_by_side.py [--out docs/images]

Writes poc-anchors.jpg (Gemini vs local anchor per character, plus the Groucho prompt
A/B) and poc-sheet.jpg (Arthur Dent's presentation sheet: Gemini, local 1K, local 2K).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PROJECTS, POC = ROOT / "projects", ROOT / "data" / "poc-local"

PAIRS = [  # (slug, character folder, caption)
    ("guia-del-autoestopista-galactico", "arthur-dent", "Arthur Dent · realistic"),
    ("guia-del-autoestopista-galactico", "zaphod-beeblebrox", "Zaphod Beeblebrox · realistic"),
    ("la-guerra-de-los-mundos", "the-martians", "The Martians · cartoon"),
    ("ubik", "glen-runciter", "Glen Runciter · comic"),
    ("suenan-los-androides-con-ovejas-electricas", "rick-deckard", "Rick Deckard · realistic"),
    ("2001-una-odisea-espacial", "moon-watcher", "Moon-Watcher · comic"),
]
GROUCHO = ("suenan-los-androides-con-ovejas-electricas", "groucho")

BG, INK, MUTED, ACCENT = (16, 20, 34), (240, 236, 228), (150, 158, 176), (255, 184, 92)


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    for name in (["Ubuntu-B.ttf", "DejaVuSans-Bold.ttf"] if bold else ["Ubuntu-R.ttf", "DejaVuSans.ttf"]):
        for path in Path("/usr/share/fonts").rglob(name):
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def fit(path: Path, size: tuple[int, int]) -> Image.Image:
    """Contain the image in the tile on a neutral backdrop (no cropping: we compare whole images)."""
    tile = Image.new("RGB", size, (40, 44, 58))
    if not path.exists():
        ImageDraw.Draw(tile).text((20, size[1] // 2), "missing", font=font(False, 28), fill=MUTED)
        return tile
    img = Image.open(path).convert("RGB")
    scale = min(size[0] / img.width, size[1] / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    tile.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
    return tile


def save(canvas: Image.Image, out: Path, max_width: int = 1600) -> None:
    """Save as a progressive JPEG no wider than the docs images."""
    if canvas.width > max_width:
        canvas = canvas.resize((max_width, round(canvas.height * max_width / canvas.width)), Image.LANCZOS)
    canvas.save(out, "JPEG", quality=86, optimize=True, progressive=True)
    print(f"wrote {out} ({canvas.width}x{canvas.height}, {out.stat().st_size // 1024} KB)")


def anchors(out: Path) -> None:
    tw, th, gap, pad, cols = 420, 630, 14, 40, 3
    pair_w = 2 * tw + gap
    head, cap = 110, 64
    rows = -(-(len(PAIRS) + 2) // cols)
    W = 2 * pad + cols * pair_w + (cols - 1) * 3 * gap
    H = pad + head + rows * (th + cap + 3 * gap) + pad
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    d.text((pad, pad - 6), "Gemini (Nano Banana Pro) vs Qwen-Image-2.1 on the local GPU", font=font(True, 40), fill=INK)
    d.text((pad, pad + 46), "Same character data. Left of each pair: the app's Gemini anchor. Right: the local model, adapted prompt, seed 1234.",
           font=font(False, 24), fill=MUTED)
    cells = [(PROJECTS / s / "characters" / c / "anchor.png", POC / s / c / "anchor-local.png", caption, ("Gemini", "Local"))
             for s, c, caption in PAIRS]
    s, c = GROUCHO
    cells.append((POC / s / c / "anchor-local-gemini-prompt.png", POC / s / c / "anchor-local.png",
                  "Groucho the goat · local, Gemini prompt vs adapted", ("Gemini prompt", "Adapted")))
    cells.append((POC / s / c / "anchor-local.png", POC / s / c / "anchor-local-cfg.png",
                  "Groucho · adapted, without vs with negative prompt", ("No guidance", "Negative + CFG 4")))
    for i, (left, right, caption, tags) in enumerate(cells):
        x = pad + (i % cols) * (pair_w + 3 * gap)
        y = pad + head + (i // cols) * (th + cap + 3 * gap)
        for j, (path, tag) in enumerate(((left, tags[0]), (right, tags[1]))):
            tx = x + j * (tw + gap)
            canvas.paste(fit(path, (tw, th)), (tx, y))
            f = font(True, 22)
            w = d.textlength(tag, font=f)
            d.rounded_rectangle((tx + 10, y + 10, tx + 30 + w, y + 46), radius=18, fill=(ACCENT if j else (70, 76, 96)))
            d.text((tx + 20, y + 14), tag, font=f, fill=(20, 20, 20) if j else INK)
        d.text((x, y + th + 14), caption, font=font(True, 26), fill=INK)
    save(canvas, out)


def sheet(out: Path) -> None:
    base = "guia-del-autoestopista-galactico"
    cols = [
        (PROJECTS / base / "characters/arthur-dent/sheet.png", "Gemini"),
        (POC / base / "arthur-dent/sheet-local-1k.png", "Local 1K"),
        (POC / base / "arthur-dent/sheet-local.png", "Local 2K"),
    ]
    tw, th, pad, head = 900, 600, 30, 120
    canvas = Image.new("RGB", (3 * tw + 4 * pad, head + th + 2 * pad), BG)
    d = ImageDraw.Draw(canvas)
    d.text((pad, pad - 6), "Presentation sheet from the anchor · Arthur Dent", font=font(True, 36), fill=INK)
    for j, (path, tag) in enumerate(cols):
        x = pad + j * (tw + pad)
        canvas.paste(fit(path, (tw, th)), (x, pad + head))
        f = font(True, 22)
        w = d.textlength(tag, font=f)
        y = pad + head - 48  # above the sheet, so the tag never covers its title block
        d.rounded_rectangle((x, y, x + 20 + w, y + 36), radius=18, fill=(ACCENT if j else (70, 76, 96)))
        d.text((x + 10, y + 4), tag, font=f, fill=(20, 20, 20) if j else INK)
    save(canvas, out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=POC)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    anchors(args.out / "poc-anchors.jpg")
    sheet(args.out / "poc-sheet.jpg")
