"""Once Upon a Time — Streamlit entry point."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from app.core import projects as project_store
from app.ui.home import render_home
from app.ui.workspace import render_workspace

st.set_page_config(
    page_title="Once Upon a Time",
    page_icon="📖",
    layout="wide",
)


def main() -> None:
    if "current_project" not in st.session_state:
        st.session_state.current_project = None

    slug = st.session_state.current_project
    if slug:
        project = project_store.load_project(slug)
        if project is None:
            st.session_state.current_project = None
            st.rerun()
        render_workspace(project)
    else:
        render_home()


main()
