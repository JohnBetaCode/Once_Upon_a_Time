"""Book research agent (title-only ingestion).

Two-step pipeline, because Google Search grounding and structured output
cannot be combined in a single Gemini call:

1. **Research** — a web-grounded query gathers everything known about the
   book: characters with physical descriptions, locations, key passages.
2. **Extraction** — a structured-output call converts the research notes
   into the validated ``BookExtraction`` schema (unknown -> "undefined").
"""

from __future__ import annotations

from app.core import gemini
from app.core.schema import BookExtraction, Character

RESEARCH_PROMPT = """\
You are a literary researcher. Research the book below using web search and
write thorough, factual notes about it. Only include information you can
ground in sources — never invent details.

Book title: {title}
{author_line}

Cover, in this order:
1. The book: full title, author, publication year, genre(s), original
   language, main themes, and a one-paragraph plot summary.
2. CHARACTERS — every named character you can find. For each one: name,
   aliases/nicknames, narrative role, and a COMPLETE visual profile:
   gender, race/species, approximate age, height, build, hair, eyes, skin,
   typical attire, distinctive visual traits. These notes drive
   illustrations, so every field needs a concrete, usable value:
   - Prefer details grounded in the book's text or in well-known
     adaptations (film, TV, cover art).
   - When a detail is documented nowhere, PROPOSE one the way a film
     production designer would: a plausible, coherent choice that fits the
     story's setting, era, culture, and the character's age and role.
   - Never write "unknown" or "no description available" for a visual
     field — always commit to a concrete design.
3. LOCATIONS — every significant place: name, visual description, why it
   matters to the story.
4. KEY PASSAGES — 5 to 12 pivotal moments (introduction, key events,
   climax, ending...). For each: a short title, what happens, which
   characters are present, and where it takes place.

Write the notes in English regardless of the book's original language.
"""

EXTRACTION_PROMPT = """\
Convert the following research notes about a book into the requested JSON
structure. Rules:
- Use the information present in the notes, including proposed/designed
  character appearances — copy those into the character sheet fields.
- Every character sheet field (gender, species, age, height, build, hair,
  eyes, skin, attire, distinctive traits) must carry a concrete value from
  the notes; use the string "undefined" only when the notes truly contain
  nothing for that field.
- Do not add facts that appear nowhere in the notes.
- Keep every character, location, and passage found in the notes.
- Everything in English.

RESEARCH NOTES:
{notes}
"""


CHARACTER_RESEARCH_PROMPT = """\
You are a production-design researcher. Research ONE character in depth using
web search. Character wikis (Fandom and other fan wikis), literature guides
(LitCharts, SparkNotes, CliffsNotes), and adaptation references (film, TV,
cover and interior art) are excellent sources — look for them explicitly.

Character: {name}{aliases_line}
From: {title}{author_line}

Write thorough, factual notes covering:
1. Narrative role, personality, and story arc (brief).
2. PHYSICAL APPEARANCE in maximum detail — gender, race/species, approximate
   age, height, build, hair, eyes, skin, typical attire, and distinctive
   visual traits. This is the priority; the notes drive illustrations.
   - Prefer details grounded in the book's text, wikis, or adaptations.
   - When a detail is documented nowhere, PROPOSE one the way a film
     production designer would: a plausible, coherent choice for the story's
     setting, era, culture, and the character's age and role.
   - Never write "unknown" — always commit to a concrete design.
3. Visually relevant extras: signature props, weapons, symbols, and the
   settings where the character usually appears.

Everything in English.
"""

CHARACTER_EXTRACTION_PROMPT = """\
Convert the following research notes about one character into the requested
JSON structure. Rules:
- Use the information in the notes, including proposed/designed appearance
  details — copy them into the character sheet fields.
- Every sheet field must carry a concrete value from the notes; use the
  string "undefined" only when the notes truly contain nothing for it.
- Keep the character's name exactly as: {name}
- Everything in English.

RESEARCH NOTES:
{notes}
"""


def research_book(title: str, author: str = "") -> tuple[BookExtraction, str, list[dict[str, str]]]:
    """Research a book by title. Returns (extraction, research_notes, sources)."""
    author_line = f"Author: {author}" if author.strip() else "Author: unknown (identify it)"
    notes, sources = gemini.web_research(
        RESEARCH_PROMPT.format(title=title.strip(), author_line=author_line)
    )
    extraction = gemini.extract_structured(EXTRACTION_PROMPT.format(notes=notes), BookExtraction)
    return extraction, notes, sources


def research_character(
    title: str,
    author: str,
    name: str,
    aliases: list[str] | None = None,
) -> tuple[Character, str, list[dict[str, str]]]:
    """Deep-research one character (wikis, guides, adaptations).

    Returns (character, research_notes, sources).
    """
    aliases_line = f" (also known as: {', '.join(aliases)})" if aliases else ""
    author_line = f" by {author}" if author.strip() else ""
    notes, sources = gemini.web_research(
        CHARACTER_RESEARCH_PROMPT.format(
            name=name, aliases_line=aliases_line, title=title, author_line=author_line
        )
    )
    character = gemini.extract_structured(
        CHARACTER_EXTRACTION_PROMPT.format(name=name, notes=notes), Character
    )
    character.name = name  # keep the project's canonical name
    return character, notes, sources
