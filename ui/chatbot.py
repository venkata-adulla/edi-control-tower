from __future__ import annotations

import os

import streamlit as st

from api.n8n_client import N8NClient


def _ensure_messages() -> None:
    st.session_state.setdefault(
        "chat_messages",
        [
            {
                "role": "assistant",
                "content": "Ask me about uploads, incidents, or overall status.",
            }
        ],
    )


def render() -> None:
    st.title("Chatbot")

    _ensure_messages()

    for m in st.session_state.chat_messages:
        with st.chat_message(m["role"]):
            st.write(m["content"])

    prompt = st.chat_input("Type a message")
    if not prompt:
        return

    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    webhook = os.getenv("N8N_CHAT_WEBHOOK_URL")

    with st.chat_message("assistant"):
        if webhook:
            try:
                client = N8NClient()
                resp = client.call_webhook(webhook, {"message": prompt})
                answer = resp.get("answer") or resp.get("text") or str(resp)
            except Exception as e:  # noqa: BLE001
                answer = f"I couldn't reach n8n: {e}"
        else:
            uploads = len(st.session_state.get("uploaded_files", []))
            incidents = len(st.session_state.get("incidents", []))
            answer = (
                "n8n chat webhook not configured. "
                f"This session: {uploads} uploads, {incidents} incidents. "
                "Set N8N_CHAT_WEBHOOK_URL to enable workflow-backed answers."
            )

        st.write(answer)

    st.session_state.chat_messages.append({"role": "assistant", "content": answer})
