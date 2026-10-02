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
   well under 200 KB. Add new screens to the table below and to `docs/usage.md` when you add them.

## Files the docs expect

The README shows only sample outputs (`sample-*.jpg`); UI screenshots are linked from
`docs/usage.md`.

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
| `docs/images/sample-pdf-export.jpg`   | Montage of the first PDF pages (`pdftoppm` + `montage`) | a built export |
| `docs/images/sample-*.jpg`            | Generated outputs shown in the README (anchors, sheets) | copied from `projects/`, resized to 800/1600 px, JPEG q85 |

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
