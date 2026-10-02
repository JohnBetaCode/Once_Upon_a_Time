---
name: inspect-project
description: Inspect and audit the on-disk state of Once Upon a Time projects under projects/<slug>/ (project.json, characters.json, locations.json, passages.json, anchor/sheet PNGs, research notes). Use this whenever the user asks what a project contains, which characters still lack a portrait or presentation sheet, why an image is missing or outdated in the UI, which sheet fields are "undefined", whether research notes exist, or when debugging anything about the pipeline state, entity names, slugs or file paths. Also use it before editing any project JSON by hand.
---

# Inspect a project

All structured state lives on disk; there is no database. Each project is a folder:

```
projects/<slug>/
  project.json                 metadata, status (created > ingested > extracted > illustrated),
                               style, source {type: text|title|pdf, ...}, book {title, author, ...}
  source/story.txt | *.pdf     raw source (text / pdf ingestion)
  source/research.md           web research notes + source links (title ingestion)
  characters/characters.json   list[Character] (see app/core/schema.py); deep_researched flag
  characters/<name-slug>/anchor.png      front-facing anchor portrait (identity reference)
  characters/<name-slug>/sheet.png       production-design presentation sheet
  characters/<name-slug>/research.md     per-character deep research notes
  locations/locations.json     list[Location]
  locations/<name-slug>.png              establishing shot
  locations/<name-slug>-sheet.png        location presentation sheet
  passages/passages.json       list[Passage]; characters_present holds character NAMES
  images/                      reserved, unused
```

File names derive from entity names through the same slug rule the UI uses
(`app/core/imaging._slugify`: lowercase, non-alphanumerics to `-`). Renaming a character
in `characters.json` therefore orphans its images; the audit script flags that.

## Commands

```bash
python .claude/skills/inspect-project/scripts/inspect.py                    # all projects, one line each
python .claude/skills/inspect-project/scripts/inspect.py the-little-prince  # full audit
python .claude/skills/inspect-project/scripts/inspect.py the-little-prince --show-character "The Fox"
python .claude/skills/inspect-project/scripts/inspect.py the-little-prince --json
```

Runs with the host `python3` (stdlib only). `projects/` is bind-mounted into the
container, so the host view is always current.

## Reading the audit

- **anchor / sheet missing**: the UI shows "No portrait yet"; the user generates them from
  the Characters tab or "Generate all missing portraits". Each is one image call (see the
  `usage-report` skill for cost).
- **stale sheet**: the anchor was regenerated after the sheet, so the two may show
  different identities. The UI warns about this; the fix is to regenerate the sheet.
- **undefined fields**: the research could not ground that attribute. The research prompts
  ask the model to propose a production-design choice rather than leave it undefined, so
  many undefined fields on a character usually means the title research was shallow and
  "Deep research" on that character will fill them.
- **deep = -**: only the book-level research produced this character; deep research
  (per-character web search) has not run.
- **passages referencing unknown characters**: name mismatch between `passages.json` and
  `characters.json` (e.g. "The Pilot" vs "The Narrator"). Scene generation, once
  implemented, will look anchors up by name, so align the names.
- **orphan images**: PNGs no current entity maps to; safe to delete or to rename to the
  current slug if the entity was merely renamed.

## Editing project data by hand

It is fine to fix JSON directly (names, aliases, a wrong `form`), but keep the shape the
Pydantic models in `app/core/schema.py` define, keep every string field present (use
`"undefined"` rather than null), and keep `characters_present` names identical to the
character names. The UI re-reads the files on each rerun, so no restart is needed.
Never edit `project.json` fields the app owns (`id`, `slug`, `created_at`).
