"""Translations of a project's text for the PDF export.

The research is stored in English (``characters.json`` and friends). A project can carry a
translation per language in ``translations/<lang>.json``; the export overlays it on the English
data and prints its own labels in that language. Anything the file leaves out stays in English,
and image paths keep using the original names, so translating a name never loses its pictures.

``translations/<lang>.json``::

    {
      "book": {"title": ..., "genre": ..., "original_language": ..., "themes": [...], "summary": ...},
      "characters": {"<English name>": {"name": ..., "role": ..., "aliases": [...],
                     "physical_description": ..., "notes": ..., "sheet": {"<field>": ...}}},
      "locations": {"<English name>": {"name": ..., "description": ..., "relevance": ...}},
      "passages": {"<English title>": {"title": ..., "passage_type": ..., "summary": ...}},
      "credits": {"translation": "<who translated it>"}
    }
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.projects import project_path

LANGUAGE_NAMES = {"en": "English", "es": "Español"}

# The export's fixed wording, by language. Keys are the English text.
LABELS: dict[str, dict[str, str]] = {
    "es": {
        "Once Upon a Time": "Once Upon a Time",
        "Character & world bible": "Biblia de personajes y mundo",
        "Characters, locations and key passages": "Personajes, lugares y pasajes clave",
        "character": "personaje",
        "characters": "personajes",
        "location": "lugar",
        "locations": "lugares",
        "key passage": "pasaje clave",
        "key passages": "pasajes clave",
        "moment": "momento",
        "moments": "momentos",
        "that carry the story": "que sostienen la historia",
        "{style} style": "estilo {style}",
        "The story": "La historia",
        "About this project": "Sobre este proyecto",
        "Author": "Autor",
        "First published": "Primera edición",
        "Genre": "Género",
        "Original language": "Idioma original",
        "Illustration style": "Estilo de ilustración",
        "Themes": "Temas",
        "The cast": "El reparto",
        "Characters": "Personajes",
        "Character": "Personaje",
        "Deep-researched": "Investigación a fondo",
        "Also known as {aliases}": "También conocido como {aliases}",
        "Author's notes": "Notas del autor",
        "No portrait yet": "Sin retrato todavía",
        "Production-design presentation sheet": "Hoja de presentación de diseño de producción",
        "The world": "El mundo",
        "Locations": "Lugares",
        "Location {number}": "Lugar {number}",
        "In the story": "En la historia",
        "Environment presentation sheet": "Hoja de presentación del entorno",
        "Key passages": "Pasajes clave",
        "Where": "Dónde",
        "With": "Con",
        "Appendix": "Apéndice",
        "Research sources": "Fuentes de investigación",
        "Book research": "Investigación del libro",
        # Credits (app/core/credits.py)
        "Made with {app}": "Hecho con {app}",
        "Colophon": "Colofón",
        "Credits": "Créditos",
        "The original work": "La obra original",
        "This art book is an unofficial illustrated companion. The novel and its characters belong to their author and publishers.":
            "Este libro de arte es un acompañamiento ilustrado no oficial. La novela y sus personajes pertenecen a su autor y a sus editores.",
        "Made with": "Hecho con",
        "{app}, an open-source project by {author}": "{app}, un proyecto de código abierto de {author}",
        "Research": "Investigación",
        "Claude (Anthropic), through Claude Code and the book-research skill: web research, then the app's schemas":
            "Claude (Anthropic), con Claude Code y la skill book-research: investigación web validada con los esquemas de la app",
        "Web research and structured extraction with Google Gemini": "Investigación web y extracción estructurada con Google Gemini",
        "Illustrations": "Ilustraciones",
        "Qwen-Image-2.1 (Qwen team, Alibaba), run on a local NVIDIA GPU": "Qwen-Image-2.1 (equipo Qwen, Alibaba), en una GPU NVIDIA local",
        "Qwen-Image-2.1-Turbo (Qwen team, Alibaba), run on a local NVIDIA GPU": "Qwen-Image-2.1-Turbo (equipo Qwen, Alibaba), en una GPU NVIDIA local",
        "Translation": "Traducción",
        "Development": "Desarrollo",
        "Code written with Claude Code (Anthropic), directed by {author}": "Código escrito con Claude Code (Anthropic), dirigido por {author}",
        "Typography and tools": "Tipografía y herramientas",
        "DM Serif Display, Spectral and Barlow, under the SIL Open Font License": "DM Serif Display, Spectral y Barlow, bajo la SIL Open Font License",
        "PDF by ReportLab; images with Pillow; app with Streamlit; local models with PyTorch and Diffusers":
            "PDF con ReportLab; imágenes con Pillow; app con Streamlit; modelos locales con PyTorch y Diffusers",
        # Character sheet fields
        "form": "forma",
        "gender": "género",
        "species": "especie",
        "age": "edad",
        "height": "estatura",
        "build": "complexión",
        "hair": "cabello",
        "eyes": "ojos",
        "skin": "piel",
        "attire": "vestimenta",
        "distinctive traits": "rasgos distintivos",
        # Illustration styles
        "cartoon": "caricatura",
        "realistic": "realista",
        "retro": "retro",
        "anime": "anime",
        "watercolor": "acuarela",
        "comic": "cómic",
        "80s-comic": "cómic de los 80",
        "pencil": "lápiz",
        "pixel-art": "pixel art",
        "noir": "noir",
    },
}

MONTHS = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
           "octubre", "noviembre", "diciembre"],
}


def translation_path(project: dict[str, Any], language: str) -> Path:
    return project_path(project["slug"]) / "translations" / f"{language}.json"


def available_languages(project: dict[str, Any]) -> list[str]:
    """English, plus every language the project has a translation file for."""
    folder = project_path(project["slug"]) / "translations"
    found = sorted(p.stem for p in folder.glob("*.json")) if folder.exists() else []
    return ["en"] + [lang for lang in found if lang != "en"]


def load_translation(project: dict[str, Any], language: str) -> dict[str, Any]:
    if language == "en":
        return {}
    path = translation_path(project, language)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def labeler(language: str) -> Callable[..., str]:
    """``t("Text {x}", x=...)``: the export's wording in ``language``, English when missing."""
    table = LABELS.get(language, {})

    def t(text: str, **values: Any) -> str:
        return table.get(text, text).format(**values) if values else table.get(text, text)

    return t


