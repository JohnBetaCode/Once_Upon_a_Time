"""Project workspace: source ingestion + characters / locations / gallery tabs."""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.core import imaging, ingestion, usage
from app.core.imaging import STYLE_PROMPTS
from app.core.projects import project_path, save_project

SOURCE_LABELS = {
    "text": "✍️ Written text",
    "title": "🔎 Book title (web research)",
    "pdf": "📄 PDF",
}


def render_workspace(project: dict[str, Any]) -> None:
    _render_sidebar(project)

    flash = st.session_state.pop("flash", None)
    if flash:
        kind, message = flash
        getattr(st, kind)(message)

    st.title(f"📖 {project['name']}")
    book = project.get("book")
    if book:
        bits = [
            book.get(field)
            for field in ("author", "publication_year", "genre", "original_language")
            if book.get(field) not in (None, "", "undefined")
        ]
        title = book.get("title") if book.get("title") not in (None, "", "undefined") else project["name"]
        st.caption(f"**{title}**" + (f" — {' · '.join(bits)}" if bits else ""))
        if book.get("summary") and book["summary"] != "undefined":
            with st.expander("Story summary"):
                st.write(book["summary"])
                themes = [t for t in (book.get("themes") or []) if t != "undefined"]
                if themes:
                    st.caption("Themes: " + ", ".join(themes))
    elif project.get("description"):
        st.caption(project["description"])

    tab_source, tab_characters, tab_locations, tab_passages, tab_gallery = st.tabs(
        ["📥 Source", "👤 Characters", "📍 Locations", "🎬 Passages", "🖼️ Gallery"]
    )
    with tab_source:
        _render_source_tab(project)
    with tab_characters:
        _render_characters_tab(project)
    with tab_locations:
        _render_locations_tab(project)
    with tab_passages:
        _render_passages_tab(project)
    with tab_gallery:
        _render_gallery_tab(project)


def _render_sidebar(project: dict[str, Any]) -> None:
    with st.sidebar:
        st.markdown("### Project")
        st.markdown(f"**{project['name']}**")
        st.caption(f"Status: `{project.get('status', 'created')}`")
        st.caption(f"Style: `{project.get('style', '—')}`")
        source = project.get("source")
        if source:
            st.caption(f"Source: {SOURCE_LABELS.get(source['type'], source['type'])}")

        spend = usage.summarize(
            [e for e in usage.load_entries() if e.get("project") == project["slug"]]
        )
        if spend["calls"]:
            st.caption(f"Est. spend: ${spend['cost_usd']:.2f} ({spend['images']} images)")

        with st.expander("✏️ Edit project"):
            with st.form("edit_project"):
                name = st.text_input("Name", value=project["name"])
                description = st.text_area("Description", value=project.get("description", ""))
                styles = list(STYLE_PROMPTS)
                current_style = project.get("style", styles[0])
                style = st.selectbox(
                    "Illustration style",
                    styles,
                    index=styles.index(current_style) if current_style in styles else 0,
                )
                if st.form_submit_button("Save changes", type="primary"):
                    project["name"] = name.strip() or project["name"]
                    project["description"] = description.strip()
                    project["style"] = style
                    save_project(project)
                    st.session_state.flash = ("success", "Project updated.")
                    st.rerun()
            st.caption(
                "Changing the style affects new generations only — regenerate "
                "existing images to apply it."
            )

        st.divider()
        if st.button("← Back to projects", use_container_width=True):
            st.session_state.current_project = None
            st.rerun()


# ---------------------------------------------------------------------------
# Source tab
# ---------------------------------------------------------------------------


def _render_source_tab(project: dict[str, Any]) -> None:
    source = project.get("source")
    if source:
        _render_current_source(project, source)
        st.divider()
        st.markdown("#### Replace source")
        st.caption("Loading a new source will replace the current one.")

    method = st.radio(
        "How do you want to provide the story?",
        options=["text", "title", "pdf"],
        format_func=lambda k: SOURCE_LABELS[k],
        horizontal=True,
        label_visibility="collapsed" if source else "visible",
    )

    if method == "text":
        _render_text_input(project)
    elif method == "title":
        _render_title_input(project)
    else:
        _render_pdf_input(project)


