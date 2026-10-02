---
name: run-app
description: Start, stop, rebuild, inspect or debug the Once Upon a Time Streamlit app (Docker Compose on port 8501). Use this whenever the user wants to run the app, see it working, check logs, restart after a code change, rebuild after changing requirements.txt or the Dockerfile, or asks why the UI is not loading, why Vertex AI calls fail (credentials, project ID, model names), or how to run the app without Docker.
---

# Run the app

The app is a single Streamlit process. In development it runs inside Docker Compose
(service `app`, container `once-upon-a-time`) with these bind mounts, so most changes
need no rebuild:

| Host path    | Purpose                                              | Reload behaviour                      |
|--------------|------------------------------------------------------|---------------------------------------|
| `app/`       | Python code                                          | Streamlit hot-reloads on save         |
| `projects/`  | Per-project data: JSON entities, research notes, PNGs | Read on every rerun                   |
| `data/`      | `usage.jsonl` cost log                               | Read on every rerun                   |
| `config/`    | `.env` secrets and settings                          | Loaded at process start; restart      |
| `~/.config/gcloud` | Application Default Credentials (read-only)    | Restart after `gcloud auth ...`       |

Only `requirements.txt` and the `Dockerfile` require an image rebuild.

## Commands

Use the bundled script instead of retyping compose commands:

```bash
.claude/skills/run-app/scripts/app.sh status     # container state + health check
.claude/skills/run-app/scripts/app.sh up         # start (builds if needed)
.claude/skills/run-app/scripts/app.sh logs 200   # tail logs
.claude/skills/run-app/scripts/app.sh restart    # after editing config/.env or module-level code
.claude/skills/run-app/scripts/app.sh rebuild    # after editing requirements.txt / Dockerfile
.claude/skills/run-app/scripts/app.sh down
.claude/skills/run-app/scripts/app.sh local      # no Docker: streamlit run app/main.py
```

The health endpoint is `GET /_stcore/health`; the UI is at http://localhost:8501.

## Verifying a change visually

Streamlit keeps its state in the browser session, so a plain `curl` only proves the
server is up. To see a page, use the `screenshots` skill (Playwright with the system
Chrome), which knows how to open a project and click through the tabs.

## Debugging checklist

Work through these in order; each one explains the next most common failure.

1. **Container not running or restarting**: `app.sh logs 200`. A Python traceback at
   import time means a syntax or import error in `app/`; Streamlit shows the same
   traceback in the browser once the file is fixed.
2. **"Google Cloud project is not configured"**: `GOOGLE_CLOUD_PROJECT` is empty in
   `config/.env`. The user sets it from the Settings panel on the home page, which
   writes `config/.env` (see `app/core/config.py`). Never paste a real project ID into
   `config/.env.example`.
3. **Auth errors from Vertex AI** (`DefaultCredentialsError`, 401/403): the container
   relies on the host's ADC file mounted from `~/.config/gcloud`. Run
   `gcloud auth application-default login` on the host, then `app.sh restart`. The
   project needs the Vertex AI API enabled and the caller needs `roles/aiplatform.user`.
4. **404 / model not found**: the model name or location in `config/.env` is wrong.
   Text models use `GOOGLE_CLOUD_LOCATION`; image models use `GEMINI_IMAGE_LOCATION`
   (image models are usually only served from `global`). Use "Save & test" in Settings.
5. **Image generation returns no image**: usually the safety filter. The client already
   retries once (`app/core/gemini.py`). Inspect the prompt the app built in
   `app/core/imaging.py` before changing anything else.
6. **Settings edited but behaviour unchanged**: `config/.env` is read at process start
   and Gemini clients are cached; `app.sh restart`.

## Notes

- Everything the UI does is synchronous: a "Generate all" button blocks the Streamlit
  script for the whole batch. Long operations are expected, not a hang. Check `data/usage.jsonl`
  growing to confirm progress (`usage-report` skill).
- The `projects/`, `data/` and `config/.env` paths are git-ignored. Do not commit them.
