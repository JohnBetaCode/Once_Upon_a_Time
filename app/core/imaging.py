"""Image generation for project entities.

Anchor -> reference strategy: each character gets one front-facing anchor
portrait first; every derived shot and passage scene passes the anchor as
a reference image so the character stays visually identical.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from app.core import gemini, local_image, usage
from app.core.config import get_settings
from app.core.projects import project_path

STYLE_PROMPTS = {
    "cartoon": "vibrant modern cartoon style, clean bold outlines, expressive faces, flat colors with soft shading",
    "realistic": "photorealistic digital painting, natural lighting, detailed textures, cinematic composition",
    "retro": "vintage 1950s storybook illustration, muted palette, textured paper grain, classic ink and gouache",
    "anime": "high-quality anime style, cel shading, detailed eyes, dynamic lighting",
    "watercolor": "soft watercolor illustration, gentle washes, visible brush strokes, dreamy atmosphere",
    "comic": "western comic book style, strong inks, halftone shading, dramatic angles",
    "pixel-art": "detailed pixel art, 32-bit era, rich color palette, crisp sprites",
    "noir": "film noir illustration, high-contrast black and white, dramatic shadows, moody atmosphere",
    "pencil": (
        "detailed black and white graphite pencil drawing, fine directional pencil strokes and "
        "cross-hatching, realistic proportions, soft tonal shading, crisp white paper"
    ),
    "80s-comic": (
        "classic 1980s mainstream American comic book art, clean confident black ink outlines of even "
        "weight, flat solid bright saturated colors, smooth clean color fills, simple graphic shading with "
        "solid black shadows, crisp vivid printed comic colors, bold simple shapes"
    ),
}

CHARACTER_ANCHOR_PROMPT = """\
Portrait of a single character: whole body, three-quarter view, in the natural
posture of its form, with a characterful attitude that fits the personality,
on a plain neutral studio background with soft, even lighting.
Style: {style}.

Character: {name}
{description}
{sheet_lines}
{notes_block}
STRICT COMPOSITION RULES:
- Depict the character EXACTLY according to its stated FORM. A REAL animal
  must look like a real animal: natural anatomy, natural posture (on four
  legs if a quadruped), NO clothing, NO human-like standing — even if it
  talks in the story. Anthropomorphize ONLY if the form says so.
- Exactly ONE figure in the image: the character appears a single time.
- NOT a reference sheet: no turnaround, no multiple views, poses or angles,
  no collage, no grid, no duplicated figures.
- Whole body visible, face clearly visible.
- Plain neutral background, no scenery.
- No text, no labels, no watermark.
"""

CHARACTER_SHEET_PROMPT = """\
A professional character production-design presentation sheet, landscape format,
like a film/animation studio character bible page. Off-white paper background,
clean editorial layout with thin black divider lines and small uppercase section
headers. ALL TEXT IN ENGLISH. Illustration style for every panel: {style}.

IDENTITY RULE (most important): the attached reference image IS the character.
Every panel of the sheet must depict EXACTLY that same individual — same face
and features, same colors and markings, same outfit (or lack of one), same
proportions, same form and posture type. Where the text below and the
reference image disagree, THE REFERENCE IMAGE WINS.

The SAME character must appear identical in every panel of the sheet.
Typography must be clean and legible. Keep every text element SHORT — labels
and captions of a few words only, never long paragraphs.

Layout:
- Top-left title block: "{name}" in large bold condensed uppercase, below it
  "{story}" and "{author}" in smaller type.
- Left column: an attribute list with small bold labels, one short line each:
  {attribute_lines}
- Center, section "BODY VIEWS": full-body turnaround of the character in the
  natural posture of its form — FRONTAL (facing viewer), 3/4 (turned 45
  degrees), PROFILE (strict side view), BACK (seen from behind) — labeled
  under each pose; the four orientations must be clearly different, with
  identical appearance and proportions. A REAL animal keeps natural animal
  anatomy and posture (four legs if a quadruped, no clothing) in every panel;
  anthropomorphize ONLY if the character's form says so.
- Below the turnaround: section "COLOR PALETTE" with 5 labeled color swatch
  circles of the character's palette, and a section "SCALE" with a small
  silhouette next to the character and height markings.
- Right column, section "EXPRESSIONS & ATTITUDES": a grid of 8 head-and-shoulders
  portraits with labels NEUTRAL, THOUGHTFUL, WORRIED, DETERMINED, SAD, SURPRISED,
  DOUBTFUL, FIRM.
