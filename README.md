![Once Upon a Time](docs/images/banner.jpg)

# 📖 Once Upon a Time

![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-app-FF4B4B?logo=streamlit&logoColor=white)
![Gemini on Vertex AI](https://img.shields.io/badge/Gemini-Vertex%20AI-4285F4?logo=googlecloud&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker-compose%20up-2496ED?logo=docker&logoColor=white)

Turn any story into consistent illustrations of its characters, locations and key passages.

Give it a book title. It researches the book, builds a validated cast, and generates studio-style
character portraits and production-design sheets with Gemini on Vertex AI, keeping every character
the same across every image.

![Cast gallery](docs/images/cast-gallery.jpg)

*Anchor portraits from six books in three of the eight styles. Every one of them started as a book
title typed into the app.*

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

## What you get

- **A researched cast.** Characters, locations and key passages gathered from the web and validated
  against a strict schema. Nothing is invented: unknown fields stay `undefined`.
- **Faithful characters.** A talking fox is still a fox. If the research gets something wrong, write
  an author's note on the character and regenerate.
- **Consistent images.** One anchor portrait per character; every other image uses it as a
  reference, so identity never drifts.
- **Eight styles.** Cartoon, realistic, retro, anime, watercolor, comic, pixel-art, noir.
- **A PDF of the whole project**, and a running estimate of what every call cost.

## Quick start

```bash
gcloud auth application-default login     # Vertex AI must be enabled on your GCP project
git clone https://github.com/JohnBetaCode/Once_Upon_a_Time.git && cd Once_Upon_a_Time
docker compose up --build
```

Open http://localhost:8501, enter your GCP project ID in **Settings**, create a project, type a
book title, and press **Research book**.

## Learn more

- [User guide](docs/usage.md): setup, walkthrough, author's notes, PDF export, configuration, costs.
- [Architecture](docs/architecture.md): modules, data layout, pipelines, design decisions.
- [Original spec](docs/once-upon-a-time-spec.md).

Built with Streamlit, Pydantic and the Gemini API on Vertex AI. Ships Claude Code skills in
`.claude/skills/` for running, inspecting and documenting the project.
