from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Dict, List

import streamlit as st

from auth.roles import Feature, Role, can_access, get_current_role
from ui.chatbot import render as render_chatbot
from ui.upload import render as render_upload
from ui.kpis import render as render_kpis
from ui.incidents import render as render_incidents
from ui.tracker import render as render_tracker


@dataclass(frozen=True)
class Page:
    label: str
    render: Callable[[], None]
    feature: Feature


def _set_role_env(selected_role_value: str) -> None:
    """
    Enforce role selection via auth/roles.py by writing CONTROL_TOWER_ROLE.
    """
    os.environ["CONTROL_TOWER_ROLE"] = selected_role_value


def main() -> None:
    st.set_page_config(page_title="AI EDI Control Tower", layout="wide")

    st.sidebar.title("AI EDI Control Tower")

    selected_role_value = st.sidebar.selectbox(
        "Role",
        options=[r.value for r in Role],
        key="selected_role",
        help="Select a role to see role-based views (Ops / Manager / Exec).",
    )
    _set_role_env(selected_role_value)
    role = get_current_role()
    st.sidebar.caption(f"Viewing as: **{role.value}**")

    all_pages: List[Page] = [
        Page("KPI Dashboard", render_kpis, Feature.kpis),
        Page("Document Tracker", render_tracker, Feature.tracker),
        Page("Incident Drill-down", render_incidents, Feature.incidents),
        Page("File Upload", render_upload, Feature.upload),
        Page("Chatbot", render_chatbot, Feature.chatbot),
    ]

    # Role enforcement: which pages render is controlled solely by auth/roles.py.
    visible_pages = [p for p in all_pages if can_access(p.feature)]
    pages_by_label: Dict[str, Callable[[], None]] = {p.label: p.render for p in visible_pages}

    st.title("AI EDI Control Tower")
    st.caption("Enterprise PoC — Streamlit frontend with webhook-based n8n backend integration.")

    if not pages_by_label:
        st.error("No pages are available for the selected role.")
        return

    page_label = st.sidebar.radio("Navigate", list(pages_by_label.keys()), index=0)
    pages_by_label[page_label]()


if __name__ == "__main__":
    main()
