"""Facts for choosing a project's illustration style, and side-by-side style trials.

Runs inside the app container, with the script fed on stdin:

    S=.claude/skills/recommend-style/scripts/styles.py
    docker compose exec -T app python - catalog [<slug>]                                           < $S
    docker compose exec -T app python - trial <slug> --styles a,b,"<clause>" --backend local [--character N] [--location N] < $S
    docker compose exec -T app python - apply <slug> <style>                                         < $S

catalog  every style key with its clause, how well the local GPU backend renders it, and which
         projects use it; with a slug, also the book's facts (genre, era, themes, summary, main
         cast, places) that the recommendation is judged on.
trial    generates the main character's anchor portrait and a location's establishing shot in
         each style, with the app's own functions and prompts, into data/style-trials/<slug>/,
         never touching the project's images; then a labelled comparison grid. A --styles entry
         that is not a style key is used as a style clause as is, to try a style the app lacks.
apply    sets the project's style (what the sidebar's style selector does) and says how many
         existing images are now in the old style.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

TRIALS = Path("data/style-trials")

# How the local backend (Qwen-Image-2.1) renders each style, from docs/local-gpu-evaluation.md.
LOCAL_NOTES = {
    "cartoon": "drifts to realism on the local backend (no tuning yet)",
    "comic": "tuned (pale blue panel, guidance): ~45 s per portrait",
    "80s-comic": "tuned (yellow panel, guidance): ~45 s per portrait",
    "pencil": "tuned (white paper, guidance) and forced to grayscale",
    "anime": "untested on the local backend",
    "retro": "untested on the local backend",
    "watercolor": "untested on the local backend",
    "pixel-art": "untested on the local backend",
    "noir": "untested on the local backend",
    "realistic": "the local model's natural register: reliable",
}


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="styles.py")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog").add_argument("slug", nargs="?")
    p = sub.add_parser("trial")
    p.add_argument("slug")
    p.add_argument("--styles", required=True, help="comma-separated style keys or style clauses")
    p.add_argument("--backend", required=True, choices=("local", "gemini"))
    p.add_argument("--character", help="exact name; default: the character in most passages")
    p.add_argument("--location", help="exact name; default: the location of most passages")
    p.add_argument("--no-location", action="store_true", help="portraits only")
    p = sub.add_parser("apply")
    p.add_argument("slug")
    p.add_argument("style")
    return parser.parse_args()


ARGS = parse_args()
if getattr(ARGS, "backend", None):
    os.environ["IMAGE_BACKEND"] = ARGS.backend  # before the app reads its settings

from app.core import imaging, ingestion  # noqa: E402
from app.core import projects as store  # noqa: E402


def load_project(slug: str) -> dict:
    project = store.load_project(slug)
    if project is None:
        fail(f"no project {slug!r}")
    return project


def main_entities(project: dict) -> tuple[list[dict], list[dict]]:
    """Characters and locations, most present in the passages first."""
    characters = ingestion.load_entities(project, "characters")
    locations = ingestion.load_entities(project, "locations")
    passages = ingestion.load_entities(project, "passages")
    seen: dict[str, int] = {}
    for p in passages:
        for name in p.get("characters_present") or []:
            seen[name] = seen.get(name, 0) + 1
        seen[p.get("location", "")] = seen.get(p.get("location", ""), 0) + 1
    order = lambda e: -seen.get(e["name"], 0)  # noqa: E731
    return sorted(characters, key=order), sorted(locations, key=order)


def cmd_catalog(args: argparse.Namespace) -> None:
    users: dict[str, list[str]] = {}
    for project in store.list_projects():
        users.setdefault(project.get("style", "?"), []).append(project["slug"])
    print("STYLES (key: clause)\n")
    for key, clause in imaging.STYLE_PROMPTS.items():
        print(f"{key}: {clause}")
        mono = "; black and white only" if key in imaging.MONOCHROME_STYLES else ""
        print(f"    local: {LOCAL_NOTES.get(key, 'untested on the local backend')}{mono}")
        print(f"    used by: {', '.join(users.get(key, [])) or 'no project yet'}\n")
    if not args.slug:
        return
    project = load_project(args.slug)
    book = project.get("book") or {}
    characters, locations = main_entities(project)
    print(f"BOOK  {project['name']} ({args.slug}), current style: {project.get('style')}")
    for key in ("title", "author", "publication_year", "genre", "original_language"):
        print(f"  {key}: {book.get(key, 'undefined')}")
    print(f"  themes: {', '.join(book.get('themes') or []) or 'undefined'}")
    print(f"  summary: {book.get('summary', 'undefined')}")
    print("\nMAIN CAST (most present first)")
    for c in characters[:8]:
        sheet = c.get("sheet") or {}
        print(f"  {c['name']}: {c.get('role', '')}; form {sheet.get('form', 'undefined')}; "
              f"age {sheet.get('age', 'undefined')}; attire {imaging._shorten(sheet.get('attire', ''), 16)}")
    print("\nPLACES (most present first)")
    for loc in locations[:6]:
        print(f"  {loc['name']}: {imaging._shorten(loc.get('description', ''), 30)}")
    images = sum(1 for _ in store.project_path(args.slug).glob("characters/*/*.png")) + sum(
        1 for _ in store.project_path(args.slug).glob("locations/*.png"))
    print(f"\n{images} images already generated in the current style")


def label_for(style: str, index: int) -> str:
    return style if style in imaging.STYLE_PROMPTS else f"custom-{index}"


def cmd_trial(args: argparse.Namespace) -> None:
    project = load_project(args.slug)
    characters, locations = main_entities(project)
    character = next((c for c in characters if c["name"] == args.character), None) if args.character else (characters or [None])[0]
    if character is None:
        fail(f"no character {args.character!r}" if args.character else "the project has no characters yet: research it first")
    location = None
    if not args.no_location:
        location = next((l for l in locations if l["name"] == args.location), None) if args.location else (locations or [None])[0]
        if args.location and location is None:
            fail(f"no location {args.location!r}")
    styles = [s.strip() for s in args.styles.split(",") if s.strip()]
    out = TRIALS / args.slug
    out.mkdir(parents=True, exist_ok=True)
    print(f"backend: {imaging.backend_label()}; character: {character['name']}"
          + (f"; location: {location['name']}" if location else ""), flush=True)

    results = []  # (label, clause, anchor path, location path)
    real_dir = store.PROJECTS_DIR
    for i, style in enumerate(styles, 1):
        label = label_for(style, i)
        trial_project = {**project, "style": style}
        with tempfile.TemporaryDirectory() as tmp:
            # The app's own generate functions write under projects/<slug>/; point them at a
            # scratch folder so the project's images are never touched.
            store.PROJECTS_DIR = Path(tmp)
            try:
                start = time.monotonic()
                anchor = imaging.generate_character_anchor(trial_project, character)
                anchor_dest = out / f"{label}-anchor-{imaging._slugify(character['name'])}.png"
                shutil.copy(anchor, anchor_dest)
                loc_dest = None
                if location:
                    shot = imaging.generate_location_image(trial_project, location)
                    loc_dest = out / f"{label}-location-{imaging._slugify(location['name'])}.png"
                    shutil.copy(shot, loc_dest)
            finally:
                store.PROJECTS_DIR = real_dir
        print(f"  {label}: {anchor_dest}" + (f", {loc_dest}" if loc_dest else "")
              + f"  ({time.monotonic() - start:.0f} s)", flush=True)
        results.append((label, imaging.STYLE_PROMPTS.get(style, style), anchor_dest, loc_dest))
    grid = compare_grid(results, out / "compare.jpg")
    print(f"\ncomparison: {grid}")
    for label, clause, *_ in results:
        if label.startswith("custom"):
            print(f"  {label} = {clause}")


def compare_grid(results: list, dest: Path) -> Path:
    """One column per style: the portrait on top, the location below, the style name as header."""
    from PIL import Image, ImageDraw, ImageFont

    col_w, portrait_h, loc_h, head_h, gap = 420, 630, 240, 36, 8
    has_loc = any(r[3] for r in results)
    height = head_h + portrait_h + (gap + loc_h if has_loc else 0)
    grid = Image.new("RGB", (len(results) * (col_w + gap) - gap, height), "white")
    draw = ImageDraw.Draw(grid)
    font = ImageFont.load_default(size=22)
    for i, (label, _, anchor, loc) in enumerate(results):
        x = i * (col_w + gap)
        draw.text((x + 8, 6), label, fill="black", font=font)
        for path, top, box_h in ((anchor, head_h, portrait_h), (loc, head_h + portrait_h + gap, loc_h)):
            if not path:
                continue
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((col_w, box_h))
                grid.paste(im, (x + (col_w - im.width) // 2, top + (box_h - im.height) // 2))
    grid.save(dest, quality=88)
    return dest


def cmd_apply(args: argparse.Namespace) -> None:
    project = load_project(args.slug)
    if args.style not in imaging.STYLE_PROMPTS:
        fail(f"{args.style!r} is not a style key; add it first (illustration-prompts skill). Keys: {', '.join(imaging.STYLE_PROMPTS)}")
    old = project.get("style")
    project["style"] = args.style
    store.save_project(project)
    root = store.project_path(args.slug)
    images = sum(1 for _ in root.glob("characters/*/*.png")) + sum(1 for _ in root.glob("locations/*.png"))
    print(f"{args.slug}: style {old} -> {args.style}")
    if images and old != args.style:
        print(f"{images} existing images are in the old style: regenerate them (anchors first, then sheets) "
              "for a consistent book")


{"catalog": cmd_catalog, "trial": cmd_trial, "apply": cmd_apply}[ARGS.command](ARGS)
