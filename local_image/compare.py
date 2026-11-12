"""Generate POC images with the local backend for characters that already have Gemini images.

Runs inside the app container (it needs app.core) and talks to the local-image service:

    docker compose exec -T app python - < local_image/compare.py

(piped through stdin because the app container only mounts app/, projects/, data/, config/).

Uses the same prompt builders as the app (imaging.anchor_request / sheet_request), a fixed
seed, and writes only to data/poc-local/ — project images are never touched. Prints one
JSON line per image with the wall time, and writes data/poc-local/results.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from app.core import imaging, ingestion, local_image, usage
from app.core import projects as store

OUT = Path("data/poc-local")
SEED = 1234

# (project slug, character, also generate a presentation sheet from the local anchor)
ANCHORS = [
    ("guia-del-autoestopista-galactico", "Arthur Dent", True),
    ("guia-del-autoestopista-galactico", "Zaphod Beeblebrox", False),
    ("la-guerra-de-los-mundos", "The Martians", False),
    ("ubik", "Glen Runciter", False),
    ("suenan-los-androides-con-ovejas-electricas", "Rick Deckard", False),
    ("2001-una-odisea-espacial", "Moon-Watcher", False),
    ("suenan-los-androides-con-ovejas-electricas", "Groucho", False),
]
# Same character with the Gemini prompt sent unchanged to the local model (rules written as
# negations, no negative prompt), to measure what the prompt adaptation buys.
# A third run adds the negative prompt, which only acts with guidance > 1 (2x compute).
CFG_AB = 4.0
PROMPT_AB = ("suenan-los-androides-con-ovejas-electricas", "Groucho")


def character(slug: str, name: str) -> tuple[dict, dict]:
    project = store.load_project(slug)
    return project, next(c for c in ingestion.load_entities(project, "characters") if c["name"] == name)


def run(slug: str, label: str, dest: Path, request: dict) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with usage.project_context(slug):
        png = local_image.generate_image(**request, seed=SEED)
    dest.write_bytes(png)
    result = {"image": str(dest), "label": label, "seconds": round(time.time() - started, 1),
              "aspect_ratio": request.get("aspect_ratio"), "refs": len(request.get("reference_images") or [])}
    print(json.dumps(result), flush=True)
    return result


def main() -> None:
    info = local_image.health()
    if info.get("status") != "ready":
        sys.exit(f"local image server not ready: {info}")
    print(json.dumps({"server": info}), flush=True)
    results = []
    for slug, name, with_sheet in ANCHORS:
        project, char = character(slug, name)
        folder = OUT / slug / imaging._slugify(name)
        anchor = folder / "anchor-local.png"
        results.append(run(slug, f"{name} anchor", anchor, imaging.anchor_request(project, char, local=True)))
        if with_sheet:
            request = imaging.sheet_request(project, char, anchor.read_bytes(), local=True)
            results.append(run(slug, f"{name} sheet", folder / "sheet-local.png", request))
    slug, name = PROMPT_AB
    project, char = character(slug, name)
    request = imaging.anchor_request(project, char, local=False)
    results.append(run(slug, f"{name} anchor, Gemini prompt unchanged",
                       OUT / slug / imaging._slugify(name) / "anchor-local-gemini-prompt.png", request))
    request = imaging.anchor_request(project, char, local=True)
    results.append(run(slug, f"{name} anchor, adapted prompt + negative prompt at guidance {CFG_AB}",
                       OUT / slug / imaging._slugify(name) / "anchor-local-cfg.png", {**request, "guidance": CFG_AB}))
    (OUT / "results.json").write_text(json.dumps({"server": info, "seed": SEED, "results": results}, indent=2))


if __name__ == "__main__":
    main()
