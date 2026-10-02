---
name: usage-report
description: Report Gemini / Vertex AI token usage and estimated USD cost for Once Upon a Time from data/usage.jsonl, per project, operation (web_research, extraction, image_generation) or model, and keep the PRICING table in app/core/usage.py current. Use this whenever the user asks how much a project or image generation cost, how many images or API calls were made, wants to compare spend between projects or days, changes GEMINI_TEXT_MODEL / GEMINI_IMAGE_MODEL, or asks about Gemini pricing.
---

# Usage and cost reporting

Every Gemini call made through `app/core/gemini.py` appends one JSON line to
`data/usage.jsonl` (see `app/core/usage.py`): timestamp, project slug, operation, model,
input/output tokens, number of images, whether Google Search grounding was used, and an
estimated cost. The home page's "Usage & costs" panel reads the same file.

The estimate is computed locally from the `PRICING` dict (USD per 1M tokens) plus a flat
per-request charge for grounded web searches. It is an approximation: the GCP billing
console is the source of truth, and say so whenever you report a figure.

## Reporting

```bash
python .claude/skills/usage-report/scripts/report.py                # everything
python .claude/skills/usage-report/scripts/report.py --days 1       # today-ish
python .claude/skills/usage-report/scripts/report.py --project the-little-prince --by operation
python .claude/skills/usage-report/scripts/report.py --tail 5       # last raw entries
python .claude/skills/usage-report/scripts/report.py --json         # for further processing
```

The script needs no third-party packages (it imports `app.core.usage`, which is stdlib
only), so it runs with the host `python3` even though Streamlit is only installed in the
container.

When answering a cost question, lead with the number the user asked for, then the
breakdown that explains it (for example: "12 images at about $0.19 each is most of the
$3.13"). Entries with project `—` were made outside a project context (connection tests).

## What drives cost

| Operation          | Model                       | Typical cost                         |
|--------------------|-----------------------------|--------------------------------------|
| `web_research`     | text model + Google Search  | tokens + ~$0.035 per grounded request |
| `extraction`       | text model, structured JSON | tokens only, usually cents           |
| `image_generation` | image model                 | ~1,100-1,600 output tokens per image; ~$0.13-0.20 at Gemini 3 Pro Image prices |
| `connection_test`  | text model                  | negligible                           |

Title research plus "deep research" of N characters costs roughly N+1 grounded requests
and N+1 extractions. Each portrait and each presentation sheet is one image call; a
sheet also sends the anchor as an input image (more input tokens).

## Keeping prices current

`PRICING` only knows the models listed in it. An unknown model is costed at $0 and the
report script prints a warning naming it. Whenever `GEMINI_TEXT_MODEL` or
`GEMINI_IMAGE_MODEL` changes (in `config/.env.example`, the Settings panel, or
`app/core/config.py` defaults):

1. Add the new model id to `PRICING` with current Vertex AI list prices (check the
   official pricing page; do not guess from memory, and keep the comment noting intro
   pricing windows where they apply).
2. Keep `config/.env.example`, the defaults in `app/core/config.py`, and the configuration
   table in `docs/usage.md` in sync.
3. Run the report to confirm no "unpriced models" warning remains.

Image models bill image output as tokens (`candidates_token_count`); the per-image cost
in comments (`~$0.134 per image`) assumes ~1,120 tokens per 1K-2K image.
