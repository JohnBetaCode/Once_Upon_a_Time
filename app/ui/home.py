"""Home page: create a new project or open an existing one."""

from __future__ import annotations

import streamlit as st

from app.core import gemini, usage
from app.core import projects as project_store
from app.core.config import get_settings, save_settings
from app.core.imaging import STYLE_PROMPTS

STYLES = list(STYLE_PROMPTS)

SOURCE_LABELS = {
    "text": "✍️ Written text",
    "title": "🔎 Book title (web research)",
    "pdf": "📄 PDF",
}

STATUS_LABELS = {
    "created": "🆕 No source yet",
    "ingested": "📥 Source loaded",
    "extracted": "🧩 Entities extracted",
    "illustrated": "🖼️ Illustrated",
}


def _warn_if_unconfigured() -> None:
    if not get_settings().configured:
        st.warning(
            "Google Cloud is not configured yet — open **⚙️ Settings** above and set "
            "your project ID before loading sources or generating images."
        )


def _render_settings_panel() -> None:
    settings = get_settings()
    with st.expander("⚙️ Settings — Gemini on Vertex AI", expanded=not settings.configured):
        st.caption(
            "Authentication uses Google Application Default Credentials "
            "(`gcloud auth application-default login`). These values are saved to `config/.env`."
        )
        with st.form("settings_form"):
            col1, col2, col3 = st.columns(3)
            project = col1.text_input("GCP project ID", value=settings.project)
            text_location = col2.text_input("Text model location", value=settings.text_location)
            image_location = col3.text_input("Image model location", value=settings.image_location)
            col4, col5 = st.columns(2)
            text_model = col4.text_input("Text model", value=settings.text_model)
            image_model = col5.text_input("Image model", value=settings.image_model)
            save_col, test_col, _ = st.columns([1, 1, 3])
            saved = save_col.form_submit_button("Save", type="primary")
            tested = test_col.form_submit_button("Save & test")

        if saved or tested:
            save_settings(
                {
                    "GOOGLE_CLOUD_PROJECT": project.strip(),
                    "GOOGLE_CLOUD_LOCATION": text_location.strip(),
                    "GEMINI_IMAGE_LOCATION": image_location.strip(),
                    "GEMINI_TEXT_MODEL": text_model.strip(),
                    "GEMINI_IMAGE_MODEL": image_model.strip(),
                }
            )
            gemini.reset_clients()
            st.success("Settings saved to config/.env.")
        if tested:
            with st.spinner("Testing connection to Vertex AI…"):
                try:
                    reply = gemini.check_connection()
                    st.success(f"Connection OK — model replied: “{reply}”")
                except gemini.GeminiError as exc:
                    st.error(f"Connection failed: {exc}")


def _render_usage_panel() -> None:
    with st.expander("📊 Usage & costs"):
        entries = usage.load_entries()
        if not entries:
            st.info("No API usage recorded yet.")
            return
        totals = usage.summarize(entries)
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("API calls", f"{totals['calls']:,}")
        col2.metric("Input tokens", f"{totals['input_tokens']:,}")
        col3.metric("Output tokens", f"{totals['output_tokens']:,}")
        col4.metric("Images", f"{totals['images']:,}")
        col5.metric("Est. cost", f"${totals['cost_usd']:.2f}")
        st.caption(
            "Estimates based on public Vertex AI list prices (including an "
            "approximate charge per web-grounded request). Your GCP billing "
            "console is the source of truth."
        )
        by_project, by_operation = st.tabs(["By project", "By operation"])
        with by_project:
            st.dataframe(usage.breakdown(entries, "project"), use_container_width=True, hide_index=True)
        with by_operation:
            st.dataframe(usage.breakdown(entries, "operation"), use_container_width=True, hide_index=True)


def render_home() -> None:
    st.title("📖 Once Upon a Time")
    st.caption(
        "Turn any story into consistent illustrations of its characters, "
        "locations, and key passages."
    )

    _render_settings_panel()
    _render_usage_panel()

    st.subheader("Create a new project")
    _warn_if_unconfigured()
    with st.form("create_project", clear_on_submit=True):
        col1, col2 = st.columns([3, 1])
        name = col1.text_input("Project name", placeholder="e.g. The Little Prince")
        style = col2.selectbox("Illustration style", STYLES)
        description = st.text_input(
            "Description (optional)", placeholder="A short note about this project"
        )
        submitted = st.form_submit_button("Create project", type="primary")

    if submitted:
        if not name.strip():
            st.error("Please give the project a name.")
        else:
            project = project_store.create_project(name, description, style)
            st.session_state.current_project = project["slug"]
            st.rerun()

    st.divider()
    st.subheader("Your projects")

    all_projects = project_store.list_projects()
    if not all_projects:
        st.info("No projects yet. Create your first one above.")
        return

    for project in all_projects:
        with st.container(border=True):
            info_col, actions_col = st.columns([5, 1])
            with info_col:
                st.markdown(f"**{project['name']}**")
                source = project.get("source")
                source_label = (
                    SOURCE_LABELS.get(source["type"], source["type"]) if source else "—"
                )
                status_label = STATUS_LABELS.get(project.get("status", ""), project.get("status", ""))
                st.caption(
                    f"{status_label} · Source: {source_label} · "
                    f"Style: {project.get('style', '—')} · "
                    f"Created: {project.get('created_at', '')[:10]}"
                )
                if project.get("description"):
                    st.caption(project["description"])
            with actions_col:
                if st.button("Open", key=f"open_{project['slug']}", type="primary", use_container_width=True):
                    st.session_state.current_project = project["slug"]
                    st.rerun()
                if st.button("Delete", key=f"delete_{project['slug']}", use_container_width=True):
                    st.session_state.pending_delete = project["slug"]

    pending = st.session_state.get("pending_delete")
    if pending:
        target = project_store.load_project(pending)
        if target:
            st.warning(
                f"Delete project **{target['name']}** and all its files? This cannot be undone."
            )
            col_yes, col_no, _ = st.columns([1, 1, 4])
            if col_yes.button("Yes, delete it", type="primary"):
                project_store.delete_project(pending)
                st.session_state.pending_delete = None
                st.rerun()
            if col_no.button("Cancel"):
                st.session_state.pending_delete = None
                st.rerun()
