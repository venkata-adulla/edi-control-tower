from __future__ import annotations

import os
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


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_metrics(partner: str) -> Dict[str, Any]:
    client = N8NClient()
    return client.kpi_metrics(filters={"partner": partner})


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
                metrics = _fetch_metrics(partner)
        except Exception as e:  # noqa: BLE001
            st.error(f"Failed to fetch metrics from n8n: {e}")
            st.info("Enable “Use demo data” to view the dashboard without n8n.")
            return

    if isinstance(metrics, dict) and isinstance(metrics.get("partners"), list):
        st.session_state["partners"] = metrics["partners"]

    kpis = metrics.get("kpis") if isinstance(metrics, dict) else None
    if not isinstance(kpis, dict):
        kpis = {}

    st.divider()
    st.subheader("Headline KPIs")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Shipments today", str(kpis.get("shipments_today", "—")))
    c2.metric("EDI docs today", str(kpis.get("edi_docs_today", "—")))
    c3.metric("ACK rate", f"{kpis.get('ack_rate_pct', '—')}%")
    c4.metric("Avg processing", f"{kpis.get('avg_processing_sec', '—')}s")

    st.divider()
    st.subheader("SLA compliance")

    sla_labels, sla_values = _normalize_sla(metrics.get("sla_compliance") if isinstance(metrics, dict) else None)
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

    top_errors = _normalize_top_errors(metrics.get("top_errors") if isinstance(metrics, dict) else None)
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

    with st.expander("Raw metrics payload", expanded=False):
        st.json(metrics)
