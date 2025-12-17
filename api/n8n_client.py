from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


@dataclass(frozen=True)
class N8NConfig:
    base_url: str
    api_key: Optional[str] = None


class N8NClient:
    """Small helper for calling n8n's REST API and webhooks.

    Environment variables:
    - N8N_BASE_URL (default: http://localhost:5678)
    - N8N_API_KEY (optional)
    """

    def __init__(self, config: Optional[N8NConfig] = None, timeout_s: int = 15):
        if config is None:
            config = N8NConfig(
                base_url=os.getenv("N8N_BASE_URL", "http://localhost:5678").rstrip("/"),
                api_key=os.getenv("N8N_API_KEY") or None,
            )

        self.config = config
        self.timeout_s = timeout_s
        self._session = requests.Session()

        if self.config.api_key:
            self._session.headers.update({"X-N8N-API-KEY": self.config.api_key})

    def health_check(self) -> bool:
        try:
            resp = self._session.get(f"{self.config.base_url}/healthz", timeout=self.timeout_s)
            return resp.ok
        except requests.RequestException:
            return False

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resp = self._session.get(
            f"{self.config.base_url}/{path.lstrip('/')}", params=params, timeout=self.timeout_s
        )
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._session.post(
            f"{self.config.base_url}/{path.lstrip('/')}", json=payload, timeout=self.timeout_s
        )
        resp.raise_for_status()
        if not resp.content:
            return {}
        return resp.json()

    def call_webhook(self, webhook_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Call an n8n webhook URL (full URL)."""
        resp = self._session.post(webhook_url, json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
        if not resp.content:
            return {}
        # webhooks sometimes return plain text
        try:
            return resp.json()
        except ValueError:
            return {"text": resp.text}
