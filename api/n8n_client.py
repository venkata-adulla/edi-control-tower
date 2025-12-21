from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

import requests


@dataclass(frozen=True)
class N8NWebhookConfig:
    """
    Configuration for calling n8n webhooks.

    Notes:
    - base_url should be the n8n root URL, e.g. https://venkat-1194.app.n8n.cloud
    - webhook_* values are paths appended to base_url, e.g. /webhook/chat
    """

    base_url: str
    webhook_chat: str = "/webhook/chat"
    webhook_upload: str = "/webhook/upload"
    webhook_kpis: str = "/webhook/kpis"
    webhook_incidents: str = "/webhook/incidents"
    webhook_tracker: str = "/webhook/tracker"


class N8NClient:
    """HTTP client for calling n8n webhooks (PoC backend surface).

    Environment variables:
    - N8N_BASE_URL (default: https://venkat-1194.app.n8n.cloud)
    - N8N_WEBHOOK_CHAT (default: /webhook/chat)
    - N8N_WEBHOOK_UPLOAD (default: /webhook/upload)
    - N8N_WEBHOOK_KPIS (default: /webhook/kpis)
    - N8N_WEBHOOK_INCIDENTS (default: /webhook/incidents)
    - N8N_WEBHOOK_TRACKER (default: /webhook/tracker)
    """

    def __init__(self, config: Optional[N8NWebhookConfig] = None, timeout_s: int = 15):
        if config is None:
            config = N8NWebhookConfig(
                base_url=(os.getenv("N8N_BASE_URL", "https://venkat-1194.app.n8n.cloud") or "").rstrip("/"),
                webhook_chat=os.getenv("N8N_WEBHOOK_CHAT", "/webhook/chat"),
                webhook_upload=os.getenv("N8N_WEBHOOK_UPLOAD", "/webhook/upload"),
                webhook_kpis=os.getenv("N8N_WEBHOOK_KPIS", "/webhook/kpis"),
                webhook_incidents=os.getenv("N8N_WEBHOOK_INCIDENTS", "/webhook/incidents"),
                webhook_tracker=os.getenv("N8N_WEBHOOK_TRACKER", "/webhook/tracker"),
            )

        self.config = config
        self.timeout_s = timeout_s
        self._session = requests.Session()

    def _abs_url(self, path: str) -> str:
        base = self.config.base_url.rstrip("/")
        return f"{base}/{path.lstrip('/')}"

    def _json_or_text(self, resp: requests.Response) -> Dict[str, Any]:
        if not resp.content:
            return {}
        try:
            payload = resp.json()
            # Ensure we always return a JSON object (dict-like) from this client surface.
            if isinstance(payload, dict):
                return payload
            return {"data": payload}
        except ValueError:
            return {"text": resp.text}

    def _post_json(
        self,
        url: str,
        payload: Optional[Mapping[str, Any]] = None,
        *,
        files: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # If files are present, we must use multipart/form-data. In that case, `json=...`
        # is ignored by requests, so we send the payload as regular form fields instead.
        if files:
            form: Dict[str, str] = {}
            if payload:
                for k, v in payload.items():
                    if v is None:
                        continue
                    form[str(k)] = str(v)
            resp = self._session.post(url, data=form, files=files, timeout=self.timeout_s)
        else:
            resp = self._session.post(url, json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
        return self._json_or_text(resp)

    def call_webhook(self, webhook_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Call an n8n webhook URL (full URL). Returns JSON (or wraps text)."""
        return self._post_json(webhook_url, payload)

    # --- Webhook API surface (PoC) ---

    def chat_query(self, message: str, *, context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Calls the chat webhook with a user query string."""
        payload: Dict[str, Any] = {"message": message}
        if context:
            payload["context"] = dict(context)
        return self._post_json(self._abs_url(self.config.webhook_chat), payload)

    def file_upload(
        self,
        filename: str,
        content: bytes,
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        as_multipart: bool = True,
    ) -> Dict[str, Any]:
        """Uploads a file to n8n via webhook.

        By default sends multipart/form-data with a 'file' field (most common for webhooks).
        """
        url = self._abs_url(self.config.webhook_upload)
        if as_multipart:
            # n8n Webhook node commonly expects the binary property name `data`
            # (but many workflows use `file`). Send both to be compatible.
            file_part = (filename, content, "application/octet-stream")
            files = {"file": file_part, "data": file_part}
            payload = dict(metadata or {})
            return self._post_json(url, payload, files=files)
        payload = {"filename": filename, "content": content.decode("utf-8", errors="replace")}
        if metadata:
            payload["metadata"] = dict(metadata)
        return self._post_json(url, payload)

    def kpi_metrics(self, *, filters: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Fetches KPI metrics (partner-based) via webhook."""
        return self._post_json(self._abs_url(self.config.webhook_kpis), dict(filters or {}))

    def incident_list(self, *, filters: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Fetches incident list/drill-down payloads via webhook."""
        return self._post_json(self._abs_url(self.config.webhook_incidents), dict(filters or {}))

    def document_tracker(self, *, filters: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Fetches document tracking data via webhook."""
        return self._post_json(self._abs_url(self.config.webhook_tracker), dict(filters or {}))