- Below it, section "DETAILS": 4 close-up panels (face, hands, attire fabric,
  a signature prop or distinctive trait) with short captions.
- Bottom: section "ENVIRONMENT" — one wide cinematic strip of the character in
  their typical setting, with a short caption.
- Footer bar: "{story}" on the left, "CHARACTER PRESENTATION SHEET / PRODUCTION
  DESIGN" on the right.

Character appearance (secondary to the reference image):
{description}
{sheet_lines}
{notes_block}"""

AUTHOR_NOTES_BLOCK = """
AUTHOR'S CORRECTIONS — highest priority. Written by the story's owner; they
override anything above that contradicts them (form, species, anatomy,
clothing, colors, props):
{notes}
"""

LOCATION_SHEET_PROMPT = """\
A professional environment production-design presentation sheet, landscape
format, like a film/animation studio location bible page. Off-white paper
background, clean editorial layout with thin black divider lines and small
uppercase section headers. ALL TEXT IN ENGLISH. Illustration style for every
panel: {style}.

The SAME location must be depicted consistently in every panel.
Typography must be clean and legible. Keep every text element SHORT — labels
and captions of a few words only, never long paragraphs.

Layout:
- Top-left title block: "{name}" in large bold condensed uppercase, below it
  "{story}" in smaller type, then a short DESCRIPTION caption: {description}
  and a short RELEVANCE note: {relevance}
- Center, section "MAIN VIEW": one large wide establishing shot of the location.
- Right column, section "VIEWS & MOODS": 4 smaller panels — DAY, NIGHT, DETAIL,
  ALTERNATE ANGLE — each labeled.
- Below, section "COLOR PALETTE" with 5 labeled color swatch circles, and a
  section "DETAILS" with 3 close-up panels of characteristic elements, captioned.
- Footer bar: "{story}" on the left, "ENVIRONMENT PRESENTATION SHEET /
  PRODUCTION DESIGN" on the right.

No people in any panel. No watermark.
"""

LOCATION_PROMPT = """\
Establishing shot of a story location, no people.
Style: {style}.

Location: {name}
{description}

Wide composition, rich environmental detail. No text, no watermark.
"""


# --- Local GPU backend (IMAGE_BACKEND=local, app/core/local_image.py) ---------------------
# Diffusion models follow descriptions well but obey rules and negations poorly: "no text"
# can add text, because the word is in the prompt. The local anchor prompt therefore
# states the composition positively, leads with the style (early tokens weigh more), and
# moves everything that must not appear into a negative prompt. The style is repeated at
# the end: with it only at the start, long realistic descriptions pulled "cartoon" and
# "comic" projects towards photorealism.

LOCAL_ANCHOR_PROMPT = """\
{style}. A full-body character portrait of {name}, who appears exactly once, seen in a
three-quarter view, {posture}, with an attitude that fits the character. The whole body
and the face are clearly visible. The character stands alone on {background}.{figure}

{description}
{sheet_lines}{notes_line}

Art style for the whole image: {style}."""

# Sheets: the local model garbles small type, and every caption on a sheet repeats what the
# book already prints as plain text. So the local sheets are wordless art-book plates: the
# same panels as the Gemini sheet (turnaround, expressions, palette, scale, details,
# setting) with no title, labels or captions. Nothing on them is quoted or named as a
# section, because quoted words and "labeled"/"header" invite the model to write them.

LOCAL_CHARACTER_SHEET_PROMPT = """\
{style}. A wordless concept-art plate from a film art book, landscape format: many drawings
of the same character on one sheet of warm off-white paper, arranged in clean panels
separated by thin dark lines and generous margins. The page is pure artwork: every panel is
a picture and the paper between the panels is empty.

The character is the one in the reference image: the same face, hair, colors, markings,
outfit (or lack of one), proportions and form in every drawing. Where the notes below and
the reference image disagree, the reference image wins. In every drawing the character is
{posture}.

The plate holds:
- Across the left half, a full-body turnaround: the character four times side by side,
  facing the viewer, turned three-quarters, in strict side profile and seen from behind.
- On the right, a grid of eight head-and-shoulders portraits, each with a different
  expression: calm, thoughtful, worried, determined, sad, surprised, doubtful and resolute.
