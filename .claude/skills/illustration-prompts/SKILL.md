---
name: illustration-prompts
description: Guidance for changing how Once Upon a Time generates images and researches characters: the prompt templates in app/core/imaging.py (anchor portraits, character and location presentation sheets, establishing shots) and app/core/research.py (web research and structured extraction), the STYLE_PROMPTS illustration styles, aspect ratios, and the anchor-to-reference character consistency strategy. Use this whenever the user wants to add or tweak an illustration style, fix characters that look wrong (anthropomorphized animals, duplicated figures, text in images, identity drift between portrait and sheet), change what a sheet contains, improve research quality, or implement passage/scene illustration.
---

# Illustration and research prompts

Two modules own every prompt:

- `app/core/research.py`: `RESEARCH_PROMPT` and `CHARACTER_RESEARCH_PROMPT` (web-grounded
  notes), `EXTRACTION_PROMPT` and `CHARACTER_EXTRACTION_PROMPT` (notes to validated JSON).
  Research and extraction are separate calls because Google Search grounding and
  structured output cannot be combined in one Gemini request.
- `app/core/imaging.py`: `STYLE_PROMPTS`, `CHARACTER_ANCHOR_PROMPT`, `CHARACTER_SHEET_PROMPT`,
  `LOCATION_PROMPT`, `LOCATION_SHEET_PROMPT`, plus the `generate_*` functions that fill them.

`app/core/gemini.py` is the thin client (structured output, grounding, image generation
with reference images). Prompt changes should not need to touch it.

## The consistency model

Identity is never regenerated from text twice. The **anchor** portrait is generated from
the character sheet once; every other image of that character passes the anchor PNG as a
reference image and tells the model "the reference image IS the character; where text and
image disagree, the image wins". That is why:

- `generate_character_sheet` generates the anchor first if it is missing.
- Regenerating an anchor makes existing sheets stale (the UI warns; `inspect-project` flags it).
- Future passage scenes should pass the anchor of every character present (the model
  accepts up to 14 reference images and keeps about 5 subjects consistent).

Keep this invariant when editing prompts: text describes, the reference image decides.

One exception sits above both: the **author's notes** on a character (`character["notes"]`,
edited from the Characters tab, stored outside the Pydantic schema). They are injected as
an "AUTHOR'S CORRECTIONS — highest priority" block (`AUTHOR_NOTES_BLOCK` in `imaging.py`)
into the anchor and sheet prompts, and as `RESEARCH_NOTES_BLOCK` / `EXTRACTION_NOTES_BLOCK`
into deep research. When a user reports a character "comes out wrong" (humanoid rose,
dressed fox), the first answer is a note plus regenerating the portrait, not a prompt edit;
edit the shared prompts only when the defect repeats across characters.

## Rules that exist because of real failures

Each of these lines in the prompts fixed an observed defect; keep them unless replacing
them with something that solves the same problem.

| Prompt text                                             | Defect it prevents                                   |
|---------------------------------------------------------|------------------------------------------------------|
| "Depict the character EXACTLY according to its stated FORM... REAL animal..." | the fox drawn as a bipedal, dressed creature |
| "Exactly ONE figure... NOT a reference sheet... no grid" | anchor came back as a turnaround / collage           |
| "No text, no labels, no watermark" (anchor, location)   | captions baked into portraits                        |
| aspect ratio `2:3` for upright forms, `1:1` for quadrupeds | wide canvases invite duplicated figures          |
| sheet: "ALL TEXT IN ENGLISH", "keep every text element SHORT" | garbled long captions on sheets                |
| research: "PROPOSE one the way a production designer would... never write unknown" | sheets full of "undefined", bland portraits |

The `form` field in `CharacterSheet` (`app/core/schema.py`) feeds both the FORM rule and
the aspect-ratio choice; if you add a new form category (e.g. "flying creature"), update
the `upright` heuristic in `generate_character_anchor`.

## Adding or changing a style

`STYLE_PROMPTS` is a dict of `key -> style clause`. The keys appear verbatim in the home
page style selector and in the sidebar editor; the clause is interpolated as `{style}` in
every image prompt. To add one: add the entry, keep the clause to one line of concrete
visual vocabulary (medium, line, palette, lighting), and update the style list in
`README.md` and `docs/usage.md`. Existing projects keep their stored key, so never rename a key without
migrating `project.json` files.

## Changing what a sheet shows

Sheets are a single generated image of a layout described in words. Add or remove panels
by editing the "Layout" bullets; keep labels short and uppercase, and keep the identity
rule paragraph at the top. Expect the model to drop a panel when the layout gets crowded:
a sheet at `3:2` holds roughly a title block, one turnaround, one 8-portrait grid, a
palette, 3-4 detail panels and one strip.

## Testing a prompt change cheaply

1. Pick one character with a known-good anchor and a representative `form` (one human,
   one real animal). Use `inspect-project` to find them.
2. Regenerate only that image from the UI (or call `imaging.generate_character_anchor`
   from a Python shell inside the container: `docker compose exec app python`).
3. Check the output for: single figure, correct form, whole body visible, no text, style
   applied, and (for sheets) the same face/outfit as the anchor in every panel.
4. Check cost with the `usage-report` skill; one image is about $0.13-0.20, so iterate
   on one image, not on "Generate all".
5. Describe the change in the commit message with the defect it fixes, as in the table above.

## Implementing passage scenes (planned, see README roadmap)

Follow the location pattern: a `SCENE_PROMPT` with `{style}`, the passage summary and the
location description; collect `reference_images` from the anchors of
`passage["characters_present"]` (names must match `characters.json`); add a
`passage_image_path` helper and a button in `_render_passages_tab`. Prefer `16:9`.
Mention each character by name in the prompt in the same order as the reference images so
the model can map names to faces.
