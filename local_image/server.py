"""Local image generation server (proof of concept).

Serves an open-weights text-to-image / multi-reference editing model on the local GPU
behind a tiny HTTP API, so the app can swap it in for Gemini image generation.

    GET  /health    {"status": "loading" | "ready" | "error", "model": ..., ...}
    POST /generate  JSON {prompt, negative_prompt?, aspect_ratio?, reference_images?: [base64],
                          steps?, seed?, guidance?, size?, transparent?}  ->  image/png
                    headers: X-Model, X-Seed, X-Elapsed-Seconds, X-Peak-VRAM-GB, X-CFG,
                    X-Ignored (negative_prompt when guidance <= 1)

Environment: LOCAL_IMAGE_MODEL, LOCAL_IMAGE_STEPS (40), LOCAL_IMAGE_SIZE (default per-request size: 1k | 2k),
LOCAL_IMAGE_CFG (1.0 = no guidance, as the model is meant to run), LOCAL_IMAGE_OFFLOAD.

The model loads in a background thread at start-up (the first start downloads the
weights into the /models volume). Requests are served one at a time.
"""

from __future__ import annotations

import base64
import inspect
import io
import logging
import os
import random
import threading
import time
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field

MODEL_ID = os.environ.get("LOCAL_IMAGE_MODEL", "Qwen/Qwen-Image-2.1")
DEFAULT_STEPS = int(os.environ.get("LOCAL_IMAGE_STEPS", "40"))
# "model": components move to the GPU only while they run (the bf16 weights are ~33 GB, more
# than a 32 GB card holds at once). "none": keep everything on the GPU (needs a bigger card).
OFFLOAD = os.environ.get("LOCAL_IMAGE_OFFLOAD", "model")
# Output size per aspect ratio, from the model card (native 2K). "1k" halves them, which
# matches the sizes Gemini returns (e.g. 848x1264 for 2:3) and is the pipeline's default scale.
ASPECT_SIZES_2K = {
    "1:1": (2048, 2048),
    "4:3": (2400, 1792),
    "3:4": (1792, 2400),
    "3:2": (2528, 1696),
    "2:3": (1696, 2528),
    "16:9": (2752, 1536),
    "9:16": (1536, 2752),
}
ASPECT_SIZES = {
    "2k": ASPECT_SIZES_2K,
    "1k": {k: (w // 2, h // 2) for k, (w, h) in ASPECT_SIZES_2K.items()},
}
SIZE = os.environ.get("LOCAL_IMAGE_SIZE", "1k")  # default when a request does not say
# Qwen-Image-2.1 is meant to be sampled without guidance (true_cfg_scale 1.0); a negative
# prompt only acts when guidance is > 1, which also doubles the compute per step.
DEFAULT_CFG = float(os.environ.get("LOCAL_IMAGE_CFG", "1.0"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per weight-file request otherwise
log = logging.getLogger("local-image")

state: dict = {"status": "loading", "model": MODEL_ID, "error": None, "params": []}
pipe = None
lock = threading.Lock()


def _load() -> None:
    global pipe
    try:
        from diffusers import DiffusionPipeline

        started = time.time()
        log.info("loading %s (offload=%s); the first run downloads the weights", MODEL_ID, OFFLOAD)
        p = DiffusionPipeline.from_pretrained(MODEL_ID, torch_dtype=torch.bfloat16)
        if OFFLOAD == "model":
            p.enable_model_cpu_offload()
        else:
            p.to("cuda")
        if hasattr(p.vae, "enable_tiling"):
            # A 2K sheet with a reference image ran out of VRAM in the VAE decode on a 32 GB
            # card; tiled decoding fixes it (images below the tile size are decoded whole).
            p.vae.enable_tiling()
        p.set_progress_bar_config(disable=True)
        pipe = p
        state.update(
            status="ready",
            pipeline=type(p).__name__,
            params=sorted(inspect.signature(p.__call__).parameters),
            load_seconds=round(time.time() - started, 1),
        )
        log.info("ready: %s in %.0fs", type(p).__name__, time.time() - started)
    except Exception as exc:  # surfaced through /health
        log.exception("model load failed")
        state.update(status="error", error=repr(exc))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_load, daemon=True).start()
    yield


app = FastAPI(title="Once Upon a Time local image server", lifespan=lifespan)


class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str | None = None
    aspect_ratio: str | None = None
    reference_images: list[str] = Field(default_factory=list, description="base64-encoded PNG/JPEG")
    steps: int | None = None
    seed: int | None = None
    guidance: float | None = Field(default=None, description="true CFG scale, when the pipeline supports it")
    size: str | None = Field(default=None, description='"1k" (fast, Gemini-sized) or "2k" (native; legible text)')
    transparent: bool = Field(default=False, description="keep the alpha channel (RGBA prompts only)")


@app.get("/health")
def health() -> dict:
    info = dict(state)
    if torch.cuda.is_available():
        info["gpu"] = torch.cuda.get_device_name(0)
        info["vram_allocated_gb"] = round(torch.cuda.memory_allocated() / 1e9, 2)
    return info


@app.post("/generate")
def generate(req: GenerateRequest) -> Response:
    if state["status"] != "ready":
        raise HTTPException(503, f"model not ready: {state['status']} {state.get('error') or ''}".strip())
    params = set(state["params"])
    seed = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)
    kwargs: dict = {
        "prompt": req.prompt,
        "num_inference_steps": req.steps or DEFAULT_STEPS,
        "generator": torch.Generator("cuda").manual_seed(seed),
    }
    size = req.size or SIZE
    if size not in ASPECT_SIZES:
        raise HTTPException(400, f"unsupported size {size}; use 1k or 2k")
    if req.aspect_ratio:
        if req.aspect_ratio not in ASPECT_SIZES[size]:
            raise HTTPException(400, f"unsupported aspect ratio {req.aspect_ratio}; use one of {sorted(ASPECT_SIZES[size])}")
        kwargs["width"], kwargs["height"] = ASPECT_SIZES[size][req.aspect_ratio]
    guidance = req.guidance if req.guidance is not None else DEFAULT_CFG
    ignored = []
    if guidance > 1 and "true_cfg_scale" in params:
        kwargs["true_cfg_scale"] = guidance
        kwargs["negative_prompt"] = req.negative_prompt or " "
    elif req.negative_prompt:
        ignored.append("negative_prompt")  # only used with guidance > 1
    if req.reference_images:
        images = [Image.open(io.BytesIO(base64.b64decode(b))).convert("RGB") for b in req.reference_images]
        kwargs["image"] = images if len(images) > 1 else images[0]

    with lock:
        torch.cuda.reset_peak_memory_stats()
        started = time.time()
        try:
            image = pipe(**kwargs).images[0]
        except Exception as exc:
            log.exception("generation failed")
            raise HTTPException(500, f"generation failed: {exc!r}") from exc
        elapsed = time.time() - started
        peak = torch.cuda.max_memory_allocated() / 1e9

    if image.mode == "RGBA" and not req.transparent:
        # The model always returns RGBA; on ordinary images the alpha is noise between ~216
        # and 255 over 10-30 % of the pixels, which renders as a faint veil. Drop it.
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    log.info("generated %dx%d in %.1fs (seed %d, cfg %.1f, peak VRAM %.1f GB, refs %d)",
             image.width, image.height, elapsed, seed, guidance, peak, len(req.reference_images))
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={
            "X-Model": MODEL_ID,
            "X-Seed": str(seed),
            "X-Elapsed-Seconds": f"{elapsed:.1f}",
            "X-Peak-VRAM-GB": f"{peak:.1f}",
            "X-CFG": f"{guidance:.1f}",
            "X-Ignored": ",".join(ignored),
        },
    )
