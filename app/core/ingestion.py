"""Source ingestion.

Three ways to feed a story into a project:

1. Written text — ``save_text_source`` stores it; ``process_text`` (chunked
   extraction) is still a stub.
2. Book title  — ``research_title`` runs the web-grounded research agent
   (``app.core.research``) and persists the validated extraction;
   ``deep_research_character`` enriches one character at a time.
3. PDF         — ``save_pdf_source`` stores the file; ``extract_pdf_text``
   (native text + OCR fallback) is still a stub.

Stubs raise ``NotImplementedError``; the UI catches it and reports that
processing is pending.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import usage
from app.core.projects import project_path, save_project
from app.core.research import research_book, research_character
from app.core.schema import BookExtraction

# ---------------------------------------------------------------------------
# Raw source persistence (implemented)
# ---------------------------------------------------------------------------


def save_text_source(project: dict[str, Any], text: str) -> Path:
    """Save pasted/written story text into the project's source folder."""
    dest = project_path(project["slug"]) / "source" / "story.txt"
    dest.write_text(text, encoding="utf-8")
    project["source"] = {"type": "text", "file": str(dest.name), "chars": len(text)}
    project["status"] = "ingested"
    save_project(project)
    return dest


def save_title_source(project: dict[str, Any], title: str, author: str = "") -> None:
    """Record a book title as the project's source (research-based ingestion)."""
    project["source"] = {"type": "title", "title": title.strip(), "author": author.strip()}
    project["status"] = "ingested"
    save_project(project)


def save_pdf_source(project: dict[str, Any], filename: str, data: bytes) -> Path:
    """Save an uploaded PDF into the project's source folder."""
    safe_name = Path(filename).name or "book.pdf"
    dest = project_path(project["slug"]) / "source" / safe_name
    dest.write_bytes(data)
    project["source"] = {"type": "pdf", "file": safe_name, "bytes": len(data)}
    project["status"] = "ingested"
    save_project(project)
    return dest


# ---------------------------------------------------------------------------
# Extraction persistence
# ---------------------------------------------------------------------------


