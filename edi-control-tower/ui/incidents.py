from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from auth.roles import Permission, has_permission


def render() -> None:
    st.title("Incidents")

    st.session_state.setdefault("incidents", [])

    can_manage = has_permission(Permission.manage_incidents)

    with st.expander("Create incident", expanded=can_manage):
        if not can_manage:
            st.info("Your role does not allow incident management.")
        else:
            col1, col2 = st.columns([1, 3])
            severity = col1.selectbox("Severity", ["low", "medium", "high", "critical"], index=1)
            summary = col2.text_input("Summary", placeholder="e.g. 997 functional ack failures")
            details = st.text_area("Details", placeholder="What happened? Impact? Next steps?")

            if st.button("Add incident", type="primary", disabled=not bool(summary.strip())):
                st.session_state.incidents.append(
                    {
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "severity": severity,
                        "summary": summary.strip(),
                        "details": details.strip(),
                        "status": "open",
                    }
                )
                st.success("Incident created")

    st.subheader("Incident log")

    if not st.session_state.incidents:
        st.caption("No incidents yet.")
        return

    df = pd.DataFrame(st.session_state.incidents)
    st.dataframe(df, use_container_width=True, hide_index=True)
