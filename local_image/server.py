"""Local image generation server for Once Upon a Time.

Runs an open-weights image model (Qwen-Image-2.1 by default) on the local NVIDIA GPU behind a
small HTTP API. The app sends its image requests here when IMAGE_BACKEND=local
(app/core/local_image.py); Compose starts it with the ``gpu`` profile.

    GET  /health    lifecycle, GPU, download progress (see below)
    POST /generate  JSON {prompt, negative_prompt?, aspect_ratio?, reference_images?: [base64],
                          steps?, seed?, guidance?, size?, transparent?}  ->  image/png
                    headers: X-Model, X-Seed, X-Elapsed-Seconds, X-Peak-VRAM-GB, X-CFG,
                    X-Ignored (negative_prompt when guidance <= 1)

Lifecycle ("status" in /health):

    checking      start-up checks (CUDA, VRAM)
    unsupported   no CUDA GPU, or less VRAM than LOCAL_IMAGE_MIN_VRAM_GB; requests get 503
    downloading   first start: weights are fetched into the /models volume ("progress")
    idle          weights on disk, model not in memory; the next request loads it
    loading       loading the model (seconds from a warm disk cache)
    ready         loaded; requests are served one at a time
    error         download or load failed ("error"); fix the cause and restart the service

After LOCAL_IMAGE_IDLE_MINUTES without requests the model is unloaded, which frees the ~25 GB
of RAM it holds, and the server goes back to "idle". All settings come from the environment
(Compose passes config/.env); empty values fall back to the defaults below.
"""

from __future__ import annotations

import base64
import gc
import inspect
import io
import logging
import os
import random
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


MODEL_ID = _env("LOCAL_IMAGE_MODEL", "Qwen/Qwen-Image-2.1")
DEFAULT_STEPS = int(_env("LOCAL_IMAGE_STEPS", "40"))
# Default output scale when a request does not say. "1k" matches the sizes Gemini returns and
# takes ~25 s on an RTX 5090; "2k" is the model's native size, needed for legible sheet text.
DEFAULT_SIZE = _env("LOCAL_IMAGE_SIZE", "1k")
# Qwen-Image-2.1 is meant to be sampled without guidance (true_cfg_scale 1.0). A negative
# prompt only acts with guidance > 1, which also costs ~1.6x the time.
DEFAULT_CFG = float(_env("LOCAL_IMAGE_CFG", "1.0"))
# "model": each component moves to the GPU only while it runs (the bf16 weights are ~33 GB,
# more than a 32 GB card holds at once). "none": keep everything on the GPU (bigger cards).
OFFLOAD = _env("LOCAL_IMAGE_OFFLOAD", "model")
IDLE_MINUTES = float(_env("LOCAL_IMAGE_IDLE_MINUTES", "20"))  # 0 keeps the model loaded
PRELOAD = _env("LOCAL_IMAGE_PRELOAD", "1") not in ("0", "false", "no")
MIN_VRAM_GB = float(_env("LOCAL_IMAGE_MIN_VRAM_GB", "24"))

# Output size per aspect ratio, from the model card (native 2K); "1k" halves them.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per weight-file request otherwise
log = logging.getLogger("local-image")

state: dict = {
    "status": "checking",
    "model": MODEL_ID,
    "error": None,
    "progress": None,
    "params": [],
    "last_used": None,
    "idle_unload_minutes": IDLE_MINUTES,
}
pipe = None
model_path: str | None = None
lock = threading.Lock()  # one load or generation at a time


# --- start-up ------------------------------------------------------------------------------

def _gpu_check() -> str | None:
    """Return why this machine cannot run the model, or None when it can."""
    if not torch.cuda.is_available():
        return ("No CUDA GPU is visible to the container. Install the NVIDIA driver and the NVIDIA "
                "Container Toolkit, then restart Docker.")
    props = torch.cuda.get_device_properties(0)
    vram = props.total_memory / 2**30
    state.update(gpu=props.name, vram_total_gb=round(vram, 1))
    if vram < MIN_VRAM_GB:
        return (f"{props.name} has {vram:.0f} GB of VRAM; {MODEL_ID} needs at least {MIN_VRAM_GB:.0f} GB "
                f"(32 GB recommended). Use the Gemini image backend instead.")
    return None


