import os
from typing import Callable, Dict

import streamlit as st

from ui.chatbot import render as render_chatbot
from ui.upload import render as render_upload
from ui.kpis import render as render_kpis
from ui.incidents import render as render_incidents


def _sidebar_role_badge() -> None:
    role = os.getenv("EDI_ROLE", "viewer")
    st.sidebar.caption(f"Role: **{role}**")


def main() -> None:
    st.set_page_config(page_title="EDI Control Tower", layout="wide")

    st.sidebar.title("EDI Control Tower")
    _sidebar_role_badge()

    pages: Dict[str, Callable[[], None]] = {
        "KPIs": render_kpis,
        "Upload": render_upload,
        "Incidents": render_incidents,
        "Chatbot": render_chatbot,
    }

    page = st.sidebar.radio("Navigate", list(pages.keys()), index=0)
    pages[page]()


if __name__ == "__main__":
    main()
