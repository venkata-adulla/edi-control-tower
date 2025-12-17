from __future__ import annotations

import os
from datetime import datetime, timezone

import streamlit as st

from auth.roles import Permission, has_permission
from api.n8n_client import N8NClient


def render() -> None:
    st.title("Upload")

    if not has_permission(Permission.upload):
        st.info("Your role does not allow uploads.")
        return

    st.caption("Upload EDI files for processing. Optionally forwards to an n8n ingest webhook.")

    uploaded = st.file_uploader(
        "Choose a file",
        type=None,
        accept_multiple_files=False,
    )

    if uploaded is None:
        return

    content = uploaded.getvalue()
    record = {
        "name": uploaded.name,
        "size_bytes": len(content),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    st.session_state.setdefault("uploaded_files", [])
    st.session_state.uploaded_files.append(record)

    st.success(f"Uploaded: {uploaded.name} ({len(content)} bytes)")
    st.json(record)

    webhook = os.getenv("N8N_INGEST_WEBHOOK_URL")
    if webhook:
        if st.button("Forward to n8n", type="primary"):
            client = N8NClient()
            payload = {"filename": uploaded.name, "size_bytes": len(content)}
            try:
                resp = client.call_webhook(webhook, payload)
                st.success("Forwarded to n8n webhook")
                st.json(resp)
            except Exception as e:  # noqa: BLE001
                st.error(f"n8n webhook call failed: {e}")
    else:
        st.caption("Set N8N_INGEST_WEBHOOK_URL to enable forwarding.")