def _render_current_source(project: dict[str, Any], source: dict[str, Any]) -> None:
    st.success(f"Source loaded: {SOURCE_LABELS.get(source['type'], source['type'])}")
    if source["type"] == "text":
        st.caption(f"{source.get('chars', 0):,} characters saved to `source/{source['file']}`")
        text_file = project_path(project["slug"]) / "source" / source["file"]
        if text_file.exists():
            with st.expander("Preview text"):
                st.text(text_file.read_text(encoding="utf-8")[:5000])
    elif source["type"] == "title":
        author = f" by {source['author']}" if source.get("author") not in ("", "undefined", None) else ""
        st.caption(f"Book: **{source['title']}**{author}")
        research_file = project_path(project["slug"]) / "source" / "research.md"
        if research_file.exists():
            with st.expander("Research notes & sources"):
                st.markdown(research_file.read_text(encoding="utf-8"))
    elif source["type"] == "pdf":
        st.caption(f"File: `source/{source['file']}` ({source.get('bytes', 0):,} bytes)")


def _render_text_input(project: dict[str, Any]) -> None:
    st.markdown("Write or paste the full story below. Long texts are fine — they are processed in chunks.")
    text = st.text_area(
        "Story text",
        height=400,
        placeholder="Once upon a time...",
        key="source_text",
    )
    if st.button("Save & process text", type="primary", disabled=not text.strip()):
        ingestion.save_text_source(project, text)
        try:
            ingestion.process_text(project, text)
            st.session_state.flash = ("success", "Text processed.")
        except NotImplementedError as exc:
            st.session_state.flash = ("info", f"Text saved. Processing pending: {exc}")
        st.rerun()


def _render_title_input(project: dict[str, Any]) -> None:
    st.markdown(
        "Give a book title and a research agent will look up its characters, "
        "locations, and key passages on the web."
    )
    col1, col2 = st.columns([3, 2])
    title = col1.text_input("Book title", placeholder="e.g. Don Quixote", key="source_title")
    author = col2.text_input("Author (optional)", placeholder="e.g. Miguel de Cervantes", key="source_author")
    deep = st.checkbox(
        "Deep-research each character individually (wikis, guides, adaptations) — "
        "slower and ~$0.05–0.10 per character, but much richer character sheets",
        value=True,
        key="source_deep_research",
    )
    if st.button("Research book", type="primary", disabled=not title.strip()):
        with st.spinner("Researching the book on the web and extracting entities… (~1 minute)"):
            try:
                extraction = ingestion.research_title(project, title, author)
            except Exception as exc:
                st.error(f"Research failed: {exc}")
                return
        if deep and extraction.characters:
            characters = ingestion.load_entities(project, "characters")
            _deep_research_all(project, characters)
        else:
            st.session_state.flash = (
                "success",
                f"Research complete: {len(extraction.characters)} characters, "
                f"{len(extraction.locations)} locations, {len(extraction.passages)} passages.",
            )
        st.rerun()


def _render_pdf_input(project: dict[str, Any]) -> None:
    st.markdown(
        "Upload a PDF of the book. Text will be extracted chapter by chapter "
        "(with OCR for scanned pages) before processing."
    )
    uploaded = st.file_uploader("Book PDF", type=["pdf"], key="source_pdf")
    if uploaded is not None and st.button("Save & extract PDF", type="primary"):
        pdf_path = ingestion.save_pdf_source(project, uploaded.name, uploaded.getvalue())
        try:
            ingestion.extract_pdf_text(project, pdf_path)
            st.session_state.flash = ("success", "PDF processed.")
        except NotImplementedError as exc:
            st.session_state.flash = ("info", f"PDF saved. Processing pending: {exc}")
        st.rerun()


# ---------------------------------------------------------------------------
# Characters tab
# ---------------------------------------------------------------------------