def save_extraction(project: dict[str, Any], extraction: BookExtraction) -> None:
    """Persist a validated extraction into the project folder."""
    root = project_path(project["slug"])
    data = extraction.model_dump()
    (root / "characters" / "characters.json").write_text(
        json.dumps(data["characters"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (root / "locations" / "locations.json").write_text(
        json.dumps(data["locations"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (root / "passages" / "passages.json").write_text(
        json.dumps(data["passages"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    project["book"] = {
        "title": data["title"],
        "author": data["author"],
        "publication_year": data["publication_year"],
        "genre": data["genre"],
        "original_language": data["original_language"],
        "themes": data["themes"],
        "summary": data["summary"],
    }
    if not project.get("description") and data["summary"] != "undefined":
        summary = data["summary"]
        project["description"] = summary[:177] + "…" if len(summary) > 180 else summary


def load_entities(project: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Load extracted entities ('characters', 'locations', or 'passages')."""
    path = project_path(project["slug"]) / kind / f"{kind}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


# ---------------------------------------------------------------------------
# Per-character deep research
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unnamed"


def character_research_path(project: dict[str, Any], character: dict[str, Any]) -> Path:
    return (
        project_path(project["slug"]) / "characters" / _slugify(character["name"]) / "research.md"
    )


# Keys on a character dict that belong to the user/app, not to the LLM
# extraction, and must survive a re-research.
CHARACTER_LOCAL_KEYS = ("notes", "notes_updated_at")


def _write_characters(project: dict[str, Any], characters: list[dict[str, Any]]) -> None:
    (project_path(project["slug"]) / "characters" / "characters.json").write_text(
        json.dumps(characters, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def update_character(project: dict[str, Any], name: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Merge ``changes`` into the character called ``name`` and persist."""
    characters = load_entities(project, "characters")
    for i, existing in enumerate(characters):
        if existing["name"] == name:
            characters[i] = {**existing, **changes}
            _write_characters(project, characters)
            return characters[i]
    raise KeyError(f"No character named {name!r}")


def save_character_notes(project: dict[str, Any], character: dict[str, Any], notes: str) -> dict[str, Any]:
    """Store the author's corrections for a character.

    The notes are injected, with top priority, into the portrait and sheet
    prompts and into any later deep research of that character.
    """
    return update_character(
        project,
        character["name"],
        {"notes": notes.strip(), "notes_updated_at": datetime.now(timezone.utc).isoformat()},
    )


def deep_research_character(project: dict[str, Any], character: dict[str, Any]) -> dict[str, Any]:
    """Deep-research one character (wikis, guides, adaptations) and merge the
    result into the project's characters.json. Returns the updated character.

    The author's notes, when present, steer the research and are preserved."""
    book = project.get("book") or {}
    title = book.get("title") or (project.get("source") or {}).get("title") or project["name"]
    author = book.get("author") or ""
    if author == "undefined":
        author = ""

    with usage.project_context(project["slug"]):
        result, notes, sources = research_character(
            title,
            author,
            character["name"],
            character.get("aliases") or [],
            author_notes=character.get("notes") or "",
        )

    notes_path = character_research_path(project, character)
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    source_lines = [f"- [{s['title']}]({s['uri']})" for s in sources]
    notes_path.write_text(
        f"# Character research: {character['name']}\n\n{notes}\n\n## Sources\n\n"
        + "\n".join(source_lines),
        encoding="utf-8",
    )

    updated = result.model_dump()
    updated["deep_researched"] = True
    for key in CHARACTER_LOCAL_KEYS:
        if character.get(key):
            updated[key] = character[key]
    characters = load_entities(project, "characters")
    for i, existing in enumerate(characters):
        if existing["name"] == character["name"]:
            characters[i] = updated
            break
    else:
        characters.append(updated)
    _write_characters(project, characters)
    return updated


# ---------------------------------------------------------------------------
# Processing pipeline (stubs — to be implemented)
# ---------------------------------------------------------------------------


def process_text(project: dict[str, Any], text: str) -> None:
    """Process raw story text into characters / locations / passages.

    TODO:
      - Chunk the text with overlap (may exceed the model context window).
      - Run LLM extraction per chunk (Gemini on Vertex, structured output).
      - Consolidate + deduplicate entities across chunks.
      - Validate against the schema (missing fields -> "undefined").
      - Persist results into the project folder.
    """
    raise NotImplementedError("Text processing is not implemented yet.")


def research_title(project: dict[str, Any], title: str, author: str = "") -> BookExtraction:
    """Research a book by title with the web-grounded agent and persist results."""
    with usage.project_context(project["slug"]):
        extraction, notes, sources = research_book(title, author)

    root = project_path(project["slug"])
    source_lines = [f"- [{s['title']}]({s['uri']})" for s in sources]
    (root / "source" / "research.md").write_text(
        f"# Research notes: {title}\n\n{notes}\n\n## Sources\n\n" + "\n".join(source_lines),
        encoding="utf-8",
    )
    save_extraction(project, extraction)

    project["source"] = {
        "type": "title",
        "title": title.strip(),
        "author": author.strip() or extraction.author,
        "sources": sources,
    }
    project["status"] = "extracted"
    save_project(project)
    return extraction


def extract_pdf_text(project: dict[str, Any], pdf_path: Path) -> str:
    """Extract text from a PDF, chapter by chapter.

    TODO:
      - Try native text extraction first (e.g. pymupdf).
      - Fall back to OCR for scanned pages.
      - Detect chapter boundaries and store per-chapter text files.
      - Then feed the result into ``process_text``.
    """
    raise NotImplementedError("PDF text extraction (OCR) is not implemented yet.")
