"""Unit tests for auth MCP handlers."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from amprealize.mcp.handlers.auth_handlers import (
    AUTH_HANDLERS,
    AuthToolValidationError,
    handle_device_poll,
    handle_list_grants,
)
from amprealize.mcp_server import _redact_oauth_tokens_for_mcp_tool_result


pytestmark = pytest.mark.unit


class FakeDeviceFlowHandler:
    def __init__(self) -> None:
        self.calls = []

    async def handle_tool_call(self, tool_name, params):
        self.calls.append((tool_name, params))
        if tool_name == "auth.listGrants":
            return {"grants": []}
        return {"status": "ok"}


def _fake_server() -> SimpleNamespace:
    return SimpleNamespace(
        _device_flow_handler=FakeDeviceFlowHandler(),
        _session_context=SimpleNamespace(identity="session-agent"),
    )


@pytest.mark.asyncio
async def test_list_grants_defaults_agent_id_from_session_identity():
    server = _fake_server()

    result = await handle_list_grants(server, {})

    assert result == {"grants": []}
    tool_name, params = server._device_flow_handler.calls[0]
    assert tool_name == "auth.listGrants"
    assert params["agent_id"] == "session-agent"


@pytest.mark.asyncio
async def test_device_poll_requires_device_code_at_runtime():
    with pytest.raises(AuthToolValidationError, match="device_code"):
        await handle_device_poll(_fake_server(), {})


def test_auth_manifests_have_handlers():
    root = Path(__file__).resolve().parents[1]
    manifest_names = {
        json.loads(path.read_text())["name"]
        for path in (root / "mcp" / "tools").glob("auth*.json")
    }

    assert manifest_names <= set(AUTH_HANDLERS)


def test_auth_token_redaction_removes_raw_tokens_by_default():
    redacted = _redact_oauth_tokens_for_mcp_tool_result(
        {
            "status": "authorized",
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "token_type": "Bearer",
        }
    )

    assert "access_token" not in redacted
    assert "refresh_token" not in redacted
    assert redacted["status"] == "authorized"
    assert redacted["oauth_tokens_redacted"] is True
