"""Image generation for project entities.

Anchor -> reference strategy: each character gets one front-facing anchor
portrait first; every derived shot and passage scene passes the anchor as
a reference image so the character stays visually identical.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.core import gemini, usage
from app.core.projects import project_path

STYLE_PROMPTS = {
    "cartoon": "vibrant modern cartoon style, clean bold outlines, expressive faces, flat colors with soft shading",
    "realistic": "photorealistic digital painting, natural lighting, detailed textures, cinematic composition",
    "retro": "vintage 1950s storybook illustration, muted palette, textured paper grain, classic ink and gouache",
    "anime": "high-quality anime style, cel shading, detailed eyes, dynamic lighting",
    "watercolor": "soft watercolor illustration, gentle washes, visible brush strokes, dreamy atmosphere",
    "comic": "western comic book style, strong inks, halftone shading, dramatic angles",
    "pixel-art": "detailed pixel art, 32-bit era, rich color palette, crisp sprites",
    "noir": "film noir illustration, high-contrast black and white, dramatic shadows, moody atmosphere",
}

CHARACTER_ANCHOR_PROMPT = """\
Character reference image: full body, three-quarter view, standing in a
natural, characterful pose that fits the personality, on a plain neutral
studio background with soft lighting.
Style: {style}.

Character: {name}
{description}
{sheet_lines}

Single character only, whole body visible head to toe, face clearly visible.
No text, no watermark.
"""

CHARACTER_SHEET_PROMPT = """\
A professional character production-design presentation sheet, landscape format,
like a film/animation studio character bible page. Off-white paper background,
clean editorial layout with thin black divider lines and small uppercase section
headers. ALL TEXT IN ENGLISH. Illustration style for every panel: {style}.

The SAME character must appear identical in every panel of the sheet.
Typography must be clean and legible. Keep every text element SHORT — labels
and captions of a few words only, never long paragraphs.

Layout:
- Top-left title block: "{name}" in large bold condensed uppercase, below it
  "{story}" and "{author}" in smaller type.
- Left column: an attribute list with small bold labels, one short line each:
  {attribute_lines}
- Center, section "BODY VIEWS": full-body turnaround of the character standing —
  FRONTAL (facing viewer), 3/4 (turned 45 degrees), PROFILE (strict side view),
  BACK (seen from behind) — labeled under each pose; the four orientations must
  be clearly different, with identical outfit and proportions.
- Below the turnaround: section "COLOR PALETTE" with 5 labeled color swatch
  circles of the character's palette, and a section "SCALE" with a small
  silhouette next to the character and height markings.
- Right column, section "EXPRESSIONS & ATTITUDES": a grid of 8 head-and-shoulders
  portraits with labels NEUTRAL, THOUGHTFUL, WORRIED, DETERMINED, SAD, SURPRISED,
  DOUBTFUL, FIRM.
- Below it, section "DETAILS": 4 close-up panels (face, hands, attire fabric,
  a signature prop or distinctive trait) with short captions.
- Bottom: section "ENVIRONMENT" — one wide cinematic strip of the character in
  their typical setting, with a short caption.
- Footer bar: "{story}" on the left, "CHARACTER PRESENTATION SHEET / PRODUCTION
  DESIGN" on the right.

Character appearance (follow the attached reference image for identity):
{description}
{sheet_lines}
"""

LOCATION_SHEET_PROMPT = """\
A professional environment production-design presentation sheet, landscape
format, like a film/animation studio location bible page. Off-white paper
background, clean editorial layout with thin black divider lines and small
uppercase section headers. ALL TEXT IN ENGLISH. Illustration style for every
panel: {style}.

The SAME location must be depicted consistently in every panel.
Typography must be clean and legible. Keep every text element SHORT — labels
and captions of a few words only, never long paragraphs.

Layout:
- Top-left title block: "{name}" in large bold condensed uppercase, below it
  "{story}" in smaller type, then a short DESCRIPTION caption: {description}
  and a short RELEVANCE note: {relevance}
- Center, section "MAIN VIEW": one large wide establishing shot of the location.
- Right column, section "VIEWS & MOODS": 4 smaller panels — DAY, NIGHT, DETAIL,
  ALTERNATE ANGLE — each labeled.
- Below, section "COLOR PALETTE" with 5 labeled color swatch circles, and a
  section "DETAILS" with 3 close-up panels of characteristic elements, captioned.
- Footer bar: "{story}" on the left, "ENVIRONMENT PRESENTATION SHEET /
  PRODUCTION DESIGN" on the right.

No people in any panel. No watermark.
"""

LOCATION_PROMPT = """\
Establishing shot of a story location, no people.
Style: {style}.

Location: {name}
{description}

