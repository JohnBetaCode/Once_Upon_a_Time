"""Application settings.

Values are read from environment variables, with ``config/.env`` loaded
first (git-ignored; see ``config/.env.example``). Defaults below mirror
``config/.env.example`` and are used when a variable is absent. Authentication uses
Google Application Default Credentials — either a mounted ADC file
(``GOOGLE_APPLICATION_CREDENTIALS``) or ``gcloud auth application-default login``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
ENV_FILE = CONFIG_DIR / ".env"

load_dotenv(ENV_FILE)


@dataclass
class Settings:
    project: str
    text_location: str
    image_location: str
    text_model: str
    image_model: str
    # Where images are generated: "gemini" (cloud, default) or "local", an open-weights model
    # served by the local-image Compose service on this machine's NVIDIA GPU. Research and
    # extraction always use the Gemini text model.
    image_backend: str = "gemini"
    local_image_url: str = "http://local-image:8000"

    @property
    def configured(self) -> bool:
        return bool(self.project)


def get_settings() -> Settings:
    return Settings(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        text_location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        image_location=os.environ.get("GEMINI_IMAGE_LOCATION", "global"),
        text_model=os.environ.get("GEMINI_TEXT_MODEL", "gemini-3.8-flash"),
        image_model=os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3-pro-image"),
        image_backend=os.environ.get("IMAGE_BACKEND", "gemini"),
        local_image_url=os.environ.get("LOCAL_IMAGE_URL", "http://local-image:8000"),
    )


def save_settings(values: dict[str, str]) -> None:
    """Persist settings to config/.env and apply them to the running process.

    Keys in ``values`` are updated in place and new ones appended; every other line (comments,
    the local GPU server's LOCAL_IMAGE_* settings, anything set by hand) is kept as is.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text().splitlines()
    else:
        lines = ["# Once Upon a Time settings: edited from the app's Settings panel or by hand"]
    pending = dict(values)
    merged = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else None
        merged.append(f"{key}={pending.pop(key)}" if key in pending else line)
    merged += [f"{key}={value}" for key, value in pending.items()]
    ENV_FILE.write_text("\n".join(merged) + "\n")
    for key, value in values.items():
        os.environ[key] = value
