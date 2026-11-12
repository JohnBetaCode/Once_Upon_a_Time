# Local GPU images: evaluation

How images generated on a local GPU with Qwen-Image-2.1 compare with Gemini (Nano Banana Pro)
for the same researched characters, and why the local backend works the way it does. To set it
up, see [Images on your own GPU](setup.md#images-on-your-own-gpu).

## Summary

- **Realistic portraits are on par with Gemini.** Arthur Dent, Rick Deckard, Zaphod Beeblebrox
  (two heads) and Groucho the goat follow their sheets as faithfully as Gemini's, in about
  25 seconds and at no API cost. Arthur even gets the Babel fish in his ear, which Gemini left out.
- **Cartoon and comic styles drift towards realism.** Prompt changes help only partly.
- **Presentation sheets keep the identity but not the small text.** At the native 2K the layout,
  headers, attribute column and expression labels are mostly legible; captions are not.
- **Research stays on Gemini.** Local models do not search the web.

Gemini remains the default image backend; switching is one setting.

## Setup

| Item | Value |
|---|---|
| Model | [Qwen-Image-2.1](https://huggingface.co/Qwen/Qwen-Image-2.1), released 2026-09-20 |
| Weights | 33.1 GB bf16: Qwen3-VL text encoder 17.5 GB, transformer 14.2 GB, VAE 1.4 GB |
| License | Qwen Research License: research and non-commercial use only |
| GPU | RTX 5090, 32 GB, driver 580, CUDA 12.8 wheels |
| Software | torch 2.11.0+cu128, diffusers 0.43.0.dev0 (pinned commit of main), transformers 5.22.2 |
| Memory strategy | Model CPU offload: the weights do not fit in 32 GB at once |
| Sampling | 40 steps, no guidance (the model's default), seed 1234 |

## Measurements

| Image | Size | Time | Peak VRAM |
|---|---|---|---|
| Anchor portrait | 832×1248 | 25 s | 18 GB |
| First image after a restart | 832×1248 | 32–48 s | 18 GB |
| Presentation sheet, anchor as reference | 1248×832 | 68 s | 20.5 GB |
| Presentation sheet, anchor as reference | 2528×1696 | 103–115 s | 21 GB |
| Anchor with negative prompt (guidance 4) | 1024×1024 | 41 s | 18 GB |

Cost per image: $0 in the usage log, against about $0.13–0.18 with Gemini. The first start
downloads the 33 GB of weights (about 7 minutes on this connection) into a Docker volume.

## What the comparison showed

![Gemini vs local anchors](images/local-gpu-anchors.jpg)

- **Prompt rules.** The app's Gemini prompt is half description, half rules written as
  negations ("NO clothing", "no text"). Sent unchanged, the local model still produced a clean,
  single, unclothed goat: the negations did no visible harm. The local prompt states the
  composition positively anyway.
- **Negative prompt.** It only acts with guidance above 1, which costs 1.6× the time. On
  Groucho it only saturated the halter colour, so guidance stays off by default.
- **Form.** "In the natural posture of its form" put The Martians on legs. Spelling the form
  out ("a giant head with tentacles, unable to stand, sagging into a mound") fixed it.
- **Style.** Repeating the style at the end of the prompt did not bring cartoon or comic styles
  back. Phrasing the style as the kind of drawing and dropping the attribute list did (ink
  outlines on Glen Runciter), but lost details such as Moon-Watcher's bone tool. The app keeps
  the variant that preserves details.

![Prompt variants for the three style misses](images/local-gpu-style-prompts.jpg)

- **Sheets.** The local model builds the full layout from the anchor and keeps the same face,
  robe and Babel fish in every panel. At 1K the attribute column is partly garbled; at 2K it is
  legible, but small labels still slip ("PRICILE" for PROFILE) and captions are noise. Sheets
  therefore render at 2K locally.

![Sheets: Gemini, local 1K, local 2K](images/local-gpu-sheet.jpg)

## Decisions this led to

| Finding | What the implementation does |
|---|---|
| The bf16 weights (33 GB) exceed 32 GB of VRAM | Model CPU offload; peak VRAM stays at 18–21 GB |
| The loaded model holds ~25 GB of RAM | The server unloads it after 20 idle minutes and reloads on demand |
| The model card omits `torchvision` | Installed next to torch; all versions pinned, diffusers to a tested commit |
| A 2K sheet ran out of VRAM in the VAE decode | Tiled VAE decoding |
| Output is RGBA with a noisy alpha (216–255 over 10–30 % of pixels) | The server returns RGB unless transparency is requested |
| Negative prompts need guidance (1.6× slower), with little gain | Guidance off; the local prompt states rules positively |
| Generic posture wording ignored the form | The local prompt spells the form out |
| Sheet text is only legible at 2K | Local sheets request 2K; portraits and locations use 1K |

## Next steps worth trying

1. **Style reference images.** The model accepts up to 10 references; a fixed example image per
   style, passed next to the anchor, may fix cartoon and comic where text does not.
2. **Qwen-Image-2.1-Turbo** (8 steps) for portraits, if quality holds at a fifth of the time.
3. **Per-project backend**, so realistic books go local and stylized ones stay on Gemini.
4. **FLUX.2 [dev]** as a second open model for the same comparison.

## Reproduce

```bash
./launch.sh gpu
docker compose exec -T app python - < local_image/compare.py   # writes data/local-gpu-eval/
python3 local_image/side_by_side.py --out docs/images            # comparison images
```