def _render_characters_tab(project: dict[str, Any]) -> None:
    characters = ingestion.load_entities(project, "characters")
    if not characters:
        st.info("No characters yet. Load a source in the **Source** tab first.")
        return

    action_col1, action_col2 = st.columns(2)
    if action_col1.button("🎨 Generate all missing portraits"):
        _generate_all_portraits(project, characters)
        st.rerun()
    pending_research = [c for c in characters if not c.get("deep_researched")]
    if action_col2.button(
        f"🔎 Deep research all characters ({len(pending_research)} pending)",
        disabled=not pending_research,
        help="Researches each character individually on the web (wikis, guides, "
        "adaptations) for a much richer sheet. Roughly $0.05–0.10 per character.",
    ):
        _deep_research_all(project, pending_research)
        st.rerun()

    for character in characters:
        with st.container(border=True):
            img_col, info_col = st.columns([1, 2])
            anchor = imaging.character_anchor_path(project, character)
            with img_col:
                if anchor.exists():
                    st.image(str(anchor), use_container_width=True)
                else:
                    st.markdown(
                        "<div style='height:180px;display:flex;align-items:center;"
                        "justify-content:center;background:#8882;border-radius:8px;'>"
                        "No portrait yet</div>",
                        unsafe_allow_html=True,
                    )
                label = "Regenerate portrait" if anchor.exists() else "Generate portrait"
                if st.button(f"🎨 {label}", key=f"gen_char_{character['name']}"):
                    with st.spinner(f"Generating portrait of {character['name']}…"):
                        try:
                            imaging.generate_character_anchor(project, character)
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
            with info_col:
                aliases = ", ".join(character.get("aliases") or [])
                badge = " 🔎" if character.get("deep_researched") else ""
                st.markdown(f"### {character['name']}{badge}" + (f" *({aliases})*" if aliases else ""))
                st.caption(f"Role: {character.get('role', 'undefined')}")
                st.write(character.get("physical_description", "undefined"))
                sheet = character.get("sheet") or {}
                with st.expander("Character sheet"):
                    for field, value in sheet.items():
                        st.markdown(f"- **{field.replace('_', ' ').capitalize()}**: {value}")
                notes_path = ingestion.character_research_path(project, character)
                if notes_path.exists():
                    with st.expander("Research notes & sources"):
                        st.markdown(notes_path.read_text(encoding="utf-8"))
                research_label = (
                    "Research again" if character.get("deep_researched") else "Deep research"
                )
                if st.button(f"🔎 {research_label}", key=f"research_char_{character['name']}"):
                    with st.spinner(f"Researching {character['name']} on the web…"):
                        try:
                            ingestion.deep_research_character(project, character)
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

            sheet_image = imaging.character_sheet_path(project, character)
            if sheet_image.exists():
                if anchor.exists() and anchor.stat().st_mtime > sheet_image.stat().st_mtime:
                    st.warning(
                        "The portrait is newer than this presentation sheet — "
                        "regenerate the sheet so both show the same identity."
                    )
                st.image(str(sheet_image), use_container_width=True)
            sheet_label = (
                "Regenerate presentation sheet" if sheet_image.exists() else "Generate presentation sheet"
            )
            if st.button(f"📋 {sheet_label}", key=f"gen_sheet_{character['name']}"):
                with st.spinner(
                    f"Generating presentation sheet for {character['name']}… "
                    "(generates the portrait first if missing)"
                ):
                    try:
                        imaging.generate_character_sheet(project, character)
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))


def _deep_research_all(project: dict[str, Any], characters: list[dict[str, Any]]) -> None:
    progress = st.progress(0.0, text="Deep-researching characters…")
    failed: list[str] = []
    for i, character in enumerate(characters):
        progress.progress(
            i / len(characters),
            text=f"Researching {character['name']}… ({i + 1}/{len(characters)})",
        )
        try:
            ingestion.deep_research_character(project, character)
        except Exception:
            failed.append(character["name"])
    progress.empty()
    if failed:
        st.session_state.flash = ("warning", f"Done, but these failed: {', '.join(failed)}.")
    else:
        st.session_state.flash = ("success", f"Deep-researched {len(characters)} characters.")


