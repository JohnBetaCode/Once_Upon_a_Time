"""Client for the local GPU image server (``local_image/server.py``).

When ``IMAGE_BACKEND=local``, ``imaging`` sends every image request here instead of
``gemini.generate_image``: the ``local-image`` Compose service runs an open-weights model
(Qwen-Image-2.1 by default) on this machine's NVIDIA GPU.

Calls are recorded in the usage log like Gemini calls, under a ``<model>-local`` model name
priced at $0 in ``usage.PRICING``.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request

from app.core import usage
from app.core.config import get_settings

# A 2K sheet takes ~105 s on an RTX 5090, and a request after an idle unload also reloads
# the model; leave room for slower GPUs.
TIMEOUT_SECONDS = 900

LAUNCH_HINT = "Start it with ./launch.sh gpu (or: docker compose --profile gpu up -d)."

class LocalImageError(RuntimeError):
    """Raised when the local image server is unreachable, not ready, or fails."""


# (url, timestamp, payload or error) of the last /health call
_health_cache: tuple[str, float, dict | LocalImageError] | None = None


def model_label(model_id: str) -> str:
    """Usage-log model name for a Hugging Face model id: 'Qwen/Qwen-Image-2.1' -> 'qwen-image-2.1-local'."""
    return model_id.rsplit("/", 1)[-1].lower() + "-local"


def _url(path: str) -> str:
    return get_settings().local_image_url.rstrip("/") + path


def _detail(exc: urllib.error.HTTPError) -> str:
    body = exc.read().decode(errors="replace")
    try:
        return str(json.loads(body).get("detail", body))
    except ValueError:
        return body[:300]


def health(max_age: float = 0) -> dict:
    """The server's /health payload; raises LocalImageError when it is unreachable.

    ``max_age`` reuses the last answer, reachable or not, for that many seconds: UI reruns
    poll it, and resolving a Compose service that is not running can take a moment.
    """
    global _health_cache
    now = time.time()
    url = _url("/health")
    if max_age and _health_cache and _health_cache[0] == url and now - _health_cache[1] < max_age:
        result = _health_cache[2]
        if isinstance(result, LocalImageError):
            raise result
        return result
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            result = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        result = LocalImageError(f"The local GPU server is not reachable at {_url('')}. {LAUNCH_HINT}")
        result.__cause__ = exc
    _health_cache = (url, now, result)
    if isinstance(result, LocalImageError):
        raise result
    return result


def describe(info: dict) -> tuple[str, str]:
    """(level, sentence) summarising a /health payload; level is success|info|warning|error."""
    status = info.get("status")
    where = f"{info.get('model')} on {info.get('gpu') or 'the GPU'}"
    if status == "ready":
        return "success", f"Local GPU server ready: {where}."
    if status == "idle":
        return "success", (f"Local GPU server ready: {where}. The model is unloaded while idle; "
                           "the next image reloads it in a few seconds.")
    if status in ("checking", "loading"):
        return "info", f"Local GPU server is {status}: {where}."
    if status == "downloading":
        return "info", f"Local GPU server is {info.get('message') or 'downloading the model weights.'}"
    return "error", f"Local GPU server cannot generate images: {info.get('message') or info.get('error') or status}"


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

    Same contract as ``gemini.generate_image``: pass the character's anchor as a reference
    image for every derived shot. ``negative_prompt`` only acts when the server runs with
    guidance (``guidance`` > 1, or LOCAL_IMAGE_CFG). ``size`` is "1k" (fast, the size Gemini
    returns) or "2k" (native; needed for legible text on sheets); LOCAL_IMAGE_SIZE applies
    when it is omitted.
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
        raise LocalImageError(f"Local GPU server: {_detail(exc)}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LocalImageError(f"The local GPU server is not reachable at {_url('')}. {LAUNCH_HINT}") from exc

    usage.record("image_generation", model_label(model_id), None, images=1)
    return data
