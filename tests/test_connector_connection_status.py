"""Tests for connector_connection_status (socket + invoke probe)."""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from amprealize.connector_connection_status import build_connector_connection_status
from amprealize.local_execution_connector_hub import LocalExecutionConnectorHub

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_build_socket_depth() -> None:
    hub = MagicMock(spec=LocalExecutionConnectorHub)
    hub.user_has_live_connector_socket.return_value = True
    data = await build_connector_connection_status(user_id="u1", depth="socket", hub=hub)
    assert data.connected is True
    assert data.tool_invoke_ok is None
    assert data.tool_invoke_error is None


@pytest.mark.asyncio
async def test_build_invoke_without_socket() -> None:
    hub = MagicMock(spec=LocalExecutionConnectorHub)
    hub.user_has_live_connector_socket.return_value = False
    data = await build_connector_connection_status(user_id="u1", depth="invoke", hub=hub)
    assert data.connected is False
    assert data.tool_invoke_ok is False
    assert data.tool_invoke_error == "no_socket"
    hub.invoke_tool.assert_not_called()


@pytest.mark.asyncio
async def test_build_invoke_tool_success() -> None:
    hub = MagicMock(spec=LocalExecutionConnectorHub)
    hub.user_has_live_connector_socket.return_value = True
    hub.invoke_tool = AsyncMock(return_value={"ok": True, "output": "[]"})
    data = await build_connector_connection_status(user_id="u1", depth="invoke", hub=hub)
    assert data.connected is True
    assert data.tool_invoke_ok is True
    assert data.tool_invoke_error is None


@pytest.mark.asyncio
async def test_build_invoke_tool_failure_payload() -> None:
    hub = MagicMock(spec=LocalExecutionConnectorHub)
    hub.user_has_live_connector_socket.return_value = True
    hub.invoke_tool = AsyncMock(return_value={"ok": False, "error": "not_found_or_unsafe"})
    data = await build_connector_connection_status(user_id="u1", depth="invoke", hub=hub)
    assert data.tool_invoke_ok is False
    assert data.tool_invoke_error == "not_found_or_unsafe"


@pytest.mark.asyncio
async def test_build_invoke_tool_timeout() -> None:
    hub = MagicMock(spec=LocalExecutionConnectorHub)
    hub.user_has_live_connector_socket.return_value = True
    hub.invoke_tool = AsyncMock(side_effect=asyncio.TimeoutError())
    data = await build_connector_connection_status(user_id="u1", depth="invoke", hub=hub)
    assert data.connected is True
    assert data.tool_invoke_ok is False
    assert data.tool_invoke_error == "probe_timeout"


@pytest.mark.asyncio
async def test_build_invalid_depth() -> None:
    hub = MagicMock(spec=LocalExecutionConnectorHub)
    with pytest.raises(ValueError, match="depth"):
        await build_connector_connection_status(user_id="u1", depth="both", hub=hub)
