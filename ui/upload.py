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
    return f"{client.config.base_url.rstrip('/')}/{client.config.webhook_status.lstrip('/')}"


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
    sslmode_raw = (os.getenv("CONTROL_TOWER_PG_SSLMODE", "require") or "require").strip()
    sslmode = sslmode_raw.lower()
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


def _pg_is_configured() -> bool:
    cfg = _pg_settings()
    return bool(cfg.get("host") and cfg.get("user") and cfg.get("password"))


def _pg_connect():
    if psycopg is None:
        raise ModuleNotFoundError("psycopg is not installed")
    cfg = _pg_settings()
    if not _pg_is_configured():
        raise ValueError("Postgres env vars not configured")
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
    st.subheader("Automation run")

    col1, col2 = st.columns([1, 1])
    max_wait_s = col1.number_input("Max wait (seconds)", min_value=10, max_value=600, value=90, step=10)
    interval_s = col2.number_input("Poll interval (seconds)", min_value=1, max_value=30, value=3, step=1)
    use_db = st.toggle(
        "Show live status from Postgres (document_events)",
        value=_pg_is_configured(),
        disabled=not _pg_is_configured(),
        help="Uses documents.original_filename → documents.document_id → document_events for live status.",
    )

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
                    metadata={"uploaded_at": record["uploaded_at"], "size_bytes": record["size_bytes"]},
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
            st.json(upload_resp)

        # If the webhook already returned a final result, show it immediately.
        if upload_resp.get("result") is not None and not poll_url and not job_id:
            st.subheader("Final automation result")
            st.json(upload_resp.get("result"))
            return

        status_placeholder = st.empty()
        progress_bar = st.progress(0)
        logs_expander = st.expander("Processing updates", expanded=True)

        started = time.time()
        last_status: Dict[str, Any] = {}
        document_id: Optional[Any] = None

        while True:
            if time.time() - started > float(max_wait_s):
                status_placeholder.warning("Timed out waiting for processing to finish.")
                break

            try:
                if use_db:
                    # Resolve document_id from filename (documents table) once it exists.
                    if document_id is None:
                        document_id = _fetch_document_id_for_filename(uploaded.name)
                        if document_id is None:
                            status_placeholder.info("Status: waiting for document registration…")
                            time.sleep(float(interval_s))
                            continue

                    events = _fetch_document_events(document_id)
                    # Sort by time if possible, then compute latest per step.
                    events_sorted = sorted(events, key=_event_time_key)
                    latest: Dict[str, Dict[str, Any]] = {}
                    order: List[str] = []
                    for ev in events_sorted:
                        step = _infer_step_name(ev)
                        if step not in latest:
                            order.append(step)
                        latest[step] = ev

                    # Render pipeline (vertical).
                    status_placeholder.info(f"Status: tracking document_id={document_id}")
                    with logs_expander:
                        _render_pipeline([(s, latest[s]) for s in order])

                    # Progress: use latest numeric progress if present; else derive from ok/fail steps.
                    p = None
                    last_event = events_sorted[-1] if events_sorted else {}
                    if isinstance(last_event, dict):
                        raw_p = last_event.get("progress")
                        if isinstance(raw_p, (int, float)):
                            p = raw_p / 100.0 if raw_p > 1 else float(raw_p)
                    if p is None and order:
                        ok = sum(1 for s in order if _status_bucket(_infer_status(latest[s])) == "ok")
                        p = ok / max(1, len(order))
                    if p is not None:
                        progress_bar.progress(max(0.0, min(1.0, float(p))))

                    # Determine done based on last event status.
                    last_status = last_event if isinstance(last_event, dict) else {}
                    if _is_done({"status": _infer_status(last_status)}):
                        break
                else:
                    if poll_url:
                        status_resp = client.call_webhook(poll_url, {"job_id": job_id} if job_id else {})
                    else:
                        status_resp = client.call_webhook(_status_webhook_url(client), {"job_id": job_id})

                    last_status = status_resp
                    st.session_state["last_upload_run"].update({"status": "polling", "last_status": status_resp})

                    status_text = status_resp.get("status") or status_resp.get("state") or "processing"
                    status_placeholder.info(f"Status: {status_text}")

                    p = _extract_progress(status_resp)
                    if p is not None:
                        progress_bar.progress(p)

                    with logs_expander:
                        logs = status_resp.get("logs") or status_resp.get("events") or status_resp.get("steps")
                        if logs is not None:
                            st.json(logs)
                        else:
                            st.json(status_resp)

                    if _is_done(status_resp):
                        break
            except Exception as e:  # noqa: BLE001
                status_placeholder.error(f"Polling failed: {e}")
                break

            time.sleep(float(interval_s))

        st.divider()
        st.subheader("Final automation result")
        final_result = last_status.get("result") if isinstance(last_status, dict) else None
        if final_result is not None:
            st.json(final_result)
        else:
            st.json(last_status)

    # Show the last run (if any) for context after reruns.
    last_run = st.session_state.get("last_upload_run")
    if last_run:
        with st.expander("Last run (session)", expanded=False):
            st.json(last_run)
