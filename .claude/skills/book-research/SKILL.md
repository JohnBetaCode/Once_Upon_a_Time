---
name: book-research
description: Research a book (or one character) for Once Upon a Time with Claude Code's own web search instead of Gemini, and save it into a project exactly as the app's research pipeline would. Use this when the user asks Claude to research a new book or deep-research a character and Gemini is not available (no GCP project, lost credentials, quota), or when the user explicitly asks Claude to do the research. It follows the app's own research prompts, validates with the app's Pydantic schemas and saves with the app's functions, so images, sheets and the PDF work as for any researched book. It also deep-researches the cast and the locations with parallel agents (one per main character, a few locations each) that report back to the main agent, which reconciles and saves; use that when the user asks to research characters or locations in depth, in parallel, or with several agents.
---

# Research a book with Claude Code

The app researches books with Gemini (web search, then structured extraction;
`app/core/research.py`). This skill does the same two steps with Claude Code's WebSearch and
WebFetch, and saves the result through the same code (`ingestion.save_title_research`,
`ingestion.save_character_research`). The project records who did it:
`source.researched_by` and each character's `researched_by` say
"Claude Code (book-research skill)".

Use it only when the user wants Claude to research, or when Gemini cannot run. When Gemini works,
the app's **Research** button is the default.

## Rules

- **Follow the printed instructions.** `prompt-book` and `prompt-character` print the app's own
  research and extraction prompts. Those are the rules: facts about the book come from sources;
  visual details nobody documented are *proposed* the way a production designer would, never
  "unknown"; every character's form is stated; notes and JSON are in English.
- **Never invent the story.** Plot, characters, places and passages must come from sources you
  read (publisher pages, reviews, interviews, summaries, wikis). If the web has little, the
  extraction has fewer characters and passages; do not fill gaps with fiction. In the notes, mark
  designed appearance details as *Proposed design* so the user can tell them apart.
- **Cite.** Every source used goes in the sources file; the save step refuses an empty list.
- **Short quotes only.** Summarize; do not copy long passages from the book or from reviews.
- Spanish (or other) books: search in the original language and in English, write in English.

## Workflow

The script runs inside the app container (start it with `./launch.sh` if needed). Drafts live in
`data/research-drafts/<slug>/` (git-ignored user data), visible on the host and in the container.

```bash
S=.claude/skills/book-research/scripts/research.py
docker compose exec -T app python - prompt-book "<title>" --author "<author>" < $S   # 1. instructions + schema
docker compose exec -T app python - new "<project name>" --style <style> < $S        # 2. project (prints the slug)
#   3. research with WebSearch / WebFetch, then write in data/research-drafts/<slug>/:
#        book-notes.md      the research notes, as the prompt asks
#        book.json          the extraction, valid against the printed BookExtraction schema
#        book-sources.json  [{"title": ..., "uri": ...}, ...]
docker compose exec -T app python - save-book <slug> --title "<title>" --author "<author>" < $S  # 4. validate + save
```

`save-book` lists the sheet fields still `"undefined"` per character. Then, optionally, deep
research per character (worth it for the main cast, or when wikis and guides exist):

```bash
docker compose exec -T app python - prompt-character <slug> "<exact name>" < $S
#   research, then write <character-slug>-notes.md, <character-slug>.json (a Character),
#   <character-slug>-sources.json; the prompt prints the exact file names
docker compose exec -T app python - save-character <slug> "<exact name>" < $S
```

`save-character` keeps the author's notes and the canonical name, and replaces the character's
entry and `characters/<slug>/research.md`, exactly like the app's **Deep research** button.
`prompt-location` / `save-location` do the same for a location (drafts `location-<slug>*`,
notes in `locations/<slug>/research.md`); the app has no Gemini equivalent, so their prompts
(`LOCATION_RESEARCH_PROMPT`, `LOCATION_EXTRACTION_PROMPT` in `app/core/research.py`) are used
only here. The saved description feeds the image prompts as is, so it stays one drawable
paragraph. `--add` on either save adds an entity the book research missed.

For more than two or three characters, or for locations, use the parallel mode below.

## Parallel deep research (characters and locations)

The main agent does the book pass, then hands one entity (or a few) to each research agent;
the agents research and write **drafts only**, report back, and the main agent reconciles the
reports and saves. Agents never run `save-*`: `characters.json` and `locations.json` are
rewritten whole on every save, so two concurrent saves lose one of them.

