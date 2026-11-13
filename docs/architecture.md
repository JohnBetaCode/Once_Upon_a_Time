# Architecture

How Once Upon a Time is built today. The [original spec](once-upon-a-time-spec.md) describes
the target product; this document describes the implementation and where it deliberately
differs.

## Overview

A single Streamlit process (`app/main.py`) renders either the home page (`app/ui/home.py`) or
one project's workspace (`app/ui/workspace.py`). All business logic lives in `app/core/` and
is UI-agnostic; the UI modules only call into it and render results. An optional second
service, the local GPU image server (`local_image/server.py`), generates images on an NVIDIA
GPU when `IMAGE_BACKEND=local`.

```
app/ui/home.py ──┐                       ┌── app/core/research.py  (prompts: book, character)
app/ui/workspace.py ──► app/core/ingestion.py ──┤
                 │                       └── app/core/schema.py    (Pydantic models)
                 ├──► app/core/imaging.py   (prompts: anchor, sheets, locations)
                 │           │
                 │           ├──► app/core/gemini.py ──► Vertex AI (google-genai)
                 │           │           │
                 │           └──► app/core/local_image.py ──HTTP──► local_image/server.py (GPU, optional)
                 │                       │
                 ├──► app/core/projects.py (projects/<slug>/*.json)   └──► app/core/usage.py (data/usage.jsonl)
                 └──► app/core/config.py   (config/.env)
```

## Modules

| Module                 | Responsibility                                                                                   |
|------------------------|--------------------------------------------------------------------------------------------------|
| `core/config.py`       | Loads `config/.env` with python-dotenv; `Settings` dataclass (including `image_backend` and `local_image_url`); `save_settings` updates the given keys in `.env` in place, keeps every other line, and updates the process environment. |
| `core/gemini.py`       | One cached `genai.Client` per location (`vertexai=True`, ADC auth). Three operations: `web_research` (Google Search grounding, returns text + source URIs), `extract_structured` (JSON mode with a Pydantic `response_schema`, one repair pass through `model_validate_json`), `generate_image` (optional reference images, optional aspect ratio, retries once when no image part comes back). Every call records usage. |
| `core/schema.py`       | `BookExtraction`, `Character`, `CharacterSheet`, `Location`, `Passage`. Every string field defaults to `"undefined"` so omitted data is explicit, never invented. `CharacterSheet.form` carries how the book depicts the character (human, real animal, anthropomorphic, robot...). |
| `core/research.py`     | Prompt templates and the two-step research pipeline: grounded notes, then structured extraction. `research_book` and `research_character`. |
| `core/ingestion.py`    | Persists sources (`save_text_source`, `save_title_source`, `save_pdf_source`), persists extractions, runs `research_title` and `deep_research_character`, loads entities. `process_text` and `extract_pdf_text` are stubs that raise `NotImplementedError`; the UI catches it and reports "processing pending". |
| `core/imaging.py`      | `STYLE_PROMPTS`, prompt templates, path helpers, and `generate_character_anchor`, `generate_character_sheet`, `generate_location_image`, `generate_location_sheet`. `anchor_request` / `sheet_request` build the prompt, negative prompt, aspect ratio and references; `_generate_image` routes them to Gemini or to the local backend (`IMAGE_BACKEND`). |
| `core/local_image.py`  | HTTP client for the optional `local-image` Compose service. `generate_image` has the contract of `gemini.generate_image` plus `negative_prompt` and `size`; calls are logged as `<model>-local` at $0. `health` (cached for UI reruns, failures included) and `describe` feed the Settings panel. |
| `local_image/server.py` | FastAPI server around the diffusers pipeline of Qwen-Image-2.1, in its own container (`gpu` profile). Lifecycle `checking → downloading → idle ⇄ loading → ready`, plus `unsupported` and `error`; unloads the model after `LOCAL_IMAGE_IDLE_MINUTES`. See [Local GPU images](local-gpu-evaluation.md). |
| `core/projects.py`     | Project folder tree, `project.json` read/write, slugs, create/delete. |
| `core/export.py`       | ReportLab PDF of the current project state, laid out as a landscape art book: cover, story, index pages, one page per character and location plus their sheets as full-page plates, passages, research sources. `export_project_pdf` builds it; `cover_choices` lists the locations that can go on the cover. |
| `core/pdf_kit.py`      | What the export is built from, with no knowledge of projects: the bundled fonts (`app/assets/fonts`) and the system fallback fonts, a `Theme` derived from the artwork's dominant hue, `Artwork` (crops, shades and re-encodes images as bounded JPEGs, cached), and the custom flowables (hand-painted pages, letter-spaced labels, drop caps). |
| `core/thumbnails.py`   | Pillow collage (up to four square tiles) of a project's portraits and locations for the home page, cached as `images/thumbnail-<key>.jpg` and rebuilt when the source images change. |
| `core/usage.py`        | Appends one JSON line per call with token counts and an estimated cost from the `PRICING` table; `project_context` attributes calls to a project; summaries and breakdowns for the UI. |

