from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from api.n8n_client import N8NClient


ChatMessage = Dict[str, str]


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


def render() -> None:
    st.title("Chatbot")
    st.caption("Ask natural-language questions. Responses are generated via n8n workflows.")

    _init_chat_state()

    messages: List[ChatMessage] = st.session_state.chat_messages
    for m in messages:
        with st.chat_message(m["role"]):
            st.write(m["content"])

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
            answer = _extract_answer(resp)
        except Exception as e:  # noqa: BLE001
            answer = f"Chat request failed: {e}"

        st.write(answer)

    messages.append({"role": "assistant", "content": answer})
