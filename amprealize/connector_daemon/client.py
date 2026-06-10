"""HTTP helpers for pairing against Amprealize REST (no server imports)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


def api_base_url() -> str:
    return (os.environ.get("AMPREALIZE_API_URL") or "http://127.0.0.1:8000").rstrip("/")


def _auth_headers() -> Dict[str, str]:
    token = os.environ.get("AMPREALIZE_TOKEN") or os.environ.get("AMPREALIZE_API_TOKEN")
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def http_json(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    """Return (status_code, parsed_json_or_error_dict)."""
    url = f"{api_base_url()}/api{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=_auth_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            if not raw.strip():
                return resp.status, {}
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        text = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(text)
        except Exception:
            return e.code, {"detail": text[:500], "status": e.code}
