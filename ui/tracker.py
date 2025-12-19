from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from api.n8n_client import N8NClient


def _demo_documents() -> List[Dict[str, Any]]:
    return [
        {
            "doc_id": "DOC-000184",
            "partner": "ACME Manufacturing",
            "type": "850",
            "status": "processed",
            "received_at": "2025-12-17T09:22:11Z",
            "last_update": "2025-12-17T09:22:34Z",
            "notes": "Matched PO and created shipment.",
        },
        {
            "doc_id": "DOC-000185",
            "partner": "ACME Manufacturing",
            "type": "856",
            "status": "exception",
            "received_at": "2025-12-17T10:03:02Z",
            "last_update": "2025-12-17T10:04:10Z",
            "notes": "Missing required segment REF*BM.",
        },
        {
            "doc_id": "DOC-000186",
            "partner": "ACME Manufacturing",
            "type": "997",
            "status": "queued",
            "received_at": "2025-12-17T10:55:19Z",
            "last_update": "2025-12-17T10:55:19Z",
            "notes": "Awaiting downstream workflow.",
        },
    ]


def _normalize_documents(payload: Any) -> List[Dict[str, Any]]:
    """
    Accepts common webhook response shapes:
    - [{"doc_id": ..., ...}, ...]
    - {"documents": [...]} or {"data": [...]}
    """
    if isinstance(payload, list):
        return [d for d in payload if isinstance(d, dict)]
    if isinstance(payload, dict):
        for key in ("documents", "data", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return [d for d in val if isinstance(d, dict)]
    return []


@st.cache_data(ttl=15, show_spinner=False)
def _fetch_documents(filters: Dict[str, Any]) -> Dict[str, Any]:
    client = N8NClient()
    return client.document_tracker(filters=filters)


def render() -> None:
    st.title("Document Tracker")
    st.caption("Track EDI documents end-to-end. Data is fetched via n8n webhooks.")

    _, right = st.columns([2, 1])
    use_demo = right.toggle("Use demo data", value=False)

    c1, c2, c3 = st.columns(3)
    doc_id = c1.text_input("Document ID", placeholder="e.g. DOC-000185")
    doc_type = c2.selectbox("Doc type", options=["Any", "850", "855", "856", "940", "945", "997"], index=0)
    status = c3.selectbox(
        "Status",
        options=["Any", "queued", "processing", "processed", "exception", "failed"],
        index=0,
    )

    filters: Dict[str, Any] = {}
    if doc_id.strip():
        filters["doc_id"] = doc_id.strip()
    if doc_type != "Any":
        filters["type"] = doc_type
    if status != "Any":
        filters["status"] = status

    if st.button("Refresh", use_container_width=True):
        _fetch_documents.clear()

    if use_demo:
        documents = _demo_documents()
        raw_payload: Optional[Dict[str, Any]] = None
    else:
        try:
            with st.spinner("Fetching documents from n8n..."):
                raw_payload = _fetch_documents(filters)
            documents = _normalize_documents(raw_payload)
        except Exception as e:  # noqa: BLE001
            st.error(f"Failed to fetch documents from n8n: {e}")
            st.info("Enable “Use demo data” to view the tracker without n8n.")
            return

    st.subheader(f"Documents ({len(documents)})")
    if not documents:
        st.caption("No documents found for the selected filters.")
        if raw_payload is not None:
            with st.expander("Raw response", expanded=False):
                st.json(raw_payload)
        return

    df = pd.DataFrame(documents)
    # Present a stable, readable ordering if columns exist.
    preferred_cols = [
        "doc_id",
        "partner",
        "type",
        "status",
        "received_at",
        "last_update",
        "notes",
    ]
    cols = [c for c in preferred_cols if c in df.columns] + [c for c in df.columns if c not in preferred_cols]
    df = df[cols]
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Details")
    selected = st.selectbox(
        "Select a document",
        options=[d.get("doc_id", f"doc-{i}") for i, d in enumerate(documents)],
        index=0,
    )
    doc = next((d for d in documents if d.get("doc_id") == selected), documents[0])
    st.json(doc)

    if raw_payload is not None:
        with st.expander("Raw response (n8n)", expanded=False):
            st.json(raw_payload)

