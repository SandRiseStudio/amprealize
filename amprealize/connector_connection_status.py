"""Connector socket presence and optional delegated-tool probe (REST + MCP).

When ``depth=invoke``, the hub sends ``tool.invoke`` with ``run_id`` equal to
``CONNECTOR_PROBE_RUN_ID``; the daemon handles this without ``run_lease`` (see
``connector_daemon.runner``). Uses bounded ``list_dir`` on ``.`` under connector workdir.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from amprealize.local_execution_connector_hub import CONNECTOR_PROBE_RUN_ID, LocalExecutionConnectorHub


@dataclass(frozen=True)
class ConnectorConnectionStatusData:
    connected: bool
    tool_invoke_ok: bool | None = None
    tool_invoke_error: str | None = None


async def build_connector_connection_status(
    *,
    user_id: str,
    depth: str,
    hub: LocalExecutionConnectorHub,
    probe_timeout_sec: float = 15.0,
) -> ConnectorConnectionStatusData:
    depth_norm = (depth or "socket").strip().lower()
    if depth_norm not in ("socket", "invoke"):
        raise ValueError("depth must be 'socket' or 'invoke'")
    connected = hub.user_has_live_connector_socket(user_id)
    if depth_norm == "socket":
        return ConnectorConnectionStatusData(connected=connected)
    if not connected:
        return ConnectorConnectionStatusData(
            connected=False,
            tool_invoke_ok=False,
            tool_invoke_error="no_socket",
        )
    try:
        raw = await hub.invoke_tool(
            user_id=user_id,
            run_id=CONNECTOR_PROBE_RUN_ID,
            tool_name="list_dir",
            tool_args={"path": "."},
            timeout_sec=probe_timeout_sec,
        )
        ok = bool(raw.get("ok"))
        return ConnectorConnectionStatusData(
            connected=True,
            tool_invoke_ok=ok,
            tool_invoke_error=None if ok else str(raw.get("error") or "probe_failed"),
        )
    except asyncio.TimeoutError:
        return ConnectorConnectionStatusData(
            connected=True,
            tool_invoke_ok=False,
            tool_invoke_error="probe_timeout",
        )