def _generate_all_portraits(project: dict[str, Any], characters: list[dict[str, Any]]) -> None:
    missing = [c for c in characters if not imaging.character_anchor_path(project, c).exists()]
    if not missing:
        st.session_state.flash = ("info", "All characters already have a portrait.")
        return
    progress = st.progress(0.0, text="Generating portraits…")
    failed: list[str] = []
    for i, character in enumerate(missing):
        progress.progress(i / len(missing), text=f"Generating {character['name']}… ({i + 1}/{len(missing)})")
        try:
            imaging.generate_character_anchor(project, character)
        except Exception:
            failed.append(character["name"])
    progress.empty()
    if failed:
        st.session_state.flash = ("warning", f"Done, but these failed: {', '.join(failed)}.")
    else:
        st.session_state.flash = ("success", f"Generated {len(missing)} portraits.")


# ---------------------------------------------------------------------------
# Locations tab
# ---------------------------------------------------------------------------


def _render_locations_tab(project: dict[str, Any]) -> None:
    locations = ingestion.load_entities(project, "locations")
    if not locations:
        st.info("No locations yet. Load a source in the **Source** tab first.")
        return

    for location in locations:
        with st.container(border=True):
            img_col, info_col = st.columns([1, 2])
            image_path = imaging.location_image_path(project, location)
            with img_col:
                if image_path.exists():
                    st.image(str(image_path), use_container_width=True)
                else:
                    st.markdown(
                        "<div style='height:140px;display:flex;align-items:center;"
                        "justify-content:center;background:#8882;border-radius:8px;'>"
                        "No image yet</div>",
                        unsafe_allow_html=True,
                    )
                label = "Regenerate image" if image_path.exists() else "Generate image"
                if st.button(f"🎨 {label}", key=f"gen_loc_{location['name']}"):
                    with st.spinner(f"Generating {location['name']}…"):
                        try:
                            imaging.generate_location_image(project, location)
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
            with info_col:
                st.markdown(f"### {location['name']}")
                st.write(location.get("description", "undefined"))
                st.caption(f"Relevance: {location.get('relevance', 'undefined')}")

            sheet_image = imaging.location_sheet_path(project, location)
            if sheet_image.exists():
                st.image(str(sheet_image), use_container_width=True)
            sheet_label = (
                "Regenerate presentation sheet" if sheet_image.exists() else "Generate presentation sheet"
            )
            if st.button(f"📋 {sheet_label}", key=f"gen_loc_sheet_{location['name']}"):
                with st.spinner(f"Generating presentation sheet for {location['name']}…"):
                    try:
                        imaging.generate_location_sheet(project, location)
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))


# ---------------------------------------------------------------------------
# Passages tab
# ---------------------------------------------------------------------------


def _render_passages_tab(project: dict[str, Any]) -> None:
    passages = ingestion.load_entities(project, "passages")
    if not passages:
        st.info("No passages yet. Load a source in the **Source** tab first.")
        return
    st.caption(
        "Scene illustration (using each character's anchor portrait as reference) is coming next."
    )
    for passage in passages:
        with st.container(border=True):
            st.markdown(f"### {passage['title']}")
            st.caption(
                f"Type: {passage.get('passage_type', 'undefined')} · "
                f"Location: {passage.get('location', 'undefined')}"
            )
            st.write(passage.get("summary", "undefined"))
            present = ", ".join(passage.get("characters_present") or [])
            if present:
                st.caption(f"Characters present: {present}")


# ---------------------------------------------------------------------------
# Gallery tab
# ---------------------------------------------------------------------------


def _render_gallery_tab(project: dict[str, Any]) -> None:
    root = project_path(project["slug"])
    images = sorted(
        p for p in root.rglob("*.png") if p.is_file()
    ) + sorted(p for p in root.rglob("*.jpg") if p.is_file())
    if not images:
        st.info("No images generated yet.")
        return
    cols = st.columns(4)
    for i, image in enumerate(images):
        with cols[i % 4]:
            st.image(str(image), caption=str(image.relative_to(root)), use_container_width=True)