- Below the turnaround, a row of five plain round paint swatches of the character's colors,
  and a small dark silhouette of the character beside an adult human silhouette for scale.
- Below the portraits, four close-up studies: the face, the hands, the texture of the
  attire, and a signature prop or distinctive trait.
- Along the bottom, one wide cinematic strip of the character in a typical setting.

Appearance notes, for drawing only:
{description}
{sheet_lines}{notes_line}

Art style for every panel: {style}. The plate holds only drawings and paint swatches."""

# Beings without a human body plan (a ship computer, a manta-like alien, a spire of light):
# a turnaround of "head-and-shoulders portraits" with "hands" gave Singer and HAL 9000 a human
# body. This plate asks for views of the whole being and close-ups of its sensory organs.
LOCAL_CREATURE_SHEET_PROMPT = """\
{style}. A wordless concept-art plate from a film art book, landscape format: many drawings
of the same being on one sheet of warm off-white paper, arranged in clean panels separated by
thin dark lines and generous margins. The page is pure artwork: every panel is a picture and
the paper between the panels is empty.

The being is the one in the reference image and keeps exactly that body plan, shape, colors
and markings in every drawing: {form}. Where the notes below and the reference image
disagree, the reference image wins.

The plate holds:
- Across the left half, four views of the whole being from different sides: from the front,
  at three-quarters, from the side, and from behind or above.
- On the right, a grid of eight close-ups of its face or sensory organs, each showing a
  different mood through its light, color and posture.
- Below the four views, a row of five plain round paint swatches of its colors, and its dark
  silhouette beside an adult human silhouette for scale.
- Below the close-ups, four close-up studies of its most distinctive features and textures.
- Along the bottom, one wide cinematic strip of the being in a typical setting.

Appearance notes, for drawing only:
{description}
{sheet_lines}{notes_line}

Art style for every panel: {style}. The plate holds only drawings and paint swatches."""

LOCAL_LOCATION_SHEET_PROMPT = """\
{style}. A wordless concept-art plate from a film art book, landscape format: several
paintings of the same place on one sheet of warm off-white paper, arranged in clean panels
separated by thin dark lines and generous margins. The page is pure artwork: every panel is
a picture and the paper between the panels is empty.

The place is {name}{reference_clause}, depicted consistently in every panel and empty of
people.

The plate holds:
- Filling the upper left, one large wide establishing view of the place.
- Down the right side, four smaller views: the place by day, by night, a close detail, and
  seen from another angle.
- Along the bottom, a row of five plain round paint swatches of the place's colors and three
  close-up studies of its characteristic elements.

About the place, for painting only:
{description}

