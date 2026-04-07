"""Tests for OAuth token redaction in MCP auth tool responses."""

from __future__ import annotations

import pytest

from amprealize.mcp_server import (
    _mcp_expose_auth_tokens_in_responses,
    _redact_oauth_tokens_for_mcp_tool_result,
)


@pytest.mark.unit
def test_redact_strips_tokens_and_adds_note() -> None:
    result = {
        "status": "authorized",
        "access_token": "ga_secret",
        "refresh_token": "gr_secret",
        "expires_in": 3600,
    }
    out = _redact_oauth_tokens_for_mcp_tool_result(result)
    assert "access_token" not in out
    assert "refresh_token" not in out
    assert out["status"] == "authorized"
    assert out["expires_in"] == 3600
    assert out.get("oauth_tokens_redacted") is True
    assert "oauth_tokens_note" in out
    assert "access_token" in result
    assert "refresh_token" in result


@pytest.mark.unit
def test_redact_leaves_non_token_payload_unchanged() -> None:
    result = {"status": "pending", "device_code": "x"}
    out = _redact_oauth_tokens_for_mcp_tool_result(result)
    assert out == result
    assert "oauth_tokens_redacted" not in out


@pytest.mark.unit
def test_expose_env_disables_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_EXPOSE_AUTH_TOKENS", "1")
    assert _mcp_expose_auth_tokens_in_responses() is True
    result = {"access_token": "visible"}
    out = _redact_oauth_tokens_for_mcp_tool_result(result)
    assert out["access_token"] == "visible"