## Data layout

There is no database. Each project is a folder under `projects/` (git-ignored, bind-mounted
into the container):

```
projects/<slug>/
  project.json                  {id, slug, name, description, style, status, source, book, created_at, updated_at}
  source/                       story.txt | <book>.pdf | research.md (title research notes + sources)
  characters/characters.json    list[Character] (+ app-owned keys: "deep_researched", "notes", "notes_updated_at")
  characters/<char-slug>/       anchor.png, sheet.png, research.md
  locations/locations.json      list[Location]
  locations/<loc-slug>.png      establishing shot;  <loc-slug>-sheet.png  environment sheet
  passages/passages.json        list[Passage]; characters_present are character names
  exports/<slug>-<timestamp>.pdf  PDF exports (never overwritten; one file per build)
  images/                       reserved
```

The local GPU server keeps its model weights (~33 GB) in the `local-image-models` Docker
volume: rebuilding its image never downloads them again, and other projects that run the same
server mount the same volume (it is declared `external`, created by `launch.sh`), so each model
is downloaded once per computer. `LOCAL_IMAGE_MODELS_DIR` makes `launch.sh` create that volume on a
folder of the user's choice instead of Docker's own storage.

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

With `IMAGE_BACKEND=local` the same flow runs on Qwen-Image-2.1 through the local server.
Diffusion models follow descriptions well but obey rules and negations poorly, so the local
anchor prompt (`LOCAL_ANCHOR_PROMPT`) states the composition positively, spells the form out
and states the style at both ends; the negative prompt only takes effect when the server runs
with guidance > 1, which costs ~1.6x the time, so it is off by default. Local sheets are
wordless art-book plates (`LOCAL_CHARACTER_SHEET_PROMPT`, `LOCAL_LOCATION_SHEET_PROMPT`): the
same panels as the Gemini sheet, with the anchor (or the establishing shot) as reference, but no
title, labels or captions, since the local model garbles small type and the PDF prints the same
facts as text. They render at the native 2K so the small portraits and close-ups keep their
detail. A character whose form has no human body plan (`is_non_humanoid`: a ship computer, an
alien, an energy being) gets `LOCAL_CREATURE_SHEET_PROMPT` instead, with views of the whole being
and close-ups of its sensory organs, because the turnaround, portraits and hands of the regular
plate gave such characters a human body. Quotation marks around phrases in the research are
dropped from the plate prompts (`_unquote`): quoted words are what the model letters onto a page.
Styles that the local model pulls towards realism can carry local-only adjustments in
`LOCAL_STYLE_TUNING` (portrait background, extra negative prompt, guidance); `80s-comic` and
`pencil` use it. Styles in `MONOCHROME_STYLES` (`pencil`) are converted to grayscale by `_finish`
before any image is saved, whichever backend drew it. With `IMAGE_BACKEND=gemini` the requests are exactly the ones Gemini always got.

The anchor → reference strategy from the spec is implemented:

- `generate_character_anchor` renders a single whole-body portrait from the sheet. The
  prompt enforces the character's `form` (real animals stay real animals), exactly one
  figure, no text. Aspect ratio is `2:3` for upright forms and `1:1` for quadrupeds, because
  wide canvases invited duplicated figures.
