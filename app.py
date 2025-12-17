from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Dict, List

import streamlit as st

from auth.roles import Feature, Role, can_access
from ui.chatbot import render as render_chatbot
from ui.upload import render as render_upload
from ui.kpis import render as render_kpis
from ui.incidents import render as render_incidents


@dataclass(frozen=True)
class Page:
    label: str
    render: Callable[[], None]
    feature: Feature


def _get_selected_role() -> Role:
    raw = st.session_state.get("selected_role", Role.ops.value)
    try:
        return Role(raw)
    except ValueError:
        return Role.ops


def _set_role_env(selected: Role) -> None:
    os.environ["CONTROL_TOWER_ROLE"] = selected.value


def main() -> None:
    st.set_page_config(page_title="AI EDI Control Tower", layout="wide")

    st.sidebar.title("AI EDI Control Tower")

    selected_role = st.sidebar.selectbox(
        "Role",
        options=[r.value for r in Role],
        key="selected_role",
        help="Select a role to see role-based views (Ops / Manager / Exec).",
    )
    role = _get_selected_role()
    _set_role_env(role)
    st.sidebar.caption(f"Viewing as: **{selected_role}**")

    all_pages: List[Page] = [
        Page("KPI Dashboard", render_kpis, Feature.kpis),
        Page("Incident Drill-down", render_incidents, Feature.incidents),
        Page("File Upload", render_upload, Feature.upload),
        Page("Chatbot", render_chatbot, Feature.chatbot),
    ]

    visible_pages = [p for p in all_pages if can_access(p.feature, role)]
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