Art style for every panel: {style}. The plate holds only paintings and paint swatches."""

LOCAL_NEGATIVE_PROMPT = (
    "text, letters, words, caption, label, watermark, signature, logo, multiple figures, "
    "duplicated character, character sheet, turnaround, multiple views, collage, grid, "
    "split screen, cropped body, scenery, busy background"
)
LOCAL_ANIMAL_NEGATIVE = ", clothing, costume, standing upright like a human, human hands, anthropomorphic"
LOCAL_SHEET_NEGATIVE = (
    "text, letters, words, title, caption, label, numbers, typography, watermark, signature, "
    "logo, blurry, extra limbs, deformed anatomy"
)
LOCAL_CREATURE_NEGATIVE = LOCAL_SHEET_NEGATIVE + ", humanoid, human body, torso, arms, legs, hands, feet"
# Real animals use the creature plate too: the regular plate's "head-and-shoulders portraits" and
# "hands" gave Fuego, a horse, one human face and a human hand. Their legs are wanted.
LOCAL_ANIMAL_SHEET_NEGATIVE = LOCAL_SHEET_NEGATIVE + ", human face, human hands, human body, anthropomorphic, clothing"

# Forms that get the creature plate. A form that starts with "human" never does, even when it
# mentions a later transformation (Bowman's "transitioning ... to a non-corporeal" Star-Child).
_NON_HUMANOID_FORM = re.compile(r"non[- ]?humanoid|non[- ]?corporeal|\bobject\b|machine|computer|cephalo")
LOCAL_LOCATION_NEGATIVE = "text, letters, words, watermark, signature, logo, people, person, characters, crowd"

LOCAL_ANCHOR_BACKGROUND = "a plain neutral gray\nstudio background with soft, even lighting"

# Comic styles turned a few human characters into caricatures (a ball-shaped body, a huge nose)
# while the rest of the cast kept human proportions: words like "massive", "rotund" or "squat"
# in a description pull a cartoon style towards caricature. Human characters of these styles get
# a proportions sentence and an anti-caricature negative; animals and creatures do not.
COMIC_FIGURE = (
    "\nThe figure has natural, realistic adult human proportions and anatomy, like the rest of a\n"
    "mainstream comic book cast; age and body type show through build, posture and clothing."
)
COMIC_FIGURE_NEGATIVE = (
    ", caricature, exaggerated proportions, oversized head, oversized nose, chibi, grotesque, "
    "deformed body, cartoon mascot"
)

# Pencil is a realistic drawing style, yet One Hundred Years of Solitude came out mixed: some
# young women with anime faces and oversized eyes, strong men drawn as bodybuilders ("colossal",
# "mountainous" in the research). Human characters get a life-drawing proportions sentence (for
# any age, children included) and a negative against anime and exaggerated anatomy.
REALISTIC_FIGURE = (
    "\nThe figure has natural, realistic human proportions and anatomy for its age, like a life\n"
    "drawing of a real person: strength, weight and age show through build, posture and clothing,\n"
    "never through exaggeration."
)
REALISTIC_FIGURE_NEGATIVE = (
    ", anime, manga, chibi, oversized eyes, doll face, cartoon, caricature, bodybuilder, "
    "exaggerated muscles, superhero physique, exaggerated proportions"
)

# Styles the local model pulls towards realism, tuned on the local backend only. "80s-comic"
# stayed gritty and painterly with the gray studio background and guidance off; a flat panel
# background plus guidance with an anti-realism negative prompt gave clean inks and flat colors.
# Sheets do not use the guidance: on a plate it brought captions back.
LOCAL_STYLE_TUNING: dict[str, dict[str, Any]] = {
    "80s-comic": {
        "background": "a flat solid bright\nyellow background, like a comic book panel",
        "figure": COMIC_FIGURE,
        "figure_negative": COMIC_FIGURE_NEGATIVE,
        "negative": (
            ", photorealistic, photograph, painterly, digital painting, 3d render, gritty texture, "
            "grime, muted colors, desaturated, soft gradients, airbrush"
        ),
        "guidance": 4.0,
    },
    # Same problem, milder: plain comic came out as gritty illustration. A flat pale panel
    # background and guidance against realism give clean inks and flat colors (tested on Ubik).
    "comic": {
        "background": "a flat solid pale\nblue background, like a comic book panel",
        "figure": COMIC_FIGURE,
        "figure_negative": COMIC_FIGURE_NEGATIVE,
        "negative": (
            ", photorealistic, photograph, painterly, digital painting, 3d render, soft gradients, "
            "airbrush, smooth skin rendering"
        ),
        "guidance": 4.0,
    },
    # Descriptions full of skin, eye and fabric colors made "black and white" pencil come out
    # as colored pencil; white paper plus guidance against color brings it close, and
    # MONOCHROME_STYLES finishes the job.
    "pencil": {
        "background": "plain white paper\nwith no background drawn",
        "figure": REALISTIC_FIGURE,
        "figure_negative": REALISTIC_FIGURE_NEGATIVE,
        "negative": (
            ", color, colorful, colored pencil, painting, watercolor, sepia, skin tones, photograph, "
            "photorealistic, 3d render"
        ),
        "guidance": 4.0,
    },
}

# Styles that are black and white by definition: every image is converted to grayscale after
# generation, on both backends, because no prompt kept the models from coloring skin and cloth.
MONOCHROME_STYLES = {"pencil"}

# Measurements a diffusion model cannot draw; they only dilute the description.
LOCAL_SKIP_FIELDS = {"height"}


def _use_local() -> bool:
    return get_settings().image_backend == "local"


def backend_label() -> str:
    """How the UI names the active image backend in progress messages."""
    return "the local GPU" if _use_local() else "Gemini"


def _generate_image(
    prompt: str,
    reference_images: list[bytes] | None = None,
    aspect_ratio: str | None = None,
    negative_prompt: str | None = None,
    size: str | None = None,
    guidance: float | None = None,
) -> bytes:
    """Route one image generation to the configured backend (``size`` and ``guidance`` are local-only)."""
    if _use_local():
        return local_image.generate_image(
            prompt, reference_images, aspect_ratio, negative_prompt, size=size, guidance=guidance
        )
    return gemini.generate_image(prompt, reference_images=reference_images, aspect_ratio=aspect_ratio)


def _shorten(text: str, max_words: int = 10) -> str:
    words = text.split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unnamed"


def _style_prompt(project: dict[str, Any]) -> str:
    return STYLE_PROMPTS.get(project.get("style", ""), project.get("style", "storybook illustration"))


def character_anchor_path(project: dict[str, Any], character: dict[str, Any]) -> Path:
    return project_path(project["slug"]) / "characters" / _slugify(character["name"]) / "anchor.png"


def location_image_path(project: dict[str, Any], location: dict[str, Any]) -> Path:
    return project_path(project["slug"]) / "locations" / f"{_slugify(location['name'])}.png"


def character_sheet_path(project: dict[str, Any], character: dict[str, Any]) -> Path:
    return project_path(project["slug"]) / "characters" / _slugify(character["name"]) / "sheet.png"


def location_sheet_path(project: dict[str, Any], location: dict[str, Any]) -> Path:
    return project_path(project["slug"]) / "locations" / f"{_slugify(location['name'])}-sheet.png"


def _notes_block(character: dict[str, Any]) -> str:
    notes = (character.get("notes") or "").strip()
    return AUTHOR_NOTES_BLOCK.format(notes=notes) if notes else ""


def _story_and_author(project: dict[str, Any]) -> tuple[str, str]:
    book = project.get("book") or {}
    story = book.get("title") if book.get("title") not in (None, "", "undefined") else project["name"]
    author = book.get("author") if book.get("author") not in (None, "", "undefined") else ""
    return story, author


def _sheet_fields(character: dict[str, Any]) -> list[tuple[str, str]]:
    sheet = character.get("sheet") or {}
    fields = [("role", character.get("role", ""))] + list(sheet.items())
    return [
        (name.replace("_", " "), value)
        for name, value in fields
        if value and value != "undefined"
    ]


def generate_character_sheet(project: dict[str, Any], character: dict[str, Any]) -> Path:
    """Generate a full production-design presentation sheet for a character.

    The anchor portrait (generated first if missing) is passed as a reference
    image so the sheet keeps the same identity.
    """
    anchor = character_anchor_path(project, character)
    if not anchor.exists():
        generate_character_anchor(project, character)

    request = sheet_request(project, character, anchor.read_bytes())
    with usage.project_context(project["slug"]):
        image = _generate_image(**request)
    dest = character_sheet_path(project, character)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_finish(project, image))
    return dest


def sheet_request(
    project: dict[str, Any], character: dict[str, Any], anchor_png: bytes, local: bool | None = None
) -> dict[str, Any]:
    """Prompt, negative prompt, aspect ratio and reference image of a presentation sheet.

    Locally the sheet is a wordless art-book plate (see ``LOCAL_CHARACTER_SHEET_PROMPT``).
    """
    local = _use_local() if local is None else local
    description = character.get("physical_description", "")
    if description == "undefined":
        description = ""
    if local:
        sheet = character.get("sheet", {}) or {}
        # Quoted phrases in the research ('low-entropy entity') made the model write text.
        notes = {
            "style": _style_prompt(project),
            "description": _unquote(description),
            "sheet_lines": _unquote(_local_sheet_lines(sheet)),
            "notes_line": _unquote(_local_notes_line(character)),
        }
        request = {
            "aspect_ratio": "3:2",
            "reference_images": [anchor_png],
            # The eight portraits and the close-ups are small: they need the native 2K
            # (about 107 s on an RTX 5090).
            "size": "2k",
        }
        if _is_animal(sheet):
            return {
                **request,
                "prompt": LOCAL_CREATURE_SHEET_PROMPT.format(form=_unquote(sheet.get("form") or ""), **notes),
                "negative_prompt": LOCAL_ANIMAL_SHEET_NEGATIVE,
            }
        if is_non_humanoid(character):
            return {
                **request,
                "prompt": LOCAL_CREATURE_SHEET_PROMPT.format(form=_unquote(sheet.get("form") or ""), **notes),
                "negative_prompt": LOCAL_CREATURE_NEGATIVE,
            }
        return {
            **request,
            "prompt": LOCAL_CHARACTER_SHEET_PROMPT.format(posture=_local_posture(sheet), **notes),
            "negative_prompt": LOCAL_SHEET_NEGATIVE,
        }
    fields = _sheet_fields(character)
    story, author = _story_and_author(project)
    attribute_lines = "; ".join(f"{n.upper()}: {_shorten(v)}" for n, v in fields) or "NAME only"
    prompt = CHARACTER_SHEET_PROMPT.format(
        style=_style_prompt(project),
        name=character["name"].upper(),
        story=story,
        author=author,
        attribute_lines=attribute_lines,
        description=description,
        sheet_lines="\n".join(f"- {n.capitalize()}: {v}" for n, v in fields),
        notes_block=_notes_block(character),
    )
    return {
        "prompt": prompt,
        "negative_prompt": None,
        "aspect_ratio": "3:2",
        "reference_images": [anchor_png],
    }


def location_sheet_request(
    project: dict[str, Any], location: dict[str, Any], local: bool | None = None
) -> dict[str, Any]:
    """Prompt, negative prompt, aspect ratio and reference image of a location sheet.

    The location's establishing shot, when it exists, is the reference image. Locally the
    sheet is a wordless art-book plate (see ``LOCAL_LOCATION_SHEET_PROMPT``).
    """
    local = _use_local() if local is None else local
    description = location.get("description", "")
    if description == "undefined":
        description = ""
    reference = location_image_path(project, location)
    references = [reference.read_bytes()] if reference.exists() else None

    if local:
        prompt = LOCAL_LOCATION_SHEET_PROMPT.format(
            style=_style_prompt(project),
            name=location["name"],
            reference_clause=", the place shown in the reference image" if references else "",
            description=_unquote(description),
        )
        return {
            "prompt": prompt,
            "negative_prompt": LOCAL_SHEET_NEGATIVE + ", people, person, crowd",
            "aspect_ratio": "3:2",
            "reference_images": references,
            "size": "2k",
        }

    relevance = location.get("relevance", "")
    if relevance == "undefined":
        relevance = ""
    story, _ = _story_and_author(project)
    prompt = LOCATION_SHEET_PROMPT.format(
        style=_style_prompt(project),
        name=location["name"].upper(),
        story=story,
        description=_shorten(description, 16),
        relevance=_shorten(relevance, 12),
    )
    return {"prompt": prompt, "negative_prompt": None, "aspect_ratio": "3:2", "reference_images": references}


def generate_location_sheet(project: dict[str, Any], location: dict[str, Any]) -> Path:
    """Generate a full production-design presentation sheet for a location."""
    request = location_sheet_request(project, location)
    with usage.project_context(project["slug"]):
        image = _generate_image(**request)
    dest = location_sheet_path(project, location)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_finish(project, image))
    return dest


def anchor_request(
    project: dict[str, Any], character: dict[str, Any], local: bool | None = None
) -> dict[str, Any]:
    """Prompt, negative prompt and aspect ratio of a character's anchor portrait.

    ``local`` picks the prompt variant (defaults to the configured backend).
    """
    local = _use_local() if local is None else local
    sheet = character.get("sheet", {}) or {}
    description = character.get("physical_description", "")
    if description == "undefined":
        description = ""
    form = sheet.get("form", "").lower()
    quadruped = any(k in form for k in ("quadruped", "four leg", "four-legged"))
    # Canvas matches the figure: vertical for upright forms, square for
    # quadrupeds/objects. A wide canvas invites the model to duplicate the figure.
    aspect_ratio = "1:1" if quadruped else "2:3"

    if not local:
        sheet_lines = "\n".join(
            f"- {field.replace('_', ' ').capitalize()}: {value}"
            for field, value in sheet.items()
            if value and value != "undefined"
        )
        prompt = CHARACTER_ANCHOR_PROMPT.format(
            style=_style_prompt(project),
            name=character["name"],
            description=description,
            sheet_lines=sheet_lines,
            notes_block=_notes_block(character),
        )
        return {"prompt": prompt, "negative_prompt": None, "aspect_ratio": aspect_ratio}

    tuning = _local_tuning(project)
    animal = quadruped or "real animal" in form
    human = not animal and not is_non_humanoid(character)
    prompt = LOCAL_ANCHOR_PROMPT.format(
        style=_style_prompt(project),
        name=character["name"],
        posture=_local_posture(sheet),
        background=tuning.get("background", LOCAL_ANCHOR_BACKGROUND),
        figure=tuning.get("figure", "") if human else "",
        description=description,
        sheet_lines=_local_sheet_lines(sheet),
        notes_line=_local_notes_line(character),
    )
    negative = (
        LOCAL_NEGATIVE_PROMPT
        + (LOCAL_ANIMAL_NEGATIVE if animal else "")
        + tuning.get("negative", "")
        + (tuning.get("figure_negative", "") if human else "")
    )
    request = {"prompt": prompt, "negative_prompt": negative, "aspect_ratio": aspect_ratio}
    return {**request, "guidance": tuning["guidance"]} if "guidance" in tuning else request


def _finish(project: dict[str, Any], image: bytes) -> bytes:
    """Last step before an image is saved: grayscale for monochrome styles, untouched otherwise."""
    if project.get("style") not in MONOCHROME_STYLES:
        return image
    out = BytesIO()
    ImageOps.grayscale(Image.open(BytesIO(image))).convert("RGB").save(out, format="PNG")
    return out.getvalue()


def _local_tuning(project: dict[str, Any]) -> dict[str, Any]:
    """Local-backend adjustments for the project's style (empty for most styles)."""
    return LOCAL_STYLE_TUNING.get(project.get("style", ""), {})