def _ram_total_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 2**20, 1)
    except OSError:
        pass
    return None


def _download() -> str:
    """Fetch the weights into the HF cache (a no-op check when they are already there)."""
    from huggingface_hub import HfApi, snapshot_download
    from huggingface_hub.constants import HF_HUB_CACHE

    try:
        info = HfApi().model_info(MODEL_ID, files_metadata=True)
        total = sum(s.size or 0 for s in info.siblings or [])
    except Exception as exc:  # offline: use what is cached
        log.warning("cannot reach Hugging Face (%s); using the local cache", exc)
        return snapshot_download(MODEL_ID, local_files_only=True)

    repo_dir = Path(HF_HUB_CACHE) / f"models--{MODEL_ID.replace('/', '--')}"
    stop = threading.Event()

    def poll() -> None:
        while not stop.wait(3):
            done = sum(f.stat().st_size for f in repo_dir.rglob("*") if f.is_file() and not f.is_symlink())
            state["progress"] = {
                "downloaded_gb": round(done / 1e9, 1),
                "total_gb": round(total / 1e9, 1),
                "percent": min(100, round(100 * done / total)) if total else None,
            }

    state.update(status="downloading", progress={"downloaded_gb": 0.0, "total_gb": round(total / 1e9, 1), "percent": 0})
    log.info("fetching %s (%.1f GB) into %s", MODEL_ID, total / 1e9, repo_dir)
    watcher = threading.Thread(target=poll, daemon=True)
    watcher.start()
    try:
        return snapshot_download(MODEL_ID)
    finally:
        stop.set()


def _load_locked() -> None:
    """Load the pipeline. The caller holds ``lock``."""
    global pipe
    from diffusers import DiffusionPipeline

    state.update(status="loading", error=None)
    started = time.time()
    log.info("loading %s (offload=%s)", MODEL_ID, OFFLOAD)
    try:
        p = DiffusionPipeline.from_pretrained(model_path or MODEL_ID, torch_dtype=torch.bfloat16)
        if OFFLOAD == "model":
            p.enable_model_cpu_offload()
        else:
            p.to("cuda")
        if hasattr(p.vae, "enable_tiling"):
            # A 2K sheet with a reference image ran out of VRAM in the VAE decode on a 32 GB
            # card; tiled decoding fixes it (images below the tile size are decoded whole).
            p.vae.enable_tiling()
        p.set_progress_bar_config(disable=True)
    except Exception as exc:
        state.update(status="error", error=f"model load failed: {exc!r}")
        raise
    pipe = p
    state.update(
        status="ready",
        pipeline=type(p).__name__,
        params=sorted(inspect.signature(p.__call__).parameters),
        load_seconds=round(time.time() - started, 1),
        last_used=time.time(),
    )
    log.info("ready: %s in %.0fs", type(p).__name__, time.time() - started)


def _unload_locked() -> None:
    """Free the model's RAM and VRAM. The caller holds ``lock``."""
    global pipe
    pipe = None
    gc.collect()
    torch.cuda.empty_cache()
    state.update(status="idle")
    log.info("unloaded after %.0f idle minutes", IDLE_MINUTES)


def _startup() -> None:
    global model_path
    state["ram_total_gb"] = _ram_total_gb()
    reason = _gpu_check()
    if reason:
        state.update(status="unsupported", error=reason)
        log.error(reason)
        return
    try:
        model_path = _download()
        state.update(status="idle", progress=None)
        if PRELOAD:
            with lock:
                _load_locked()
    except Exception as exc:
        log.exception("start-up failed")
        if state["status"] != "error":
            state.update(status="error", error=f"{exc!r}")


def _idle_watcher() -> None:
    while True:
        time.sleep(30)
        if IDLE_MINUTES <= 0 or state["status"] != "ready":
            continue
        if time.time() - (state["last_used"] or 0) < IDLE_MINUTES * 60:
            continue
        if lock.acquire(blocking=False):  # never interrupt a generation
            try:
                if state["status"] == "ready":
                    _unload_locked()
            finally:
                lock.release()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_startup, daemon=True, name="startup").start()
    threading.Thread(target=_idle_watcher, daemon=True, name="idle-watcher").start()
    yield


