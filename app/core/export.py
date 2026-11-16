"""PDF export of a project's current state, laid out as a landscape art book.

The book is A4 landscape, because every image the app generates is either a
landscape sheet, a 16:9 establishing shot or an upright portrait that fills the
page height:

- cover: a full-bleed establishing shot (or a lineup of portraits) under the title
- the story: summary with a drop cap, book facts and themes
- the cast / the world: dark index pages, one linked tile per character or location
- characters: a full-height portrait beside the description and design notes,
  then the presentation sheet as a full-page plate
- locations: the establishing shot over its description, then the sheet plate
- key passages (two columns) and research sources (four columns)

The accent colour is sampled from the cover artwork, so each book gets its own
palette. Entities without images are still laid out, so a partially illustrated
project exports fine. No Gemini calls are made. Fonts, colours, image preparation
and the custom flowables live in ``pdf_kit.py``.

Output goes to ``projects/<slug>/exports/<slug>-<timestamp>.pdf``.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib.colors import Color
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    FrameBreak,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import ImageAndFlowables

from app.core import credits, translation
from app.core.imaging import (
    character_anchor_path,
    character_sheet_path,
    location_image_path,
    location_sheet_path,
)
from app.core.ingestion import character_research_path, load_entities
from app.core.pdf_kit import (
    Artwork,
    DropCap,
    Paint,
    Picture,
    Rule,
    Tracked,
    balanced_runs,
    clean_text,
    colorfulness,
    dominant_hue,
    draw_stack,
    draw_tracked,
    font_for,
    hex_color,
    load_fonts,
    markup,
    para,
    para_style,
    rgb255,
    sample_pixels,
    stack_height,
    theme_for_hue,
)
from app.core.projects import project_path
from app.core.translation import source_name

UNDEFINED = "undefined"

# --- Page geometry (points) ---------------------------------------------------------------
PAGE_W, PAGE_H = landscape(A4)
MARGIN_X = 15 * mm
MARGIN_TOP = 15 * mm
MARGIN_BOTTOM = 17 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
BODY_H = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM
FOOTER_Y = 8.5 * mm

PANEL_W = 118 * mm  # full-height portrait on a character page
PROFILE_X = PANEL_W + 14 * mm
PROFILE_W = PAGE_W - MARGIN_X - PROFILE_X
STORY_SIDE_W = 99 * mm  # tinted panel of book facts beside the summary
STORY_W = PAGE_W - STORY_SIDE_W - MARGIN_X - 16 * mm
STORY_H = BODY_H - 3 * mm
HEADER_H = 31 * mm  # section title above the columns of passages and sources
COLUMN_GAP = 9 * mm

INDEX_TOP = PAGE_H - 49 * mm  # tile grid on the cast / world index pages
INDEX_GAP = 5 * mm
INDEX_CAPTION_H = 11.5 * mm
INDEX_LIST_ROWS = 12  # rows per column when an index has no pictures and lists names instead

LOCATION_IMAGE_MAX_H = 150 * mm
LOCATION_IMAGE_MIN_H = 92 * mm
LOCATION_BAND_H = 68 * mm  # title band of a location that has no image yet

# Text that must fit a fixed area is set at the first of these scales that fits.
FIT_SCALES = (1.0, 0.95, 0.9, 0.86, 0.82)
FIT_SCALES_DEEP = FIT_SCALES + (0.76, 0.7, 0.64, 0.58)

# Longest side, in pixels, of each kind of image once embedded.
COVER_PX = 2200
SHEET_PX = 1800
PORTRAIT_PX = 1700
TILE_PX = 420

# --- Project data -------------------------------------------------------------------------


def _defined(value: Any) -> bool:
    return value not in (None, "", UNDEFINED, [])


def _story_meta(project: dict[str, Any]) -> tuple[str, str, list[str]]:
    book = project.get("book") or {}
    title = book.get("title") if _defined(book.get("title")) else project["name"]
    author = book.get("author") if _defined(book.get("author")) else ""
    bits = [book.get(f) for f in ("publication_year", "genre", "original_language") if _defined(book.get(f))]
    return title, author, bits


def _sources_from_markdown(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return re.findall(r"^- \[(.+?)\]\((\S+?)\)\s*$", text, flags=re.MULTILINE)


def _initials(name: str) -> str:
    skip = {"the", "of", "and", "a", "an", "de", "la", "el", "los", "las"}
    words = [word for word in re.split(r"[^\w]+", name) if word and word.lower() not in skip]
    return "".join(word[0] for word in words[:2]).upper() or "?"


def cover_choices(project: dict[str, Any]) -> list[str]:
    """Names of the locations whose establishing shot can be the cover."""
    return [
        location["name"]
        for location in load_entities(project, "locations")
        if location_image_path(project, location).exists()
    ]


def custom_cover_path(project: dict[str, Any]) -> Path:
    """An artwork made for the cover (``images/cover.png``); used instead of a location when present."""
    return project_path(project["slug"]) / "images" / "cover.png"


def _cover_image(project: dict[str, Any], locations: list[dict[str, Any]], cover: str | None) -> Path | None:
    """The requested location's establishing shot, else the custom cover artwork, else the most
    vivid establishing shot."""
    custom = custom_cover_path(project)
    if cover is None and custom.exists():
        return custom
    shots = [(source_name(loc)["name"], location_image_path(project, source_name(loc))) for loc in locations]
    shots = [(name, path) for name, path in shots if path.exists()]
    for name, path in shots:
        if name == cover:
            return path
    return max((path for _, path in shots), key=lambda path: colorfulness(sample_pixels(path)), default=None)


# --- The book -----------------------------------------------------------------------------


class _Book:
    def __init__(
        self, project: dict[str, Any], include_sheets: bool, include_sources: bool, cover: str | None, language: str = "en"
    ) -> None:
        self.language = language
        self.t = translation.labeler(language)
        tr = translation.load_translation(project, language)
        self.translation = tr
        project = translation.translate_book(project, tr)
        self.project = project
        self.include_sheets = include_sheets
        self.include_sources = include_sources
        self.fonts = load_fonts()
        self.art = Artwork()
        self.characters, self.locations, self.passages = translation.translate_entities(
            load_entities(project, "characters"),
            load_entities(project, "locations"),
            load_entities(project, "passages"),
            tr,
        )
        self.title, self.author, self.meta = _story_meta(project)

        anchors = [character_anchor_path(project, source_name(character)) for character in self.characters]
        self.lineup = [path for path in anchors if path.exists()][:4]
        self.cover = _cover_image(project, self.locations, cover)
        swatch = self.cover or (self.lineup[0] if self.lineup else None)
        self.theme = theme_for_hue(dominant_hue(sample_pixels(swatch)) if swatch else None)

        self._scratch = Canvas(BytesIO())  # for measuring flowables before the document exists
        self.pages: dict[str, int] = {}  # page of each bookmark, from the previous pass
        self.seen: dict[str, int] = {}  # ... as recorded during this pass
        self.section = ""

    def _count(self, items: list[Any], singular: str, plural: str) -> str:
        return f"{len(items)} {self.t(singular) if len(items) == 1 else self.t(plural)}"

    # -- document ---------------------------------------------------------------------

    def render(self, target: Any) -> None:
        self.pages, self.seen, self.section = self.seen, {}, ""
        doc = BaseDocTemplate(
            target,
            pagesize=(PAGE_W, PAGE_H),
            leftMargin=0,
            rightMargin=0,
            topMargin=0,
            bottomMargin=0,
            title=self.title,
            author=self.author or "Once Upon a Time",
            subject=self.t("Characters, locations and key passages"),
            creator="Once Upon a Time",
        )
        doc.addPageTemplates(self._templates())
        doc.build(self._story())

    def _templates(self) -> list[PageTemplate]:
        def frame(x: float, y: float, width: float, height: float) -> Frame:
            return Frame(x, y, width, height, leftPadding=0, bottomPadding=0, rightPadding=0, topPadding=0)

        def columns(count: int, top: float) -> list[Frame]:
            width = (CONTENT_W - COLUMN_GAP * (count - 1)) / count
            return [
                frame(MARGIN_X + i * (width + COLUMN_GAP), MARGIN_BOTTOM, width, top - MARGIN_BOTTOM)
                for i in range(count)
            ]

        def header() -> Frame:
            return frame(MARGIN_X, PAGE_H - MARGIN_TOP - HEADER_H, CONTENT_W, HEADER_H)

        light = {"onPage": self._paint_paper, "onPageEnd": lambda canvas, doc: self._draw_footer(canvas, MARGIN_X)}
        templates = [
            PageTemplate("full", [frame(0, 0, PAGE_W, PAGE_H)]),  # first: the cover uses it
            PageTemplate(
                "profile",
                [frame(PROFILE_X, MARGIN_BOTTOM, PROFILE_W, BODY_H)],
                onPage=self._paint_paper,
                onPageEnd=lambda canvas, doc: self._draw_footer(canvas, PROFILE_X),
                autoNextPageTemplate="text",
            ),
            PageTemplate("story", [frame(MARGIN_X, MARGIN_BOTTOM, STORY_W, STORY_H)], autoNextPageTemplate="text", **light),
            PageTemplate("text", [frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W, BODY_H)], **light),
        ]
        for count in (2, 4):
            templates.append(
                PageTemplate(
                    f"cols{count}_first",
                    [header()] + columns(count, PAGE_H - MARGIN_TOP - HEADER_H),
                    autoNextPageTemplate=f"cols{count}",
                    **light,
                )
            )
            templates.append(PageTemplate(f"cols{count}", columns(count, PAGE_H - MARGIN_TOP), **light))
        for template in templates:  # the credit line goes on every page, after its own footer
            template.onPageEnd = self._with_credit(template.onPageEnd)
        return templates

    def _with_credit(self, on_page_end: Callable[..., None]) -> Callable[..., None]:
        def end(canvas: Any, doc: Any) -> None:
            on_page_end(canvas, doc)
            self._draw_credit(canvas)

        return end

    def _draw_credit(self, canvas: Any) -> None:
        """'Made with Once Upon a Time · <repo>' under the footer, linked to the repository.

        A mid gray reads on the paper pages and on the dark ones alike."""
        text = credits.footer_line(self.t)
        size, y = 5.2, 3.6 * mm
        canvas.saveState()
        canvas.setFont(self.fonts.ui, size)
        canvas.setFillColor(Color(0.56, 0.55, 0.53))
        canvas.drawCentredString(PAGE_W / 2, y, text)
        width = pdfmetrics.stringWidth(text, self.fonts.ui, size)
        canvas.linkURL(credits.REPO_URL, (PAGE_W / 2 - width / 2, y - 1.5, PAGE_W / 2 + width / 2, y + size), relative=0)
        canvas.restoreState()

    def _story(self) -> list[Flowable]:
        units: list[tuple[str, list[Flowable]]] = [("full", [self._page(self._paint_cover)])]
        units += self._story_units()
        units += self._character_units()
        units += self._location_units()
        units += self._passage_units()
        if self.include_sources:
            units += self._source_units()
        units += self._credit_units()

        story: list[Flowable] = []
        for index, (template, flowables) in enumerate(units):
            if index:
                story += [NextPageTemplate(template), PageBreak()]
            story += flowables
        return story

    # -- shared drawing ---------------------------------------------------------------

    @staticmethod
    def _page(painter: Callable[[Any], None]) -> Paint:
        return Paint(painter, PAGE_W, PAGE_H - 1)

    @staticmethod
    def _fill(canvas: Any, color: Color) -> None:
        canvas.setFillColor(color)
        canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    def _paint_paper(self, canvas: Any, doc: Any = None) -> None:
        self._fill(canvas, self.theme.paper)

    def _mark(self, canvas: Any, key: str, title: str, level: int) -> None:
        """Bookmark this page, add it to the PDF outline and remember its number."""
        canvas.bookmarkPage(key, fit="Fit")
        canvas.addOutlineEntry(title, key, level=level)
        self.seen[key] = canvas.getPageNumber()

    def _draw_footer(self, canvas: Any, x: float, dark: bool = False, label: str | None = None) -> None:
        theme, fonts = self.theme, self.fonts
        if label is None:
            label = f"{self.title}   ·   {self.section}" if self.section else self.title
        draw_tracked(
            canvas, x, FOOTER_Y, label, fonts.ui_bold, 6.2,
            theme.on_night_muted if dark else theme.muted, 1.3,
            max_width=PAGE_W - MARGIN_X - x - 20 * mm,
        )
        canvas.setFont(fonts.ui_bold, 8)
        canvas.setFillColor(theme.on_night if dark else theme.ink)
        canvas.drawRightString(PAGE_W - MARGIN_X, FOOTER_Y, str(canvas.getPageNumber()))

    def _fit_title(self, text: str, font: str, sizes: tuple[float, ...], width: float, color: Color, max_lines: int) -> Paragraph:
        """The title at the largest size that wraps into ``max_lines`` lines."""
        for size in sizes:
            paragraph = para(text, para_style(font, size, size * (1.06 if size > 20 else 1.14), color))
            paragraph.wrap(width, 1e5)
            if len(paragraph.blPara.lines) <= max_lines:
                break
        return paragraph

    def _kicker(self, text: str, color: Color | None = None, size: float = 7.4) -> Tracked:
        return Tracked(text, self.fonts.ui_bold, size, color or self.theme.accent, size * 0.26)

    def _label(self, text: str, scale: float = 1.0, color: Color | None = None) -> Tracked:
        return Tracked(text, self.fonts.ui_bold, 6.4 * scale, color or self.theme.accent, 1.1 * scale, space_after=1.6 * scale)

    @staticmethod
    def _rounded_image(canvas: Any, pic: Picture, x: float, y: float, width: float, height: float, radius: float) -> None:
        canvas.saveState()
        path = canvas.beginPath()
        path.roundRect(x, y, width, height, radius)
        canvas.clipPath(path, stroke=0, fill=0)
        canvas.drawImage(pic.reader(), x, y, width, height)
        canvas.restoreState()

    # -- cover ------------------------------------------------------------------------

    def _paint_cover(self, canvas: Any) -> None:
        theme, fonts = self.theme, self.fonts
        night = rgb255(theme.night)
        self._fill(canvas, theme.night)
        text_w, right = PAGE_W * 0.72, PAGE_W - MARGIN_X
        pic = None
        if self.cover:
            pic = self.art.crop(self.cover, PAGE_W / PAGE_H, COVER_PX, shade=(night, 0.6, 0.95, 0.28, 0.08), trim_bars=True)
        if pic:
            canvas.drawImage(pic.reader(), 0, 0, PAGE_W, PAGE_H)
        elif self.lineup:  # no establishing shot yet: slivers of the first portraits
            strip_x, gap = PAGE_W * 0.54, 1.2 * mm
            width = (PAGE_W - strip_x - gap * (len(self.lineup) - 1)) / len(self.lineup)
            for index, path in enumerate(self.lineup):
                sliver = self.art.crop(path, width / PAGE_H, PORTRAIT_PX)
                if sliver:
                    canvas.drawImage(sliver.reader(), strip_x + index * (width + gap), 0, width, PAGE_H)
            text_w = strip_x - MARGIN_X - 12 * mm
            right = MARGIN_X + text_w
        else:  # no images at all: the title's initial as a quiet ornament
            canvas.setFont(fonts.display, 520)
            canvas.setFillColor(theme.night_soft)
            canvas.drawRightString(PAGE_W - 6 * mm, -40, self.title.strip()[:1].upper())

        draw_tracked(canvas, MARGIN_X, PAGE_H - 14 * mm, "Once Upon a Time", fonts.ui_bold, 7.2, theme.on_night, 2.4)
        kicker = self.t("Character & world bible")
        if pic:  # over artwork small type is only safe in the shaded top corner
            draw_tracked(canvas, PAGE_W - MARGIN_X, PAGE_H - 14 * mm, kicker, fonts.ui_bold, 7.2, theme.on_night, 2.4, align="right")

        # Colophon under a hairline, then the title block stacked above it.
        base = 14 * mm
        counts = [
            self._count(items, singular, plural)
            for items, singular, plural in (
                (self.characters, "character", "characters"),
                (self.locations, "location", "locations"),
                (self.passages, "key passage", "key passages"),
            )
            if items
        ]
        today = datetime.now(timezone.utc)
        month = translation.month_name(self.language, today.month) or f"{today:%B}"
        credit = f"{today.day} {month} {today.year}"
        if _defined(self.project.get("style")):
            credit = self.t("{style} style", style=self.t(self.project["style"])) + f"   ·   {credit}"
        colophon = dict(font=fonts.ui_bold, size=6.8, color=theme.on_night_muted, tracking=1.4)
        used = draw_tracked(canvas, MARGIN_X, base, "   ·   ".join(counts), **colophon) if counts else 0
        credit_w = pdfmetrics.stringWidth(credit.upper(), fonts.ui_bold, 6.8) + 1.4 * len(credit)
        if used + credit_w + 10 * mm <= right - MARGIN_X:
            draw_tracked(canvas, right, base, credit, align="right", **colophon)
        else:
            base += 4.5 * mm  # no room beside the counts: the credit goes on a line above
            draw_tracked(canvas, MARGIN_X, base, credit, **colophon)
        line_y = base + 6.5 * mm
        canvas.saveState()
        canvas.setStrokeColor(theme.on_night)
        canvas.setStrokeAlpha(0.35)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_X, line_y, right, line_y)
        canvas.restoreState()

        blocks: list[Flowable] = [] if pic else [self._kicker(kicker, theme.accent_night, 7.6), Spacer(1, 4.5 * mm)]
        blocks.append(self._fit_title(self.title, fonts.display, (62, 54, 46, 40, 34, 29), text_w, theme.on_night, 3))
        if self.author:
            blocks += [Spacer(1, 3.5 * mm), para(self.author, para_style(fonts.display_italic, 19, 23, theme.on_night))]
        if self.meta:
            blocks += [Spacer(1, 3 * mm), para("  ·  ".join(self.meta), para_style(fonts.ui, 9.6, 13.5, theme.on_night_muted))]
        draw_stack(canvas, blocks, MARGIN_X, line_y + 9 * mm + stack_height(blocks, text_w, canvas), text_w)

    # -- the story --------------------------------------------------------------------

    def _lead(self, text: str, scale: float) -> list[Flowable]:
        """Opening text: large serif paragraphs, the first with a three-line drop cap."""
        theme, fonts = self.theme, self.fonts
        size, leading = 11.4 * scale, 17.6 * scale
        style = para_style(fonts.text, size, leading, theme.ink, TA_JUSTIFY)
        paragraphs = [part.strip() for part in clean_text(text).split("\n") if part.strip()]
        out: list[Flowable] = []
        for index, paragraph in enumerate(paragraphs):
            if index:
                out.append(Spacer(1, leading * 0.5))
            letter = paragraph[0]
            if index == 0 and letter.isalpha() and font_for(letter, fonts.display) == fonts.display and len(paragraph) > 240:
                cap_height = getattr(pdfmetrics.getFont(fonts.display).face, "capHeight", 700) / 1000
                body_cap = getattr(pdfmetrics.getFont(fonts.text).face, "capHeight", 660) / 1000
                cap_size = (2 * leading + body_cap * size) / cap_height
                cap = DropCap(letter, fonts.display, cap_size, theme.accent, 3 * leading - 1, leading - size - 1)
                rest = Paragraph(markup(paragraph[1:], fonts.text), style)
                out.append(ImageAndFlowables(cap, [rest], imageSide="left", imageRightPadding=3.2 * scale + 1, imageBottomPadding=0))
            else:
                out.append(Paragraph(markup(paragraph, fonts.text), style))
        return out

    def _story_units(self) -> list[tuple[str, list[Flowable]]]:
        theme, fonts = self.theme, self.fonts
        book = self.project.get("book") or {}
        has_summary = _defined(book.get("summary"))
        if not has_summary and not _defined(self.project.get("description")):
            return []
        text = book["summary"] if has_summary else self.project["description"]
        # Larger type for a short summary, smaller for a long one; a summary too long even
        # then continues on a plain page.
        for scale in (1.16, 1.08) + FIT_SCALES + (0.76,):
            content: list[Flowable] = [
                self._kicker(self.title if has_summary else "Once Upon a Time"),
                Spacer(1, 4 * mm),
                para(self.t("The story") if has_summary else self.t("About this project"), para_style(fonts.display, 38, 40, theme.ink)),
                Spacer(1, 5.5 * mm),
                Rule(26 * mm, 1.6, theme.accent),
                Spacer(1, 8 * mm),
                *self._lead(text, scale),
            ]
            if stack_height(content, STORY_W, self._scratch) <= STORY_H - 2:
                break
        return [("story", [Paint(self._paint_story_side), *content])]

    def _paint_story_side(self, canvas: Any) -> None:
        """Book facts and themes on a tinted panel down the right of the story page."""
        theme, fonts = self.theme, self.fonts
        book = self.project.get("book") or {}
        self.section = self.t("The story")
        self._mark(canvas, "story", self.t("The story"), 0)
        canvas.setFillColor(theme.tint)
        canvas.rect(PAGE_W - STORY_SIDE_W, 0, STORY_SIDE_W, PAGE_H, stroke=0, fill=1)

        facts = [
            (label, value)
            for label, value in (
                (self.t("Author"), self.author),
                (self.t("First published"), book.get("publication_year")),
                (self.t("Genre"), book.get("genre")),
                (self.t("Original language"), book.get("original_language")),
                (self.t("Illustration style"), self.t(self.project.get("style") or "")),
            )
            if _defined(value)
        ]
        themes = [item for item in (book.get("themes") or []) if _defined(item)]
        top = PAGE_H - MARGIN_TOP - 11 * mm
        width = STORY_SIDE_W - 13 * mm - MARGIN_X
        for scale in FIT_SCALES_DEEP:
            value_style = para_style(fonts.text, 10.8 * scale, 14.6 * scale, theme.ink)
            theme_style = para_style(
                fonts.text_italic, 10.8 * scale, 14.8 * scale, theme.ink,
                leftIndent=17 * scale, bulletIndent=0, bulletFontName=fonts.display,
                bulletFontSize=12.5 * scale, bulletColor=theme.accent,
            )
            blocks: list[Flowable] = []
            for label, value in facts:
                blocks += [self._label(label, scale), para(value, value_style), Spacer(1, 9 * scale)]
            if themes:
                if facts:
                    blocks += [Spacer(1, 3 * scale), Rule(width, 0.5, theme.accent), Spacer(1, 12 * scale)]
                blocks += [self._label(self.t("Themes"), scale), Spacer(1, 3 * scale)]
                for number, item in enumerate(themes, start=1):
                    blocks += [Paragraph(markup(item, fonts.text_italic), theme_style, bulletText=str(number)), Spacer(1, 6.5 * scale)]
            if stack_height(blocks, width, canvas) <= top - MARGIN_BOTTOM:
                break
        draw_stack(canvas, blocks, PAGE_W - STORY_SIDE_W + 13 * mm, top, width)

    # -- index pages (the cast, the world) --------------------------------------------

    def _index_units(
        self, kicker: str, title: str, key: str, outline: str, tiles: list[dict[str, Any]], aspect: float, min_cols: int, max_cols: int
    ) -> list[tuple[str, list[Flowable]]]:
        area_h = INDEX_TOP - MARGIN_BOTTOM
        if not any(tile["path"] for tile in tiles):  # nothing to show yet: a table of contents
            cols = 2 if len(tiles) <= 2 * INDEX_LIST_ROWS else 3 if len(tiles) <= 3 * INDEX_LIST_ROWS else 4
            return [
                ("full", [self._page(partial(self._paint_contents, kicker, title, key if start == 0 else None, outline, tiles[start : start + cols * INDEX_LIST_ROWS], start, cols))])
                for start in range(0, len(tiles), cols * INDEX_LIST_ROWS)
            ]
        for cols in range(min_cols, max_cols + 1):
            tile_w = (CONTENT_W - INDEX_GAP * (cols - 1)) / cols
            tile_h = tile_w / aspect
            rows = max(1, int((area_h + INDEX_GAP) // (tile_h + INDEX_CAPTION_H + INDEX_GAP)))
            if cols * rows >= len(tiles):
                break
        units = []
        for start in range(0, len(tiles), cols * rows):
            painter = partial(
                self._paint_index, kicker, title, key if start == 0 else None, outline,
                tiles[start : start + cols * rows], cols, tile_w, tile_h,
            )
            units.append(("full", [self._page(painter)]))
        return units

    def _paint_index_heading(self, canvas: Any, kicker: str, title: str, key: str | None, outline: str) -> None:
        theme, fonts = self.theme, self.fonts
        self._fill(canvas, theme.night)
        self.section = outline
        if key:
            self._mark(canvas, key, outline, 0)
        draw_tracked(canvas, MARGIN_X, PAGE_H - 21 * mm, kicker, fonts.ui_bold, 7.4, theme.accent_night, 1.9)
        canvas.setFont(fonts.display, 40)
        canvas.setFillColor(theme.on_night)
        canvas.drawString(MARGIN_X, PAGE_H - 37.5 * mm, title)
        self._draw_footer(canvas, MARGIN_X, dark=True)

    def _paint_contents(
        self, kicker: str, title: str, key: str | None, outline: str, entries: list[dict[str, Any]],
        first: int, cols: int, canvas: Any,
    ) -> None:
        """Index page without pictures: numbered names in columns, each linked to its page."""
        theme, fonts = self.theme, self.fonts
        self._paint_index_heading(canvas, kicker, title, key, outline)
        row_h = (INDEX_TOP - MARGIN_BOTTOM) / INDEX_LIST_ROWS
        rows = math.ceil(len(entries) / cols)
        col_w = (CONTENT_W - COLUMN_GAP * (cols - 1)) / cols
        number_w, page_w = 9 * mm, 11 * mm
        canvas.setStrokeColor(theme.night_soft)
        canvas.setLineWidth(0.6)
        for index, entry in enumerate(entries):
            x = MARGIN_X + (index // rows) * (col_w + COLUMN_GAP)
            top = INDEX_TOP - (index % rows) * row_h
            canvas.line(x, top, x + col_w, top)
            baseline = top - 4.4 * mm
            canvas.setFont(fonts.ui_bold, 7)
            canvas.setFillColor(theme.accent_night)
            canvas.drawString(x, baseline, f"{first + index + 1:02d}")
            name_w, text = col_w - number_w - page_w, entry["name"]
            name = self._fit_title(text, fonts.display, (12.5, 11, 9.6, 8.4), name_w, theme.on_night, 2)
            while len(name.blPara.lines) > 2 and " " in text:  # still too long for its row: cut words
                text = text.rsplit(" ", 1)[0]
                name = para(text + "…", name.style)
                name.wrap(name_w, 1e5)
            _, name_h = name.wrapOn(canvas, name_w, 1e5)
            name.drawOn(canvas, x + number_w, top - 1.6 * mm - name_h)
            page = self.pages.get(entry["key"])
            if page:
                canvas.setFont(fonts.ui, 8)
                canvas.setFillColor(theme.on_night_muted)
                canvas.drawRightString(x + col_w, baseline, str(page))
            canvas.linkRect("", entry["key"], (x, top - row_h, x + col_w, top), relative=0, thickness=0)

    def _paint_index(
        self, kicker: str, title: str, key: str | None, outline: str, tiles: list[dict[str, Any]],
        cols: int, tile_w: float, tile_h: float, canvas: Any,
    ) -> None:
        theme, fonts = self.theme, self.fonts
        self._paint_index_heading(canvas, kicker, title, key, outline)

        name_style = para_style(fonts.ui_bold, 8.2, 10, theme.on_night)
        for index, tile in enumerate(tiles):
            x = MARGIN_X + (index % cols) * (tile_w + INDEX_GAP)
            top = INDEX_TOP - (index // cols) * (tile_h + INDEX_CAPTION_H + INDEX_GAP)
            y = top - tile_h
            pic = self.art.crop(tile["path"], tile_w / tile_h, TILE_PX, **tile["crop"]) if tile["path"] else None
            if pic:
                self._rounded_image(canvas, pic, x, y, tile_w, tile_h, 3)
            else:
                canvas.setFillColor(theme.night_soft)
                canvas.roundRect(x, y, tile_w, tile_h, 3, stroke=0, fill=1)
                canvas.setFont(fonts.display, tile_h * 0.3)
                canvas.setFillColor(theme.on_night_muted)
                canvas.drawCentredString(x + tile_w / 2, y + tile_h * 0.4, _initials(tile["name"]))
            name = para(tile["name"], name_style)
            _, name_h = name.wrapOn(canvas, tile_w, 1e5)
            name.drawOn(canvas, x, y - 2 * mm - name_h)
            page = self.pages.get(tile["key"])
            if page:
                canvas.setFont(fonts.ui, 7)
                canvas.setFillColor(theme.accent_night)
                canvas.drawString(x, y - 2 * mm - name_h - 8.5, f"p. {page}")
            canvas.linkRect("", tile["key"], (x, y - INDEX_CAPTION_H, x + tile_w, top), relative=0, thickness=0)

    # -- characters -------------------------------------------------------------------

    def _character_units(self) -> list[tuple[str, list[Flowable]]]:
        if not self.characters:
            return []
        project = self.project
        tiles = []
        for index, character in enumerate(self.characters):
            anchor = character_anchor_path(project, source_name(character))
            upright = False
            if anchor.exists():
                try:
                    with PILImage.open(anchor) as img:
                        upright = img.height > img.width * 1.15
                except OSError:
                    pass
            tiles.append(
                {
                    "key": f"character-{index}",
                    "name": character["name"],
                    "path": anchor if anchor.exists() else None,
                    # Upright full-body portraits: move in on the head and torso.
                    "crop": {"focus": (0.5, 0.08), "zoom": 1.22} if upright else {},
                }
            )
        units = self._index_units(
            self._count(self.characters, "character", "characters"), self.t("The cast"), "characters", self.t("Characters"), tiles, 3 / 4, 5, 12
        )
        for index, character in enumerate(self.characters):
            units.append(("profile", self._profile(index, character)))
            sheet = character_sheet_path(project, source_name(character))
            if self.include_sheets and sheet.exists() and self.art.whole(sheet, SHEET_PX):
                painter = partial(self._paint_plate, sheet, character["name"], self.t("Production-design presentation sheet"))
                units.append(("full", [self._page(painter)]))
        return units

    def _definitions(self, rows: list[tuple[str, Any]], width: float, columns: int, scale: float) -> Table:
        """Label-over-value pairs flowing down ``columns`` balanced columns."""
        theme, fonts = self.theme, self.fonts
        gap = 8 * mm * scale
        column_w = (width - gap * (columns - 1)) / columns
        value_style = para_style(fonts.ui, 8.3 * scale, 11.4 * scale, theme.ink)
        items = [[self._label(label, scale), para(value, value_style), Spacer(1, 6.5 * scale)] for label, value in rows]
        runs = balanced_runs([stack_height(item, column_w) for item in items], columns)
        cells = [[flowable for item in items[start:end] for flowable in item] for start, end in runs]
        cells += [[Spacer(1, 1)] for _ in range(columns - len(cells))]
        # Half a gap of padding on each inner side puts the hairlines in the middle of the gaps.
        widths = [column_w + (gap if 0 < i < columns - 1 else gap / 2 if columns > 1 else 0) for i in range(columns)]
        table = Table([cells], colWidths=widths, splitInRow=1)
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (-1, -1), gap / 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), gap / 2),
            ("LEFTPADDING", (0, 0), (0, -1), 0),
            ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
        ]
        if columns > 1:
            style.append(("LINEAFTER", (0, 0), (-2, -1), 0.5, theme.hairline))
        table.setStyle(TableStyle(style))
        return table

    def _profile_content(self, character: dict[str, Any], scale: float) -> list[Flowable]:
        theme, fonts = self.theme, self.fonts
        kicker = self.t("Character") + ("   ·   " + self.t("Deep-researched") if character.get("deep_researched") else "")
        numeral_room = 27 * mm  # the page numeral sits in the top right corner
        out: list[Flowable] = [
            self._kicker(kicker, size=7.2 * scale),
            Spacer(1, 4 * scale),
            para(character["name"], para_style(fonts.display, 31 * scale, 33 * scale, theme.ink, rightIndent=numeral_room)),
        ]
        if _defined(character.get("role")):
            role = str(character["role"]).strip()
            out += [Spacer(1, 4 * scale), para(role[:1].upper() + role[1:], para_style(fonts.text_italic, 11.6 * scale, 15.4 * scale, theme.muted))]
        aliases = ", ".join(alias for alias in (character.get("aliases") or []) if _defined(alias))
        if aliases:
            out += [Spacer(1, 3 * scale), para(self.t("Also known as {aliases}", aliases=aliases), para_style(fonts.ui, 8.4 * scale, 11.6 * scale, theme.muted))]
        out += [Spacer(1, 8 * scale), Rule(26 * mm, 1.6, theme.accent), Spacer(1, 9 * scale)]
        if _defined(character.get("physical_description")):
            body = para_style(fonts.text, 9.7 * scale, 14.4 * scale, theme.ink, TA_JUSTIFY)
            out += [para(character["physical_description"], body), Spacer(1, 11 * scale)]
        rows = [
            (self.t(field.replace("_", " ")), value)
            for field, value in (character.get("sheet") or {}).items()
            if _defined(value)
        ]
        if rows:
            out.append(self._definitions(rows, PROFILE_W, 2, scale))
        if _defined(character.get("notes")):
            note = Table(
                [[[self._label(self.t("Author's notes"), scale), para(character["notes"], para_style(fonts.text_italic, 9.4 * scale, 13.4 * scale, theme.ink))]]],
                colWidths=[PROFILE_W],
                splitInRow=1,
            )
            note.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), theme.tint),
                        ("LINEBEFORE", (0, 0), (0, -1), 2, theme.accent),
                        ("LEFTPADDING", (0, 0), (-1, -1), 9),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]
                )
            )
            out += [Spacer(1, 4 * scale), note]
        return out

    def _profile(self, index: int, character: dict[str, Any]) -> list[Flowable]:
        # Shrink the text until the whole profile sits beside the portrait; a profile too
        # long even then continues on a plain page.
        for scale in FIT_SCALES:
            content = self._profile_content(character, scale)
            if stack_height(content, PROFILE_W) <= BODY_H - 2:
                break
        return [Paint(partial(self._paint_profile_backdrop, index, character)), *content]

    def _paint_profile_backdrop(self, index: int, character: dict[str, Any], canvas: Any) -> None:
        theme, fonts = self.theme, self.fonts
        self.section = self.t("Characters")
        self._mark(canvas, f"character-{index}", character["name"], 1)
        anchor = character_anchor_path(self.project, source_name(character))
        pic = self.art.panel(anchor, PANEL_W / PAGE_H, PORTRAIT_PX) if anchor.exists() else None
        if pic:
            canvas.drawImage(pic.reader(), 0, 0, PANEL_W, PAGE_H)
        else:  # no portrait yet: the initials on a quiet panel
            canvas.setFillColor(theme.tint)
            canvas.rect(0, 0, PANEL_W, PAGE_H, stroke=0, fill=1)
            canvas.setFont(fonts.display, 150)
            canvas.setFillColor(theme.numeral)
            canvas.drawCentredString(PANEL_W / 2, PAGE_H / 2 - 50, _initials(character["name"]))
            draw_tracked(canvas, MARGIN_X, FOOTER_Y, self.t("No portrait yet"), fonts.ui_bold, 6.2, theme.muted, 1.3)
        canvas.setFont(fonts.display, 56)
        canvas.setFillColor(theme.numeral)
        canvas.drawRightString(PAGE_W - MARGIN_X + 1, PAGE_H - MARGIN_TOP - 38, f"{index + 1:02d}")

    def _paint_plate(self, path: Path, name: str, caption: str, canvas: Any) -> None:
        """A presentation sheet on a dark page, as large as the page allows."""
        theme, fonts = self.theme, self.fonts
        self._fill(canvas, theme.night)
        pic = self.art.whole(path, SHEET_PX)
        box_x, box_y = 13 * mm, 17 * mm
        box_w, box_h = PAGE_W - 2 * box_x, PAGE_H - box_y - 11 * mm
        scale = min(box_w / pic.width, box_h / pic.height)
        width, height = pic.width * scale, pic.height * scale
        x, y = (PAGE_W - width) / 2, box_y + (box_h - height) / 2
        canvas.drawImage(pic.reader(), x, y, width, height)
        used = draw_tracked(canvas, x, FOOTER_Y, name, fonts.ui_bold, 6.6, theme.on_night, 1.3, max_width=width * 0.5)
        canvas.setFont(fonts.ui, 7.6)
        canvas.setFillColor(theme.on_night_muted)
        canvas.drawString(x + used + 3.5 * mm, FOOTER_Y, caption)
        canvas.setFont(fonts.ui_bold, 8)
        canvas.setFillColor(theme.on_night)
        canvas.drawRightString(x + width, FOOTER_Y, str(canvas.getPageNumber()))

    # -- locations --------------------------------------------------------------------

    def _location_units(self) -> list[tuple[str, list[Flowable]]]:
        if not self.locations:
            return []
        project = self.project
        tiles = []
        for index, location in enumerate(self.locations):
            image = location_image_path(project, source_name(location))
            tiles.append(
                {"key": f"location-{index}", "name": location["name"], "path": image if image.exists() else None, "crop": {"trim_bars": True}}
            )
        units = self._index_units(
            self._count(self.locations, "location", "locations"), self.t("The world"), "locations", self.t("Locations"), tiles, 16 / 9, 3, 6
        )
        for index, location in enumerate(self.locations):
            units.append(("full", [self._page(partial(self._paint_location, index, location))]))
            sheet = location_sheet_path(project, source_name(location))
            if self.include_sheets and sheet.exists() and self.art.whole(sheet, SHEET_PX):
                painter = partial(self._paint_plate, sheet, location["name"], self.t("Environment presentation sheet"))
                units.append(("full", [self._page(painter)]))
        return units

    def _paint_location(self, index: int, location: dict[str, Any], canvas: Any) -> None:
        theme, fonts = self.theme, self.fonts
        self._fill(canvas, theme.paper)
        self.section = self.t("Locations")
        self._mark(canvas, f"location-{index}", location["name"], 1)

        image = location_image_path(self.project, source_name(location))
        description = location.get("description") if _defined(location.get("description")) else ""
        relevance = location.get("relevance") if _defined(location.get("relevance")) else ""
        gap = 13 * mm
        left_w = (CONTENT_W - gap) * (0.58 if relevance else 1.0)
        right_w = CONTENT_W - gap - left_w
        pad = 9.5 * mm
        has_image = image.exists()
        # Without an image the text carries the page, so it is set larger under a title band.
        boost, min_image_h = (1.0, LOCATION_IMAGE_MIN_H) if has_image else (1.22, LOCATION_BAND_H)

        # The image takes whatever height the text leaves, within limits.
        for scale in FIT_SCALES_DEEP:
            scale *= boost
            left = [para(description, para_style(fonts.text, 10.4 * scale, 15.6 * scale, theme.ink, TA_JUSTIFY))] if description else []
            right = (
                [self._label(self.t("In the story"), scale), Spacer(1, 2 * scale), para(relevance, para_style(fonts.text_italic, 10.4 * scale, 15.2 * scale, theme.ink))]
                if relevance
                else []
            )
            text_h = max(stack_height(left, left_w, canvas), stack_height(right, right_w, canvas) if right else 0)
            image_h = PAGE_H - MARGIN_BOTTOM - pad - text_h
            if image_h >= min_image_h:
                break
        image_h = max(LOCATION_IMAGE_MIN_H, min(image_h, LOCATION_IMAGE_MAX_H))
        pic = None
        if has_image:
            shade = (rgb255(theme.night), 0.0, 0.9, 0.42, 0.0)
            pic = self.art.crop(image, PAGE_W / image_h, COVER_PX, shade=shade, trim_bars=True)
        if pic:
            canvas.drawImage(pic.reader(), 0, PAGE_H - image_h, PAGE_W, image_h)
        else:
            image_h = LOCATION_BAND_H
            canvas.setFillColor(theme.night)
            canvas.rect(0, PAGE_H - image_h, PAGE_W, image_h, stroke=0, fill=1)

        title = self._fit_title(location["name"], fonts.display, (29, 25, 21.5, 18.5), CONTENT_W * 0.8, theme.on_night, 2)
        heading = [self._kicker(self.t("Location {number}", number=f"{index + 1:02d}"), theme.accent_night), Spacer(1, 2.5 * mm), title]
        draw_stack(canvas, heading, MARGIN_X, PAGE_H - image_h + 8 * mm + stack_height(heading, CONTENT_W * 0.8, canvas), CONTENT_W * 0.8)

        top = PAGE_H - image_h - pad
        draw_stack(canvas, left, MARGIN_X, top, left_w)
        if right:
            draw_stack(canvas, right, MARGIN_X + left_w + gap, top + 1.5, right_w)
        self._draw_footer(canvas, MARGIN_X)

    # -- passages and sources ---------------------------------------------------------

    def _section_start(self, kicker: str, title: str, key: str, outline: str) -> list[Flowable]:
        """Header-frame content of a multi-column section, then a jump to the first column."""

        def mark(canvas: Any) -> None:
            self.section = outline
            self._mark(canvas, key, outline, 0)

        return [
            Paint(mark),
            self._kicker(kicker),
            Spacer(1, 3.5 * mm),
            para(title, para_style(self.fonts.display, 34, 36, self.theme.ink)),
            Spacer(1, 4.5 * mm),
            Rule(26 * mm, 1.6, self.theme.accent),
            FrameBreak(),
        ]

    def _passage_units(self) -> list[tuple[str, list[Flowable]]]:
        if not self.passages:
            return []
        theme, fonts = self.theme, self.fonts
        width = (CONTENT_W - COLUMN_GAP) / 2
        number_w = 15 * mm
        accent = hex_color(theme.accent)
        flow = self._section_start(
            self._count(self.passages, "moment", "moments") + " " + self.t("that carry the story"),
            self.t("Key passages"),
            "passages",
            self.t("Key passages"),
        )
        for number, passage in enumerate(self.passages, start=1):
            body: list[Flowable] = []
            if _defined(passage.get("passage_type")):
                body += [self._label(passage["passage_type"]), Spacer(1, 1.5)]
            body.append(para(passage["title"], para_style(fonts.display, 15, 17.6, theme.ink)))
            if _defined(passage.get("summary")):
                body += [Spacer(1, 3.5), para(passage["summary"], para_style(fonts.text, 9.5, 13.6, theme.ink))]
            details = []
            if _defined(passage.get("location")):
                details.append((self.t("Where"), passage["location"]))
            present = [name for name in (passage.get("characters_present") or []) if _defined(name)]
            if present:
                details.append((self.t("With"), ", ".join(present)))
            detail_style = para_style(fonts.ui, 8.1, 11.2, theme.muted)
            for label, value in details:
                line = f'<font name="{fonts.ui_bold}" color="{accent}">{label}</font>&nbsp;&nbsp;{markup(value, fonts.ui)}'
                body += [Spacer(1, 4 if label == details[0][0] else 1.5), Paragraph(line, detail_style)]
            block = Table(
                [[Paragraph(f"{number:02d}", para_style(fonts.display, 22, 22, theme.accent)), body]],
                colWidths=[number_w, width - number_w],
                splitInRow=1,
            )
            block.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 3.8 * mm),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.2 * mm),
                        ("TOPPADDING", (0, 0), (0, 0), 3.8 * mm - 2),
                        ("LINEABOVE", (0, 0), (-1, 0), 0.5, theme.hairline),
                    ]
                )
            )
            flow.append(KeepTogether([block]))
        return [("cols2_first", flow)]

    def _source_units(self) -> list[tuple[str, list[Flowable]]]:
        project, theme, fonts = self.project, self.theme, self.fonts
        root = project_path(project["slug"])
        groups: list[tuple[str, list[tuple[str, str]]]] = []
        book_sources = [(s.get("title") or s["uri"], s["uri"]) for s in ((project.get("source") or {}).get("sources") or []) if s.get("uri")]
        book_sources += _sources_from_markdown(root / "source" / "research.md")
        if book_sources:
            groups.append((self.t("Book research"), book_sources))
        for character in self.characters:
            found = _sources_from_markdown(character_research_path(project, source_name(character)))
            if found:
                groups.append((character["name"], found))
        if not groups:
            return []

        flow = self._section_start(self.t("Appendix"), self.t("Research sources"), "sources", self.t("Research sources"))
        style = para_style(fonts.ui, 8, 11.4, theme.ink)
        for heading, items in groups:
            # Grounding titles are usually bare domains, so de-duplicate on the title:
            # one line per source site, linked to the first URI seen for it.
            seen: set[str] = set()
            lines: list[Flowable] = []
            for title, uri in items:
                if title in seen:
                    continue
                seen.add(title)
                href = escape(uri, {'"': "&quot;"})
                lines.append(Paragraph(f'<link href="{href}">{markup(title, fonts.ui)}</link>', style))
            flow.append(KeepTogether([self._label(heading), Spacer(1, 1.5), *lines, Spacer(1, 6 * mm)]))
        return [("cols4_first", flow)]


    def _credit_units(self) -> list[tuple[str, list[Flowable]]]:
        """The closing credits page: the original work, the app, and who researched and drew it."""
        theme, fonts = self.theme, self.fonts
        flow = self._section_start(self.t("Colophon"), self.t("Credits"), "credits", self.t("Credits"))
        body = para_style(fonts.text, 10, 14.6, theme.ink)
        for heading, lines in credits.credit_blocks(self.project, self.t, self.translation):
            block: list[Flowable] = [self._label(heading), Spacer(1, 2 * mm)]
            for line in lines:
                if line.startswith("https://"):  # para() escapes markup, so links are built here
                    href = escape(line, {'"': "&quot;"})
                    color = theme.accent.hexval()[2:]
                    text = Paragraph(f'<link href="{href}" color="#{color}">{markup(line, fonts.text)}</link>', body)
                else:
                    text = para(line, body)
                block += [text, Spacer(1, 1.5 * mm)]
            flow.append(KeepTogether(block + [Spacer(1, 5 * mm)]))
        return [("cols2_first", flow)]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def exports_dir(project: dict[str, Any]) -> Path:
    return project_path(project["slug"]) / "exports"


def export_project_pdf(
    project: dict[str, Any],
    include_sheets: bool = True,
    include_sources: bool = True,
    cover: str | None = None,
    language: str = "en",
) -> Path:
    """Render the project's current state to a PDF and return its path.

    ``cover`` names the location whose establishing shot goes on the cover (see
    ``cover_choices``); by default the project's custom cover artwork (``images/cover.png``) is
    used when it exists, else the most vivid establishing shot.
    """
    book = _Book(project, include_sheets, include_sources, cover, language)
    dest_dir = exports_dir(project)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"{project['slug']}-{stamp}.pdf"
    # Two passes: the first learns which page every character and location lands on,
    # the second prints those numbers on the index pages.
    book.render(BytesIO())
    book.render(str(dest))
    return dest
