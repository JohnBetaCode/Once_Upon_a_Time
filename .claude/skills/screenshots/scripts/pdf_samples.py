#!/usr/bin/env python3
"""Build the PDF sample images for the docs from a built export.

    python3 .claude/skills/screenshots/scripts/pdf_samples.py projects/<slug>/exports/<file>.pdf --out /tmp/pdf-samples   # preview
    python3 .claude/skills/screenshots/scripts/pdf_samples.py projects/<slug>/exports/<file>.pdf                          # writes docs/images/

Produces three JPEGs, 1600 px wide:
  sample-pdf-export.jpg     3x3 montage: cover, story, cast, a character and its sheet,
                            another character, the world, a location, key passages
  sample-pdf-character.jpg  one character page
  sample-pdf-location.jpg   one location page

Pages are found by their text, so the script follows the book wherever its sections land.
Use an export of a fully illustrated project built with presentation sheets. Needs poppler
(`pdftotext`, `pdftoppm`) and Pillow on the host.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
WIDTH = 1600
GAP = 14
BACKGROUND = (232, 233, 236)
PLATE = re.compile(r"presentation sheet")


def find_pages(pdf: Path) -> dict[str, list[int]]:
    """1-based page numbers by role, read from the text of each page."""
    text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    pages = text.split("\f")
    roles: dict[str, list[int]] = {key: [] for key in ("story", "cast", "profile", "sheet", "world", "location", "passages")}
    section = ""
    for number, body in enumerate(pages, start=1):
        if number == 1 or not body.strip():
            continue
        if "The cast" in body and not roles["cast"]:
            roles["cast"].append(number)
            section = "characters"
        elif "The world" in body and not roles["world"]:
            roles["world"].append(number)
            section = "locations"
        elif "Key passages" in body and not roles["passages"]:
            roles["passages"].append(number)
            section = "passages"
        elif "The story" in body and not section:
            roles["story"].append(number)
        elif section == "characters":
            if PLATE.search(body):
                roles["sheet"].append(number)
            # A profile carries its ordinal as a large numeral; continuation pages do not.
            elif re.search(rf"\b{len(roles['profile']) + 1:02d}\b", body):
                roles["profile"].append(number)
        elif section == "locations" and not PLATE.search(body):
            roles["location"].append(number)
    return roles


def render(pdf: Path, page: int, width: int, workdir: Path) -> Image.Image:
    prefix = workdir / f"page-{page}"
    subprocess.run(["pdftoppm", "-r", "150", "-png", "-f", str(page), "-l", str(page), "-singlefile", str(pdf), str(prefix)], check=True)
    image = Image.open(prefix.with_suffix(".png")).convert("RGB")
    return image.resize((width, round(image.height * width / image.width)), Image.Resampling.LANCZOS)


def save(image: Image.Image, path: Path) -> None:
    image.save(path, quality=85, optimize=True, progressive=True)
    print(f"wrote {path}  {image.width}x{image.height}  {path.stat().st_size // 1024} KB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path, help="a PDF built by the app's Export PDF panel")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "images")
    parser.add_argument("--character", type=int, default=3, help="which character page to feature (1 = first)")
    parser.add_argument("--location", type=int, default=2, help="which location page to feature (1 = first)")
    args = parser.parse_args()

    roles = find_pages(args.pdf)
    missing = [key for key in ("story", "cast", "profile", "sheet", "world", "location", "passages") if not roles[key]]
    if missing:
        sys.exit(f"{args.pdf.name} has no page for: {', '.join(missing)}. Export a fully illustrated project with sheets.")

    def pick(key: str, ordinal: int) -> int:
        return roles[key][min(ordinal, len(roles[key])) - 1]

    first_profile = roles["profile"][0]
    character, location = pick("profile", args.character), pick("location", args.location)
    montage = [
        1, roles["story"][0], roles["cast"][0],
        first_profile, next(page for page in roles["sheet"] if page > first_profile), character,
        roles["world"][0], location, roles["passages"][0],
    ]
    print("pages:", {"montage": montage, "character": character, "location": location})

    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        tile_w = (WIDTH - GAP * 4) // 3
        tiles = [render(args.pdf, page, tile_w, workdir) for page in montage]
        tile_h = tiles[0].height
        sheet = Image.new("RGB", (WIDTH, 3 * tile_h + 4 * GAP), BACKGROUND)
        for index, tile in enumerate(tiles):
            sheet.paste(tile, (GAP + (index % 3) * (tile_w + GAP), GAP + (index // 3) * (tile_h + GAP)))
        save(sheet, args.out / "sample-pdf-export.jpg")
        save(render(args.pdf, character, WIDTH, workdir), args.out / "sample-pdf-character.jpg")
        save(render(args.pdf, location, WIDTH, workdir), args.out / "sample-pdf-location.jpg")


if __name__ == "__main__":
    main()
