---
name: review-illustrations
description: Art-director review of a Once Upon a Time project's generated images (character anchors and sheets, location shots and sheets). Claude looks at the PNGs, checks each against the character's form, sheet fields and author's notes and against the project's style, records a verdict per image (ok, regenerate, fix the notes, fix the prompt) and, with the user's go-ahead, regenerates the bad ones with a backup. Use this whenever the user asks to review, check, audit or QA the illustrations or portraits of a project, asks which images came out wrong or need regenerating, wants to know if a style held across the cast, or after generating many images at once (Generate all, the local GPU). Big casts are split between parallel review agents.
---

# Review a project's illustrations

Image models fail in known ways (see the table in the `illustration-prompts` skill and
`docs/local-gpu-evaluation.md`), and a project of 20 characters has 40 images nobody looks at one
by one. This skill looks at them, says what is wrong with each, and fixes what the user approves.

It never regenerates without asking: images are user data, and an anchor carries the character's
identity into every later image.

## Commands

The script runs inside the app container (`./launch.sh` if it is down); paths it prints are
relative to the repo root, the same on the host.

```bash
S=.claude/skills/review-illustrations/scripts/review.py
docker compose exec -T app python - contact  <slug> [--kind anchors,locations] [--pending] < $S
docker compose exec -T app python - manifest <slug> [--pending] [--kind sheets] [--name "<exact name>"] [--batches N] < $S
docker compose exec -T app python - record   <slug> data/reviews/<slug>/verdicts-<n>.json < $S
docker compose exec -T app python - summary  <slug> < $S
docker compose exec -T app python - regenerate <slug> anchor|sheet|location|location-sheet "<exact name>" [--backend local] < $S
```

- `contact` writes numbered grids (`data/reviews/<slug>/contact-<kind>-<n>.jpg`) and prints which
  number is which image. Kinds: `anchors`, `sheets`, `locations`, `location-sheets`.
- `manifest` prints, per entity, what the images must show (form, sheet fields, author's notes,
  location description), each image's path and date, the backend that made it (matched in
  `data/usage.jsonl`: local sheets are wordless plates, Gemini sheets carry short English labels),
  `STALE` sheets and the last verdict. `--pending` leaves out images already reviewed "ok" and
  unchanged since.
- `record` merges a verdict list into `data/reviews/<slug>/review.json` (git-ignored user data).
- `regenerate` copies the current image to `data/reviews/<slug>/replaced/` and generates it again
  with the app's own function. Use `--backend local` when Gemini is not available (the
  container's `IMAGE_BACKEND` may still say gemini; the UI's setting does not reach this script).

## Workflow

1. **Triage.** `contact <slug> --kind anchors,locations` (add `--pending` on a second pass) and
   look at the grids. They show at a glance what one image at a time hides: the style drifting
   on some characters, a figure lying down or duplicated, a costume party where the book has a
   real animal. Note the suspects.
2. **Detail.** `manifest <slug> --pending`, then open each image (Read) and compare it with its
   entry. Up to about 8 entities, do it yourself. For a bigger cast, split it:
   `manifest <slug> --pending --batches N` (N = entities / 5, at most 8) and launch one review
   agent per batch, all in the same message, with the brief below. Give every agent your triage
   notes for its entities.
3. **Record.** Write the verdicts (yours, or the agents' merged) to
   `data/reviews/<slug>/verdicts-<n>.json` and `record` them. `summary` prints what is not ok.
4. **Report** to the user, grouped by verdict: what is wrong with each image and the action;
   for `notes`, the exact note you propose; for `prompt`, the repeated defect and where it shows.
   Then ask what to fix.
5. **Fix what the user approves.** `notes`: the user writes the note in the Characters tab (or
   you append it to the existing `notes` with `ingestion.save_character_notes` if they ask you
   to); then regenerate. `regenerate`: run it, anchor before sheet. `prompt`: switch to the
   `illustration-prompts` skill. A new anchor makes the sheet stale: look at the new anchor
   first, then regenerate the sheet from it. After regenerating, review the new images
   (`--pending` picks them up because their date changed).

Each local image takes about 25 s (sheets about 107 s) and costs nothing; each Gemini image costs
about $0.13-0.20, so with Gemini say the count and the cost before regenerating.

## What to check

**Every image**
- The project's style, as the manifest prints it; the same look as the rest of the cast (the
  contact sheet). Local images of `cartoon` and `comic` drift to realism. `pencil` is grayscale:
  any colour is a defect.
- Anatomy: hands, faces and limbs that are malformed, merged or extra.

**Anchor portrait**
- Exactly one figure, whole body, face visible, three-quarter view, plain background, no scenery.
- The stated `form`: a real animal on four legs, unclothed, with no human hands or face, unless
  the form says anthropomorphic; a being with no human body (ship computer, alien) not drawn as a
  robot or a person.
- Age, gender, hair, skin, build, attire and signature props match the sheet fields, and the
  author's notes win over them. Proportions are natural: no anime eyes or bodybuilders in a
  realistic style, no caricature unless the book is one.
- No text, letters, logo or watermark.

**Character sheet**
- The same individual as the anchor in every panel: face, hair, colours, outfit, form. `STALE`
  means the anchor changed after the sheet: the verdict is `regenerate`.
- Local sheet (wordless plate): any letter is a defect. The panels are a four-view turnaround,
  eight expressions, swatches, a scale silhouette, close-ups and a setting strip. A `creature
  plate` (animals and non-humanoids) shows views of the whole being, not head-and-shoulders
  portraits with human hands.
- Gemini sheet: short English labels, legible, not garbled; the name spelled right.

**Location shot and sheet**
- No people. The place the description says (era, architecture or landscape, light), wide.
- Local location sheet: wordless; Gemini: short English labels.

**Across the project**: the same defect in three or more images (every quadruped standing, every
sheet with captions, the style lost on every location) is a `prompt` verdict, not N
regenerations.

## Verdicts

Each verdict is an object in the list that `record` reads:

```json
{"image": "projects/<slug>/characters/the-fox/anchor.png", "verdict": "notes",
 "defects": ["stands on two legs", "wears a scarf"],
 "action": "author's note: 'A real fox: four legs, no clothing, natural anatomy.' Then regenerate the anchor and the sheet."}
```

- `ok`: nothing a reader would notice.
- `regenerate`: a one-off defect (an extra figure, garbled hands, a caption, a stale sheet); a new
  seed is likely to fix it.
- `notes`: the text drove the image wrong (wrong form, age, costume, ethnicity): fix the
  character's author's notes, then regenerate. The research decides what the character looks like;
  if the image is right and the research is wrong, say so instead.
- `prompt`: a defect that repeats across the project (see above).

Judge against the book and the entry, not taste: a well-drawn image that departs from the entry
is a defect; a plain one that matches it is ok.

## Brief for each review agent

```text
You are reviewing illustrations for the Once Upon a Time project in <repo absolute path>, project
<slug>. Read .claude/skills/review-illustrations/SKILL.md, sections "What to check" and
"Verdicts": those are your rules. Your entities and what each image must show:

<paste this batch of the manifest, including the PROJECT and STYLE lines>

Triage notes from the main agent: <suspects for these entities, or "none">

Open every image path listed (Read tool) and compare it with its entry. Do not regenerate, edit
or delete anything. Your final message is only a JSON list of verdicts, one per image path listed,
in the format of the "Verdicts" section, followed by at most three lines on defects you saw
repeat across your batch.
```