def _is_animal(sheet: dict[str, Any]) -> bool:
    """Real animals (quadrupeds or a form that says so), as opposed to anthropomorphic ones."""
    form = (sheet.get("form") or "").lower()
    return "real animal" in form or any(k in form for k in ("quadruped", "four leg", "four-legged"))


def _local_posture(sheet: dict[str, Any]) -> str:
    """How the local prompts describe the character's body: its form, spelled out."""
    form = (sheet.get("form") or "").lower()
    if any(k in form for k in ("quadruped", "four leg", "four-legged")):
        return "standing naturally on four legs with real animal anatomy, unclothed"
    if "real animal" in form:
        return "in its natural animal posture with real animal anatomy, unclothed"
    # Spell the form out: "the natural posture of its form" alone let the model put
    # The Martians ("unable to stand ... sagging into a mound") on legs.
    return f"in the natural posture of its form ({sheet.get('form')})" if form else "in a natural pose"


_QUOTES = re.compile(r"(?<!\w)['\"“”‘’«»]|['\"“”‘’«»](?!\w)")


def _unquote(text: str) -> str:
    """Drop quotation marks around phrases (apostrophes inside words stay): local plates are
    wordless, and a quoted phrase is what the model is most likely to letter onto the page."""
    return _QUOTES.sub("", text)


