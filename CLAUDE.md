# Once Upon a Time — notes for Claude Code

Streamlit app that researches a book, extracts a validated cast, and generates consistent
character/location illustrations with Gemini on Vertex AI. Read `README.md` for the product
view and `docs/architecture.md` for modules and data layout.

## Conventions

- All code, comments, prompts, docs and generated text are in English.
- Business logic goes in `app/core/`; `app/ui/` only calls it and renders. Keep the UI
  modules free of Gemini SDK imports.
- Every Gemini call goes through `app/core/gemini.py` and must record usage; wrap generation
  in `usage.project_context(slug)` so cost is attributed to the project.
- LLM output is validated with the Pydantic models in `app/core/schema.py`. Missing data is
  the string `"undefined"`, never an invented value and never `null`.
- Character identity comes from the anchor image: any new image of a character must pass
  the anchor as a reference image. Do not generate identity from text twice.
- `projects/`, `data/` and `config/.env` are user data and git-ignored. Never commit them and
  never put a real GCP project ID in `config/.env.example`.
- When changing a model id (`GEMINI_*`), update `config/.env.example`, the defaults in
  `app/core/config.py`, `PRICING` in `app/core/usage.py`, and the table in `docs/usage.md`.
- When changing a UI screen shown in `docs/usage.md`, refresh the screenshot (`screenshots` skill).
  Keep `README.md` short and visual; detailed usage goes in `docs/usage.md`.

## Running

The dev loop is `docker compose up` with `app/` bind-mounted (hot reload). Streamlit is not
installed on the host; scripts that must run on the host (skills) stay stdlib-only and may
import `app.core.projects` / `app.core.usage` but not `app.core.gemini`.

## Skills

`.claude/skills/` has `run-app`, `screenshots`, `usage-report`, `inspect-project` and
`illustration-prompts`. Prefer their scripts over ad-hoc commands.
