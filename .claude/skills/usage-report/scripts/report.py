"""Summarize Gemini usage and estimated cost from data/usage.jsonl.

Usage:
    python report.py                 # totals + breakdown by project, operation, model
    python report.py --days 7        # only the last 7 days
    python report.py --project slug  # one project
    python report.py --by model      # single breakdown
    python report.py --tail 10       # last 10 raw entries
    python report.py --json          # machine-readable output
    python report.py --costs slug    # what one project cost, by stage (research, portraits, sheets...)

Reuses app.core.usage (stdlib only) so the numbers match the UI panel.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from app.core import costs, usage  # noqa: E402
from app.core import projects as store  # noqa: E402


def fmt_table(rows: list[dict]) -> str:
    if not rows:
        return "(no entries)"
    cols = list(rows[0])
    widths = {c: max(len(str(c)), *(len(str(r[c])) for r in rows)) for c in cols}
    line = " | ".join(str(c).ljust(widths[c]) for c in cols)
    sep = "-+-".join("-" * widths[c] for c in cols)
    body = [" | ".join(str(r[c]).ljust(widths[c]) for c in cols) for r in rows]
    return "\n".join([line, sep, *body])


def print_costs(slug: str, as_json: bool) -> None:
    project = store.load_project(slug)
    if project is None:
        sys.exit(f"no project {slug!r}")
    report = costs.project_costs(project)
    if as_json:
        print(json.dumps(report, indent=2))
        return
    rows = [
        {
            "stage": r["label"],
            "calls": r["calls"],
            "images": r["images"],
            "tokens": f"{r['input_tokens'] + r['output_tokens']:,}",
            "cost": f"${r['cost_usd']:.2f}",
            "on Gemini": f"${r['gemini_equivalent_usd']:.2f}",
        }
        for r in report["stages"]
    ]
    t = report["totals"]
    rows.append({"stage": "TOTAL", "calls": t["calls"], "images": t["images"],
                 "tokens": f"{t['input_tokens'] + t['output_tokens']:,}",
                 "cost": f"${t['cost_usd']:.2f}", "on Gemini": f"${t['gemini_equivalent_usd']:.2f}"})
    print(f"{project['name']} ({slug})\n")
    print(fmt_table(rows))
    print(f"\n'on Gemini' prices local images at ${report['gemini_image_usd']:.3f} each "
          "(the average Gemini image in the log). The PDF itself is built locally: $0.")
    if report["images_without_log"]:
        print(f"{report['images_without_log']} current image(s) match no log entry (made before logging, "
              "copied, or touched by hand).")
    if c := report["claude_research"]:
        print(f"Claude Code research (not in the log, rough floor): {c['documents']} notes, {c['sources']} sources, "
              f"~{c['input_tokens']:,} tokens read and ~{c['output_tokens']:,} written; its price depends on the Claude plan.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--project", default=None)
    ap.add_argument("--by", choices=["project", "operation", "model"], default=None)
    ap.add_argument("--tail", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--costs", metavar="SLUG", help="cost of one project by stage")
    args = ap.parse_args()
    if args.costs:
        print_costs(args.costs, args.json)
        return

    entries = usage.load_entries()
    if args.days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        entries = [e for e in entries if e.get("ts", "") >= cutoff]
    if args.project:
        entries = [e for e in entries if e.get("project") == args.project]

    totals = usage.summarize(entries)
    images = totals["images"] or 0
    image_entries = [e for e in entries if e.get("images")]
    image_cost = sum(e.get("cost_usd", 0.0) for e in image_entries)
    per_image = image_cost / images if images else 0.0
    unknown_models = sorted({e["model"] for e in entries if e.get("model") not in usage.PRICING})

    if args.json:
        print(json.dumps({
            "file": str(usage.USAGE_FILE),
            "totals": totals,
            "avg_cost_per_image_usd": round(per_image, 4),
            "unpriced_models": unknown_models,
            "by_project": usage.breakdown(entries, "project"),
            "by_operation": usage.breakdown(entries, "operation"),
            "by_model": usage.breakdown(entries, "model"),
            "tail": entries[-args.tail:] if args.tail else [],
        }, indent=2))
        return

    print(f"Usage log: {usage.USAGE_FILE}")
    print(f"Entries: {totals['calls']}   Input tokens: {totals['input_tokens']:,}   "
          f"Output tokens: {totals['output_tokens']:,}   Images: {images}   "
          f"Est. cost: ${totals['cost_usd']:.4f}")
    if images:
        print(f"Average estimated cost per generated image: ${per_image:.4f}")
    if unknown_models:
        print(f"WARNING: no price in app/core/usage.py PRICING for: {', '.join(unknown_models)} "
              "(their cost is counted as $0).")
    keys = [args.by] if args.by else ["project", "operation", "model"]
    for key in keys:
        print(f"\nBy {key}:")
        print(fmt_table(usage.breakdown(entries, key)))
    if args.tail:
        print(f"\nLast {args.tail} entries:")
        for e in entries[-args.tail:]:
            print(json.dumps(e))


if __name__ == "__main__":
    main()
