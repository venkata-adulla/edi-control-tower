from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from api.n8n_client import N8NClient


def _demo_incidents() -> List[Dict[str, Any]]:
    return [
        {
            "id": "INC-1007",
            "severity": "high",
            "status": "open",
            "summary": "997 functional ack failures for ACME",
            "created_at": "2025-12-17T08:12:00Z",
            "details": {
                "partner": "ACME",
                "transaction_set": "856",
                "impact": "Shipments not acknowledged within SLA window",
                "next_steps": ["Validate segment mapping", "Reprocess last batch", "Notify partner"],
            },
        },
        {
            "id": "INC-1006",
            "severity": "medium",
            "status": "monitoring",
            "summary": "Intermittent webhook latency spikes",
            "created_at": "2025-12-16T21:40:00Z",
            "details": {"impact": "Delayed processing; no data loss observed"},
        },
    ]


def _normalize_incidents(payload: Any) -> List[Dict[str, Any]]:
    """
    Accepts common shapes:
    - [{"id": ..., ...}, ...]
    - {"incidents": [...]} or {"data": [...]}
    """
    if isinstance(payload, list):
        return [i for i in payload if isinstance(i, dict)]
    if isinstance(payload, dict):
        for key in ("incidents", "data", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return [i for i in val if isinstance(i, dict)]
    return []


def _incident_title(i: Dict[str, Any]) -> str:
    inc_id = i.get("id") or i.get("incident_id") or i.get("key") or "INC"
    sev = (i.get("severity") or "—").upper()
    status = i.get("status") or "—"
    summary = i.get("summary") or i.get("title") or "Incident"
    return f"{inc_id} · {sev} · {status} — {summary}"


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_incidents(filters: Dict[str, Any]) -> Dict[str, Any]:
    client = N8NClient()
    return client.incident_list(filters=filters)


def render() -> None:
    st.title("Incident drill-down")
    st.caption("Incidents are fetched via n8n webhooks and can be expanded for full details.")

    left, right = st.columns([2, 1])
    query = left.text_input("Search", placeholder="Search by id, partner, summary, status...")
    use_demo = right.toggle("Use demo data", value=False)
    if right.button("Refresh", use_container_width=True):
        _fetch_incidents.clear()

    severity = st.multiselect("Severity", options=["low", "medium", "high", "critical"], default=[])
    status = st.multiselect("Status", options=["open", "monitoring", "resolved", "closed", "error"], default=[])

    filters: Dict[str, Any] = {
        "query": query.strip() if query else None,
        "severity": severity or None,
        "status": status or None,
    }
    filters = {k: v for k, v in filters.items() if v is not None}

    incidents: List[Dict[str, Any]]
    raw_payload: Optional[Dict[str, Any]] = None

    if use_demo:
        incidents = _demo_incidents()
    else:
        try:
            with st.spinner("Fetching incidents from n8n..."):
                raw_payload = _fetch_incidents(filters)
            incidents = _normalize_incidents(raw_payload)
        except Exception as e:  # noqa: BLE001
            st.error(f"Failed to fetch incidents from n8n: {e}")
            st.info("Enable “Use demo data” to view the drill-down without n8n.")
            return

    if query:
        q = query.strip().lower()
        incidents = [
            i
            for i in incidents
            if q in str(i.get("id", "")).lower()
            or q in str(i.get("summary", i.get("title", ""))).lower()
            or q in str(i.get("status", "")).lower()
            or q in str(i.get("severity", "")).lower()
            or q in str(i.get("partner", i.get("details", ""))).lower()
        ]

    st.subheader(f"Incidents ({len(incidents)})")
    if not incidents:
        st.caption("No incidents found.")
        if raw_payload is not None:
            with st.expander("Raw response", expanded=False):
                st.json(raw_payload)
        return

    for inc in incidents:
        with st.expander(_incident_title(inc), expanded=False):
            cols = st.columns(4)
            cols[0].metric("Severity", str(inc.get("severity", "—")))
            cols[1].metric("Status", str(inc.get("status", "—")))
            cols[2].metric("Partner", str(inc.get("partner", inc.get("details", {}).get("partner", "—"))))
            cols[3].metric("Created", str(inc.get("created_at", "—")))

            details = inc.get("details")
            if isinstance(details, dict) and details:
                st.subheader("Details")
                st.json(details)

            st.subheader("Full payload")
            st.json(inc)

    if raw_payload is not None:
        with st.expander("Raw response (n8n)", expanded=False):
            st.json(raw_payload)
