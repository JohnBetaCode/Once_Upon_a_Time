"""Credits printed in the PDF export: a line at the foot of every page and a closing credits page.

Who did what is read from the project itself: ``source.researched_by`` (set by the book-research
skill; Gemini otherwise) and the usage log (``data/usage.jsonl``), which records the model of every
image generated for the project. Wording goes through the export's labeler, so it is translated
with the rest of the book (``app/core/translation.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core import usage

APP_NAME = "Once Upon a Time"
REPO_URL = "https://github.com/JohnBetaCode/Once_Upon_a_Time"
REPO_LABEL = "github.com/JohnBetaCode/Once_Upon_a_Time"
AUTHOR = "JohnBetaCode"

# Model ids in the usage log -> how the credits name them.
MODEL_NAMES = {
    "qwen-image-2.1-local": "Qwen-Image-2.1 (Qwen team, Alibaba), run on a local NVIDIA GPU",
    "qwen-image-2.1-turbo-local": "Qwen-Image-2.1-Turbo (Qwen team, Alibaba), run on a local NVIDIA GPU",
}


def _model_name(model: str) -> str:
    if model in MODEL_NAMES:
        return MODEL_NAMES[model]
    if model.startswith("gemini"):
        return f"{model} (Google Gemini, Vertex AI)"
    return model


def _models(slug: str, operations: set[str]) -> list[str]:
    """Models used for ``operations`` in this project, most used first."""
    counts: dict[str, int] = {}
    for entry in usage.load_entries():
        if entry.get("project") == slug and entry.get("operation") in operations and entry.get("model"):
            counts[entry["model"]] = counts.get(entry["model"], 0) + int(entry.get("images") or 1)
    return sorted(counts, key=counts.get, reverse=True)


def footer_line(t: Callable[..., str]) -> str:
    return t("Made with {app}", app=APP_NAME) + f"   ·   {REPO_LABEL}"


def credit_blocks(
    project: dict[str, Any], t: Callable[..., str], translation: dict[str, Any] | None = None
) -> list[tuple[str, list[str]]]:
    """(heading, lines) for the credits page."""
    book = project.get("book") or {}
    title = book.get("title") or project.get("name", "")
    author = book.get("author") if book.get("author") not in (None, "", "undefined") else ""
    source = project.get("source") or {}

    blocks: list[tuple[str, list[str]]] = []
    original = [f"{title}" + (f", {author}" if author else "")]
    original.append(t("This art book is an unofficial illustrated companion. The novel and its characters belong to their author and publishers."))
    blocks.append((t("The original work"), original))

    blocks.append((
        t("Made with"),
        [
            t("{app}, an open-source project by {author}", app=APP_NAME, author=AUTHOR),
            REPO_URL,
        ],
    ))

    researched_by = source.get("researched_by") or ""
    research_models = [_model_name(m) for m in _models(project["slug"], {"web_research", "extraction"})]
    if "Claude" in researched_by:
        research = [t("Claude (Anthropic), through Claude Code and the book-research skill: web research, then the app's schemas")]
    elif research_models:
        research = research_models
    else:
        research = [t("Web research and structured extraction with Google Gemini")]
    blocks.append((t("Research"), research))

    image_models = [t(_model_name(m)) for m in _models(project["slug"], {"image_generation"})]
    if image_models:
        blocks.append((t("Illustrations"), image_models))

    translated_by = ((translation or {}).get("credits") or {}).get("translation")
    if translated_by:
        blocks.append((t("Translation"), [translated_by]))

    blocks.append((
        t("Development"),
        [t("Code written with Claude Code (Anthropic), directed by {author}", author=AUTHOR)],
    ))
    blocks.append((
        t("Typography and tools"),
        [
            t("DM Serif Display, Spectral and Barlow, under the SIL Open Font License"),
            t("PDF by ReportLab; images with Pillow; app with Streamlit; local models with PyTorch and Diffusers"),
        ],
    ))
    return blocks
