"""Bridge ToolExecutor to LocalExecutionConnectorHub (hybrid delegation)."""

from __future__ import annotations

import os
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from amprealize.local_execution_connector_hub import LocalExecutionConnectorHub


class ConnectorToolDelegate:
    """Async RPC for delegated filesystem/shell tools over the connector WebSocket."""

    __slots__ = ("_hub", "_run_id", "_user_id", "_timeout_sec")

    def __init__(
        self,
        *,
        user_id: str,
        run_id: str,
        hub: LocalExecutionConnectorHub,
        timeout_sec: float | None = None,
    ) -> None:
        self._user_id = user_id
        self._run_id = run_id
        self._hub = hub
        self._timeout_sec = timeout_sec or float(
            os.environ.get("AMPREALIZE_CONNECTOR_TOOL_TIMEOUT_SEC", "120")
        )

    async def invoke(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        raw = await self._hub.invoke_tool(
            user_id=self._user_id,
            run_id=self._run_id,
            tool_name=tool_name,
            tool_args=dict(tool_args or {}),
            timeout_sec=self._timeout_sec,
        )
        if raw.get("ok"):
            return str(raw.get("output") or "")
        from amprealize.tool_executor import ToolExecutionError

        raise ToolExecutionError(tool_name, str(raw.get("error") or "connector_delegate_failed"))
