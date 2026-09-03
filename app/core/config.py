"""Application settings.

Values are read from environment variables, with ``config/.env`` loaded
first (git-ignored; see ``config/.env.example``). Authentication uses
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

    @property
    def configured(self) -> bool:
        return bool(self.project)


def get_settings() -> Settings:
    return Settings(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        text_location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        image_location=os.environ.get("GEMINI_IMAGE_LOCATION", "global"),
        text_model=os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash"),
        image_model=os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"),
    )


def save_settings(values: dict[str, str]) -> None:
    """Persist settings to config/.env and apply them to the running process."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Gemini on Vertex AI — managed from the app's Settings panel"]
    for key, value in values.items():
        lines.append(f"{key}={value}")
        os.environ[key] = value
    ENV_FILE.write_text("\n".join(lines) + "\n")
