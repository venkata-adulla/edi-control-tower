from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from api.n8n_client import N8NClient

try:
    import plotly.express as px
except ModuleNotFoundError:  # pragma: no cover
    px = None  # type: ignore[assignment]

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

_FALLBACK_PARTNERS = ["Amazon Retail", "Walmart Inc.", "Home Depot", "DHL Supply Chain"]


def _pg_settings() -> Dict[str, Any]:
    """
    Postgres connection settings for fetching trading partners.

    Uses environment variables so credentials are not hard-coded:
    - CONTROL_TOWER_PG_HOST
    - CONTROL_TOWER_PG_PORT
    - CONTROL_TOWER_PG_DB
    - CONTROL_TOWER_PG_USER
    - CONTROL_TOWER_PG_PASSWORD
    - CONTROL_TOWER_PG_SSLMODE (default: require)
    """
    sslmode_raw = (os.getenv("CONTROL_TOWER_PG_SSLMODE", "require") or "require").strip()
    sslmode = sslmode_raw.lower()
    # Normalize common variants (e.g., "Disable", "disabled", "off")
    if sslmode in {"disabled", "disable", "off", "false", "0", "no"}:
        sslmode = "disable"
    elif sslmode in {"require", "required", "on", "true", "1", "yes"}:
        sslmode = "require"

    return {
        "host": os.getenv("CONTROL_TOWER_PG_HOST", "aws-1-ap-south-1.pooler.supabase.com"),
        "port": int(os.getenv("CONTROL_TOWER_PG_PORT", "5432")),
        "dbname": os.getenv("CONTROL_TOWER_PG_DB", "postgres"),
        "user": os.getenv("CONTROL_TOWER_PG_USER", "postgres.qzyvkjcgfyltezraiqwh"),
        "password": os.getenv("CONTROL_TOWER_PG_PASSWORD"),
        "sslmode": sslmode,
    }


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_partners_from_postgres() -> List[str]:
    if psycopg is None:
        raise ModuleNotFoundError("psycopg is not installed")

    cfg = _pg_settings()
    if not cfg.get("password"):
        raise ValueError("Missing CONTROL_TOWER_PG_PASSWORD")

    query = "SELECT partner_name FROM trading_partners WHERE partner_name IS NOT NULL ORDER BY partner_name"
    partners: List[str] = []

    # psycopg.connect supports keyword args (host, port, dbname, user, password, sslmode)
    try:
        conn_ctx = psycopg.connect(connect_timeout=8, **cfg)
    except Exception as e:  # noqa: BLE001
        # Supabase poolers typically require SSL; if user set disable, retry with require.
        if str(cfg.get("sslmode", "")).lower() == "disable":
            cfg_retry = dict(cfg)
            cfg_retry["sslmode"] = "require"
            conn_ctx = psycopg.connect(connect_timeout=8, **cfg_retry)
        else:
            raise e

    with conn_ctx as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            for (tp_name,) in cur.fetchall():
                if tp_name is None:
                    continue
                name = str(tp_name).strip()
                if name:
                    partners.append(name)

    # Deduplicate while preserving order
    seen = set()
    unique: List[str] = []
    for p in partners:
        if p in seen:
            continue
        seen.add(p)
        unique.append(p)
    return unique


def _demo_metrics(partner: str) -> Dict[str, Any]:
    return {
        "partner": partner,
        "kpis": {
            "shipments_today": 128,
            "edi_docs_today": 542,
            "ack_rate_pct": 97.8,
            "avg_processing_sec": 18.4,
        },
        "sla_compliance": {"compliant": 92, "breached": 8},
        "top_errors": [
            {"error": "997 rejected", "count": 12},
            {"error": "Missing PO number", "count": 9},
            {"error": "Invalid segment", "count": 6},
        ],
        "as_of": "demo",
    }


def _normalize_sla(sla: Any) -> Tuple[List[str], List[float]]:
    """
    Accepts common shapes:
    - {"compliant": 92, "breached": 8}
    - {"compliant_pct": 92, "breached_pct": 8}
    - [{"label": "compliant", "value": 92}, ...]
    """
    if isinstance(sla, dict):
        if "compliant" in sla and "breached" in sla:
            return (["Compliant", "Breached"], [float(sla["compliant"]), float(sla["breached"])])
        if "compliant_pct" in sla and "breached_pct" in sla:
            return (["Compliant", "Breached"], [float(sla["compliant_pct"]), float(sla["breached_pct"])])
    if isinstance(sla, list):
        labels: List[str] = []
        values: List[float] = []
        for item in sla:
            if isinstance(item, dict) and "label" in item and "value" in item:
                labels.append(str(item["label"]))
                values.append(float(item["value"]))
        if labels and values:
            return (labels, values)
    return (["Compliant", "Breached"], [0.0, 0.0])


def _normalize_top_errors(errors: Any) -> List[Dict[str, Any]]:
    if isinstance(errors, list):
        out: List[Dict[str, Any]] = []
        for e in errors:
            if not isinstance(e, dict):
                continue
            label = e.get("error") or e.get("label") or e.get("name")
            count = e.get("count") or e.get("value") or e.get("n")
            if label is None or count is None:
                continue
            out.append({"error": str(label), "count": int(count)})
        return out
    return []


def _unwrap_n8n_payload(payload: Any) -> Dict[str, Any]:
    """
    n8n sometimes returns:
    - a dict (ideal)
    - a list of items (often [{\"output\": {...}}])
    - a dict wrapper from our client: {\"data\": [...]}
    This function normalizes to the inner metrics dict.
    """
    if isinstance(payload, dict):
        # Our client wraps non-dicts as {"data": ...}
        if "output" in payload and isinstance(payload.get("output"), dict):
            return payload["output"]
        if "data" in payload:
            return _unwrap_n8n_payload(payload.get("data"))
        return payload

    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict) and "output" in first and isinstance(first.get("output"), dict):
            return first["output"]
        if isinstance(first, dict):
            return first
    return {}


