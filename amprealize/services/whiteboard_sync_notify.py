"""Best-effort notifier that asks the whiteboard-sync sidecar to reload a room.

When the brainstorm agent writes shapes via the MCP tools, the data goes
straight to the shared whiteboard store. The sync sidecar that serves the
browser is otherwise authoritative for a live session and only re-reads on a
timer, so agent edits would lag. This pings ``POST /reload/whiteboard/{room_id}``
so those edits appear immediately (and the sidecar's next save then preserves
them instead of clobbering).

Strictly best-effort: it never raises and uses a short timeout, so a missing or
slow sidecar never breaks (or meaningfully delays) a tool call.
"""

from __future__ import annotations

import logging
import os
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


def notify_whiteboard_reload(
    room_id: str,
    *,
    sync_base_url: Optional[str] = None,
    timeout: float = 1.5,
) -> bool:
    """Ping the sidecar to reload ``room_id``. Returns True on a 2xx response.

    ``sync_base_url`` defaults to ``AMPREALIZE_WHITEBOARD_SYNC_URL`` (e.g.
    ``http://localhost:3040``). Returns False (without raising) when no sidecar
    URL is configured or the request fails.
    """
    if not room_id:
        return False

    base = (sync_base_url or os.environ.get("AMPREALIZE_WHITEBOARD_SYNC_URL") or "").rstrip("/")
    if not base:
        return False

    url = f"{base}/reload/whiteboard/{room_id}"
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("WHITEBOARD_SERVICE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(url, data=b"", method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (localhost sidecar)
            return 200 <= resp.status < 300
    except Exception as exc:  # noqa: BLE001 — best-effort, must never raise
        logger.debug("whiteboard reload notify failed for room=%s: %s", room_id, exc)
        return False
