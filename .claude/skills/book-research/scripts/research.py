"""Book research done by Claude Code, saved exactly like the app's Gemini research.

Runs inside the app container (it needs the app's Pydantic schemas and save functions), with
the script fed on stdin so nothing has to be mounted:

    S=.claude/skills/book-research/scripts/research.py
    docker compose exec -T app python - prompt-book "<title>" [--author "<author>"]       < $S
    docker compose exec -T app python - new "<project name>" --style <style>              < $S
    docker compose exec -T app python - save-book <slug> --title "<title>" [--author ..] < $S
    docker compose exec -T app python - prompt-character <slug> "<name>"                < $S
    docker compose exec -T app python - save-character <slug> "<name>" [--add]          < $S
    docker compose exec -T app python - plan <slug>                                      < $S
    docker compose exec -T app python - prompt-location <slug> "<name>"                 < $S
    docker compose exec -T app python - save-location <slug> "<name>" [--add]           < $S
    docker compose exec -T app python - check <slug>                                     < $S

prompt-*  print the app's own research and extraction instructions plus the JSON schema to fill,
          so the research follows the same rules as the Gemini pipeline (app/core/research.py).
save-*    validate the draft against app/core/schema.py and persist it with the app's functions
          (ingestion.save_title_research / save_character_research). Drafts are read from
          data/research-drafts/<slug>/: book-notes.md, book.json, book-sources.json for the book;
          <character-slug>-notes.md, <character-slug>.json, <character-slug>-sources.json for a
          character; location-<location-slug>{-notes.md,.json,-sources.json} for a location.
          Sources are a JSON list of {"title": ..., "uri": ...}. --add saves a character or
          location the book research missed (found later by a research agent).
plan      lists the cast and the locations with their draft stems and status, to split the
          deep research between parallel agents (see SKILL.md, "Parallel deep research").
check     validates every draft of a project without saving anything, so the drafts the
          agents wrote can be reviewed before the (sequential) save-* calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.core import ingestion, research
from app.core import projects as store
from app.core.imaging import STYLE_PROMPTS
from app.core.schema import BookExtraction, Character, Location

RESEARCHED_BY = "Claude Code (book-research skill)"
DRAFTS = Path("data/research-drafts")


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def load_project(slug: str) -> dict:
    project = store.load_project(slug)
    if project is None:
        fail(f"no project {slug!r}; create it with: new")
    return project


def read_drafts(slug: str, stem: str) -> tuple[str, dict, list[dict[str, str]]]:
    folder = DRAFTS / slug
    paths = [folder / f"{stem}-notes.md", folder / f"{stem}.json", folder / f"{stem}-sources.json"]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        fail("missing draft files: " + ", ".join(missing))
    notes = paths[0].read_text(encoding="utf-8").strip()
    data = json.loads(paths[1].read_text(encoding="utf-8"))
    sources = json.loads(paths[2].read_text(encoding="utf-8"))
    if not isinstance(sources, list) or not all({"title", "uri"} <= set(s) for s in sources):
        fail(f"{paths[2]} must be a list of {{'title': ..., 'uri': ...}}")
    if not sources:
        fail("no sources: the research must cite the pages it used")
    return notes, data, sources


def undefined_fields(character: Character) -> list[str]:
    return [k for k, v in character.sheet.model_dump().items() if v == "undefined"]


def cmd_prompt_book(args: argparse.Namespace) -> None:
    author_line = f"Author: {args.author}" if args.author.strip() else "Author: unknown (identify it)"
    print("=== RESEARCH INSTRUCTIONS (app/core/research.py RESEARCH_PROMPT) ===\n")
    print(research.RESEARCH_PROMPT.format(title=args.title.strip(), author_line=author_line))
    print("=== EXTRACTION RULES (EXTRACTION_PROMPT, applied to your notes) ===\n")
    print(research.EXTRACTION_PROMPT.split("RESEARCH NOTES:")[0])
    print("=== book.json MUST VALIDATE AGAINST THIS SCHEMA (BookExtraction) ===\n")
    print(json.dumps(BookExtraction.model_json_schema(), indent=1))


def cmd_new(args: argparse.Namespace) -> None:
    if args.style not in STYLE_PROMPTS:
        fail(f"unknown style {args.style!r}; one of {sorted(STYLE_PROMPTS)}")
    project = store.create_project(args.name, "", args.style)
    (DRAFTS / project["slug"]).mkdir(parents=True, exist_ok=True)
    print(f"created project {project['slug']} (style {args.style}); drafts go in {DRAFTS / project['slug']}/")


def cmd_save_book(args: argparse.Namespace) -> None:
    project = load_project(args.slug)
    notes, data, sources = read_drafts(args.slug, "book")
    extraction = BookExtraction.model_validate(data)
    ingestion.save_title_research(
        project, args.title, args.author, extraction, notes, sources, researched_by=RESEARCHED_BY
    )
    print(
        f"saved {extraction.title!r}: {len(extraction.characters)} characters, "
        f"{len(extraction.locations)} locations, {len(extraction.passages)} passages, {len(sources)} sources"
    )
    for character in extraction.characters:
        if fields := undefined_fields(character):
            print(f"  {character.name}: undefined {', '.join(fields)}")


def find_entity(project: dict, kind: str, name: str, add: bool = False) -> dict:
    """The entity called ``name`` (exact match); with ``add``, a new one when it is missing."""
    for entity in ingestion.load_entities(project, kind):
        if entity["name"] == name:
            if add:
                fail(f"{name!r} is already in {kind}.json; save it without --add")
            return entity
    if add:
        return {"name": name}
    names = ", ".join(e["name"] for e in ingestion.load_entities(project, kind))
    fail(f"no {kind[:-1]} named {name!r} in {project['slug']} (use --add for a new one). Known: {names}")


def find_character(project: dict, name: str, add: bool = False) -> dict:
    return find_entity(project, "characters", name, add)


def location_stem(name: str) -> str:
    # Prefixed: a character and a location may share a name (a ship, a house named after its owner).
    return "location-" + ingestion._slugify(name)


def cmd_prompt_character(args: argparse.Namespace) -> None:
    project = load_project(args.slug)
    character = find_character(project, args.name)
    book = project.get("book") or {}
    author = book.get("author", "")
    author = "" if author == "undefined" else author
    aliases = character.get("aliases") or []
    author_notes = (character.get("notes") or "").strip()
    print("=== RESEARCH INSTRUCTIONS (CHARACTER_RESEARCH_PROMPT) ===\n")
    print(
        research.CHARACTER_RESEARCH_PROMPT.format(
            name=character["name"],
            aliases_line=f" (also known as: {', '.join(aliases)})" if aliases else "",
            title=book.get("title") or project["name"],
            author_line=f" by {author}" if author else "",
            notes_block=research.RESEARCH_NOTES_BLOCK.format(notes=author_notes) if author_notes else "",
        )
    )
    print("=== EXTRACTION RULES (CHARACTER_EXTRACTION_PROMPT) ===\n")
    print(
        research.CHARACTER_EXTRACTION_PROMPT.split("RESEARCH NOTES:")[0].format(
            name=character["name"],
            notes_block=research.EXTRACTION_NOTES_BLOCK.format(notes=author_notes) if author_notes else "",
        )
    )
    print("=== CURRENT ENTRY (from the book research) ===\n")
    print(json.dumps({k: v for k, v in character.items() if k not in ingestion.CHARACTER_LOCAL_KEYS}, indent=1, ensure_ascii=False))
    print(f"\n=== drafts: {DRAFTS / args.slug}/{ingestion._slugify(character['name'])}{{-notes.md,.json,-sources.json}} ===")
    print("=== the .json MUST VALIDATE AGAINST THIS SCHEMA (Character) ===\n")
    print(json.dumps(Character.model_json_schema(), indent=1))


def cmd_save_character(args: argparse.Namespace) -> None:
    project = load_project(args.slug)
    character = find_character(project, args.name, args.add)
    notes, data, sources = read_drafts(args.slug, ingestion._slugify(character["name"]))
    result = Character.model_validate(data)
    updated = ingestion.save_character_research(
        project, character, result, notes, sources, researched_by=RESEARCHED_BY
    )
    fields = undefined_fields(result)
    print(f"saved {updated['name']}" + (f" (undefined: {', '.join(fields)})" if fields else ""))


def cmd_prompt_location(args: argparse.Namespace) -> None:
    project = load_project(args.slug)
    location = find_entity(project, "locations", args.name)
    book = project.get("book") or {}
    author = book.get("author", "")
    author = "" if author == "undefined" else author
    print("=== RESEARCH INSTRUCTIONS (LOCATION_RESEARCH_PROMPT) ===\n")
    print(
        research.LOCATION_RESEARCH_PROMPT.format(
            name=location["name"],
            title=book.get("title") or project["name"],
            author_line=f" by {author}" if author else "",
            description=location.get("description") or "undefined",
        )
    )
    print("=== EXTRACTION RULES (LOCATION_EXTRACTION_PROMPT) ===\n")
    print(research.LOCATION_EXTRACTION_PROMPT.split("RESEARCH NOTES:")[0].format(name=location["name"]))
    print("=== CURRENT ENTRY (from the book research) ===\n")
    print(json.dumps(location, indent=1, ensure_ascii=False))
    print(f"\n=== drafts: {DRAFTS / args.slug}/{location_stem(location['name'])}{{-notes.md,.json,-sources.json}} ===")
    print("=== the .json MUST VALIDATE AGAINST THIS SCHEMA (Location) ===\n")
    print(json.dumps(Location.model_json_schema(), indent=1))


def cmd_save_location(args: argparse.Namespace) -> None:
    project = load_project(args.slug)
    location = find_entity(project, "locations", args.name, args.add)
    notes, data, sources = read_drafts(args.slug, location_stem(location["name"]))
    result = Location.model_validate(data)
    updated = ingestion.save_location_research(
        project, location, result, notes, sources, researched_by=RESEARCHED_BY
    )
    words = len(updated["description"].split())
    print(f"saved {updated['name']} (description: {words} words)")


def cmd_plan(args: argparse.Namespace) -> None:
    project = load_project(args.slug)
    folder = DRAFTS / args.slug
    characters = ingestion.load_entities(project, "characters")
    locations = ingestion.load_entities(project, "locations")
    passages = ingestion.load_entities(project, "passages")
    appearances = {c["name"]: 0 for c in characters}
    scenes = {loc["name"]: 0 for loc in locations}
    for passage in passages:
        for name in passage.get("characters_present") or []:
            if name in appearances:
                appearances[name] += 1
        if passage.get("location") in scenes:
            scenes[passage["location"]] += 1

    def row(entity: dict, stem: str, count: int, extra: str) -> str:
        draft = "draft" if (folder / f"{stem}.json").exists() else "-"
        deep = "deep" if entity.get("deep_researched") else "-"
        return f"  {entity['name'][:44]:44} {stem[:40]:40} {deep:5} {draft:6} {count:3}  {extra[:50]}"

    print(f"{project['name']} ({project['slug']}): {len(characters)} characters, {len(locations)} locations")
    print(f"\nCHARACTERS{'':35} {'draft stem':40} {'deep':5} {'draft':6} {'in#':3}  role")
    for c in sorted(characters, key=lambda c: -appearances[c["name"]]):
        undefined = len(undefined_fields(Character.model_validate(c)))
        role = (c.get("role") or "") + (f"; {undefined} undefined" if undefined else "")
        row_text = row(c, ingestion._slugify(c["name"]), appearances[c["name"]], role)
        print(row_text + ("  [author notes]" if (c.get("notes") or "").strip() else ""))
    print(f"\nLOCATIONS{'':36} {'draft stem':40} {'deep':5} {'draft':6} {'in#':3}  description words")
    for loc in sorted(locations, key=lambda l: -scenes[l["name"]]):
        words = len((loc.get("description") or "").split())
        print(row(loc, location_stem(loc["name"]), scenes[loc["name"]], f"{words} words"))
    print("\nin# = passages the entity appears in. Sorted by it: the top of each list is the main cast.")


def cmd_check(args: argparse.Namespace) -> None:
    """Validate every character / location draft without saving."""
    project = load_project(args.slug)
    folder = DRAFTS / args.slug
    if not folder.is_dir():
        fail(f"no drafts folder {folder}")
    characters = {ingestion._slugify(c["name"]): c["name"] for c in ingestion.load_entities(project, "characters")}
    locations = {location_stem(l["name"]): l["name"] for l in ingestion.load_entities(project, "locations")}
    problems = 0
    alias_owner: dict[str, str] = {}
    for path in sorted(folder.glob("*.json")):
        stem = path.stem
        if stem == "book" or stem.endswith("-sources"):
            continue
        is_location = stem.startswith("location-")
        label = f"{'location ' if is_location else 'character'} {stem}"
        missing = [s for s in (f"{stem}-notes.md", f"{stem}-sources.json") if not (folder / s).exists()]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entity = (Location if is_location else Character).model_validate(data)
        except Exception as exc:  # noqa: BLE001 - report every invalid draft, not only the first
            print(f"  INVALID  {label}: {str(exc).splitlines()[0]}")
            problems += 1
            continue
        known = (locations if is_location else characters).get(stem)
        notes = []
        blocking = False
        if missing:
            notes.append("missing " + ", ".join(missing))
            blocking = True
        else:
            sources = json.loads((folder / f"{stem}-sources.json").read_text(encoding="utf-8"))
            notes.append(f"{len(sources)} sources")
            blocking = not sources
        problems += blocking
        if known is None:
            notes.append(f"NEW {entity.name!r}: save with --add, or merge it into an existing entry")
        elif entity.name != known:
            notes.append(f"name {entity.name!r} != {known!r} (the canonical name is kept on save)")
        if is_location:
            words = len(entity.description.split())
            if not 40 <= words <= 140:
                notes.append(f"description {words} words (aim for 50-120)")
        else:
            if fields := undefined_fields(entity):
                notes.append("undefined " + ", ".join(fields))
            for alias in [entity.name, *entity.aliases]:
                owner = alias_owner.setdefault(alias.lower(), entity.name)
                if owner != entity.name:
                    notes.append(f"alias {alias!r} also used by {owner!r}: same person?")
        print(f"  {'BLOCKED' if blocking else 'ok':8} {label}: " + "; ".join(notes))
    print(f"\n{problems} blocking problem(s)" if problems else "\nall drafts valid")


def main() -> None:
    parser = argparse.ArgumentParser(prog="research.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prompt-book")
    p.add_argument("title")
    p.add_argument("--author", default="")
    p = sub.add_parser("new")
    p.add_argument("name")
    p.add_argument("--style", required=True)
    p = sub.add_parser("save-book")
    p.add_argument("slug")
    p.add_argument("--title", required=True)
    p.add_argument("--author", default="")
    for name in ("prompt-character", "save-character", "prompt-location", "save-location"):
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.add_argument("name")
        if name.startswith("save-"):
            p.add_argument("--add", action="store_true", help="the entity is new: append it")
    for name in ("plan", "check"):
        sub.add_parser(name).add_argument("slug")
    args = parser.parse_args()
    {
        "prompt-book": cmd_prompt_book,
        "new": cmd_new,
        "save-book": cmd_save_book,
        "prompt-character": cmd_prompt_character,
        "save-character": cmd_save_character,
        "prompt-location": cmd_prompt_location,
        "save-location": cmd_save_location,
        "plan": cmd_plan,
        "check": cmd_check,
    }[args.command](args)


if __name__ == "__main__":
    main()
