# Architecture

How Once Upon a Time is built today. The [original spec](once-upon-a-time-spec.md) describes
the target product; this document describes the implementation and where it deliberately
differs.

## Overview

A single Streamlit process (`app/main.py`) renders either the home page (`app/ui/home.py`) or
one project's workspace (`app/ui/workspace.py`). All business logic lives in `app/core/` and
is UI-agnostic; the UI modules only call into it and render results.

```
app/ui/home.py ──┐                       ┌── app/core/research.py  (prompts: book, character)
app/ui/workspace.py ──► app/core/ingestion.py ──┤
                 │                       └── app/core/schema.py    (Pydantic models)
                 ├──► app/core/imaging.py   (prompts: anchor, sheets, locations)
                 │           │
                 │           └──► app/core/gemini.py ──► Vertex AI (google-genai)
                 │                       │
                 ├──► app/core/projects.py (projects/<slug>/*.json)   └──► app/core/usage.py (data/usage.jsonl)
                 └──► app/core/config.py   (config/.env)
```

## Modules

| Module                 | Responsibility                                                                                   |
|------------------------|--------------------------------------------------------------------------------------------------|
| `core/config.py`       | Loads `config/.env` with python-dotenv; `Settings` dataclass; `save_settings` rewrites `.env` and the process environment. |
| `core/gemini.py`       | One cached `genai.Client` per location (`vertexai=True`, ADC auth). Three operations: `web_research` (Google Search grounding, returns text + source URIs), `extract_structured` (JSON mode with a Pydantic `response_schema`, one repair pass through `model_validate_json`), `generate_image` (optional reference images, optional aspect ratio, retries once when no image part comes back). Every call records usage. |
| `core/schema.py`       | `BookExtraction`, `Character`, `CharacterSheet`, `Location`, `Passage`. Every string field defaults to `"undefined"` so omitted data is explicit, never invented. `CharacterSheet.form` carries how the book depicts the character (human, real animal, anthropomorphic, robot...). |
| `core/research.py`     | Prompt templates and the two-step research pipeline: grounded notes, then structured extraction. `research_book` and `research_character`. |
| `core/ingestion.py`    | Persists sources (`save_text_source`, `save_title_source`, `save_pdf_source`), persists extractions, runs `research_title` and `deep_research_character`, loads entities. `process_text` and `extract_pdf_text` are stubs that raise `NotImplementedError`; the UI catches it and reports "processing pending". |
| `core/imaging.py`      | `STYLE_PROMPTS`, prompt templates, path helpers, and `generate_character_anchor`, `generate_character_sheet`, `generate_location_image`, `generate_location_sheet`. |
| `core/projects.py`     | Project folder tree, `project.json` read/write, slugs, create/delete. |
| `core/export.py`       | ReportLab PDF of the current project state: cover, summary, characters (portrait, attributes, sheet), locations, passages, research sources. Images are re-encoded as bounded JPEGs so a full book exports to a few MB. Uses DejaVu Sans (installed in the image) for Unicode. |
| `core/usage.py`        | Appends one JSON line per call with token counts and an estimated cost from the `PRICING` table; `project_context` attributes calls to a project; summaries and breakdowns for the UI. |

## Data layout

There is no database. Each project is a folder under `projects/` (git-ignored, bind-mounted
into the container):

```
projects/<slug>/
  project.json                  {id, slug, name, description, style, status, source, book, created_at, updated_at}
  source/                       story.txt | <book>.pdf | research.md (title research notes + sources)
  characters/characters.json    list[Character] (+ "deep_researched": true after deep research)
  characters/<char-slug>/       anchor.png, sheet.png, research.md
  locations/locations.json      list[Location]
  locations/<loc-slug>.png      establishing shot;  <loc-slug>-sheet.png  environment sheet
  passages/passages.json        list[Passage]; characters_present are character names
  exports/<slug>-<timestamp>.pdf  PDF exports (never overwritten; one file per build)
  images/                       reserved
```

`status` moves `created → ingested → extracted → illustrated`; today the app sets the first
three. File names derive from entity names with a shared slug rule (lowercase,
non-alphanumerics to `-`), so renaming an entity orphans its images.

## Pipelines

### Title ingestion

1. `gemini.web_research(RESEARCH_PROMPT)` returns free-form notes plus grounding sources.
2. `gemini.extract_structured(EXTRACTION_PROMPT, BookExtraction)` validates them.
3. `ingestion.save_extraction` writes the three JSON files and the `book` block of `project.json`;
   notes and source links go to `source/research.md`.
4. Optionally, for every character, `deep_research_character` repeats steps 1-2 with
   `CHARACTER_RESEARCH_PROMPT` / `Character` and merges the result into `characters.json`
   (matched by name), writing `characters/<slug>/research.md`.

Research prompts instruct the model to *propose* a production-design choice when a visual
attribute is documented nowhere, so sheets are usable for illustration. The schema still
allows `"undefined"` for truly empty fields.

### Image generation and character consistency

The anchor → reference strategy from the spec is implemented:

- `generate_character_anchor` renders a single whole-body portrait from the sheet. The
  prompt enforces the character's `form` (real animals stay real animals), exactly one
  figure, no text. Aspect ratio is `2:3` for upright forms and `1:1` for quadrupeds, because
  wide canvases invited duplicated figures.
- `generate_character_sheet` sends the anchor PNG as a reference image with an explicit
  identity rule ("the reference image IS the character; where text and image disagree, the
  image wins") and renders a landscape `3:2` production-design sheet.
- Location sheets pass the establishing shot as a reference when it exists.
- Passage scenes are not implemented yet; the plan is to pass the anchors of every character
  present (the model accepts up to 14 reference images).

Each generated image is one synchronous call from the Streamlit script. "Generate all"
buttons loop with a progress bar and collect failures per item.

### PDF export

`export.export_project_pdf(project, include_sheets, include_sources)` reads the same JSON
and PNG files the tabs read and lays them out with ReportLab Platypus (A4, footer with
page numbers). Entities without images get a placeholder box, so a half-illustrated project
exports fine. The sidebar panel stores the resulting path in `st.session_state` and offers
it through `st.download_button`.

## Deliberate differences from the spec

| Spec                                      | Implementation                                   | Why                                                            |
|-------------------------------------------|--------------------------------------------------|----------------------------------------------------------------|
| SQLite as source of truth                  | JSON files per project                           | Simpler to inspect, diff and hand-edit while the schema settles |
| Background image worker, UI polls jobs     | Synchronous calls inside the Streamlit rerun     | Single-user tool; a worker is planned once batch sizes grow    |
| Resumable per-item job status              | Presence of the PNG on disk is the status        | Idempotent by construction: existing images are never regenerated unless asked |
| Text / PDF ingestion with chunking         | Sources are saved; processing raises `NotImplementedError` | Title research shipped first                           |
| Front/side/back/full-body as separate images | One presentation sheet containing the turnaround | Cheaper (one image) and consistent by design                 |
| `config/prompts/styles/` template files    | `STYLE_PROMPTS` dict in `imaging.py`              | Eight one-line clauses did not justify files                  |

## Cross-cutting concerns

- **Secrets.** Only `config/.env` holds project configuration; authentication is ADC mounted
  from the host. Nothing secret is baked into the image.
- **Cost visibility.** `usage.record` never raises, so accounting cannot break a generation.
  Unknown models are costed at $0; keep `PRICING` in sync with the configured models.
- **Failure handling in the UI.** `GeminiError` wraps every SDK exception with a readable
  message; tab actions show `st.error` and leave files untouched on failure.
