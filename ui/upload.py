from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import streamlit as st

from auth.roles import Feature, can_access, get_current_role
from api.n8n_client import N8NClient


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

        while True:
            if time.time() - started > float(max_wait_s):
                status_placeholder.warning("Timed out waiting for processing to finish.")
                break

            try:
                if poll_url:
                    status_resp = client.call_webhook(poll_url, {"job_id": job_id} if job_id else {})
                else:
                    status_resp = client.call_webhook(_status_webhook_url(client), {"job_id": job_id})
            except Exception as e:  # noqa: BLE001
                status_placeholder.error(f"Polling failed: {e}")
                break

            last_status = status_resp
            st.session_state["last_upload_run"].update({"status": "polling", "last_status": status_resp})

            status_text = status_resp.get("status") or status_resp.get("state") or "processing"
            status_placeholder.info(f"Status: {status_text}")

            p = _extract_progress(status_resp)
            if p is not None:
                progress_bar.progress(p)

            with logs_expander:
                # Prefer concise log stream if present.
                logs = status_resp.get("logs") or status_resp.get("events") or status_resp.get("steps")
                if logs is not None:
                    st.json(logs)
                else:
                    st.json(status_resp)

            if _is_done(status_resp):
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
