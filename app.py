from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List

import streamlit as st

from ui.chatbot import render as render_chatbot
from ui.upload import render as render_upload
from ui.kpis import render as render_kpis
from ui.incidents import render as render_incidents


class UserRole(str, Enum):
    ops = "Ops"
    manager = "Manager"
    exec = "Exec"


# Map business roles (sidebar) to permission roles used by the UI modules.
_BUSINESS_ROLE_TO_EDI_ROLE = {
    UserRole.ops: "operator",
    UserRole.manager: "admin",
    UserRole.exec: "viewer",
}


@dataclass(frozen=True)
class Page:
    label: str
    render: Callable[[], None]
    allowed_roles: List[UserRole]


def _get_selected_role() -> UserRole:
    raw = st.session_state.get("selected_role", UserRole.ops.value)
    try:
        return UserRole(raw)
    except ValueError:
        return UserRole.ops


def _set_edi_role_env(selected: UserRole) -> None:
    """
    The UI modules rely on auth helpers that read EDI_ROLE from the environment.
    We set it from the sidebar selector so role-based views work consistently.
    """
    os.environ["EDI_ROLE"] = _BUSINESS_ROLE_TO_EDI_ROLE[selected]


def main() -> None:
    st.set_page_config(page_title="AI EDI Control Tower", layout="wide")

    st.sidebar.title("AI EDI Control Tower")

    selected_role = st.sidebar.selectbox(
        "Role",
        options=[r.value for r in UserRole],
        key="selected_role",
        help="Select a role to see role-based views (Ops / Manager / Exec).",
    )
    role = _get_selected_role()
    _set_edi_role_env(role)
    st.sidebar.caption(f"Viewing as: **{selected_role}**")

    all_pages: List[Page] = [
        Page("KPI Dashboard", render_kpis, [UserRole.ops, UserRole.manager, UserRole.exec]),
        Page("Incident Drill-down", render_incidents, [UserRole.ops, UserRole.manager, UserRole.exec]),
        Page("File Upload", render_upload, [UserRole.ops, UserRole.manager]),
        Page("Chatbot", render_chatbot, [UserRole.ops, UserRole.manager, UserRole.exec]),
    ]

    visible_pages = [p for p in all_pages if role in p.allowed_roles]
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