Wide composition, rich environmental detail. No text, no watermark.
"""


def _shorten(text: str, max_words: int = 10) -> str:
    words = text.split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unnamed"


def _style_prompt(project: dict[str, Any]) -> str:
    return STYLE_PROMPTS.get(project.get("style", ""), project.get("style", "storybook illustration"))


def character_anchor_path(project: dict[str, Any], character: dict[str, Any]) -> Path:
    return project_path(project["slug"]) / "characters" / _slugify(character["name"]) / "anchor.png"


def location_image_path(project: dict[str, Any], location: dict[str, Any]) -> Path:
    return project_path(project["slug"]) / "locations" / f"{_slugify(location['name'])}.png"


def character_sheet_path(project: dict[str, Any], character: dict[str, Any]) -> Path:
    return project_path(project["slug"]) / "characters" / _slugify(character["name"]) / "sheet.png"


def location_sheet_path(project: dict[str, Any], location: dict[str, Any]) -> Path:
    return project_path(project["slug"]) / "locations" / f"{_slugify(location['name'])}-sheet.png"


def _story_and_author(project: dict[str, Any]) -> tuple[str, str]:
    book = project.get("book") or {}
    story = book.get("title") if book.get("title") not in (None, "", "undefined") else project["name"]
    author = book.get("author") if book.get("author") not in (None, "", "undefined") else ""
    return story, author


def _sheet_fields(character: dict[str, Any]) -> list[tuple[str, str]]:
    sheet = character.get("sheet") or {}
    fields = [("role", character.get("role", ""))] + list(sheet.items())
    return [
        (name.replace("_", " "), value)
        for name, value in fields
        if value and value != "undefined"
    ]


def generate_character_sheet(project: dict[str, Any], character: dict[str, Any]) -> Path:
    """Generate a full production-design presentation sheet for a character.

    The anchor portrait (generated first if missing) is passed as a reference
    image so the sheet keeps the same identity.
    """
    anchor = character_anchor_path(project, character)
    if not anchor.exists():
        generate_character_anchor(project, character)

    description = character.get("physical_description", "")
    if description == "undefined":
        description = ""
    fields = _sheet_fields(character)
    story, author = _story_and_author(project)
    attribute_lines = "; ".join(f"{n.upper()}: {_shorten(v)}" for n, v in fields) or "NAME only"
    prompt = CHARACTER_SHEET_PROMPT.format(
        style=_style_prompt(project),
        name=character["name"].upper(),
        story=story,
        author=author,
        attribute_lines=attribute_lines,
        description=description,
        sheet_lines="\n".join(f"- {n.capitalize()}: {v}" for n, v in fields),
    )
    with usage.project_context(project["slug"]):
        image = gemini.generate_image(
            prompt,
            reference_images=[anchor.read_bytes()],
            aspect_ratio="3:2",
        )
    dest = character_sheet_path(project, character)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(image)
    return dest


def generate_location_sheet(project: dict[str, Any], location: dict[str, Any]) -> Path:
    """Generate a full production-design presentation sheet for a location."""
    description = location.get("description", "")
    if description == "undefined":
        description = ""
    relevance = location.get("relevance", "")
    if relevance == "undefined":
        relevance = ""
    story, _ = _story_and_author(project)

    reference = location_image_path(project, location)
    references = [reference.read_bytes()] if reference.exists() else None

    prompt = LOCATION_SHEET_PROMPT.format(
        style=_style_prompt(project),
        name=location["name"].upper(),
        story=story,
        description=_shorten(description, 16),
        relevance=_shorten(relevance, 12),
    )
    with usage.project_context(project["slug"]):
        image = gemini.generate_image(prompt, reference_images=references, aspect_ratio="3:2")
    dest = location_sheet_path(project, location)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(image)
    return dest


def generate_character_anchor(project: dict[str, Any], character: dict[str, Any]) -> Path:
    """Generate (or regenerate) a character's front-facing anchor portrait."""
    sheet = character.get("sheet", {})
    sheet_lines = "\n".join(
        f"- {field.replace('_', ' ').capitalize()}: {value}"
        for field, value in sheet.items()
        if value and value != "undefined"
    )
    description = character.get("physical_description", "")
    if description == "undefined":
        description = ""
    prompt = CHARACTER_ANCHOR_PROMPT.format(
        style=_style_prompt(project),
        name=character["name"],
        description=description,
        sheet_lines=sheet_lines,
    )
    with usage.project_context(project["slug"]):
        image = gemini.generate_image(prompt)
    dest = character_anchor_path(project, character)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(image)
    return dest


def generate_location_image(project: dict[str, Any], location: dict[str, Any]) -> Path:
    """Generate (or regenerate) a location's establishing shot."""
    description = location.get("description", "")
    if description == "undefined":
        description = ""
    prompt = LOCATION_PROMPT.format(
        style=_style_prompt(project),
        name=location["name"],
        description=description,
    )
    with usage.project_context(project["slug"]):
        image = gemini.generate_image(prompt)
    dest = location_image_path(project, location)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(image)
    return dest
