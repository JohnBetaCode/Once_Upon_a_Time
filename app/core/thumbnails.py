"""Project thumbnails: a small collage of the images generated so far.

The home page shows one per project. Collages are built with Pillow from the
character anchor portraits and location establishing shots (presentation sheets
only fill in when nothing else exists), cached under ``projects/<slug>/images/``
and rebuilt whenever the set of source images or their timestamps change.
No Gemini calls are made.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from app.core.projects import project_path

TILE_PX = 256
GAP_PX = 4
MAX_TILES = 4
BACKGROUND = "#f3f4f6"
THUMBNAIL_PREFIX = "thumbnail-"


def _source_images(root: Path) -> list[Path]:
    """Images worth showing, best first: portraits, then locations, then sheets."""
    anchors = sorted((root / "characters").glob("*/anchor.png"))
    locations = sorted(
        p for p in (root / "locations").glob("*.png") if not p.name.endswith("-sheet.png")
    )
    sheets = sorted((root / "characters").glob("*/sheet.png")) + sorted(
        (root / "locations").glob("*-sheet.png")
    )
    chosen = anchors + locations
    if len(chosen) < MAX_TILES:
        chosen += sheets
    return chosen[:MAX_TILES]


def _cache_key(images: list[Path]) -> str:
    digest = hashlib.sha1()
    for path in images:
        digest.update(f"{path.name}:{path.stat().st_mtime_ns}\n".encode())
    return digest.hexdigest()[:12]


def _grid(count: int) -> tuple[int, int]:
    """(columns, rows) for ``count`` tiles."""
    if count <= 3:
        return count, 1
    return 2, 2


def _build(images: list[Path], dest: Path) -> None:
    cols, rows = _grid(len(images))
    width = cols * TILE_PX + (cols - 1) * GAP_PX
    height = rows * TILE_PX + (rows - 1) * GAP_PX
    canvas = Image.new("RGB", (width, height), BACKGROUND)
    for index, path in enumerate(images):
        try:
            with Image.open(path) as img:
                tile = ImageOps.fit(img.convert("RGB"), (TILE_PX, TILE_PX), Image.Resampling.LANCZOS)
        except OSError:
            continue
        x = (index % cols) * (TILE_PX + GAP_PX)
        y = (index // cols) * (TILE_PX + GAP_PX)
        canvas.paste(tile, (x, y))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, format="JPEG", quality=85, optimize=True)


def project_thumbnail(project: dict[str, Any]) -> Path | None:
    """Return the collage for a project, building it if stale; None without images."""
    root = project_path(project["slug"])
    images = _source_images(root)
    if not images:
        return None
    dest = root / "images" / f"{THUMBNAIL_PREFIX}{_cache_key(images)}.jpg"
    if not dest.exists():
        _build(images, dest)
        for stale in dest.parent.glob(f"{THUMBNAIL_PREFIX}*.jpg"):
            if stale != dest:
                stale.unlink(missing_ok=True)
    return dest