def is_non_humanoid(character: dict[str, Any]) -> bool:
    """Whether the character's form has no human body plan (computer, alien, energy being)."""
    form = ((character.get("sheet") or {}).get("form") or "").strip().lower()
    return not form.startswith("human") and bool(_NON_HUMANOID_FORM.search(form))


def _local_sheet_lines(sheet: dict[str, Any]) -> str:
    return "\n".join(
        f"- {field.replace('_', ' ').capitalize()}: {value}"
        for field, value in sheet.items()
        if value and value != "undefined" and field not in LOCAL_SKIP_FIELDS
    )


def _local_notes_line(character: dict[str, Any]) -> str:
    notes = (character.get("notes") or "").strip()
    return f"\nAuthor's corrections, which take precedence over everything above: {notes}" if notes else ""


def generate_character_anchor(project: dict[str, Any], character: dict[str, Any]) -> Path:
    """Generate (or regenerate) a character's front-facing anchor portrait."""
    request = anchor_request(project, character)
    with usage.project_context(project["slug"]):
        image = _generate_image(**request)
    dest = character_anchor_path(project, character)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_finish(project, image))
    return dest


def generate_location_image(project: dict[str, Any], location: dict[str, Any]) -> Path:
    """Generate (or regenerate) a location's establishing shot."""
    description = location.get("description", "")
    if description == "undefined":
        description = ""
    prompt = LOCATION_PROMPT.format(
        style=_style_prompt(project),
        name=location["name"],
        description=description,
    )
    with usage.project_context(project["slug"]):
        if _use_local():
            tuning = _local_tuning(project)
            # Gemini returns a wide shot by default; ask the local model for the same.
            image = _generate_image(
                prompt,
                aspect_ratio="16:9",
                negative_prompt=LOCAL_LOCATION_NEGATIVE + tuning.get("negative", ""),
                guidance=tuning.get("guidance"),
            )
        else:
            image = _generate_image(prompt)
    dest = location_image_path(project, location)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_finish(project, image))
    return dest
