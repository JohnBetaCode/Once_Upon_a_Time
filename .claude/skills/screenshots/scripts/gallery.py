#!/usr/bin/env python3
"""Build the images of docs/gallery.md from finished projects.

    python3 .claude/skills/screenshots/scripts/gallery.py --out /tmp/gallery   # preview
    python3 .claude/skills/screenshots/scripts/gallery.py                      # writes docs/images/

For every book in BOOKS it writes two JPEGs:
  gallery-<key>-cast.jpg   up to twelve anchor portraits, 6 x 2, each fitted on a paper card
  gallery-<key>-world.jpg  one presentation sheet beside one establishing shot

Images are taken as they are (no captions: docs/gallery.md names the book and the style).
Missing files are skipped with a warning. Needs Pillow on the host (stdlib otherwise).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[4]
P = ROOT / "projects"
D = ROOT / "docs" / "images"

BG = (24, 22, 20)
CARD = (243, 239, 230)
GAP = 14
TILE = (260, 390)  # 2:3, the anchor canvas
WORLD_HEIGHT = 560
WIDTH = 1600  # final width of every image

# key -> (project slug, portraits, sheet (character slug or location sheet path), location shot)
BOOKS: dict[str, tuple[str, list[str], str, str]] = {
    "2001": (
        "2001-una-odisea-espacial",
        ["moon-watcher", "dr-david-bowman", "hal-9000", "dr-heywood-r-floyd", "dr-frank-poole",
         "the-weaver-the-entity", "one-ear", "dr-dimitri-moisevitch", "miss-simmons", "diana-halvorsen",
         "dr-sivasubramanian-chandrasegarampillai", "ralph-halvorsen"],
        "characters/hal-9000/sheet.png",
        "locations/japetus-iapetus-moon-of-saturn.png",
    ),
    "hitchhikers-guide": (
        "guia-del-autoestopista-galactico",
        ["arthur-dent", "ford-prefect", "zaphod-beeblebrox", "tricia-mcmillan-trillian",
         "marvin-the-paranoid-android", "prostetnic-vogon-jeltz", "slartibartfast", "deep-thought",
         "eddie-the-shipboard-computer", "lunkwill-and-fook", "mr-l-prosser", "benjy-mouse-and-frankie-mouse"],
        "characters/arthur-dent/sheet.png",
        "locations/the-starship-heart-of-gold.png",
    ),
    "androids": (
        "suenan-los-androides-con-ovejas-electricas",
        ["rachael-rosen", "john-r-isidore", "pris-stratton", "roy-baty", "luba-luft", "wilbur-mercer",
         "buster-friendly", "iran-deckard", "garland", "horace", "groucho", "the-spider"],
        "characters/horace/sheet.png",
        "locations/deckard-s-apartment-building-roof-pasture.png",
    ),
    "deaths-end": (
        "el-fin-de-la-muerte",
        ["cheng-xin", "yun-tianming", "thomas-wade", "luo-ji", "sophon", "ai-aa", "guan-yifan",
         "fraisse", "constantine-xi-palaiologos", "helena", "singer", "the-elder"],
        "characters/cheng-xin/sheet.png",
        "locations/constantinople-the-magic-minaret-may-1453-c-e.png",
    ),
    "war-of-the-worlds": (
        "la-guerra-de-los-mundos",
        ["the-narrator", "the-narrator-s-brother", "the-artilleryman", "miss-elphinstone", "ogilvy",
         "the-curate", "mrs-elphinstone", "lord-hilton", "henderson", "stent", "marshall", "the-martians"],
        "characters/the-martians/sheet.png",
        "locations/primrose-hill-regent-s-park-london.png",
    ),
    "ubik": (
        "ubik",
        ["joe-chip", "glen-runciter", "ella-runciter", "pat-conley", "jory-miller",
         "herbert-schoenheit-von-vogelsang", "raymond-ray-hollis", "stanton-mick", "zoe-wirt", "g-g-ashwood",
         "wendy-wright", "mrs-frick"],
        "characters/glen-runciter/sheet.png",
        "locations/runciter-associates-headquarters-new-york-city.png",
    ),
    "one-hundred-years": (
        "cien-a-os-de-soledad",
        ["jos-arcadio-buend-a", "rsula-iguar-n", "colonel-aureliano-buend-a", "amaranta",
         "remedios-moscote", "pilar-ternera", "pietro-crespi", "aureliano-segundo", "fernanda-del-carpio",
         "the-17-aurelianos", "gaston", "melqu-ades"],
        "characters/rsula-iguar-n/sheet.png",
        "locations/the-buend-a-family-residence.png",
    ),
}


def load(path: Path) -> Image.Image | None:
    if not path.exists():
        print(f"warning: missing {path.relative_to(ROOT)}", file=sys.stderr)
        return None
    return Image.open(path).convert("RGB")


def card(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """The image scaled to fit inside a paper card of ``size``, centered."""
    tile = Image.new("RGB", size, CARD)
    scale = min(size[0] / img.width, size[1] / img.height)
    fitted = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    tile.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
    return tile


def paste_rounded(canvas: Image.Image, img: Image.Image, xy: tuple[int, int], radius: int = 16) -> None:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    canvas.paste(img, xy, mask)


def save(canvas: Image.Image, out: Path) -> None:
    if canvas.width != WIDTH:
        canvas = canvas.resize((WIDTH, round(canvas.height * WIDTH / canvas.width)), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "JPEG", quality=84, optimize=True, progressive=True)
    print(f"wrote {out}  {canvas.width}x{canvas.height}  {out.stat().st_size // 1024} KB")


def build_cast(slug: str, names: list[str], out: Path) -> None:
    tiles = [img for n in names if (img := load(P / slug / "characters" / n / "anchor.png"))]
    if not tiles:
        return
    cols = 6
    rows = (len(tiles) + cols - 1) // cols
    w, h = TILE
    canvas = Image.new("RGB", (GAP + cols * (w + GAP), GAP + rows * (h + GAP)), BG)
    for i, img in enumerate(tiles):
        paste_rounded(canvas, card(img, TILE), (GAP + (i % cols) * (w + GAP), GAP + (i // cols) * (h + GAP)))
    save(canvas, out)


def build_world(slug: str, sheet: str, location: str, out: Path) -> None:
    images = [img for rel in (sheet, location) if (img := load(P / slug / rel))]
    if not images:
        return
    scaled = [i.resize((round(i.width * WORLD_HEIGHT / i.height), WORLD_HEIGHT), Image.LANCZOS) for i in images]
    canvas = Image.new("RGB", (GAP + sum(i.width + GAP for i in scaled), WORLD_HEIGHT + 2 * GAP), BG)
    x = GAP
    for img in scaled:
        paste_rounded(canvas, img, (x, GAP))
        x += img.width + GAP
    save(canvas, out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=D, help="output directory (default docs/images)")
    parser.add_argument("--only", default=",".join(BOOKS), help="comma list of book keys")
    args = parser.parse_args()
    for key in args.only.split(","):
        slug, names, sheet, location = BOOKS[key]
        build_cast(slug, names, args.out / f"gallery-{key}-cast.jpg")
        build_world(slug, sheet, location, args.out / f"gallery-{key}-world.jpg")


if __name__ == "__main__":
    main()
