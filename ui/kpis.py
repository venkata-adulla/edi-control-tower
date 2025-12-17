from __future__ import annotations

import streamlit as st

from auth.roles import Permission, has_permission
from utils.live_status import get_live_status


def render() -> None:
    st.title("KPIs")

    status = get_live_status()
    left, right = st.columns(2)

    with left:
        st.subheader("Platform")
        st.metric("Live status", "OK" if status.ok else "Degraded")
        st.caption(f"Checked at: {status.checked_at.isoformat()}")

    with right:
        st.subheader("Access")
        st.metric("Can upload", "Yes" if has_permission(Permission.upload) else "No")
        st.metric(
            "Can manage incidents",
            "Yes" if has_permission(Permission.manage_incidents) else "No",
        )

    st.divider()

    st.subheader("EDI activity (demo)")
    uploads = len(st.session_state.get("uploaded_files", []))
    incidents = len(st.session_state.get("incidents", []))

    c1, c2, c3 = st.columns(3)
    c1.metric("Uploads this session", str(uploads))
    c2.metric("Incidents this session", str(incidents))
    c3.metric("n8n reachable", "Yes" if status.details.get("n8n", {}).get("ok") else "No")
