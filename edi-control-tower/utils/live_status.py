from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from api.n8n_client import N8NClient


@dataclass(frozen=True)
class LiveStatus:
    ok: bool
    checked_at: datetime
    details: Dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_live_status(n8n_client: Optional[N8NClient] = None) -> LiveStatus:
    checked_at = utc_now()

    if n8n_client is None:
        n8n_client = N8NClient()

    n8n_ok = n8n_client.health_check()

    ok = bool(n8n_ok)
    details: Dict[str, Any] = {
        "n8n": {"ok": n8n_ok},
    }

    return LiveStatus(ok=ok, checked_at=checked_at, details=details)
