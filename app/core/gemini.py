"""Gemini on Vertex AI client.

All LLM calls go through this module:
  - ``web_research``      — web-grounded query (Google Search grounding).
  - ``extract_structured`` — structured output validated against a Pydantic schema.
  - ``generate_image``    — image generation, optionally with reference images
                            (anchor -> derived shots for character consistency).

Auth: Google Application Default Credentials. Settings: ``config/.env``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core import usage
from app.core.config import get_settings

T = TypeVar("T", bound=BaseModel)


class GeminiError(RuntimeError):
    """Raised when a Gemini call fails or returns an unusable response."""


@lru_cache(maxsize=4)
def _client(location: str) -> genai.Client:
    settings = get_settings()
    if not settings.configured:
        raise GeminiError(
            "Google Cloud project is not configured. "
            "Set GOOGLE_CLOUD_PROJECT in config/.env (see Settings panel)."
        )
    return genai.Client(vertexai=True, project=settings.project, location=location)


def reset_clients() -> None:
    """Drop cached clients (call after settings change)."""
    _client.cache_clear()


def check_connection() -> str:
    """Cheap connectivity test; returns the model's reply or raises GeminiError."""
    settings = get_settings()
    try:
        response = _client(settings.text_location).models.generate_content(
            model=settings.text_model,
            contents="Reply with the single word: ok",
        )
        usage.record("connection_test", settings.text_model, response.usage_metadata)
        return (response.text or "").strip()
    except Exception as exc:  # surface a clean message to the UI
        raise GeminiError(str(exc)) from exc


def web_research(prompt: str) -> tuple[str, list[dict[str, str]]]:
    """Run a web-grounded query. Returns (answer_text, sources).

    Sources are ``{"title": ..., "uri": ...}`` dicts from grounding metadata.
    """
    settings = get_settings()
    try:
        response = _client(settings.text_location).models.generate_content(
            model=settings.text_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
    except Exception as exc:
        raise GeminiError(f"Web research call failed: {exc}") from exc

    usage.record("web_research", settings.text_model, response.usage_metadata, web_search=True)
    if not response.text:
        raise GeminiError("Web research returned an empty response.")

    sources: list[dict[str, str]] = []
    candidate = response.candidates[0] if response.candidates else None
    metadata = candidate.grounding_metadata if candidate else None
    for chunk in (metadata.grounding_chunks or []) if metadata else []:
        if chunk.web and chunk.web.uri:
            sources.append({"title": chunk.web.title or chunk.web.uri, "uri": chunk.web.uri})
    return response.text, sources


def extract_structured(prompt: str, schema: type[T]) -> T:
    """Run a structured-output call validated against ``schema``."""
    settings = get_settings()
    try:
        response = _client(settings.text_location).models.generate_content(
            model=settings.text_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
    except Exception as exc:
        raise GeminiError(f"Structured extraction call failed: {exc}") from exc

    usage.record("extraction", settings.text_model, response.usage_metadata)
    parsed = response.parsed
    if parsed is None:
        # Repair-retry: re-validate the raw text through the schema once.
        try:
            parsed = schema.model_validate_json(response.text or "")
        except Exception as exc:
            raise GeminiError(f"Model output failed schema validation: {exc}") from exc
    return parsed


def generate_image(
    prompt: str,
    reference_images: list[bytes] | None = None,
    aspect_ratio: str | None = None,
) -> bytes:
    """Generate one image (PNG bytes), optionally conditioned on references.

    Character consistency: pass the character's anchor image as a reference
    for every derived shot and passage scene.
    """
    settings = get_settings()
    parts: list[types.Part] = [
        types.Part.from_bytes(data=img, mime_type="image/png")
        for img in (reference_images or [])
    ]
    parts.append(types.Part.from_text(text=prompt))

    config = types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])
    if aspect_ratio:
        config.image_config = types.ImageConfig(aspect_ratio=aspect_ratio)

    # The model occasionally returns a response with no image part; retry once.
    last_error = "Image generation returned no image (possibly blocked by safety filters)."
    for _ in range(2):
        try:
            response = _client(settings.image_location).models.generate_content(
                model=settings.image_model,
                contents=types.Content(role="user", parts=parts),
                config=config,
            )
        except Exception as exc:
            raise GeminiError(f"Image generation call failed: {exc}") from exc

        usage.record("image_generation", settings.image_model, response.usage_metadata, images=1)
        candidate = response.candidates[0] if response.candidates else None
        for part in (candidate.content.parts or []) if candidate and candidate.content else []:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data
    raise GeminiError(last_error)
