"""Art-director review of a project's illustrations: what to look at, contact sheets, verdicts.

Runs inside the app container (it reads the app's prompts, paths and usage log), with the script
fed on stdin like the book-research script:

    S=.claude/skills/review-illustrations/scripts/review.py
    docker compose exec -T app python - manifest <slug> [--pending] [--kind K] [--name N ...] [--batches N] < $S
    docker compose exec -T app python - contact  <slug> [--kind K] [--pending]                         < $S
    docker compose exec -T app python - record   <slug> <verdicts.json>                                 < $S
    docker compose exec -T app python - summary  <slug>                                                 < $S
    docker compose exec -T app python - regenerate <slug> <anchor|sheet|location|location-sheet> "<name>" [--backend local] < $S

manifest    per image: path, date, the backend that made it (matched in data/usage.jsonl), what it
            must show (form, sheet fields, author's notes, description) and its last verdict.
            --pending leaves out images reviewed "ok" and unchanged since. --batches N splits the
            entities into N groups, one per review agent.
contact     numbered contact sheets (JPEG grids) of anchors, sheets or locations, for a first
            triage and for checking that the style holds across the whole cast.
record      merges a JSON list of verdicts into data/reviews/<slug>/review.json, stamping each
            with the image's current modification time.
summary     what is not "ok", and which reviewed images changed since.
regenerate  backs the current image up to data/reviews/<slug>/replaced/ and generates it again
            with the app's own function (a new random seed on the local backend).

K is one of: anchors, sheets, locations, location-sheets (several allowed, comma-separated).
Verdicts: ok | regenerate (a one-off defect, a new seed should fix it) | notes (the research or
the author's notes are wrong or missing: fix the text, then regenerate) | prompt (the defect
repeats across the project: a prompt change, see the illustration-prompts skill).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("anchors", "sheets", "locations", "location-sheets")
VERDICTS = ("ok", "regenerate", "notes", "prompt")
REVIEWS = Path("data/reviews")
SHEET_FIELDS = ("form", "gender", "species", "age", "build", "hair", "eyes", "skin", "attire", "distinctive_traits")


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="review.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("manifest", "contact"):
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.add_argument("--kind", default=",".join(KINDS))
        p.add_argument("--pending", action="store_true")
        if name == "manifest":
            p.add_argument("--name", action="append", default=[], help="only these entities (exact names)")
            p.add_argument("--batches", type=int, default=1)
    p = sub.add_parser("record")
    p.add_argument("slug")
    p.add_argument("verdicts")
    sub.add_parser("summary").add_argument("slug")
    p = sub.add_parser("regenerate")
    p.add_argument("slug")
    p.add_argument("what", choices=("anchor", "sheet", "location", "location-sheet"))
    p.add_argument("name")
    p.add_argument("--backend", choices=("local", "gemini"), help="override IMAGE_BACKEND for this run")
    return parser.parse_args()


ARGS = parse_args()
if getattr(ARGS, "backend", None):
    # Before the app is imported: config.get_settings() reads the environment on each call.
    os.environ["IMAGE_BACKEND"] = ARGS.backend

from app.core import imaging, ingestion, usage  # noqa: E402
from app.core import projects as store  # noqa: E402


def load_project(slug: str) -> dict:
    project = store.load_project(slug)
    if project is None:
        fail(f"no project {slug!r}")
    return project


def review_file(slug: str) -> Path:
    return REVIEWS / slug / "review.json"


def load_reviews(slug: str) -> dict:
    path = review_file(slug)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(Path.cwd().resolve()))


def kinds(arg: str) -> list[str]:
    chosen = [k.strip() for k in arg.split(",") if k.strip()]
    if bad := [k for k in chosen if k not in KINDS]:
        fail(f"unknown kind {bad}; one of {KINDS}")
    return chosen


def backend_index(slug: str) -> list[tuple[float, str]]:
    """(timestamp, model) of every image generated for the project, oldest first."""
    rows = []
    for entry in usage.load_entries():
        if entry.get("project") == slug and entry.get("operation") == "image_generation":
            try:
                rows.append((datetime.fromisoformat(entry["ts"]).timestamp(), entry.get("model", "?")))
            except (KeyError, ValueError):
                continue
    return sorted(rows)


def made_by(index: list[tuple[float, str]], mtime: float) -> str:
    # Usage is recorded when the image comes back; the file is written right after.
    candidates = [model for ts, model in index if mtime - 60 <= ts <= mtime + 2]
    if not candidates:
        return "unknown backend"
    model = candidates[-1]
    return f"local ({model})" if model.endswith("-local") else f"Gemini ({model})"


def images_of(project: dict, kind_list: list[str]) -> list[dict]:
    """One row per entity: its images of the chosen kinds and what they must show."""
    rows = []
    if {"anchors", "sheets"} & set(kind_list):
        for c in ingestion.load_entities(project, "characters"):
            paths = []
            if "anchors" in kind_list:
                paths.append(("anchor", imaging.character_anchor_path(project, c)))
            if "sheets" in kind_list:
                paths.append(("sheet", imaging.character_sheet_path(project, c)))
            rows.append({"kind": "character", "entity": c, "paths": paths})
    if {"locations", "location-sheets"} & set(kind_list):
        for loc in ingestion.load_entities(project, "locations"):
            paths = []
            if "locations" in kind_list:
                paths.append(("establishing shot", imaging.location_image_path(project, loc)))
            if "location-sheets" in kind_list:
                paths.append(("location sheet", imaging.location_sheet_path(project, loc)))
            rows.append({"kind": "location", "entity": loc, "paths": paths})
    return rows


def is_pending(path: Path, reviews: dict) -> bool:
    if not path.exists():
        return False
    last = reviews.get(rel(path))
    return not (last and last.get("verdict") == "ok" and abs(last.get("mtime", 0) - path.stat().st_mtime) < 1)


def cmd_manifest(args: argparse.Namespace) -> None:
    project = load_project(args.slug)
    reviews = load_reviews(args.slug)
    index = backend_index(args.slug)
    style = project.get("style", "")
    rows = images_of(project, kinds(args.kind))
    if args.name:
        rows = [r for r in rows if r["entity"]["name"] in args.name]
        if missing := set(args.name) - {r["entity"]["name"] for r in rows}:
            fail(f"no entity named {sorted(missing)}")
    if args.pending:
        for r in rows:
            r["paths"] = [(label, p) for label, p in r["paths"] if is_pending(p, reviews)]
        rows = [r for r in rows if r["paths"]]

    print(f"PROJECT {project['name']} ({args.slug})")
    print(f"STYLE {style}: {imaging.STYLE_PROMPTS.get(style, style)}")
    if style in imaging.MONOCHROME_STYLES:
        print("  monochrome style: every image is saved in grayscale; any colour is a defect")
    print(f"{sum(len(r['paths']) for r in rows)} images, {len(rows)} entities\n")

    batches = max(1, min(args.batches, len(rows) or 1))
    size = math.ceil(len(rows) / batches) if rows else 0
    for b in range(batches):
        if batches > 1:
            print(f"==================== BATCH {b + 1}/{batches} ====================\n")
        for r in rows[b * size:(b + 1) * size]:
            print_entity(project, r, reviews, index)


def print_entity(project: dict, row: dict, reviews: dict, index: list[tuple[float, str]]) -> None:
    e = row["entity"]
    if row["kind"] == "character":
        sheet = e.get("sheet") or {}
        plate = "creature plate" if imaging._is_animal(sheet) or imaging.is_non_humanoid(e) else "character plate"
        print(f"## {e['name']}  (character; {e.get('role', 'undefined')})")
        for field in SHEET_FIELDS:
            value = sheet.get(field, "undefined")
            if value and value != "undefined":
                print(f"  {field}: {value}")
        if (notes := (e.get("notes") or "").strip()):
            print(f"  AUTHOR'S NOTES (override everything): {notes}")
    else:
        plate = "location plate"
        print(f"## {e['name']}  (location)")
        print(f"  description: {e.get('description', 'undefined')}")
    for label, path in row["paths"]:
        if not path.exists():
            print(f"  {label}: missing")
            continue
        mtime = path.stat().st_mtime
        when = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        backend = made_by(index, mtime)
        extra = ""
        if label == "sheet":
            anchor = imaging.character_anchor_path(project, e)
            if anchor.exists() and anchor.stat().st_mtime > mtime:
                extra += "  STALE (anchor is newer)"
            extra += f"  [{plate}; " + ("wordless: any text is a defect]" if "local" in backend else "Gemini sheet: short English labels expected]")
        if label == "location sheet":
            extra += "  [" + ("wordless: any text is a defect]" if "local" in backend else "Gemini sheet: short English labels expected]")
        last = reviews.get(rel(path))
        if last:
            changed = abs(last.get("mtime", 0) - mtime) >= 1
            extra += f"  last review: {last['verdict']} {last.get('reviewed_at', '')[:10]}" + (" (image changed since)" if changed else "")
        print(f"  {label}: {rel(path)}  {when}  {backend}{extra}")
    print()


def cmd_contact(args: argparse.Namespace) -> None:
    from PIL import Image, ImageDraw, ImageFont

    project = load_project(args.slug)
    reviews = load_reviews(args.slug)
    out_dir = REVIEWS / args.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    tile, label_h, cols, per_page = 300, 28, 6, 24
    font = ImageFont.load_default(size=16)
    for kind in kinds(args.kind):
        items = []
        for r in images_of(project, [kind]):
            for _, path in r["paths"]:
                if path.exists() and (not args.pending or is_pending(path, reviews)):
                    items.append((r["entity"]["name"], path))
        if not items:
            print(f"{kind}: no images")
            continue
        wide = kind in ("sheets", "locations", "location-sheets")
        tw, th = (tile * 3 // 2, tile) if wide else (tile, tile * 3 // 2)
        pages = math.ceil(len(items) / per_page)
        for page in range(pages):
            chunk = items[page * per_page:(page + 1) * per_page]
            rows = math.ceil(len(chunk) / cols)
            sheet = Image.new("RGB", (cols * tw, rows * (th + label_h)), "white")
            draw = ImageDraw.Draw(sheet)
            for i, (name, path) in enumerate(chunk):
                n = page * per_page + i + 1
                x, y = (i % cols) * tw, (i // cols) * (th + label_h)
                with Image.open(path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((tw - 8, th - 8))
                    sheet.paste(im, (x + (tw - im.width) // 2, y + (th - im.height) // 2))
                draw.text((x + 6, y + th + 4), f"{n}. {name}"[:40], fill="black", font=font)
            dest = out_dir / f"contact-{kind}-{page + 1}.jpg"
            sheet.save(dest, quality=85)
            first = page * per_page + 1
            print(f"{rel(dest)}  ({kind} {first}-{first + len(chunk) - 1} of {len(items)})")
            for i, (name, path) in enumerate(chunk):
                print(f"    {first + i}. {name}: {rel(path)}")


def cmd_record(args: argparse.Namespace) -> None:
    load_project(args.slug)
    verdicts = json.loads(Path(args.verdicts).read_text(encoding="utf-8"))
    if not isinstance(verdicts, list):
        fail("the verdicts file must hold a JSON list")
    reviews = load_reviews(args.slug)
    now = datetime.now(timezone.utc).isoformat()
    for v in verdicts:
        path = Path(v.get("image", ""))
        if v.get("verdict") not in VERDICTS:
            fail(f"{v.get('image')}: verdict must be one of {VERDICTS}")
        if not path.exists():
            fail(f"no image {path}")
        reviews[rel(path)] = {
            "verdict": v["verdict"],
            "defects": v.get("defects", []),
            "action": v.get("action", ""),
            "mtime": path.stat().st_mtime,
            "reviewed_at": now,
        }
    review_file(args.slug).parent.mkdir(parents=True, exist_ok=True)
    review_file(args.slug).write_text(json.dumps(reviews, indent=1, ensure_ascii=False), encoding="utf-8")
    counts = {k: sum(1 for v in verdicts if v["verdict"] == k) for k in VERDICTS}
    print(f"recorded {len(verdicts)} verdicts: " + ", ".join(f"{k} {n}" for k, n in counts.items() if n))


def cmd_summary(args: argparse.Namespace) -> None:
    load_project(args.slug)
    reviews = load_reviews(args.slug)
    if not reviews:
        print("no reviews yet")
        return
    by_verdict: dict[str, list[str]] = {k: [] for k in VERDICTS}
    changed = []
    for image, r in sorted(reviews.items()):
        path = Path(image)
        if path.exists() and abs(path.stat().st_mtime - r.get("mtime", 0)) >= 1:
            changed.append(f"{image} (was {r['verdict']})")
            continue
        line = image
        if r.get("defects"):
            line += ": " + "; ".join(r["defects"])
        if r.get("action"):
            line += f"  -> {r['action']}"
        by_verdict[r["verdict"]].append(line)
    print(f"{len(reviews)} images reviewed; ok {len(by_verdict['ok'])}")
    for verdict in ("prompt", "notes", "regenerate"):
        if by_verdict[verdict]:
            print(f"\n{verdict.upper()} ({len(by_verdict[verdict])})")
            print("\n".join(f"  {line}" for line in by_verdict[verdict]))
    if changed:
        print(f"\nCHANGED SINCE REVIEW, to look at again ({len(changed)})")
        print("\n".join(f"  {line}" for line in changed))


def cmd_regenerate(args: argparse.Namespace) -> None:
    project = load_project(args.slug)
    kind = "characters" if args.what in ("anchor", "sheet") else "locations"
    entity = next((e for e in ingestion.load_entities(project, kind) if e["name"] == args.name), None)
    if entity is None:
        fail(f"no {kind[:-1]} named {args.name!r}")
    path_fn, gen_fn = {
        "anchor": (imaging.character_anchor_path, imaging.generate_character_anchor),
        "sheet": (imaging.character_sheet_path, imaging.generate_character_sheet),
        "location": (imaging.location_image_path, imaging.generate_location_image),
        "location-sheet": (imaging.location_sheet_path, imaging.generate_location_sheet),
    }[args.what]
    dest = path_fn(project, entity)
    if dest.exists():
        backup_dir = REVIEWS / args.slug / "replaced"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(dest.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
        backup = backup_dir / f"{rel(dest).replace('/', '__')[:-4]}-{stamp}.png"
        shutil.copy2(dest, backup)
        print(f"backed up {rel(dest)} -> {rel(backup)}")
    print(f"generating {args.what} of {entity['name']} with {imaging.backend_label()}…", flush=True)
    start = time.monotonic()
    gen_fn(project, entity)
    print(f"wrote {rel(dest)} in {time.monotonic() - start:.0f} s")
    if args.what == "anchor" and imaging.character_sheet_path(project, entity).exists():
        print("the sheet is now stale: review the new anchor, then regenerate the sheet from it")


{
    "manifest": cmd_manifest,
    "contact": cmd_contact,
    "record": cmd_record,
    "summary": cmd_summary,
    "regenerate": cmd_regenerate,
}[ARGS.command](ARGS)