- `generate_character_sheet` sends the anchor PNG as a reference image with an explicit
  identity rule ("the reference image IS the character; where text and image disagree, the
  image wins") and renders a landscape `3:2` production-design sheet.
- Location sheets pass the establishing shot as a reference when it exists.
- **Author's notes** (`character["notes"]`, edited in the Characters tab) are appended to the
  anchor and sheet prompts as an "AUTHOR'S CORRECTIONS — highest priority" block and to the
  character research/extraction prompts as authoritative guidance. They live outside the
  Pydantic schema so the LLM never writes them, and `deep_research_character` carries them
  over when it replaces the extracted fields. `notes_updated_at` lets the UI warn when a
  portrait predates the latest note.
- Passage scenes are not implemented yet; the plan is to pass the anchors of every character
  present (the model accepts up to 14 reference images).

Each generated image is one synchronous call from the Streamlit script. "Generate all"
buttons loop with a progress bar and collect failures per item.

### PDF export

`export.export_project_pdf(project, include_sheets, include_sources, cover)` reads the same JSON
and PNG files the tabs read and lays them out with ReportLab as an A4 landscape art book: the
format fits every image the app produces (3:2 sheets, 16:9 establishing shots, and upright
portraits that fill the page height).

| Pages                 | Built by (`_Book` in `export.py`)                       | Page template                     |
|-----------------------|---------------------------------------------------------|-----------------------------------|
| Cover                 | `_paint_cover`                                          | `full`                            |
| The story             | `_story_units`, side panel by `_paint_story_side`       | `story`, continues on `text`      |
| The cast, the world   | `_index_units`: `_paint_index`, or `_paint_contents` when nothing has an image | `full`     |
| Character             | `_profile`, portrait by `_paint_profile_backdrop`       | `profile`, continues on `text`    |
| Sheet plate           | `_paint_plate`                                          | `full`                            |
| Location              | `_paint_location`                                       | `full`                            |
| Key passages          | `_passage_units`                                        | `cols2_first`, then `cols2`       |
| Research sources      | `_source_units`                                         | `cols4_first`, then `cols4`       |

All measurements are constants at the top of `export.py`.

- **Two kinds of page.** Pages that are mostly artwork (cover, index pages, locations, sheet
  plates) are painted directly on the canvas by a `Paint` flowable that claims the whole page.
  Pages that are mostly text (the story, character profiles, passages, sources) flow through
  Platypus frames, with a zero-sized `Paint` behind them for the portrait or side panel.
- **Fitting text.** A profile is measured before it is placed and set at the first type scale
  (`FIT_SCALES`) at which it sits beside the portrait; one that is too long even at the smallest
  scale continues on a plain page, and so does a long story summary. Location pages give the
  image whatever height the text leaves, down to a minimum, and then shrink the text. Tables
  that may outgrow a page are built with `splitInRow=1`, so long input never raises a
  `LayoutError`.
- **Images.** `pdf_kit.Artwork` crops to the slot, bakes a gradient under any text drawn over the
  image, trims black bars baked into an establishing shot, and re-encodes as bounded JPEG. Square
  or wide portraits are not cropped to the tall panel: their studio backdrop is extended instead.
- **Palette.** The accent, tint and dark page colour come from the dominant hue of the cover
  image, adjusted until labels meet a contrast ratio; greyscale artwork gets a warm default.
- **Fonts.** DM Serif Display, Spectral and Barlow are bundled under `app/assets/fonts` (SIL OFL).
  Characters they lack are set in a system font when one has the glyph: DejaVu Sans, then
  WenQuanYi Micro Hei for CJK (both installed by the `Dockerfile`).
- **Navigation.** The document is built twice: the first pass records the page of every character
  and location, the second prints those numbers on the index pages. Tiles link to their pages
  and the PDF outline lists every entity.
- **Partial projects.** Without an establishing shot the cover lines up the first portraits;
  without any image the index pages become a table of contents and portraits become initials.

The sidebar panel stores the resulting path in `st.session_state`, opens it in an inline viewer
(`st.pdf`, which needs the `streamlit-pdf` package) and offers it through `st.download_button`.

## Deliberate differences from the spec

| Spec                                      | Implementation                                   | Why                                                            |
|-------------------------------------------|--------------------------------------------------|----------------------------------------------------------------|
| SQLite as source of truth                  | JSON files per project                           | Simpler to inspect, diff and hand-edit while the schema settles |
| Background image worker, UI polls jobs     | Synchronous calls inside the Streamlit rerun     | Single-user tool; a worker is planned once batch sizes grow    |
| Resumable per-item job status              | Presence of the PNG on disk is the status        | Idempotent by construction: existing images are never regenerated unless asked |
| Text / PDF ingestion with chunking         | Sources are saved; processing raises `NotImplementedError` | Title research shipped first                           |
| Front/side/back/full-body as separate images | One presentation sheet containing the turnaround | Cheaper (one image) and consistent by design                 |
| `config/prompts/styles/` template files    | `STYLE_PROMPTS` dict in `imaging.py`              | Eight one-line clauses did not justify files                  |
| Gemini on Vertex AI for every image        | Gemini or an open-weights model on a local GPU   | No per-image cost for owners of a 24-32 GB GPU; realistic styles match |

## Cross-cutting concerns

- **Secrets.** Only `config/.env` holds project configuration; authentication is ADC mounted
  from the host. `.dockerignore` keeps `config/.env`, `projects/` and `data/` out of the build
  context, so nothing secret is baked into the image. The local GPU server has no
  authentication and binds to `127.0.0.1` only.
- **Cost visibility.** `usage.record` never raises, so accounting cannot break a generation.
  Unknown models are costed at $0; keep `PRICING` in sync with the configured models.
- **Failure handling in the UI.** `GeminiError` wraps every SDK exception with a readable
  message, and `LocalImageError` does the same for the local server (unreachable, downloading,
  unsupported GPU, out of memory); tab actions show `st.error` and leave files untouched on failure.
