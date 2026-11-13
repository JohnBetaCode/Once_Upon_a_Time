---
name: screenshots
description: Capture or refresh screenshots of the Once Upon a Time Streamlit UI (home page, usage panel, project workspace tabs) and the sample images used in README.md and docs/. Use this whenever the user asks for screenshots, wants to update the README images after a UI change, wants to "see" how a page looks, or needs a visual check of a Streamlit change that curl cannot show. Drives the running app with Playwright and the system Chrome.
---

# UI screenshots

Streamlit pages depend on browser session state (which project is open, which tab is
selected), so a screenshot needs a real browser that clicks through the UI. The bundled
`scripts/capture.py` does that with Playwright on the system Google Chrome.

## Workflow

1. Make sure the app is running (`run-app` skill, `app.sh status`). Captures use whatever
   projects exist under `projects/`; the default project is "The little prince" because
   it has portraits and presentation sheets. Pass `--project` to use another one.
2. Set up the Playwright environment once (prints the interpreter to use):
   ```bash
   PY=$(.claude/skills/screenshots/scripts/setup.sh)
   ```
3. Capture into the scratch directory, never into the repo:
   ```bash
   $PY .claude/skills/screenshots/scripts/capture.py --out /tmp/shots --project "The little prince"
   # subset: --only characters,gallery
   ```
4. Look at every PNG before publishing (Read tool). Check for: spinners still visible,
   images not yet loaded (grey boxes), an expander left open by mistake, the settings
   panel expanded (it reveals the GCP project ID; keep it collapsed), dark theme.
5. Publish into `docs/images/` with the stable names the README links to:
   ```bash
   .claude/skills/screenshots/scripts/publish.sh /tmp/shots docs/images
   ```
   This resizes to 1280 px wide and quantizes to 255 colours so each UI screenshot stays
   well under 200 KB. Add new screens to the table below and to `docs/usage.md` (or
   `docs/setup.md` for setup screens) when you add them.

## Files the docs expect

The README shows only sample outputs (`sample-*.jpg`); UI screenshots are linked from
`docs/usage.md` and `docs/setup.md`.

| File                                  | Shows                                      | Captured from            |
|---------------------------------------|--------------------------------------------|--------------------------|
| `docs/images/ui-home.png`             | Home: settings, usage, create, project list| any state                |
| `docs/images/ui-usage.png`            | Usage & costs panel expanded               | any state                |
| `docs/images/ui-workspace-source.png` | Source tab of a researched project         | title-researched project |
| `docs/images/ui-characters.png`       | Characters tab with portrait + sheet       | project with sheets      |
| `docs/images/ui-locations.png`        | Locations tab with a generated sheet       | project with a location sheet (E2E Test) |
| `docs/images/ui-passages.png`         | Passages tab                               | any extracted project    |
| `docs/images/ui-gallery.png`          | Gallery tab                                | project with images      |
| `docs/images/ui-export.png`           | Sidebar Export PDF panel with download button | any project (builds a PDF) |
| `docs/images/ui-notes.png`            | A character card with the author's notes expander open (element screenshot, not full page) | character with notes (The Rose) |
| `docs/images/sample-pdf-export.jpg`   | 3x3 montage of PDF pages: cover, story, cast, a character and its sheet, another character, the world, a location, passages (README and user guide) | `scripts/pdf_samples.py` |
| `docs/images/sample-pdf-character.jpg`| One character page of the PDF              | `scripts/pdf_samples.py` |
| `docs/images/sample-pdf-location.jpg` | One location page of the PDF               | `scripts/pdf_samples.py` |
| `docs/images/sample-*.jpg`            | Generated outputs shown in the README (anchors, sheets) | copied from `projects/`, resized to 800/1600 px, JPEG q85 |
| `docs/images/banner.jpg`              | README hero: title plus a lineup of anchor portraits across styles | `scripts/collage.py` |
| `docs/images/cast-gallery.jpg`        | README 4x2 grid of captioned anchor portraits | `scripts/collage.py` |
| `docs/images/locations.jpg`           | README strip of three captioned establishing shots | `scripts/collage.py` |
| `docs/images/page-to-portrait.jpg`    | README "Why": researched details on paper cards, an arrow, and the anchor drawn from them | `scripts/collage.py` |
| `docs/images/social-preview.jpg`      | Banner at 1280x640 for GitHub Settings > Social preview (not linked from the docs) | `scripts/collage.py` |
| `docs/images/gallery-<book>-cast.jpg` | `docs/gallery.md`: twelve anchor portraits of one book, 6x2, no captions | `scripts/gallery.py` |
| `docs/images/gallery-<book>-world.jpg`| `docs/gallery.md`: one presentation sheet beside one establishing shot | `scripts/gallery.py` |

