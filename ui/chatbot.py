from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict, Union

import pandas as pd
import streamlit as st

from api.n8n_client import N8NClient


class ChatMessage(TypedDict, total=False):
    role: str
    content: str
    payload: Dict[str, Any]


def _init_chat_state() -> None:
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = [
            {
                "role": "assistant",
                "content": "Ask me about documents, shipments, SLAs, KPIs, or incidents.",
            }
        ]


def _extract_answer(payload: Dict[str, Any]) -> str:
    """
    Normalize n8n webhook responses to a string.
    We accept common patterns like {"answer": "..."} or {"text": "..."}.
    """
    for key in ("answer", "response", "message", "text"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return str(payload)


def _is_effectively_empty_list(val: Any) -> bool:
    if not isinstance(val, list) or len(val) == 0:
        return True
    for item in val:
        if item is None:
            continue
        if isinstance(item, dict) and len(item) == 0:
            continue
        if isinstance(item, str) and not item.strip():
            continue
        return False
    return True


def _render_structured_payload(payload: Dict[str, Any]) -> bool:
    """
    Render known structured response shapes.
    Returns True if we rendered something structured, False to fall back to text.
    """
    details = payload.get("details")
    findings = payload.get("findings")
    summary = payload.get("summary")

    # Only treat as structured if at least one of these keys exists.
    if summary is None and findings is None and details is None:
        return False

    empty_details = _is_effectively_empty_list(details)
    empty_findings = _is_effectively_empty_list(findings)
    empty_summary = not (isinstance(summary, str) and summary.strip())

    # If n8n returned an empty structured payload, show a friendly "no results" message.
    if empty_details and empty_findings and empty_summary:
        st.info(
            "🤔 I couldn’t find any matching records for your request.\n\n"
            "Try changing your filter (status, date range, partner, etc.) or ask the question in a slightly different way."
        )
        with st.expander("Raw response", expanded=False):
            st.json(payload)
        return True

    st.subheader("Details")
    if empty_details:
        st.write("NA")
    elif isinstance(details, list) and all(isinstance(x, dict) for x in details):
        df = pd.DataFrame(details)
        preferred_cols = [
            "document_id",
            "document_type",
            "trading_partner_name",
            "status",
            "current_stage",
            "sla_overall_status",
            "has_incident",
            "created_at",
        ]
        cols = [c for c in preferred_cols if c in df.columns] + [c for c in df.columns if c not in preferred_cols]
        if cols:
            df = df[cols]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.write(str(details))

    st.subheader("Findings")
    if empty_findings:
        st.write("NA")
    elif isinstance(findings, list):
        for item in findings:
            if isinstance(item, str) and item.strip():
                st.write(f"- {item.strip()}")
            else:
                st.write(f"- {item}")
    else:
        st.write(str(findings))

    st.subheader("Summary")
    if isinstance(summary, str) and summary.strip():
        st.write(summary.strip())
    else:
        st.write("NA")

    with st.expander("Raw response", expanded=False):
        st.json(payload)

    return True


def render() -> None:
    st.title("Chatbot")
    st.caption("Ask natural-language questions. Responses are generated via n8n workflows.")

    _init_chat_state()

    messages: List[ChatMessage] = st.session_state.chat_messages
    for m in messages:
        with st.chat_message(m["role"]):
            if "payload" in m and isinstance(m["payload"], dict):
                # Re-render structured payloads if present.
                if not _render_structured_payload(m["payload"]):
                    st.write(m.get("content", ""))
            else:
                st.write(m.get("content", ""))

    prompt: Optional[str] = st.chat_input("Ask a question")
    if not prompt:
        return

    prompt = prompt.strip()
    if not prompt:
        return

    messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        try:
            client = N8NClient()
            with st.spinner("Thinking..."):
                resp = client.chat_query(prompt)
            # If response is structured (summary/findings/details), render nicely.
            if isinstance(resp, dict) and _render_structured_payload(resp):
                answer = resp.get("summary") if isinstance(resp.get("summary"), str) else "Response received."
                messages.append({"role": "assistant", "content": answer, "payload": resp})
                return

            answer = _extract_answer(resp if isinstance(resp, dict) else {"data": resp})
        except Exception as e:  # noqa: BLE001
            answer = f"Chat request failed: {e}"

        st.write(answer)

    messages.append({"role": "assistant", "content": answer})
