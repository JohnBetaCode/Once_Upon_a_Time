"""Token and cost accounting for Gemini calls.

Every call made through ``app.core.gemini`` appends one JSON line to
``data/usage.jsonl`` with the operation, model, token counts, and an
APPROXIMATE cost in USD based on public Vertex AI list prices. Treat the
figures as estimates — the GCP billing console is the source of truth.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
USAGE_FILE = ROOT_DIR / "data" / "usage.jsonl"

# USD per 1M tokens (Vertex AI list prices, approximate).
PRICING = {
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    # Intro pricing through 2026-12-31; doubles to 1.50/7.50 from 2027.
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75},
    "gemini-2.5-flash-image": {"input": 0.30, "output": 30.00},
    # Image output tokens; ~1120 tokens/image => ~$0.134 per image.
    "gemini-3-pro-image": {"input": 2.00, "output": 120.00},
    "gemini-3-pro-image-preview": {"input": 2.00, "output": 120.00},
}

# Grounding with Google Search, USD per grounded request (approximate;
# there is a daily free tier).
WEB_SEARCH_COST_PER_REQUEST = 0.035

_current_project: str | None = None


@contextmanager
def project_context(slug: str):
    """Attribute all Gemini calls inside this block to a project."""
    global _current_project
    previous = _current_project
    _current_project = slug
    try:
        yield
    finally:
        _current_project = previous


def record(
    operation: str,
    model: str,
    usage_metadata: Any = None,
    images: int = 0,
    web_search: bool = False,
) -> None:
    """Append one usage entry. Never raises — accounting must not break calls."""
    try:
        input_tokens = int(getattr(usage_metadata, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage_metadata, "candidates_token_count", 0) or 0) + int(
            getattr(usage_metadata, "thoughts_token_count", 0) or 0
        )
        prices = PRICING.get(model, {"input": 0.0, "output": 0.0})
        cost = (
            input_tokens * prices["input"] / 1e6
            + output_tokens * prices["output"] / 1e6
            + (WEB_SEARCH_COST_PER_REQUEST if web_search else 0.0)
        )
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "project": _current_project,
            "operation": operation,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "images": images,
            "web_search": web_search,
            "cost_usd": round(cost, 6),
        }
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def load_entries() -> list[dict[str, Any]]:
    if not USAGE_FILE.exists():
        return []
    entries = []
    for line in USAGE_FILE.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "calls": len(entries),
        "input_tokens": sum(e.get("input_tokens", 0) for e in entries),
        "output_tokens": sum(e.get("output_tokens", 0) for e in entries),
        "images": sum(e.get("images", 0) for e in entries),
        "cost_usd": sum(e.get("cost_usd", 0.0) for e in entries),
    }


def breakdown(entries: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Aggregate entries by a field ('project', 'operation', or 'model')."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        groups.setdefault(entry.get(key) or "—", []).append(entry)
    rows = []
    for name, group in sorted(groups.items()):
        summary = summarize(group)
        rows.append(
            {
                key: name,
                "calls": summary["calls"],
                "input tokens": summary["input_tokens"],
                "output tokens": summary["output_tokens"],
                "images": summary["images"],
                "est. cost (USD)": round(summary["cost_usd"], 4),
            }
        )
    rows.sort(key=lambda r: r["est. cost (USD)"], reverse=True)
    return rows