### Gallery

`scripts/gallery.py` builds the two images per book of `docs/gallery.md`. The books, the
portraits, the sheet and the location it shows are listed in `BOOKS` at the top of the script;
add a book there and a section to `docs/gallery.md` (title, author, style) when a project is
finished. Same Pillow-only requirements as `collage.py`:

```bash
python3 .claude/skills/screenshots/scripts/gallery.py --out /tmp/gallery   # preview, then Read the JPEGs
python3 .claude/skills/screenshots/scripts/gallery.py                      # publish into docs/images/
```

### PDF samples

After a change to the PDF layout (`app/core/export.py`, `app/core/pdf_kit.py`), rebuild the three
`sample-pdf-*.jpg` images from an export of a fully illustrated project that includes the
presentation sheets. The `export` capture above builds one, or use **Build PDF** in the app:

```bash
PDF=$(ls -t projects/<slug>/exports/*.pdf | head -1)
python3 .claude/skills/screenshots/scripts/pdf_samples.py "$PDF" --out /tmp/pdf-samples   # preview, then Read the JPEGs
python3 .claude/skills/screenshots/scripts/pdf_samples.py "$PDF"                          # publish into docs/images/
```

The script finds the pages by their text (cover, story, cast, profiles, sheets, the world,
locations, passages), so it follows the book wherever the sections land; `--character N` and
`--location N` choose which ones to feature. It needs poppler (`pdftotext`, `pdftoppm`) and
Pillow on the host. Every `export` capture writes a new PDF into `projects/<slug>/exports/`;
delete the ones you do not need.

### README banner and collages

`scripts/collage.py` composes the README images above from anchors and establishing
shots under `projects/` plus the `sample-*.jpg` files, drawing titles and captions itself (never
let the image model render text). It needs Pillow on the host, runs in about a second, and
writes 1600 px wide progressive JPEGs:

```bash
python3 .claude/skills/screenshots/scripts/collage.py --out /tmp/collages   # preview, then Read the JPEGs
python3 .claude/skills/screenshots/scripts/collage.py                        # publish into docs/images/
```

The source lists (`BANNER_SOURCES`, `CAST_SOURCES`, `LOCATION_SOURCES`, `PAGE_SOURCES`) are at
the top of the script; edit them to swap characters. The details on the `PAGE_SOURCES` paper cards
are condensed by hand from that character's research in `characters.json`: keep them faithful to
the data and short enough for four or five wrapped lines. Missing files are skipped with a warning, so the script
still runs on a clone whose `projects/` differ. Pick upright 2:3 anchors for the banner; wide or
square images are shown whole over a blurred copy of themselves, and a `(path, (l, t, r, b))`
entry crops to the figure first.

Sample outputs come from `projects/<slug>/characters/<slug>/{anchor,sheet}.png` and
`projects/<slug>/locations/*-sheet.png`. Convert them with
`convert in.png -resize 1600x -quality 85 out.jpg` so the repository does not grow by
megabytes per image. `projects/` itself is git-ignored.

## Why the images live in the repo

GitHub's issue-attachment uploader is browser-only (no API or `gh` support), so the
documentation images are committed under `docs/images/` and linked with relative paths.
That keeps the README self-contained in forks and offline clones.

## Selector notes (when the UI changes)

- Tabs: `page.get_by_role("tab", name="Characters")`.
- Project card "Open" button: the card is a `stHorizontalBlock` whose left column contains
  the project name in `<strong>`. If Streamlit renames the test id, dump the ancestry with
  `locator.evaluate(...)` and update the XPath in `capture.py`.
- Expanders toggle by clicking their label text.
- Allow 2-4 s after each click: images are served lazily and the Streamlit rerun is async.
