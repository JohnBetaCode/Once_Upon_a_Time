"""What a project cost to make, by stage, from the usage log.

``data/usage.jsonl`` records every Gemini call and every local image with its project, operation,
model, tokens and estimated cost, but not which image or which research it was. This module
splits a project's entries into stages:

- research: the first web search and extraction are the book research; the rest are per-character
  deep research (the app runs them in that order).
- images: each image_generation entry is matched to the file it produced (the file is written
  right after the call is logged), so it is a portrait, a character sheet, a location shot, a
  location sheet or the cover. Entries with no current file are attempts that were regenerated or
  discarded: they cost too.

Local images cost $0; ``gemini_equivalent`` prices them as Gemini images, at the average cost per
Gemini image in the log, to show what the same book would have cost on Gemini.

Research done by Claude Code (``source.researched_by``) is not in the log; it is reported as an
estimate of tokens from the notes it wrote and the sources it read, without a price (it depends on
the Claude plan).

Stdlib only (like ``usage``), so host scripts can import it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core import usage
from app.core.projects import project_path

# Stage keys, in the order they are reported.
STAGES = {
    "book_research": "Book research",
    "deep_research": "Character deep research",
    "portraits": "Character portraits",
    "character_sheets": "Character sheets",
    "location_shots": "Location shots",
    "location_sheets": "Location sheets",
    "cover": "Cover",
    "discarded": "Regenerated or discarded images",
    "other": "Other",
}

# A Gemini image is about 1120 output tokens; used when the log holds too few Gemini images.
FALLBACK_GEMINI_IMAGE_USD = 1120 * usage.PRICING["gemini-3-pro-image"]["output"] / 1e6
# Claude Code research estimate: tokens read per source page, and characters per token.
TOKENS_PER_SOURCE_PAGE = 4000
CHARS_PER_TOKEN = 4


def _slugify(name: str) -> str:
    # Mirrors imaging._slugify (not imported: imaging pulls in the Gemini SDK).
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unnamed"


def _image_files(root: Path) -> list[tuple[float, str]]:
    """(modification time, stage) of every image file the project currently has."""
    files = []
    for path in root.glob("characters/*/anchor.png"):
        files.append((path.stat().st_mtime, "portraits"))
    for path in root.glob("characters/*/sheet.png"):
        files.append((path.stat().st_mtime, "character_sheets"))
    for path in root.glob("locations/*.png"):
        files.append((path.stat().st_mtime, "location_sheets" if path.name.endswith("-sheet.png") else "location_shots"))
    for path in root.glob("images/cover*.png"):
        files.append((path.stat().st_mtime, "cover"))
    return sorted(files)


def gemini_image_usd(entries: list[dict[str, Any]] | None = None) -> float:
    """Average logged cost of one Gemini image (all projects), or the token-based fallback."""
    entries = usage.load_entries() if entries is None else entries
    gemini = [e for e in entries if e.get("operation") == "image_generation" and str(e.get("model", "")).startswith("gemini")]
    images = sum(int(e.get("images") or 1) for e in gemini)
    if images < 5:
        return FALLBACK_GEMINI_IMAGE_USD
    return sum(float(e.get("cost_usd") or 0) for e in gemini) / images


def _empty() -> dict[str, Any]:
    return {"calls": 0, "images": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "gemini_equivalent_usd": 0.0}


def project_costs(project: dict[str, Any]) -> dict[str, Any]:
    """Cost breakdown of one project: stages, totals and the Claude Code research estimate."""
    slug = project["slug"]
    all_entries = usage.load_entries()
    entries = sorted((e for e in all_entries if e.get("project") == slug), key=lambda e: e.get("ts", ""))
    per_image = gemini_image_usd(all_entries)
    files = _image_files(project_path(slug))
    claimed: set[int] = set()
    stages = {key: _empty() for key in STAGES}
    seen_research = {"web_research": False, "extraction": False}

    for e in entries:
        op = e.get("operation")
        if op in seen_research:
            stage = "deep_research" if seen_research[op] else "book_research"
            seen_research[op] = True
        elif op == "image_generation":
            ts = datetime.fromisoformat(e["ts"]).timestamp()
            # The file is written right after the call is logged (grayscale conversion included):
            # take the closest unclaimed file a few seconds later. An image regenerated since has
            # a newer file, so its old entry stays unmatched.
            near = [(mtime - ts, i) for i, (mtime, _) in enumerate(files) if i not in claimed and 0 <= mtime - ts <= 10]
            match = min(near)[1] if near else None
            if match is None:
                stage = "discarded"
            else:
                claimed.add(match)
                stage = files[match][1]
        else:
            stage = "other"
        s = stages[stage]
        s["calls"] += 1
        s["images"] += int(e.get("images") or 0)
        s["input_tokens"] += int(e.get("input_tokens") or 0)
        s["output_tokens"] += int(e.get("output_tokens") or 0)
        s["cost_usd"] += float(e.get("cost_usd") or 0)
        local_image = op == "image_generation" and str(e.get("model", "")).endswith("-local")
        s["gemini_equivalent_usd"] += per_image * int(e.get("images") or 1) if local_image else float(e.get("cost_usd") or 0)

    rows = [{"stage": key, "label": STAGES[key], **s} for key, s in stages.items() if s["calls"]]
    totals = _empty()
    for row in rows:
        for key in totals:
            totals[key] += row[key]
    unmatched = len(files) - len(claimed)
    return {
        "slug": slug,
        "stages": rows,
        "totals": totals,
        "gemini_image_usd": per_image,
        "images_without_log": unmatched,
        "claude_research": claude_research_estimate(project),
    }


def claude_research_estimate(project: dict[str, Any]) -> dict[str, Any] | None:
    """Rough token estimate of research Claude Code did for the project (not in the usage log).

    Input: the source pages it read, at TOKENS_PER_SOURCE_PAGE each. Output: the notes it wrote,
    twice (the notes, then the JSON extracted from them)."""
    root = project_path(project["slug"])
    notes = []
    if "Claude Code" in str((project.get("source") or {}).get("researched_by", "")):
        notes.append(root / "source" / "research.md")
    for kind in ("characters", "locations"):
        for entity in _load(root / kind / f"{kind}.json"):
            if "Claude Code" in str(entity.get("researched_by", "")):
                notes.append(root / kind / _slugify(entity.get("name", "")) / "research.md")
    notes = [p for p in notes if p.exists()]
    if not notes:
        return None
    text = "".join(p.read_text(encoding="utf-8") for p in notes)
    sources = text.count("](http")
    return {
        "documents": len(notes),
        "sources": sources,
        "input_tokens": sources * TOKENS_PER_SOURCE_PAGE,
        "output_tokens": 2 * len(text) // CHARS_PER_TOKEN,
    }


def _load(path: Path) -> list[dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