app = FastAPI(title="Once Upon a Time local image server", lifespan=lifespan)


# --- API -----------------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str | None = None
    aspect_ratio: str | None = None
    reference_images: list[str] = Field(default_factory=list, description="base64-encoded PNG/JPEG")
    steps: int | None = None
    seed: int | None = None
    guidance: float | None = Field(default=None, description="true CFG scale; > 1 enables the negative prompt")
    size: str | None = Field(default=None, description='"1k" (fast, Gemini-sized) or "2k" (native; legible text)')
    transparent: bool = Field(default=False, description="keep the alpha channel (RGBA prompts only)")


def _status_message() -> str:
    status = state["status"]
    if status == "downloading" and state.get("progress"):
        p = state["progress"]
        return (f"downloading the model weights: {p['downloaded_gb']} of {p['total_gb']} GB "
                f"({p['percent']}%). This happens once; try again when it finishes.")
    if status in ("unsupported", "error"):
        return state.get("error") or status
    return f"the server is {status}; try again in a moment"


@app.get("/health")
def health() -> dict:
    info = {k: v for k, v in state.items() if k != "params"}
    info["loaded"] = pipe is not None
    if state.get("last_used"):
        info["idle_seconds"] = round(time.time() - state["last_used"])
    if torch.cuda.is_available():
        info["vram_allocated_gb"] = round(torch.cuda.memory_allocated() / 1e9, 2)
    info["message"] = None if state["status"] in ("ready", "idle") else _status_message()
    return info


@app.post("/generate")
def generate(req: GenerateRequest) -> Response:
    if state["status"] not in ("ready", "idle", "loading"):
        raise HTTPException(503, _status_message())
    size = req.size or DEFAULT_SIZE
    if size not in ASPECT_SIZES:
        raise HTTPException(400, f"unsupported size {size}; use 1k or 2k")
    if req.aspect_ratio and req.aspect_ratio not in ASPECT_SIZES[size]:
        raise HTTPException(400, f"unsupported aspect ratio {req.aspect_ratio}; use one of {sorted(ASPECT_SIZES[size])}")
    images = [Image.open(io.BytesIO(base64.b64decode(b))).convert("RGB") for b in req.reference_images]

    with lock:
        if pipe is None:
            try:
                _load_locked()
            except Exception as exc:
                raise HTTPException(500, state.get("error") or repr(exc)) from exc
        params = set(state["params"])
        seed = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)
        kwargs: dict = {
            "prompt": req.prompt,
            "num_inference_steps": req.steps or DEFAULT_STEPS,
            "generator": torch.Generator("cuda").manual_seed(seed),
        }
        if req.aspect_ratio:
            kwargs["width"], kwargs["height"] = ASPECT_SIZES[size][req.aspect_ratio]
        guidance = req.guidance if req.guidance is not None else DEFAULT_CFG
        ignored = []
        if guidance > 1 and "true_cfg_scale" in params:
            kwargs["true_cfg_scale"] = guidance
            kwargs["negative_prompt"] = req.negative_prompt or " "
        elif req.negative_prompt:
            ignored.append("negative_prompt")  # only used with guidance > 1
        if images:
            kwargs["image"] = images if len(images) > 1 else images[0]

        torch.cuda.reset_peak_memory_stats()
        started = time.time()
        try:
            image = pipe(**kwargs).images[0]
        except torch.cuda.OutOfMemoryError as exc:
            torch.cuda.empty_cache()
            raise HTTPException(507, "the GPU ran out of memory; close other GPU programs or use size 1k") from exc
        except Exception as exc:
            log.exception("generation failed")
            raise HTTPException(500, f"generation failed: {exc!r}") from exc
        finally:
            state["last_used"] = time.time()
        elapsed = time.time() - started
        peak = torch.cuda.max_memory_allocated() / 1e9

    if image.mode == "RGBA" and not req.transparent:
        # The model always returns RGBA; on ordinary images the alpha is noise between ~216
        # and 255 over 10-30 % of the pixels, which renders as a faint veil. Drop it.
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    log.info("generated %dx%d in %.1fs (seed %d, cfg %.1f, peak VRAM %.1f GB, refs %d)",
             image.width, image.height, elapsed, seed, guidance, peak, len(images))
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
