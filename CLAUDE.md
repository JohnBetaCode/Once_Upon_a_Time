# Once Upon a Time — notes for Claude Code

Streamlit app that researches a book, extracts a validated cast, and generates consistent
character/location illustrations with Gemini on Vertex AI or, optionally, with an open-weights
model (Qwen-Image-2.1) on a local NVIDIA GPU. Read `README.md` for the product
view and `docs/architecture.md` for modules and data layout.

## Conventions

- All code, comments, prompts, docs and generated text are in English.
- Business logic goes in `app/core/`; `app/ui/` only calls it and renders. Keep the UI
  modules free of Gemini SDK imports.
- Every Gemini call goes through `app/core/gemini.py` and must record usage; wrap generation
  in `usage.project_context(slug)` so cost is attributed to the project.
- Images go through `imaging._generate_image`, which routes by `IMAGE_BACKEND` to
  `gemini.generate_image` or `local_image.generate_image` (HTTP to `local_image/server.py`, logged
  as `<model>-local` at $0). Prompt changes must keep the Gemini request unchanged unless that is
  the intent, and be checked on both backends; the local prompts live next to the Gemini ones.
- `local_image/` is its own container with pinned dependencies (torch, diffusers commit). Nothing
  under `app/` imports torch or diffusers.
- LLM output is validated with the Pydantic models in `app/core/schema.py`. Missing data is
  the string `"undefined"`, never an invented value and never `null`.
- Character identity comes from the anchor image: any new image of a character must pass
  the anchor as a reference image. Do not generate identity from text twice.
- The PDF export is laid out in `app/core/export.py` from the parts in `app/core/pdf_kit.py`
  (fonts, palette, image preparation, flowables). Its fonts are bundled under `app/assets/fonts`
  with their OFL licences; fallback fonts for other scripts come from the `Dockerfile`. After a
  layout change, export a fully illustrated project and one without images, and look at the pages.
- `projects/`, `data/` and `config/.env` are user data and git-ignored. Never commit them and
  never put a real GCP project ID in `config/.env.example`.
- When changing a model id (`GEMINI_*`), update `config/.env.example`, the defaults in
  `app/core/config.py`, `PRICING` in `app/core/usage.py`, and the table in `docs/setup.md`. For the
  local model (`LOCAL_IMAGE_MODEL`), update the default in `local_image/server.py`, the commented
  line in `config/.env.example`, the second table in `docs/setup.md`, and add `<model>-local` at
  $0 to `PRICING`.
- `config/.env` is shared: the app's Settings panel edits its keys in place and keeps the rest,
  and the local GPU server reads its `LOCAL_IMAGE_*` keys at container start. The model weights live
  in the shared external volume `local-image-models`, which `launch.sh` creates (on
  `LOCAL_IMAGE_MODELS_DIR` when set); never declare it as a per-project volume.
- When changing a UI screen shown in `docs/usage.md` or `docs/setup.md`, refresh the screenshot
  (`screenshots` skill). Keep `README.md` short and visual, with no setup, credential or Vertex AI
  details: installation and configuration go in `docs/setup.md`, detailed usage in `docs/usage.md`.

## Running

`./launch.sh` starts everything and adds the local GPU server (Compose profile `gpu`) when the
machine can run it; `./launch.sh status` shows both. The dev loop is `docker compose up` with
`app/` bind-mounted (hot reload). Streamlit is not
installed on the host; scripts that must run on the host (skills) stay stdlib-only and may
import `app.core.projects` / `app.core.usage` but not `app.core.gemini`.

## Skills

`.claude/skills/` has `run-app`, `screenshots`, `usage-report`, `inspect-project` and
`illustration-prompts`. Prefer their scripts over ad-hoc commands.
