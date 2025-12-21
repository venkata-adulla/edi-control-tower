from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from auth.roles import Feature, can_access, get_current_role
from api.n8n_client import N8NClient

try:
    import psycopg
    from psycopg.rows import dict_row
except ModuleNotFoundError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


def _status_webhook_url(client: N8NClient) -> str:
    webhook_status = getattr(client.config, "webhook_status", None)
    if not webhook_status:
        raise ValueError("n8n status webhook is not configured")
    return f"{client.config.base_url.rstrip('/')}/{str(webhook_status).lstrip('/')}"


def _extract_poll_target(upload_resp: Dict[str, Any], client: N8NClient) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (poll_url, job_id). If poll_url isn't provided by the webhook response,
    we can still poll the configured status webhook using job_id.
    """
    job_id = (
        upload_resp.get("job_id")
        or (upload_resp.get("job") or {}).get("id")
        or (upload_resp.get("job") or {}).get("job_id")
    )
    poll_url = upload_resp.get("poll_url") or upload_resp.get("status_url")
    return (poll_url, job_id)


def _extract_progress(status_resp: Dict[str, Any]) -> Optional[float]:
    # Accept either 0..1 or 0..100. Normalize to 0..1 for Streamlit progress.
    val = status_resp.get("progress")
    if isinstance(val, (int, float)):
        if val > 1:
            return max(0.0, min(1.0, float(val) / 100.0))
        return max(0.0, min(1.0, float(val)))
    return None


def _is_done(status_resp: Dict[str, Any]) -> bool:
    if status_resp.get("done") is True:
        return True
    status = (status_resp.get("status") or "").lower()
    return status in {"completed", "complete", "succeeded", "success", "failed", "error", "cancelled"}


def _pg_settings() -> Dict[str, Any]:
    """
    Connection settings for direct Postgres reads (documents + document_events).

    Uses environment variables:
    - CONTROL_TOWER_PG_HOST / PORT / DB / USER / PASSWORD / SSLMODE
    """
    def _get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
        # Prefer environment variables; fall back to Streamlit secrets if present.
        v = os.getenv(name)
        if v is not None and str(v).strip() != "":
            return v
        try:
            secrets = st.secrets  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            secrets = {}
        # Common patterns: flat keys or a nested "postgres" section.
        if isinstance(secrets, dict):
            sv = secrets.get(name)
            if sv is None and isinstance(secrets.get("postgres"), dict):
                sv = secrets["postgres"].get(name)
            if sv is not None and str(sv).strip() != "":
                return str(sv)
        return default

    sslmode_raw = (os.getenv("CONTROL_TOWER_PG_SSLMODE", "require") or "require").strip()
    sslmode = sslmode_raw.lower()
    if sslmode in {"disabled", "disable", "off", "false", "0", "no"}:
        sslmode = "disable"
    elif sslmode in {"require", "required", "on", "true", "1", "yes"}:
        sslmode = "require"

    return {
        "host": _get_setting("CONTROL_TOWER_PG_HOST", "aws-1-ap-south-1.pooler.supabase.com"),
        "port": int(_get_setting("CONTROL_TOWER_PG_PORT", "5432") or "5432"),
        "dbname": _get_setting("CONTROL_TOWER_PG_DB", "postgres"),
        "user": _get_setting("CONTROL_TOWER_PG_USER", "postgres.qzyvkjcgfyltezraiqwh"),
        "password": _get_setting("CONTROL_TOWER_PG_PASSWORD"),
        "sslmode": sslmode,
    }


def _pg_is_configured() -> bool:
    cfg = _pg_settings()
    # Host/user have sensible defaults; password is the only required secret.
    return bool(cfg.get("password"))


def _pg_connect():
    if psycopg is None:
        raise ModuleNotFoundError("psycopg is not installed")
    cfg = _pg_settings()
    if not _pg_is_configured():
        raise ValueError("Postgres credentials not configured")
    # Prefer dict rows for flexible schemas.
    try:
        return psycopg.connect(connect_timeout=8, row_factory=dict_row, **cfg)
    except Exception as e:  # noqa: BLE001
        # Some poolers require SSL; if user set disable, retry with require.
        if str(cfg.get("sslmode", "")).lower() == "disable":
            cfg_retry = dict(cfg)
            cfg_retry["sslmode"] = "require"
            return psycopg.connect(connect_timeout=8, row_factory=dict_row, **cfg_retry)
        raise e


def _fetch_document_id_for_filename(filename: str) -> Optional[Any]:
    """
    Resolve document_id by joining documents.original_filename.
    Assumes table 'documents' has columns: document_id, original_filename.
    """
    query = "SELECT document_id FROM documents WHERE original_filename = %s LIMIT 1"
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (filename,))
            row = cur.fetchone()
            if not row:
                return None
            return row.get("document_id")


def _fetch_events_for_filename(filename: str, limit: int = 500) -> Tuple[Optional[Any], List[Dict[str, Any]]]:
    """
    Fetch document_events for a given documents.original_filename.
    Returns (document_id, events). If document isn't registered yet, returns (None, []).
    """
    # 1) Best case: documents.original_filename matches and we can join directly.
    query_join_exact = """
        SELECT de.*, d.document_id
        FROM documents d
        JOIN document_events de ON de.document_id = d.document_id
        WHERE d.original_filename = %s
        ORDER BY de.event_time ASC
        LIMIT %s
    """

    # 2) Fallback: documents.original_filename may store full paths or normalized variants.
    query_doc_like = """
        SELECT document_id
        FROM documents
        WHERE original_filename ILIKE %s
        LIMIT 1
    """

    # 3) Fallback: sometimes events exist before documents row is created; try correlation_id/details.
    query_events_by_hint = """
        SELECT *
        FROM document_events
        WHERE correlation_id = %s
           OR details ILIKE %s
        ORDER BY event_time ASC
        LIMIT %s
    """
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query_join_exact, (filename, limit))
            rows = cur.fetchall() or []
            if rows:
                doc_id = rows[0].get("document_id")
                return (doc_id, [dict(r) for r in rows])

            # Fallback (2): find a document_id via ILIKE and then fetch events by document_id.
            cur.execute(query_doc_like, (f"%{filename}%",))
            doc_row = cur.fetchone()
            if doc_row and doc_row.get("document_id"):
                doc_id = doc_row.get("document_id")
                events = _fetch_document_events(doc_id, limit=limit)
                return (doc_id, events)

            # Fallback (3): query events directly by correlation_id/details.
            cur.execute(query_events_by_hint, (filename, f"%{filename}%", limit))
            ev_rows = cur.fetchall() or []
            if ev_rows:
                doc_id = ev_rows[0].get("document_id")
                # We may only have a subset due to LIMIT; fetch full timeline by document_id if present.
                if doc_id:
                    return (doc_id, _fetch_document_events(doc_id, limit=limit))
                return (None, [dict(r) for r in ev_rows])

            # Still nothing.
            return (None, [])


def _fetch_document_events(document_id: Any, limit: int = 500) -> List[Dict[str, Any]]:
    """
    Fetch events for a document_id from document_events.
    Assumes document_events has a document_id column; other columns are flexible.
    """
    query = """
        SELECT *
        FROM document_events
        WHERE document_id = %s
        ORDER BY event_time ASC
        LIMIT %s
    """
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (document_id, limit))
            rows = cur.fetchall() or []
            return [dict(r) for r in rows]


def _event_time_key(event: Dict[str, Any]) -> Any:
    for k in ("created_at", "event_time", "updated_at", "timestamp", "ts"):
        if k in event:
            return event.get(k)
    return None


def _infer_step_name(event: Dict[str, Any]) -> str:
    # document_events uses `stage` as the pipeline step name.
    for k in ("stage", "step", "step_name", "activity", "task", "event_type", "type"):
        v = event.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Last resort: status value as a "step"
    v = event.get("status")
    return str(v) if v is not None else "event"


def _infer_status(event: Dict[str, Any]) -> str:
    # document_events uses `status` (e.g., queued/processing/completed/failed).
    v = event.get("status") or event.get("state") or event.get("result")
    if isinstance(v, str) and v.strip():
        return v.strip().lower()
    # fall back to event_type if present
    v2 = event.get("event_type") or event.get("type")
    if isinstance(v2, str) and v2.strip():
        return v2.strip().lower()
    return "unknown"


def _status_bucket(status: str) -> str:
    s = (status or "").lower()
    if s in {"completed", "complete", "success", "succeeded", "processed", "done", "resolved"}:
        return "ok"
    if s in {"failed", "error", "exception", "rejected", "cancelled", "canceled"}:
        return "fail"
    if s in {"processing", "running", "in_progress", "in-progress", "queued", "pending"}:
        return "active"
    return "unknown"


def _symbol(bucket: str) -> str:
    # Avoid emoji; keep to simple symbols.
    if bucket == "ok":
        return "[OK]"
    if bucket == "fail":
        return "[FAIL]"
    if bucket == "active":
        return "[... ]"
    return "[ ? ]"


def _render_pipeline(latest_by_step: List[Tuple[str, Dict[str, Any]]]) -> None:
    """
    Render a vertical pipeline with status symbols.
    latest_by_step is ordered.
    """
    for i, (step, ev) in enumerate(latest_by_step):
        bucket = _status_bucket(_infer_status(ev))
        cols = st.columns([0.18, 0.62, 0.20])
        cols[0].write(_symbol(bucket))
        cols[1].write(step)
        ts = _event_time_key(ev)
        cols[2].write(ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts else ""))
        details = ev.get("details")
        if isinstance(details, str) and details.strip():
            st.caption(details.strip())
        if i < len(latest_by_step) - 1:
            st.write("│")


def _render_pipeline_table(events: List[Dict[str, Any]]) -> None:
    """
    Render a pipeline timeline as a table (human readable) similar to tracker.py.
    Expects document_events-style rows (stage/status/details/event_time/...).
    """
    if not events:
        st.write("NA")
        return

    # Deduplicate by stage, keep latest event for each stage (by event_time).
    latest_by_stage: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for ev in events:
        stage = _infer_step_name(ev)
        if stage not in latest_by_stage:
            order.append(stage)
        latest_by_stage[stage] = ev

    rows: List[Dict[str, Any]] = []
    for stage in order:
        ev = latest_by_stage[stage]
        rows.append(
            {
                "Stage": stage,
                "Status": (ev.get("status") or "").upper() if isinstance(ev.get("status"), str) else (ev.get("status") or "NA"),
                "Details": ev.get("details") or "NA",
                "Event time": ev.get("event_time") or ev.get("created_at") or "NA",
                "Severity": ev.get("severity") or "NA",
                "Actor": ev.get("actor") or "NA",
                "Event type": ev.get("event_type") or "NA",
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)


def _unwrap_final_upload_payload(upload_resp: Dict[str, Any]) -> Dict[str, Any]:
    """
    Try to normalize n8n upload responses into a dict we can render.
    Common patterns:
    - {"result": {...}}
    - {"output": "..."} or {"summary": "..."}
    - {"data": [...]} (wrapped)
    """
    if not isinstance(upload_resp, dict):
        return {}
    if isinstance(upload_resp.get("result"), dict):
        return upload_resp["result"]
    if "data" in upload_resp:
        data = upload_resp.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            # n8n sometimes wraps items as {"json": {...}}
            if "json" in data[0] and isinstance(data[0].get("json"), dict):
                return data[0]["json"]
            return data[0]
    return upload_resp


def _render_human_readable_result(payload: Dict[str, Any]) -> None:
    """
    Render a human-readable summary for common n8n workflow outputs.
    """
    summary = payload.get("Summary") or payload.get("summary") or payload.get("output") or payload.get("text")
    findings = payload.get("findings")
    details = payload.get("details")

    if isinstance(summary, str) and summary.strip():
        st.subheader("Summary")
        st.write(summary.strip())

    if isinstance(findings, list) and findings:
        st.subheader("Findings")
        for f in findings:
            if isinstance(f, str) and f.strip():
                st.write(f"- {f.strip()}")
            else:
                st.write(f"- {f}")

    if isinstance(details, list) and details:
        st.subheader("Details")
        st.dataframe(details, use_container_width=True, hide_index=True)

    if not any([summary, findings, details]):
        # Fallback to showing key/value fields at least.
        st.subheader("Result")
        for k, v in payload.items():
            if isinstance(v, (dict, list)):
                continue
            st.write(f"**{k}**: {v}")


def render() -> None:
    st.title("File upload")

    if not can_access(Feature.upload, get_current_role()):
        st.info("Your role does not allow uploads.")
        return

    st.caption("Upload an EDI file and trigger an n8n automation. The UI will poll for live updates.")

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

    st.divider()
    # Polling configuration (kept intentionally out of the UI)
    max_wait_s = 90
    interval_s = 3
    # Prefer Postgres live status when configured; otherwise fall back to n8n status polling.
    use_db = _pg_is_configured()

    if st.button("Send to n8n and process", type="primary"):
        client = N8NClient()

        st.session_state["last_upload_run"] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "filename": uploaded.name,
            "status": "starting",
        }

        try:
            with st.spinner("Uploading to n8n..."):
                upload_resp = client.file_upload(
                    filename=uploaded.name,
                    content=content,
                    metadata={
                        "filename": uploaded.name,
                        "uploaded_at": record["uploaded_at"],
                        "size_bytes": record["size_bytes"],
                    },
                )
        except Exception as e:  # noqa: BLE001
            st.error(f"Upload failed: {e}")
            return

        poll_url, job_id = _extract_poll_target(upload_resp, client)
        st.session_state["last_upload_run"].update(
            {
                "status": "uploaded",
                "job_id": job_id,
                "poll_url": poll_url,
                "upload_response": upload_resp,
            }
        )

        st.success("Upload accepted by n8n")
        with st.expander("Upload response", expanded=False):
            _render_human_readable_result(_unwrap_final_upload_payload(upload_resp))
            with st.expander("Upload response (raw)", expanded=False):
                st.json(upload_resp)

        # If the webhook already returned a final result, show it immediately.
        if upload_resp.get("result") is not None and not poll_url and not job_id:
            st.subheader("Final automation result")
            st.json(upload_resp.get("result"))
            return

        status_placeholder = st.empty()
        progress_bar = st.progress(0)

        started = time.time()
        last_status: Dict[str, Any] = {}
        document_id: Optional[Any] = None
        last_events: List[Dict[str, Any]] = []

        while True:
            if time.time() - started > float(max_wait_s):
                status_placeholder.warning("Timed out waiting for processing to finish.")
                break

            try:
                if use_db:
                    # Poll document_events joined via documents.original_filename.
                    if not _pg_is_configured():
                        raise ValueError("Postgres not configured for live updates")

                    document_id, events = _fetch_events_for_filename(uploaded.name)
                    if not events:
                        status_placeholder.info("Waiting for document events…")
                        time.sleep(float(interval_s))
                        continue

                    last_events = events
                    events_sorted = events  # already ordered by event_time asc
                    # Do not render live updates here; only show timeline at the end.
                    status_placeholder.info("Processing…")

                    # Progress: use latest numeric progress if present; else derive from ok/fail steps.
                    p = None
                    last_event = events_sorted[-1] if events_sorted else {}
                    if isinstance(last_event, dict):
                        raw_p = last_event.get("progress")
                        if isinstance(raw_p, (int, float)):
                            p = raw_p / 100.0 if raw_p > 1 else float(raw_p)
                    if p is None:
                        # derive based on stage completion ratio
                        stages = []
                        seen = set()
                        for ev in events_sorted:
                            s = _infer_step_name(ev)
                            if s in seen:
                                continue
                            seen.add(s)
                            stages.append(s)
                        if stages:
                            ok = 0
                            # Compute completion ratio from last status per stage.
                            latest_by_stage: Dict[str, Dict[str, Any]] = {}
                            for ev in events_sorted:
                                latest_by_stage[_infer_step_name(ev)] = ev
                            for s in stages:
                                bucket = _status_bucket(_infer_status(latest_by_stage.get(s, {})))
                                if bucket == "ok":
                                    ok += 1
                            p = ok / max(1, len(stages))
                    if p is not None:
                        progress_bar.progress(max(0.0, min(1.0, float(p))))

                    # Determine done based on last event status.
                    last_status = last_event if isinstance(last_event, dict) else {}
                    if _is_done({"status": _infer_status(last_status)}):
                        break
                else:
                    # No Postgres live status. Poll n8n only if a poll URL exists or a status webhook is configured.
                    webhook_status = getattr(client.config, "webhook_status", None)
                    if poll_url:
                        status_resp = client.call_webhook(poll_url, {"job_id": job_id} if job_id else {})
                    elif webhook_status:
                        status_resp = client.call_webhook(_status_webhook_url(client), {"job_id": job_id})
                    else:
                        status_placeholder.warning(
                            "Live status polling is unavailable (no Postgres configuration and no n8n status webhook)."
                        )
                        break

                    last_status = status_resp
                    st.session_state["last_upload_run"].update({"status": "polling", "last_status": status_resp})

                    status_text = status_resp.get("status") or status_resp.get("state") or "processing"
                    status_placeholder.info(f"Status: {status_text}")

                    p = _extract_progress(status_resp)
                    if p is not None:
                        progress_bar.progress(p)

                    if _is_done(status_resp):
                        break
            except Exception as e:  # noqa: BLE001
                status_placeholder.error(f"Polling failed: {e}")
                break

            time.sleep(float(interval_s))

        st.divider()
        st.subheader("Final automation result")

        # 1) Always show the final pipeline from Postgres if available.
        if use_db and last_events:
            st.subheader("Processing timeline")
            _render_pipeline_table(last_events)

        # 2) Show the final response from n8n (human readable), then raw payload for debugging.
        final_payload = _unwrap_final_upload_payload(upload_resp if isinstance(upload_resp, dict) else {})
        _render_human_readable_result(final_payload)
        with st.expander("Final response (raw)", expanded=False):
            st.json(upload_resp)

    # Show the last run (if any) for context after reruns.
    last_run = st.session_state.get("last_upload_run")
    if last_run:
        with st.expander("Last run (session)", expanded=False):
            st.json(last_run)
