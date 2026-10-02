"""Project management.

Each project lives in its own folder under ``projects/`` (git-ignored):

    projects/<slug>/
        project.json     # project metadata and pipeline status
        source/          # raw source material (text file, pdf, research notes)
        characters/      # extracted character sheets + generated images
        locations/       # extracted locations + generated images
        passages/        # extracted key passages + generated scene images
        images/          # misc / gallery images
        exports/         # PDF exports of the project state

``project.json`` is the single metadata file for the project for now.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECTS_DIR = Path(__file__).resolve().parents[2] / "projects"

PROJECT_SUBDIRS = ["source", "characters", "locations", "passages", "images", "exports"]

SOURCE_TYPES = ("text", "title", "pdf")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "project"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_path(slug: str) -> Path:
    return PROJECTS_DIR / slug


def list_projects() -> list[dict[str, Any]]:
    """Return metadata for every project on disk, newest first."""
    projects = []
    if not PROJECTS_DIR.exists():
        return projects
    for meta_file in sorted(PROJECTS_DIR.glob("*/project.json")):
        try:
            projects.append(json.loads(meta_file.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    projects.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return projects


def load_project(slug: str) -> dict[str, Any] | None:
    meta_file = project_path(slug) / "project.json"
    if not meta_file.exists():
        return None
    return json.loads(meta_file.read_text())


def save_project(project: dict[str, Any]) -> None:
    project["updated_at"] = _now()
    meta_file = project_path(project["slug"]) / "project.json"
    meta_file.write_text(json.dumps(project, indent=2, ensure_ascii=False))


def create_project(name: str, description: str = "", style: str = "cartoon") -> dict[str, Any]:
    """Create the project folder tree and its metadata file."""
    slug = _slugify(name)
    if project_path(slug).exists():
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    root = project_path(slug)
    for sub in PROJECT_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)

    project = {
        "id": uuid.uuid4().hex,
        "slug": slug,
        "name": name.strip(),
        "description": description.strip(),
        "style": style,
        "status": "created",  # created -> ingested -> extracted -> illustrated
        "source": None,  # {"type": "text"|"title"|"pdf", ...}
        "created_at": _now(),
        "updated_at": _now(),
    }
    save_project(project)
    return project


def delete_project(slug: str) -> None:
    root = project_path(slug)
    if root.exists():
        shutil.rmtree(root)