def month_name(language: str, month: int) -> str | None:
    names = MONTHS.get(language)
    return names[month - 1] if names else None


def source_name(entity: dict[str, Any]) -> dict[str, Any]:
    """The entity as stored on disk (original name), for image and research paths."""
    return {**entity, "name": entity.get("_source_name", entity.get("name", ""))}


def translate_book(project: dict[str, Any], translation: dict[str, Any]) -> dict[str, Any]:
    book = {**(project.get("book") or {}), **(translation.get("book") or {})}
    return {**project, "book": book}


def translate_entities(
    characters: list[dict[str, Any]],
    locations: list[dict[str, Any]],
    passages: list[dict[str, Any]],
    translation: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Overlay the translation; translated entities keep their original name in ``_source_name``."""
    if not translation:
        return characters, locations, passages
    tr_chars = translation.get("characters") or {}
    tr_locs = translation.get("locations") or {}
    tr_pass = translation.get("passages") or {}

    def overlay(entity: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
        merged = {**entity, **{k: v for k, v in changes.items() if k != "sheet"}, "_source_name": entity["name"]}
        if changes.get("sheet"):
            merged["sheet"] = {**(entity.get("sheet") or {}), **changes["sheet"]}
        return merged

    characters = [overlay(c, tr_chars.get(c["name"], {})) for c in characters]
    locations = [overlay(loc, tr_locs.get(loc["name"], {})) for loc in locations]
    char_names = {c["_source_name"]: c["name"] for c in characters}
    loc_names = {loc["_source_name"]: loc["name"] for loc in locations}
    out_passages = []
    for passage in passages:
        merged = {**passage, **(tr_pass.get(passage.get("title", "")) or {})}
        merged["characters_present"] = [char_names.get(n, n) for n in passage.get("characters_present") or []]
        merged["location"] = loc_names.get(passage.get("location"), passage.get("location"))
        out_passages.append(merged)
    return characters, locations, out_passages
