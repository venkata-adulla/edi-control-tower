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


def _unwrap_n8n_items(payload: Any) -> List[Dict[str, Any]]:
    """
    n8n can return lists of items where each item is shaped like:
    - {"json": {...}}
    or already a list of dicts.
    """
    if isinstance(payload, dict) and "data" in payload:
        return _unwrap_n8n_items(payload.get("data"))

    if isinstance(payload, list):
        out: List[Dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict) and "json" in item and isinstance(item.get("json"), dict):
                out.append(item["json"])
            elif isinstance(item, dict):
                out.append(item)
        return out
    if isinstance(payload, dict):
        # Some workflows return {"documents": [...]} or {"items": [...]}
        for key in ("documents", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return _unwrap_n8n_items(val)
    return []


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


def _is_effectively_empty_list(val: Any) -> bool:
    if not isinstance(val, list) or len(val) == 0:
        return True
    # Treat lists with only empty dicts/empty strings as empty for display purposes.
    for item in val:
        if isinstance(item, dict) and len(item) == 0:
            continue
        if item is None:
            continue
        if isinstance(item, str) and not item.strip():
            continue
        return False
    return True


def _render_kv(label: str, value: Any) -> None:
    v = "NA" if value in (None, "", []) else str(value)
    st.write(f"**{label}**: {v}")


def _render_list_section(title: str, items: Any, *, fields: Optional[List[str]] = None) -> None:
    st.subheader(title)
    if _is_effectively_empty_list(items):
        st.write("NA")
        return

    if not isinstance(items, list):
        st.write(str(items))
        return

    cleaned: List[Dict[str, Any]] = [i for i in items if isinstance(i, dict) and len(i) > 0]
    if not cleaned:
        st.write("NA")
        return

    df = pd.DataFrame(cleaned)
    if fields:
        cols = [c for c in fields if c in df.columns]
        if cols:
            df = df[cols]
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_document_human(doc: Dict[str, Any]) -> None:
    st.subheader("Document overview")
    c1, c2, c3 = st.columns(3)
    with c1:
        _render_kv("Document ID", doc.get("document_id") or doc.get("doc_id"))
        _render_kv("Document type", doc.get("document_type") or doc.get("type"))
    with c2:
        _render_kv("Trading partner", doc.get("trading_partner_name") or doc.get("partner"))
        _render_kv("Status", doc.get("status"))
    with c3:
        _render_kv("Created at", doc.get("created_at") or doc.get("received_at"))
        _render_kv("Closed at", doc.get("closed_at"))

    st.divider()

    _render_list_section(
        "Pipeline",
        doc.get("pipeline"),
        fields=["stage", "status", "details"],
    )
    _render_list_section(
        "Acknowledgments",
        doc.get("acknowledgments"),
        fields=["ack_type", "status", "sent_at"],
    )
    _render_list_section(
        "Shipments",
        doc.get("shipments"),
        fields=None,
    )
    _render_list_section(
        "SLA tracking",
        doc.get("sla_tracking"),
        fields=["sla_type", "status", "start_time", "end_time"],
    )
    _render_list_section(
        "Incidents",
        doc.get("incidents"),
        fields=None,
    )
    _render_list_section(
        "AI insights",
        doc.get("ai_insights"),
        fields=None,
    )

    st.subheader("Summary")
    summary = doc.get("Summary") or doc.get("summary")
    if isinstance(summary, str) and summary.strip():
        st.write(summary.strip())
    else:
        st.write("NA")


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
            # Normalize n8n item shape: [{"json": {...}}] -> [{...}]
            documents = _unwrap_n8n_items(raw_payload)
            if not documents:
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
        options=[
            d.get("document_id")
            or d.get("doc_id")
            or d.get("documentId")
            or f"doc-{i}"
            for i, d in enumerate(documents)
        ],
        index=0,
    )
    doc = next(
        (
            d
            for d in documents
            if (d.get("document_id") or d.get("doc_id") or d.get("documentId")) == selected
        ),
        documents[0],
    )
    _render_document_human(doc)

    if raw_payload is not None:
        with st.expander("Raw response (n8n)", expanded=False):
            st.json(raw_payload)