def _normalize_sla_chart(payload: Any) -> Tuple[List[str], List[float]]:
    """
    Accepts:
    - {"labels": [...], "values": [...]}
    - fallback to _normalize_sla shapes
    """
    if isinstance(payload, dict) and isinstance(payload.get("labels"), list) and isinstance(payload.get("values"), list):
        labels = [str(x) for x in payload["labels"]]
        values = [float(x) for x in payload["values"]]
        return labels, values
    return _normalize_sla(payload)


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_metrics(partner: str, start_date: str, end_date: str) -> Dict[str, Any]:
    client = N8NClient()
    return client.kpi_metrics(filters={"partner": partner, "start_date": start_date, "end_date": end_date})


def render() -> None:
    st.title("KPI dashboard")
    st.caption("Partner-based operational metrics fetched via n8n webhooks.")

    if px is None:
        st.error("Plotly is not installed. Install it to view KPI charts.")
        st.code("python -m pip install plotly", language="bash")
        st.caption("Alternatively: `pip install -r requirements.txt`")
        return

    left, right = st.columns([2, 1])

    with left:
        # Prefer DB-backed trading partners, fall back to last known list or a small demo list.
        partners: List[str] = st.session_state.get("partners", [])
        if not partners:
            try:
                partners = _fetch_partners_from_postgres()
                st.session_state["partners"] = partners
            except Exception:
                partners = _FALLBACK_PARTNERS

        partner = st.selectbox(
            "Partner",
            options=partners,
            index=0,
            key="kpi_partner",
        )

        st.caption("Date range")
        default_end = date.today()
        default_start = default_end - timedelta(days=7)
        start_date, end_date = st.date_input(
            "Start date / End date",
            value=(st.session_state.get("kpi_start_date", default_start), st.session_state.get("kpi_end_date", default_end)),
        )
        # Persist last selection (Streamlit returns datetime.date)
        st.session_state["kpi_start_date"] = start_date
        st.session_state["kpi_end_date"] = end_date

        if start_date > end_date:
            st.error("Start date must be on or before end date.")
            return

    with right:
        use_demo = st.toggle("Use demo data", value=False, help="Use local demo metrics (no n8n call).")
        if st.button("Refresh", use_container_width=True):
            _fetch_metrics.clear()
            _fetch_partners_from_postgres.clear()

    metrics: Optional[Dict[str, Any]] = None
    if use_demo:
        metrics = _demo_metrics(partner)
    else:
        try:
            with st.spinner("Fetching metrics from n8n..."):
                metrics = _fetch_metrics(partner, start_date.isoformat(), end_date.isoformat())
        except Exception as e:  # noqa: BLE001
            st.error(f"Failed to fetch metrics from n8n: {e}")
            st.info("Enable “Use demo data” to view the dashboard without n8n.")
            return

    # Normalize n8n response shapes (e.g., [{"output": {...}}] or {"data": [...]}).
    metrics = _unwrap_n8n_payload(metrics)

    period = metrics.get("period")
    if isinstance(period, str) and period.strip():
        st.caption(f"Period: **{period.strip()}**")

    if isinstance(metrics, dict) and isinstance(metrics.get("partners"), list):
        st.session_state["partners"] = metrics["partners"]

    kpis = metrics.get("kpis") if isinstance(metrics, dict) else None
    if not isinstance(kpis, dict):
        kpis = {}

    st.divider()
    st.subheader("Headline KPIs")

    c1, c2, c3, c4 = st.columns(4)
    # Support both our demo keys and the KPI workflow keys.
    c1.metric("Total docs", str(kpis.get("total_docs", kpis.get("edi_docs_today", "—"))))
    c2.metric("Failed docs", str(kpis.get("failed_docs", "—")))
    c3.metric("Success %", f"{kpis.get('success_pct', kpis.get('ack_rate_pct', '—'))}%")
    c4.metric("SLA %", f"{kpis.get('sla_pct', '—')}%")

    st.divider()
    st.subheader("SLA compliance")

    sla_labels, sla_values = _normalize_sla_chart(metrics.get("sla_chart") or metrics.get("sla_compliance"))
    sla_df = {"label": sla_labels, "value": sla_values}
    fig_pie = px.pie(
        sla_df,
        names="label",
        values="value",
        hole=0.45,
    )
    fig_pie.update_layout(margin=dict(l=0, r=0, t=10, b=0), legend_title_text="")
    st.plotly_chart(fig_pie, use_container_width=True)

    st.divider()
    st.subheader("Top errors")

    top_errors = _normalize_top_errors(metrics.get("error_chart") or metrics.get("top_errors"))
    if not top_errors:
        st.caption("No error breakdown available.")
    else:
        fig_bar = px.bar(
            top_errors,
            x="count",
            y="error",
            orientation="h",
        )
        fig_bar.update_layout(margin=dict(l=0, r=0, t=10, b=0), yaxis_title=None, xaxis_title=None)
        st.plotly_chart(fig_bar, use_container_width=True)

    insights = metrics.get("ai_insights")
    if isinstance(insights, list) and insights:
        with st.expander("AI insights", expanded=True):
            for item in insights:
                if isinstance(item, str) and item.strip():
                    st.write(f"- {item.strip()}")

    recs = metrics.get("ai_recommendations")
    if isinstance(recs, list) and recs:
        with st.expander("AI recommendations", expanded=True):
            for item in recs:
                if isinstance(item, str) and item.strip():
                    st.write(f"- {item.strip()}")

    with st.expander("Raw metrics payload", expanded=False):
        st.json(metrics)
