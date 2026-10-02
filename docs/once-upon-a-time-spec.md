# Project: Once Upon a Time

> **Status note (October 2026).** This is the original product spec, kept for intent and
> scope. The implementation differs in several places (JSON files instead of SQLite,
> synchronous generation instead of a background worker, title research shipped before
> text/PDF ingestion). See [architecture.md](architecture.md) for how the app is actually
> built and the README for the current status table.

Build a containerized web application that ingests a story/book/tale (plain text, PDF, or URL), extracts its narrative content via an LLM, and generates **consistent** illustrations of the characters and key passages using Google's Nano Banana Pro. State must persist across sessions.

## Architecture principles (read first)

This project is built around five hard rules that shape everything below:

1. **The image worker is decoupled from the UI.** Image generation is async, expensive, and slow (8–25 s/image, dozens of images per book). It runs as background jobs, never inline in the Streamlit request cycle. Streamlit only submits jobs and polls their status.
2. **SQLite is the source of truth for structured state; the filesystem holds only blobs.** Sessions, characters, passages, and generation status live in a queryable SQLite database. Only images and source files live on disk under `media/`. Per-character JSON is an export format, not the primary store.
3. **The pipeline is a resumable state machine.** Stages — `uploaded → extracted → characters_generated → passages_generated` — are independent and individually resumable. A failure on item 12 of 20 resumes from 12; it never re-extracts or re-pays for completed work.
4. **LLM output is validated, never trusted.** Use structured output / function calling where available, and validate every extraction against a Pydantic schema before it touches storage. The "missing field → undefined" rule is enforced by the schema layer, with a repair-retry on invalid JSON.
5. **Character consistency is pinned to the anchor→reference approach and de-risked first.** Before building the app, a throwaway script proves Nano Banana Pro can hold identity across front/side/back/full-body. The whole product rests on this; it is validated in hour two, not week two.


## Character consistency strategy (core requirement)

Same character must look identical across all its shots and across passage scenes. Rule: **generate an anchor, derive everything from it** — never regenerate identity from scratch.

1. **Anchor**: generate the front-facing portrait first, from the character's validated sheet + extracted description.
2. **Derived shots**: generate side, back, and full-body by passing the anchor as a reference image (Nano Banana Pro supports up to 14 reference images and holds consistency for up to 5 subjects per generation, no fine-tuning).
3. **Passage scenes**: pass the anchor of every character present in the scene as references so they reappear as the same person.
4. **Style**: apply the session's selected style prompt consistently across all generations.
5. **Caching / idempotency**: every image is a tracked job with a status; never regenerate unless explicitly requested. Costs add up fast (~$0.134 per 1–2K, ~$0.24 per 4K; ~4 shots/character + 1/passage).

## Application flow (resumable pipeline)

Each stage is a distinct, independently resumable state. The current stage and per-item status are tracked in SQLite.

**Stage 1 — `uploaded` (ingest)**: accept `.txt`, `.pdf`, or URL. Extract PDF text (OCR optional for scanned). Fetch + clean main content from URLs. Detect language. Source file saved to `media/`, metadata row written to SQLite.

**Stage 2 — `extracted` (LLM → validated JSON)**: text may exceed context window → process in **batches/chunks with overlap**, then consolidate and deduplicate. Every chunk's output is validated against a Pydantic schema (repair-retry on failure) before persistence. Schema:
- `characters[]`: name, aliases, role, physical description, sheet (gender, race/species, age, height, build, attire, distinctive traits…), appearances.
- `locations[]`: name, description, relevance.
- `passages[]`: title/type (introduction, key event, death, climax…), excerpt/summary, characters present, location.
- **Missing-field rule**: enforced by the schema — any absent field serializes to `"undefined"`. Never invented.

**Stage 3 — `characters_generated`**: for each character, enqueue anchor → derived shots (front, side, back, full-body) as jobs. Resumable per character and per shot. Images cached in `media/`, status tracked in SQLite.

**Stage 4 — `passages_generated`**: for each passage, enqueue a scene job that references the anchors of the characters present. Resumable per passage.

**Sessions & persistence**: each loaded source is its own isolated session (Book 1, Book 2…). State lives in SQLite, so reopening the app and querying ("all passages with character X", "which images failed") is instant. On reopen, sessions and their progress load automatically.

## UI tabs

- **Characters tab**: each character's front/side/back/full-body shots, with the validated sheet and text-extracted description beside them (missing fields show "undefined"). Per-image regenerate button (submits a single job).
- **Passages tab**: each passage's scene, illustrated with the same characters from the Characters tab when present.
- Both tabs read from SQLite and poll job status for in-flight images, showing progress and any failures with per-item retry.

## Config & secrets (`config/`)

All secrets in `config/.env` (git-ignored); ship `config/.env.example` with
`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GEMINI_IMAGE_LOCATION`,
`GEMINI_TEXT_MODEL` and `GEMINI_IMAGE_MODEL`. Authentication uses Application Default
Credentials mounted from the host.


## Style prompts (`config/prompts/styles/`)

Reusable templates with placeholders (`{character_description}`, `{scene_description}`), one per style: cartoon, realistic, retro, anime, watercolor, comic, pixel-art, noir. User picks a style in the UI; saved in the session row so reopened sessions keep their look.

## docs/ (linked from README)

- `usage.md` — installation, walkthrough, configuration, costs and roadmap.
- `architecture.md` — modules, data layout, pipelines and deliberate differences from this spec.
- `images/` — screenshots and sample outputs used by the README.


