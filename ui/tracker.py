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
    - {"json": [{...}, {"acks": [...]}, {"shipments": [...]}, ...]}
    - {"json": [[{...}, {"acks": [...]}, ...]]}  (nested list)
    or already a list of dicts.
    """
    if isinstance(payload, dict) and "data" in payload:
        return _unwrap_n8n_items(payload.get("data"))

    def _flatten_list(val: Any) -> List[Any]:
        if isinstance(val, list) and len(val) == 1 and isinstance(val[0], list):
            return list(val[0])
        if isinstance(val, list):
            return list(val)
        return []

    def _merge_doc_fragments(items: Any) -> Optional[Dict[str, Any]]:
        """
        Merge a list of dict fragments into a single document dict.
        Example:
          [{doc fields...}, {"acks":[...]}, {"shipments":[...]}] -> {doc fields..., "acks":[...], "shipments":[...]}
        """
        parts = _flatten_list(items)
        if not parts:
            return None

        merged: Dict[str, Any] = {}
        for part in parts:
            if not isinstance(part, dict):
                continue
            # If it's a single-key wrapper, merge it in.
            if len(part) == 1:
                (k, v), = part.items()
                merged[k] = v
                continue
            # Otherwise merge the dict fields.
            merged.update(part)
        return merged or None

    if isinstance(payload, list):
        out: List[Dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict) and "json" in item and isinstance(item.get("json"), dict):
                out.append(item["json"])
            elif isinstance(item, dict) and "json" in item and isinstance(item.get("json"), list):
                merged = _merge_doc_fragments(item["json"])
                if merged:
                    out.append(merged)
            elif isinstance(item, dict):
                out.append(item)
            elif isinstance(item, list):
                # Occasionally nested lists appear; flatten them.
                out.extend(_unwrap_n8n_items(item))
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
        fields=["stage", "status", "details", "event_time"],
    )
    _render_list_section(
        "Acknowledgments",
        doc.get("acknowledgments") or doc.get("acks"),
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
    summary = doc.get("Summary") or doc.get("summary") or doc.get("output")
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

    st.subheader("Enter the Document ID and click on Refresh")
    doc_id = st.text_input(
        "Document ID",
        placeholder="e.g. DOC-030",
        help="Enter a Document ID to fetch the full tracking view.",
    )

    filters: Dict[str, Any] = {}
    if doc_id.strip():
        filters["doc_id"] = doc_id.strip()

    if st.button("Refresh", use_container_width=True):
        _fetch_documents.clear()

    if not use_demo and not filters.get("doc_id"):
        st.info("Enter a Document ID and click Refresh to view tracking details.")
        return

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

    if not documents:
        st.caption("No documents found for the selected filters.")
        if raw_payload is not None:
            with st.expander("Raw response", expanded=False):
                st.json(raw_payload)
        return

    # Document ID lookups should return a single record; if multiple arrive, show the first.
    doc = documents[0]
    _render_document_human(doc)

    if raw_payload is not None:
        with st.expander("Raw response (n8n)", expanded=False):
            st.json(raw_payload)

