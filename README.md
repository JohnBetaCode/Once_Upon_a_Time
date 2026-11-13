![Once Upon a Time](docs/images/banner.jpg)

# 📖 Once Upon a Time

![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-app-FF4B4B?logo=streamlit&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-image%20%2B%20research-8E75B2?logo=googlegemini&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker-compose%20up-2496ED?logo=docker&logoColor=white)

Turn any story into consistent illustrations of its characters, locations and key passages.

Give it a book title. It researches the book, builds a validated cast, and generates studio-style
character portraits and production-design sheets with Gemini, keeping every character the same
across every image. When you are done, it binds the whole project into an art book.

## Why I built this

> *I always wanted to meet the characters the way the author wrote them.*

Every book I've loved left me with a cast I could almost see. Almost. A face would shift between
chapters. A creature the author spent a whole page describing would come out of my head as a vague
shape. A two-headed, three-armed galactic president never quite assembled. I wanted the most
faithful version possible, and sometimes my imagination just didn't get there.

So I built the companion I wanted next to me while reading. Give it a title and it goes looking for
every detail the book, and the people who have studied it, have to say about each character, writes
them into a sheet, and draws them. When the research leans on a film instead of the page, an
author's note pulls it back. Once a character has a face, it keeps it in every image that follows.

It doesn't replace your imagination. It gives it something solid to stand on.

![From the notes to the portrait](docs/images/page-to-portrait.jpg)

## The cast so far

![Cast gallery](docs/images/cast-gallery.jpg)

*Anchor portraits from six books in three of the ten styles. Every one of them started as a book
title typed into the app.* The [gallery](docs/gallery.md) shows whole books, each in its own style:
comic, realistic, 80s comic and pencil.

## From anchor to presentation sheet

One anchor portrait per character; every later image uses it as a reference image, so the sheet
shows the same individual from every angle.

| Anchor portrait | Presentation sheet |
|---|---|
| ![The Fox](docs/images/sample-fox-anchor.jpg) | ![The Fox sheet](docs/images/sample-fox-sheet.jpg) |
| ![Hari Seldon](docs/images/sample-seldon-anchor.jpg) | ![Hari Seldon sheet](docs/images/sample-seldon-sheet.jpg) |

The Fox from *The Little Prince* (cartoon, and still a real fox) and Hari Seldon from *Foundation*
(realistic).

## Locations too

An establishing shot per location, then an environment sheet with views, moods, palette and details.

![Locations](docs/images/locations.jpg)

![The Ugly Duckling farmyard](docs/images/sample-location-sheet.jpg)

## And a book at the end

One click turns the project into a landscape art book: a cover, the story, the cast, a page for
every character and location, their sheets as full-page plates, and the key passages. Its colours
come from the cover artwork, so every book looks like itself.

![Pages of the exported PDF](docs/images/sample-pdf-export.jpg)

*The Hitchhiker's Guide to the Galaxy, exported as it stood: 48 pages.*

## What you get

- **A researched cast.** Characters, locations and key passages gathered from the web and validated
  against a strict schema. Nothing is invented: unknown fields stay `undefined`.
- **Faithful characters.** A talking fox is still a fox. If the research gets something wrong, write
  an author's note on the character and regenerate.
- **Consistent images.** One anchor portrait per character; every other image uses it as a
  reference, so identity never drifts.
- **Ten styles.** Cartoon, realistic, retro, anime, watercolor, comic, 80s comic, pencil, pixel-art, noir.
- **Cloud or your own GPU.** Images come from Gemini, or from an open model on an NVIDIA GPU with
  24 GB or more, at no cost per image.
- **A book to keep.** The whole project as an art-book PDF, at any point, even half illustrated.
- **Costs in view.** A running estimate of what every call cost.

## Try it

The [setup guide](docs/setup.md) gets it running with one command. Then create a project, type
the title of a book you love, and press **Research book**.

## Learn more

- [Setup](docs/setup.md): what you need, launching it, images on your own GPU, configuration,
  troubleshooting.
- [Local GPU images](docs/local-gpu-evaluation.md): how the local model compares with Gemini.
- [User guide](docs/usage.md): your first book, author's notes, PDF export, costs, roadmap.
- [Gallery](docs/gallery.md): finished books, their casts and worlds, one style each.
- [Architecture](docs/architecture.md): modules, data layout, pipelines, design decisions.
- [Original spec](docs/once-upon-a-time-spec.md).

Built with Streamlit, Pydantic and Gemini. Ships Claude Code skills in `.claude/skills/` for
running, inspecting and documenting the project.
