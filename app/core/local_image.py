"""Client for the local image generation server (proof of concept).

The ``local-image`` Compose service (``local_image/server.py``) runs an open-weights
model (Qwen-Image-2.1 by default) on this machine's GPU. ``imaging`` calls this module
instead of ``gemini.generate_image`` when ``IMAGE_BACKEND=local``.

Calls are recorded in the usage log like Gemini calls, under a ``<model>-local`` model
name priced at $0 in ``usage.PRICING``.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

from app.core import usage
from app.core.config import get_settings

# A 2K image at 40 steps takes on the order of a minute; leave room for a cold GPU.
TIMEOUT_SECONDS = 900

START_HINT = "Start it with: docker compose --profile local-image up -d local-image"


class LocalImageError(RuntimeError):
    """Raised when the local image server is unreachable or fails."""


def model_label(model_id: str) -> str:
    """Usage-log model name for a Hugging Face model id: 'Qwen/Qwen-Image-2.1' -> 'qwen-image-2.1-local'."""
    return model_id.rsplit("/", 1)[-1].lower() + "-local"


def _url(path: str) -> str:
    return get_settings().local_image_url.rstrip("/") + path


def health() -> dict:
    """Return the server's /health payload, or raise LocalImageError."""
    try:
        with urllib.request.urlopen(_url("/health"), timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise LocalImageError(f"Local image server unreachable at {_url('')}: {exc}. {START_HINT}") from exc


def generate_image(
    prompt: str,
    reference_images: list[bytes] | None = None,
    aspect_ratio: str | None = None,
    negative_prompt: str | None = None,
    seed: int | None = None,
    guidance: float | None = None,
    size: str | None = None,
) -> bytes:
    """Generate one image (PNG bytes) on the local GPU.

    Same contract as ``gemini.generate_image``: pass the character's anchor as a
    reference image for every derived shot. ``negative_prompt`` only acts when the
    server runs with guidance (``guidance`` > 1, or LOCAL_IMAGE_CFG on the server).
    ``size`` is "1k" (fast, the size Gemini returns) or "2k" (native; needed for legible
    text on sheets); the server's LOCAL_IMAGE_SIZE applies when it is omitted.
    """
    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "aspect_ratio": aspect_ratio,
        "reference_images": [base64.b64encode(img).decode() for img in reference_images or []],
        "seed": seed,
        "guidance": guidance,
        "size": size,
    }
    request = urllib.request.Request(
        _url("/generate"),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
            data = resp.read()
            model_id = resp.headers.get("X-Model", "local-model")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise LocalImageError(f"Local image server returned {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LocalImageError(f"Local image server unreachable at {_url('')}: {exc}. {START_HINT}") from exc

    usage.record("image_generation", model_label(model_id), None, images=1)
    return data
