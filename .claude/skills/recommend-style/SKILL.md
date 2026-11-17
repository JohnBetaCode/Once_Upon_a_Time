---
name: recommend-style
description: Recommend the illustration style for a Once Upon a Time book from its vibe (genre, era, tone, audience, culture, the book's own visual tradition), then prove it with a side-by-side trial: the main character's portrait and a location rendered in two or three candidate styles on the local GPU, without touching the project's images. Use this whenever the user asks which style fits a book, is unsure what style to pick for a new project, wants to compare styles, says the images "don't feel like the book", or wants a style the app lacks (cyberpunk, ukiyo-e...), which the trial can test before it is added.
---

# Recommend a style

A project's style (`project.json` `style`, one of `STYLE_PROMPTS` in `app/core/imaging.py`) is
interpolated into every image prompt. Changing it after "Generate all" means regenerating the
whole book, so the best moment to choose is after the research and before the first portrait.

## Commands

```bash
S=.claude/skills/recommend-style/scripts/styles.py
docker compose exec -T app python - catalog [<slug>] < $S
docker compose exec -T app python - trial <slug> --styles <a>,<b>,"<clause>" --backend local [--character "<name>"] [--location "<name>"] [--no-location] < $S
docker compose exec -T app python - apply <slug> <style> < $S
```

- `catalog` prints every style with its clause, how the local GPU renders it (tuned, drifts,
  untested) and which projects use it; with a slug, the book's facts the choice rests on.
- `trial` generates, per style, the anchor portrait of the character in most passages and the
  establishing shot of the most frequent location, with the app's own functions and prompts
  (local tuning, grayscale for pencil included), into `data/style-trials/<slug>/`, plus
  `compare.jpg` with one column per style. A `--styles` entry that is not a key is used as the
  style clause verbatim (`custom-1`, ...). About 30-50 s per image on the local GPU (plus a couple
  of minutes if the model has to load); on Gemini about $0.13-0.20 per image, so say so first.
- `apply` sets the style, as the sidebar selector does, and warns when images already exist.

## Workflow

1. **Read the book.** `catalog <slug>`. With no project yet, use what you know of the book plus a
   quick web search on its covers, illustrated editions and adaptations; recommend, and the trial
   waits until the research gives it a cast.
2. **Judge the vibe**, in this order:
   - *The book's own visual tradition*: canonical illustrations (Saint-Exupéry's watercolours), an
     iconic cover or adaptation the reader will expect, the art of its era and country.
   - *Tone*: light or dark, lyrical or hard, comic or tragic, intimate or epic.
   - *Audience*: a picture book, young adult or adult literature.
   - *Setting and era*: Victorian, rural Colombia, a far future; a style anchored in the book's
     time (a 1950s storybook for a 1950s fable) usually reads better than a neutral one.
   - *Colour*: whether the world is bright, muted or black and white.
3. **Recommend** one style and two alternatives. For each: why, tied to concrete traits of the
   book (not generic adjectives); the risk on the local backend (`catalog`); and, when the gallery
   matters, that the style is not overused (`used by`). If no key fits, write a candidate clause
   (one line of concrete visual vocabulary: medium, line, palette, light, as the existing ones).
4. **Prove it.** With the user's go-ahead, `trial` the recommendation and the alternatives (a
   custom clause too), open `compare.jpg` and the full images, and judge: does the style hold on
   the local backend, does the face survive it, does the place look like the book? Show the user
   the grid, with your reading of it.
5. **Apply** the user's choice with `apply`. A custom clause first becomes a style key (the
   `illustration-prompts` skill: `STYLE_PROMPTS`, plus `LOCAL_STYLE_TUNING` if the trial drifted,
   `README.md` and `docs/usage.md`); then `apply`.

## Style profiles

| Style | Fits | Watch out |
|-------|------|-----------|
| `realistic` | adult literary fiction, hard science fiction, historical drama, anything grounded | safe and reliable locally, but generic: four projects already use it |
| `pencil` | literary classics, magic realism, memory and mourning, period pieces, introspective books | black and white only; tuned locally |
| `watercolor` | lyrical, gentle, pastoral, children's picture books, dreamlike or nostalgic stories | untested locally; soft edges can blur faces |
| `retro` | fables, classic children's literature, mid-century settings, cosy mysteries | untested locally |
| `comic` | pulp and paranoid science fiction, satire, action, unreliable reality (Philip K. Dick) | tuned locally (pale blue panel) |
| `80s-comic` | adventure, invasion and monster stories, Victorian science fiction, bright pulp | tuned locally (yellow panel) |
| `noir` | crime, hard-boiled detectives, dystopia, urban violence, moral grey zones | untested locally; black and white |
| `anime` | young adult, coming of age, Japanese works, emotional action | untested locally; faces turn young |
| `cartoon` | humour, children's books, absurd comedy (Douglas Adams) | drifts to realism on the local backend |
| `pixel-art` | games, retro computing, playful techno stories | untested locally; breaks down on detailed sheets |

These are starting points, not rules: a dark book in a bright style can be the right call when the
book is itself ironic. Untested styles are worth a `trial` before committing a whole book.
