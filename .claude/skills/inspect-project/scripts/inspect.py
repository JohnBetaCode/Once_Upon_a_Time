"""Audit the on-disk state of Once Upon a Time projects (projects/<slug>/).

Usage:
    python inspect.py                      # one line per project
    python inspect.py <slug>               # full audit of one project
    python inspect.py <slug> --json        # machine-readable
    python inspect.py <slug> --show-character "The Fox"   # dump one character's JSON + research notes path

The audit reports, per character: anchor / sheet / research presence, deep-research flag,
a stale sheet (anchor newer than sheet), and "undefined" sheet fields. Per location: image
and sheet presence. Plus orphaned PNGs that no current entity maps to (left behind after a
rename or re-research) and passages that reference characters not in characters.json.

Stdlib only: imports app.core.projects but not the Gemini modules.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from app.core import projects as store  # noqa: E402

UNDEFINED = "undefined"


def slugify(name: str) -> str:
    # Mirrors app.core.imaging._slugify (not imported: that module pulls in google-genai).
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unnamed"


def load(root: Path, kind: str) -> list[dict]:
    path = root / kind / f"{kind}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def audit(project: dict) -> dict:
    root = store.project_path(project["slug"])
    characters = load(root, "characters")
    locations = load(root, "locations")
    passages = load(root, "passages")

    expected: set[Path] = set()
    char_rows = []
    for c in characters:
        d = root / "characters" / slugify(c["name"])
        anchor, sheet, notes = d / "anchor.png", d / "sheet.png", d / "research.md"
        expected.update({anchor, sheet})
        undefined = [k for k, v in (c.get("sheet") or {}).items() if v == UNDEFINED]
        if c.get("physical_description", UNDEFINED) == UNDEFINED:
            undefined.append("physical_description")
        char_rows.append({
            "name": c["name"],
            "role": c.get("role", UNDEFINED),
            "anchor": anchor.exists(),
            "sheet": sheet.exists(),
            "stale_sheet": anchor.exists() and sheet.exists() and anchor.stat().st_mtime > sheet.stat().st_mtime,
            "deep_researched": bool(c.get("deep_researched")),
            "research_notes": notes.exists(),
            "author_notes": bool(c.get("notes")),
            "undefined_fields": undefined,
        })

    loc_rows = []
    for loc in locations:
        base = root / "locations" / slugify(loc["name"])
        image, sheet = base.with_suffix(".png"), base.parent / f"{base.name}-sheet.png"
        expected.update({image, sheet})
        loc_rows.append({"name": loc["name"], "image": image.exists(), "sheet": sheet.exists()})

    known = {c["name"] for c in characters}
    dangling = []
    for p in passages:
        missing = [n for n in (p.get("characters_present") or []) if n not in known]
        if missing:
            dangling.append({"passage": p["title"], "unknown_characters": missing})

    pngs = {p for p in root.rglob("*.png")}
    orphans = sorted(str(p.relative_to(root)) for p in pngs - expected)

    return {
        "slug": project["slug"],
        "name": project["name"],
        "status": project.get("status"),
        "style": project.get("style"),
        "source": (project.get("source") or {}).get("type"),
        "book": (project.get("book") or {}).get("title"),
        "counts": {
            "characters": len(characters),
            "locations": len(locations),
            "passages": len(passages),
            "images": len(pngs),
        },
        "characters": char_rows,
        "locations": loc_rows,
        "passages_with_unknown_characters": dangling,
        "orphan_images": orphans,
        "research_notes": (root / "source" / "research.md").exists(),
    }


def mark(b: bool) -> str:
    return "yes" if b else "-"


def print_audit(a: dict) -> None:
    c = a["counts"]
    print(f"{a['name']}  [{a['slug']}]")
    print(f"  status={a['status']}  style={a['style']}  source={a['source']}  book={a['book']!r}")
    print(f"  {c['characters']} characters, {c['locations']} locations, {c['passages']} passages, {c['images']} PNGs"
          f"  book research notes: {mark(a['research_notes'])}")
    if a["characters"]:
        print("\n  Characters:")
        print(f"  {'name':34} {'anchor':6} {'sheet':6} {'stale':6} {'deep':5} {'notes':5} {'author':6} undefined fields")
        for r in a["characters"]:
            print(f"  {r['name'][:34]:34} {mark(r['anchor']):6} {mark(r['sheet']):6} {mark(r['stale_sheet']):6} "
                  f"{mark(r['deep_researched']):5} {mark(r['research_notes']):5} {mark(r['author_notes']):6} {', '.join(r['undefined_fields']) or '-'}")
    if a["locations"]:
        print("\n  Locations:")
        for r in a["locations"]:
            print(f"  {r['name'][:50]:50} image={mark(r['image']):4} sheet={mark(r['sheet'])}")
    if a["passages_with_unknown_characters"]:
        print("\n  Passages referencing characters not in characters.json:")
        for d in a["passages_with_unknown_characters"]:
            print(f"  - {d['passage']}: {', '.join(d['unknown_characters'])}")
    if a["orphan_images"]:
        print("\n  Orphan images (no current entity maps to them):")
        for o in a["orphan_images"]:
            print(f"  - {o}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-character", default=None)
    args = ap.parse_args()

    if not args.slug:
        rows = [audit(p) for p in store.list_projects()]
        if args.json:
            print(json.dumps(rows, indent=2))
            return
        if not rows:
            print(f"No projects under {store.PROJECTS_DIR}")
            return
        for a in rows:
            c = a["counts"]
            anchors = sum(r["anchor"] for r in a["characters"])
            sheets = sum(r["sheet"] for r in a["characters"])
            print(f"{a['slug']:28} {a['status']:10} {a['style']:10} src={a['source'] or '-':6} "
                  f"chars={c['characters']:3} (anchors {anchors}, sheets {sheets})  locs={c['locations']:3}  "
                  f"passages={c['passages']:3}  orphans={len(a['orphan_images'])}")
        return

    project = store.load_project(args.slug)
    if project is None:
        sys.exit(f"No project with slug {args.slug!r}. Known: {[p['slug'] for p in store.list_projects()]}")

    if args.show_character:
        root = store.project_path(args.slug)
        for c in load(root, "characters"):
            if c["name"].lower() == args.show_character.lower():
                print(json.dumps(c, indent=2, ensure_ascii=False))
                notes = root / "characters" / slugify(c["name"]) / "research.md"
                print(f"\nresearch notes: {notes if notes.exists() else '(none)'}")
                return
        sys.exit(f"No character named {args.show_character!r}")

    a = audit(project)
    print(json.dumps(a, indent=2, ensure_ascii=False) if args.json else "", end="")
    if not args.json:
        print_audit(a)


if __name__ == "__main__":
    main()
