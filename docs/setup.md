# Setup

How to install, configure and run Once Upon a Time. Once it is running, the
[user guide](usage.md) walks you through your first book.

## Contents

1. [What you need](#what-you-need)
2. [Google Cloud and Vertex AI](#google-cloud-and-vertex-ai)
3. [Run with Docker](#run-with-docker)
4. [Run locally](#run-locally)
5. [Configuration](#configuration)
6. [Troubleshooting](#troubleshooting)

## What you need

- Docker with the Compose plugin, or Python 3.12 to run without Docker.
- A Google Cloud project with billing active. Every research and image call goes to Gemini on
  Vertex AI and is billed to that project; the app shows a running estimate of the cost.
- The [gcloud CLI](https://cloud.google.com/sdk/docs/install).

## Google Cloud and Vertex AI

1. Enable the **Vertex AI API** on your project.
2. Give the account you will use the `roles/aiplatform.user` role on that project.
3. Log in with Application Default Credentials:

   ```bash
   gcloud auth application-default login
   ```

The app authenticates with those credentials; there are no API keys to create. With Docker, the
container mounts `~/.config/gcloud` read-only, so no credential file is copied into the image or
the repository.

## Run with Docker

```bash
git clone https://github.com/JohnBetaCode/Once_Upon_a_Time.git
cd Once_Upon_a_Time
cp config/.env.example config/.env       # optional: everything can be set from the Settings panel
docker compose up --build
```

Open http://localhost:8501. On first launch the **⚙️ Settings** panel is expanded: enter your GCP
project ID, keep the default models and locations unless you know otherwise, and click
**Save & test**. Settings are written to `config/.env`, which is git-ignored.

![Home page](images/ui-home.png)

Code under `app/` is bind-mounted and hot-reloads. Rebuild only after changing
`requirements.txt` or the `Dockerfile`.

> **Keep it private.** The app has no login of its own, and Compose publishes port 8501 on every
> network interface. Anyone who can reach that port can generate images billed to your project and
> read the project ID in Settings. Use it on your machine, your home network or a VPN, and never
> expose the port to the internet.

## Run locally

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/main.py
```

The PDF export uses DejaVu Sans when it is installed (`fonts-dejavu-core` on Debian/Ubuntu) and
falls back to Helvetica otherwise.

## Configuration

Values live in `config/.env` and can be edited from the Settings panel. They are read at start-up,
so restart the app after editing the file by hand.

| Variable                 | Default (`.env.example`) | Purpose                                                      |
|--------------------------|--------------------------|--------------------------------------------------------------|
| `GOOGLE_CLOUD_PROJECT`   | (required)               | GCP project that hosts Vertex AI and gets billed             |
| `GOOGLE_CLOUD_LOCATION`  | `global`                 | Region for the text model (research and extraction)          |
| `GEMINI_IMAGE_LOCATION`  | `global`                 | Region for the image model                                   |
| `GEMINI_TEXT_MODEL`      | `gemini-3.8-flash`       | Model for web research and structured extraction             |
| `GEMINI_IMAGE_MODEL`     | `gemini-3-pro-image`     | Image model (supports reference images for consistency)      |

## Troubleshooting

| Symptom | What to do |
|---|---|
| The page does not load | `docker compose ps`, then `docker compose logs --tail 200`. A Python traceback at start-up points at the broken file. |
| "Google Cloud project is not configured" | Enter the project ID in **Settings** and click **Save & test**. |
| `DefaultCredentialsError`, 401 or 403 | Run `gcloud auth application-default login` again, check the Vertex AI API and the `roles/aiplatform.user` role, then `docker compose restart`. |
| 404 or "model not found" | The model name or location is wrong. Image models are usually served only from `global`. |
| 429 `RESOURCE_EXHAUSTED` | You hit the per-minute token quota. Wait a minute and research one book at a time; failed characters can be retried with **Deep research** on their card. |
| A portrait comes back empty | Usually the safety filter; the app already retries once. Reword the character with an author's note and regenerate. |
| You edited `config/.env` and nothing changed | Settings are loaded at start-up: `docker compose restart`. |