1. **Plan.** `plan <slug>` lists characters and locations sorted by the number of passages they
   appear in (`in#`), with their draft stem, `deep` status, existing drafts and author notes.
   Skip entities already `deep` or with a draft unless the user asks to redo them.
2. **Split.** One agent per main character (the top of the list), two or three secondary
   characters per agent, three or four locations per agent. At most 8 agents per wave: beyond
   that the cost grows faster than the result, and minor characters rarely have sources. Tell
   the user the split (how many agents, who gets what) before launching.
3. **Launch** every agent in the same message (Agent tool, `general-purpose`, so they run
   concurrently), each with the brief below.
4. **Reconcile** (main agent, see the checklist), then **save one at a time**: `save-character`
   for each character, `save-location` for each location, `--add` for an accepted new one.
5. **Report** to the user, as at the end of the workflow, plus what changed visually.

### Brief for each research agent

Fill in the brackets; keep the rest as is. The agent knows nothing else about the project.

```text
You are researching for the Once Upon a Time project in <repo absolute path>, book "<title>" by
<author>, project slug <slug>. Your entities: <exact names, each marked character or location>.

For each entity:
1. From the repo root, print its instructions:
   docker compose exec -T app python - prompt-character <slug> "<name>" < .claude/skills/book-research/scripts/research.py
   (prompt-location for a location). They are the app's own research rules, the current entry
   and the JSON schema; follow them. Author's notes in them are authoritative.
2. Research with WebSearch and WebFetch: book text quoted in reviews and guides, literature
   guides, wikis, interviews, adaptations, the real place for a real location. Search in the
   book's original language and in English; write in English.
3. Write the three drafts the prompt names in data/research-drafts/<slug>/: <stem>-notes.md,
   <stem>.json (valid against the schema), <stem>-sources.json ([{"title": ..., "uri": ...}],
   every page you used). Mark designed details as *Proposed design* in the notes.
Rules: never invent the plot or facts; propose only visual details nobody documented, as a
production designer would; short quotes only; do NOT run save-character or save-location and
do not edit anything under projects/.

Your final message is your report to the main agent, at most 300 words per entity:
ENTITY: <exact name> (character | location)
DRAFTS: written | failed (why)
SOURCED: the key visual facts, each with its source
PROPOSED: the details you designed, with no source
CONFLICTS: sources that disagree with each other or with the current entry, and what you chose
RELATIONS: cast members and places this one is tied to (exact names) and how (mother of,
           lives in, twin of, ages ten years before...)
NEW: named characters or places the book research missed, one line and one source each
```

### Reconciliation checklist (main agent)

- `check <slug>` validates every draft without saving: fix `INVALID` and `BLOCKED` first (a
  draft with no sources cannot be saved). It also flags names that differ from the canonical one,
  `NEW` entities, undefined sheet fields, an alias claimed by two characters (the same person
  twice?) and location descriptions outside 50-120 words.
- Cross-check the reports against each other, which no single agent could do: family
  resemblance and ethnicity across relatives, ages consistent with the relations and the
  timeline, the same place described alike by the character and location agents, a prop or
  outfit the same wherever it appears. Fix the losing draft's JSON (and its notes) by hand.
- Conflicts: book text over adaptations over fan wikis; the author's notes over everything.
- `NEW` entities: add one only if it is sourced and worth an illustration; it then needs drafts
  (a second, small wave, or research it yourself) and `--add`. List the rest for the user.
- If the project already has images, deep research changes the text but not the pictures: tell
  the user which characters changed visually (form, age, hair, attire) and so need a new anchor,
  then a new sheet. Location research is saved under `locations/<slug>/research.md`; the app shows
  no button or badge for it and the PDF does not list its sources yet.

## After saving

Check the project with the `inspect-project` skill, then generate images as usual
(the app's buttons, or the local GPU). Tell the user which details were proposed rather than
sourced, and give them the sources.

## Quality checklist before saving

- Every character in the notes is in `book.json`, with its `form` and a concrete value in each
  sheet field (or `"undefined"` when the notes truly have nothing).
- Character names in passages (`characters_present`) match the `name` fields exactly.
- `summary`, `themes`, `genre`, `publication_year` and `original_language` are filled when sources
  give them.
- Locations have a visual description an illustrator can draw, not only a name.
