"""PDF export of a project's current state.

Builds a single PDF with everything generated so far: cover and story summary,
characters (anchor portrait, attributes, presentation sheet), locations
(establishing shot, sheet), key passages, and an appendix of research sources.
Entities without images are still listed, so a partially illustrated project
exports fine. No Gemini calls are made.

Output goes to ``projects/<slug>/exports/<slug>-<timestamp>.pdf``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.imaging import (
    character_anchor_path,
    character_sheet_path,
    location_image_path,
    location_sheet_path,
)
from app.core.ingestion import character_research_path, load_entities
from app.core.projects import project_path

UNDEFINED = "undefined"
PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# Images are re-encoded as JPEG at a bounded resolution so a 13-character
# project exports to a few MB instead of tens of MB of raw PNG.
IMAGE_MAX_PX = 1600
IMAGE_JPEG_QUALITY = 85

_FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/TTF")]


def _register_fonts() -> tuple[str, str]:
    """Use DejaVu Sans when available (full Unicode), else Helvetica."""
    for directory in _FONT_DIRS:
        regular, bold = directory / "DejaVuSans.ttf", directory / "DejaVuSans-Bold.ttf"
        if regular.exists() and bold.exists():
            if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("DejaVuSans", str(regular)))
                pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(bold)))
            return "DejaVuSans", "DejaVuSans-Bold"
    return "Helvetica", "Helvetica-Bold"


def _styles() -> dict[str, ParagraphStyle]:
    body_font, bold_font = _register_fonts()
    ink, muted, accent = colors.HexColor("#1f2933"), colors.HexColor("#6b7280"), colors.HexColor("#b45309")
    return {
        "title": ParagraphStyle("title", fontName=bold_font, fontSize=30, leading=36, textColor=ink, alignment=TA_CENTER),
        "subtitle": ParagraphStyle("subtitle", fontName=body_font, fontSize=13, leading=18, textColor=muted, alignment=TA_CENTER),
        "cover_meta": ParagraphStyle("cover_meta", fontName=body_font, fontSize=9.5, leading=14, textColor=muted, alignment=TA_CENTER),
        "h1": ParagraphStyle("h1", fontName=bold_font, fontSize=20, leading=24, textColor=ink, spaceAfter=4 * mm),
        "h2": ParagraphStyle("h2", fontName=bold_font, fontSize=14, leading=18, textColor=ink, spaceAfter=1 * mm),
        "label": ParagraphStyle("label", fontName=bold_font, fontSize=7.5, leading=10, textColor=accent),
        "body": ParagraphStyle("body", fontName=body_font, fontSize=9.5, leading=13.5, textColor=ink),
        "small": ParagraphStyle("small", fontName=body_font, fontSize=8.5, leading=11.5, textColor=muted),
        "cell_key": ParagraphStyle("cell_key", fontName=bold_font, fontSize=8.5, leading=11, textColor=ink),
        "cell_val": ParagraphStyle("cell_val", fontName=body_font, fontSize=8.5, leading=11, textColor=ink),
        "placeholder": ParagraphStyle("placeholder", fontName=body_font, fontSize=8.5, leading=11, textColor=muted, alignment=TA_CENTER),
        "caption": ParagraphStyle("caption", fontName=body_font, fontSize=8, leading=10, textColor=muted, alignment=TA_CENTER, spaceBefore=1 * mm),
    }


def _defined(value: Any) -> bool:
    return value not in (None, "", UNDEFINED, [])


def _text(value: Any) -> str:
    return escape(str(value))


def _fit_image(path: Path, max_w: float, max_h: float) -> Image | None:
    """Downscale/re-encode an image and return a flowable that fits the box."""
    try:
        with PILImage.open(path) as img:
            img.load()
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                background = PILImage.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.split()[-1])
                img = background
            else:
                img = img.convert("RGB")
            img.thumbnail((IMAGE_MAX_PX, IMAGE_MAX_PX))
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
            width_px, height_px = img.size
    except OSError:
        return None
    buffer.seek(0)
    scale = min(max_w / width_px, max_h / height_px)
    return Image(buffer, width=width_px * scale, height=height_px * scale)


def _placeholder(text: str, width: float, height: float, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table([[Paragraph(text, styles["placeholder"])]], colWidths=[width], rowHeights=[height])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f4f6")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def _attributes_table(rows: list[tuple[str, str]], styles: dict[str, ParagraphStyle], width: float) -> Table:
    data = [[Paragraph(_text(k), styles["cell_key"]), Paragraph(_text(v), styles["cell_val"])] for k, v in rows]
    table = Table(data, colWidths=[32 * mm, width - 32 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e5e7eb")),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _media_row(image: Image | Table, right: list[Any], image_w: float) -> Table:
    table = Table([[image, right]], colWidths=[image_w, CONTENT_W - image_w])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (-1, -1), (-1, -1), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _sources_from_markdown(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return re.findall(r"^- \[(.+?)\]\((\S+?)\)\s*$", text, flags=re.MULTILINE)


def _story_meta(project: dict[str, Any]) -> tuple[str, str, list[str]]:
    book = project.get("book") or {}
    title = book.get("title") if _defined(book.get("title")) else project["name"]
    author = book.get("author") if _defined(book.get("author")) else ""
    bits = [book.get(f) for f in ("publication_year", "genre", "original_language") if _defined(book.get(f))]
    return title, author, bits


def _footer_factory(label: str, font: str):
    def draw(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#9ca3af"))
        canvas.drawString(MARGIN, 11 * mm, label)
        canvas.drawRightString(PAGE_W - MARGIN, 11 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _cover(project: dict[str, Any], characters: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> list[Any]:
    title, author, bits = _story_meta(project)
    story: list[Any] = [Spacer(1, 30 * mm), Paragraph(_text(title), styles["title"])]
    if author:
        story.append(Paragraph(_text(author), styles["subtitle"]))
    if bits:
        story.append(Paragraph(_text(" · ".join(bits)), styles["cover_meta"]))
    story.append(Spacer(1, 8 * mm))

    hero = next(
        (character_anchor_path(project, c) for c in characters if character_anchor_path(project, c).exists()),
        None,
    )
    if hero:
        image = _fit_image(hero, CONTENT_W, 110 * mm)
        if image:
            image.hAlign = "CENTER"
            story += [image, Spacer(1, 8 * mm)]
    else:
        story.append(Spacer(1, 60 * mm))

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story.append(
        Paragraph(
            _text(f"Project “{project['name']}” · Illustration style: {project.get('style', '—')} · "
                  f"Status: {project.get('status', '—')}"),
            styles["cover_meta"],
        )
    )
    story.append(Paragraph(_text(f"Generated by Once Upon a Time on {generated}"), styles["cover_meta"]))
    story.append(PageBreak())
    return story


def _summary(project: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    book = project.get("book") or {}
    story: list[Any] = []
    if _defined(book.get("summary")):
        story += [Paragraph("The story", styles["h1"]), Paragraph(_text(book["summary"]), styles["body"])]
        themes = [t for t in (book.get("themes") or []) if _defined(t)]
        if themes:
            story += [Spacer(1, 3 * mm), Paragraph("THEMES", styles["label"])]
            story += [Paragraph(f"• {_text(t)}", styles["body"]) for t in themes]
    elif _defined(project.get("description")):
        story += [Paragraph("About this project", styles["h1"]), Paragraph(_text(project["description"]), styles["body"])]
    if story:
        story.append(PageBreak())
    return story


def _characters(
    project: dict[str, Any],
    characters: list[dict[str, Any]],
    styles: dict[str, ParagraphStyle],
    include_sheets: bool,
) -> list[Any]:
    if not characters:
        return []
    story: list[Any] = [Paragraph(f"Characters ({len(characters)})", styles["h1"])]
    image_w = 52 * mm
    for index, character in enumerate(characters):
        anchor = character_anchor_path(project, character)
        image = (_fit_image(anchor, image_w, 78 * mm) if anchor.exists() else None) or _placeholder(
            "No portrait yet", image_w, 60 * mm, styles
        )

        aliases = ", ".join(a for a in (character.get("aliases") or []) if _defined(a))
        right: list[Any] = [Paragraph(_text(character["name"]), styles["h2"])]
        meta = [f"Role: {character['role']}" for _ in [0] if _defined(character.get("role"))]
        if aliases:
            meta.append(f"Also known as: {aliases}")
        if character.get("deep_researched"):
            meta.append("Deep-researched")
        if meta:
            right.append(Paragraph(_text(" · ".join(meta)), styles["small"]))
        right.append(Spacer(1, 2 * mm))
        if _defined(character.get("physical_description")):
            right.append(Paragraph(_text(character["physical_description"]), styles["body"]))
            right.append(Spacer(1, 2 * mm))
        sheet_rows = [
            (field.replace("_", " ").capitalize(), value)
            for field, value in (character.get("sheet") or {}).items()
            if _defined(value)
        ]
        if sheet_rows:
            right.append(_attributes_table(sheet_rows, styles, CONTENT_W - image_w - 5 * mm))
        if _defined(character.get("notes")):
            right += [Spacer(1, 2 * mm), Paragraph("AUTHOR'S NOTES", styles["label"]), Paragraph(_text(character["notes"]), styles["small"])]

        story.append(KeepTogether([_media_row(image, right, image_w)]))

        sheet = character_sheet_path(project, character)
        if include_sheets and sheet.exists():
            sheet_image = _fit_image(sheet, CONTENT_W, 125 * mm)
            if sheet_image:
                sheet_image.hAlign = "CENTER"
                story += [Spacer(1, 4 * mm), sheet_image, Paragraph("Production-design presentation sheet", styles["caption"])]

        if index < len(characters) - 1:
            story += [Spacer(1, 4 * mm), HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#e5e7eb")), Spacer(1, 4 * mm)]
    story.append(PageBreak())
    return story


def _locations(
    project: dict[str, Any],
    locations: list[dict[str, Any]],
    styles: dict[str, ParagraphStyle],
    include_sheets: bool,
) -> list[Any]:
    if not locations:
        return []
    story: list[Any] = [Paragraph(f"Locations ({len(locations)})", styles["h1"])]
    image_w = 62 * mm
    for index, location in enumerate(locations):
        image_path = location_image_path(project, location)
        image = (_fit_image(image_path, image_w, 50 * mm) if image_path.exists() else None) or _placeholder(
            "No image yet", image_w, 36 * mm, styles
        )
        right: list[Any] = [Paragraph(_text(location["name"]), styles["h2"])]
        if _defined(location.get("description")):
            right.append(Paragraph(_text(location["description"]), styles["body"]))
        if _defined(location.get("relevance")):
            right += [Spacer(1, 1.5 * mm), Paragraph(_text(f"Relevance: {location['relevance']}"), styles["small"])]
        story.append(KeepTogether([_media_row(image, right, image_w)]))

        sheet = location_sheet_path(project, location)
        if include_sheets and sheet.exists():
            sheet_image = _fit_image(sheet, CONTENT_W, 125 * mm)
            if sheet_image:
                sheet_image.hAlign = "CENTER"
                story += [Spacer(1, 4 * mm), sheet_image, Paragraph("Environment presentation sheet", styles["caption"])]
        if index < len(locations) - 1:
            story += [Spacer(1, 4 * mm), HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#e5e7eb")), Spacer(1, 4 * mm)]
    story.append(PageBreak())
    return story


def _passages(passages: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> list[Any]:
    if not passages:
        return []
    story: list[Any] = [Paragraph(f"Key passages ({len(passages)})", styles["h1"])]
    for index, passage in enumerate(passages, start=1):
        block: list[Any] = [Paragraph(_text(f"{index}. {passage['title']}"), styles["h2"])]
        meta = []
        if _defined(passage.get("passage_type")):
            meta.append(f"Type: {passage['passage_type']}")
        if _defined(passage.get("location")):
            meta.append(f"Location: {passage['location']}")
        if meta:
            block.append(Paragraph(_text(" · ".join(meta)), styles["small"]))
        if _defined(passage.get("summary")):
            block += [Spacer(1, 1.5 * mm), Paragraph(_text(passage["summary"]), styles["body"])]
        present = [p for p in (passage.get("characters_present") or []) if _defined(p)]
        if present:
            block += [Spacer(1, 1.5 * mm), Paragraph(_text("Characters present: " + ", ".join(present)), styles["small"])]
        block.append(Spacer(1, 5 * mm))
        story.append(KeepTogether(block))
    story.append(PageBreak())
    return story


def _sources(project: dict[str, Any], characters: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> list[Any]:
    root = project_path(project["slug"])
    groups: list[tuple[str, list[tuple[str, str]]]] = []
    book_sources = [(s.get("title") or s["uri"], s["uri"]) for s in ((project.get("source") or {}).get("sources") or []) if s.get("uri")]
    book_sources += _sources_from_markdown(root / "source" / "research.md")
    if book_sources:
        groups.append(("Book research", book_sources))
    for character in characters:
        found = _sources_from_markdown(character_research_path(project, character))
        if found:
            groups.append((character["name"], found))
    if not groups:
        return []

    story: list[Any] = [Paragraph("Research sources", styles["h1"])]
    for heading, items in groups:
        # Grounding titles are usually bare domains, so de-duplicate on the title:
        # one line per source site, linked to the first URI seen for it.
        seen: set[str] = set()
        lines = []
        for title, uri in items:
            if title in seen:
                continue
            seen.add(title)
            lines.append(Paragraph(f'• <link href="{escape(uri, {chr(34): "&quot;"})}" color="#1d4ed8">{_text(title)}</link>', styles["small"]))
        story.append(KeepTogether([Paragraph(_text(heading).upper(), styles["label"]), *lines, Spacer(1, 3 * mm)]))
    return story


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def exports_dir(project: dict[str, Any]) -> Path:
    return project_path(project["slug"]) / "exports"


def export_project_pdf(
    project: dict[str, Any],
    include_sheets: bool = True,
    include_sources: bool = True,
) -> Path:
    """Render the project's current state to a PDF and return its path."""
    styles = _styles()
    body_font, _ = _register_fonts()
    characters = load_entities(project, "characters")
    locations = load_entities(project, "locations")
    passages = load_entities(project, "passages")

    story: list[Any] = []
    story += _cover(project, characters, styles)
    story += _summary(project, styles)
    story += _characters(project, characters, styles, include_sheets)
    story += _locations(project, locations, styles, include_sheets)
    story += _passages(passages, styles)
    if include_sources:
        story += _sources(project, characters, styles)
    if not story:
        story = [Paragraph(_text(project["name"]), styles["title"])]
    # Drop a trailing page break so the document does not end with a blank page.
    while story and isinstance(story[-1], PageBreak):
        story.pop()

    dest_dir = exports_dir(project)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"{project['slug']}-{stamp}.pdf"

    title, author, _ = _story_meta(project)
    doc = SimpleDocTemplate(
        str(dest),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=title,
        author=author or "Once Upon a Time",
        subject="Characters, locations and key passages",
        creator="Once Upon a Time",
    )
    footer = _footer_factory(f"{title} · Once Upon a Time", body_font)
    doc.build(story, onFirstPage=lambda c, d: None, onLaterPages=footer)
    return dest
