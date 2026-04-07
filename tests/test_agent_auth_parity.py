"""Parity tests for AgentAuth across CLI, REST, and MCP surfaces."""

import json
from typing import Any, Dict, List

import pytest

from amprealize.agent_auth import AgentAuthClient
from amprealize.adapters import (
    CLIAgentAuthServiceAdapter,
    RestAgentAuthServiceAdapter,
    MCPAgentAuthServiceAdapter,
)


@pytest.fixture
def agent_auth_client() -> AgentAuthClient:
    """Create a fresh AgentAuthClient for each test."""
    return AgentAuthClient()


@pytest.fixture
def cli_adapter(agent_auth_client: AgentAuthClient) -> CLIAgentAuthServiceAdapter:
    """CLI adapter with dedicated client."""
    return CLIAgentAuthServiceAdapter(agent_auth_client)


@pytest.fixture
def rest_adapter(agent_auth_client: AgentAuthClient) -> RestAgentAuthServiceAdapter:
    """REST adapter with dedicated client."""
    return RestAgentAuthServiceAdapter(agent_auth_client)


@pytest.fixture
def mcp_adapter(agent_auth_client: AgentAuthClient) -> MCPAgentAuthServiceAdapter:
    """MCP adapter with dedicated client."""
    return MCPAgentAuthServiceAdapter(agent_auth_client)


class TestEnsureGrantParity:
    """Test ensure_grant operation across surfaces."""

    def test_cli_ensure_grant(self, cli_adapter: CLIAgentAuthServiceAdapter) -> None:
        """CLI ensure_grant returns expected structure."""
        result = cli_adapter.ensure_grant(
            agent_id="test-agent-cli",
            tool_name="test-tool",
            scopes=["actions.read"],
        )

        assert "decision" in result
        assert result["decision"] in ["ALLOW", "DENY", "CONSENT_REQUIRED"]
        if result["decision"] == "ALLOW":
            assert "grant" in result
            assert "audit_action_id" in result
            assert result["grant"]["agent_id"] == "test-agent-cli"

    def test_rest_ensure_grant(self, rest_adapter: RestAgentAuthServiceAdapter) -> None:
        """REST ensure_grant returns expected structure."""
        payload = {
            "agent_id": "test-agent-rest",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        }
        result = rest_adapter.ensure_grant(payload)

        assert "decision" in result
        assert result["decision"] in ["ALLOW", "DENY", "CONSENT_REQUIRED"]
        if result["decision"] == "ALLOW":
            assert "grant" in result
            assert "audit_action_id" in result

    def test_mcp_ensure_grant(self, mcp_adapter: MCPAgentAuthServiceAdapter) -> None:
        """MCP ensure_grant returns expected structure."""
        payload = {
            "agent_id": "test-agent-mcp",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        }
        result = mcp_adapter.ensure_grant(payload)

        assert "decision" in result
        assert result["decision"] in ["ALLOW", "DENY", "CONSENT_REQUIRED"]
        if result["decision"] == "ALLOW":
            assert "grant" in result
            assert "audit_action_id" in result

    def test_cross_surface_grant_structure_parity(
        self,
        cli_adapter: CLIAgentAuthServiceAdapter,
        rest_adapter: RestAgentAuthServiceAdapter,
        mcp_adapter: MCPAgentAuthServiceAdapter,
    ) -> None:
        """All surfaces return consistent grant structure."""
        cli_result = cli_adapter.ensure_grant(
            agent_id="test-agent",
            tool_name="test-tool",
            scopes=["actions.read"],
        )

        rest_result = rest_adapter.ensure_grant({
            "agent_id": "test-agent",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })

        mcp_result = mcp_adapter.ensure_grant({
            "agent_id": "test-agent",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })

        # All should have same top-level keys
        assert set(cli_result.keys()) == set(rest_result.keys())
        assert set(rest_result.keys()) == set(mcp_result.keys())

        # Grant structures should match if present
        if "grant" in cli_result:
            cli_grant_keys = set(cli_result["grant"].keys())
            rest_grant_keys = set(rest_result["grant"].keys())
            mcp_grant_keys = set(mcp_result["grant"].keys())
            assert cli_grant_keys == rest_grant_keys == mcp_grant_keys


class TestListGrantsParity:
    """Test list_grants operation across surfaces."""

    def test_cli_list_grants(self, cli_adapter: CLIAgentAuthServiceAdapter) -> None:
        """CLI list_grants returns array of grants."""
        # First create a grant
        cli_adapter.ensure_grant(
            agent_id="test-agent-cli",
            tool_name="test-tool",
            scopes=["actions.read"],
        )

        grants = cli_adapter.list_grants(agent_id="test-agent-cli")
        assert isinstance(grants, list)
        assert len(grants) > 0
        assert "grant_id" in grants[0]
        assert "agent_id" in grants[0]

    def test_rest_list_grants(self, rest_adapter: RestAgentAuthServiceAdapter) -> None:
        """REST list_grants returns array of grants."""
        # First create a grant
        rest_adapter.ensure_grant({
            "agent_id": "test-agent-rest",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })

        grants = rest_adapter.list_grants({
            "agent_id": "test-agent-rest",
            "include_expired": False,
        })
        assert isinstance(grants, list)
        assert len(grants) > 0

    def test_mcp_list_grants(self, mcp_adapter: MCPAgentAuthServiceAdapter) -> None:
        """MCP list_grants returns array of grants."""
        # First create a grant
        mcp_adapter.ensure_grant({
            "agent_id": "test-agent-mcp",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })

        grants = mcp_adapter.list_grants({
            "agent_id": "test-agent-mcp",
            "include_expired": False,
        })
        assert isinstance(grants, list)
        assert len(grants) > 0

    def test_grant_field_consistency(
        self,
        cli_adapter: CLIAgentAuthServiceAdapter,
        rest_adapter: RestAgentAuthServiceAdapter,
    ) -> None:
        """Grant objects have consistent fields across surfaces."""
        # Create grants
        cli_adapter.ensure_grant(
            agent_id="field-test-agent",
            tool_name="test-tool",
            scopes=["actions.read"],
        )

        cli_grants = cli_adapter.list_grants(agent_id="field-test-agent")
        rest_grants = rest_adapter.list_grants({"agent_id": "field-test-agent", "include_expired": False})

        if cli_grants and rest_grants:
            cli_keys = set(cli_grants[0].keys())
            rest_keys = set(rest_grants[0].keys())
            assert cli_keys == rest_keys


class TestPolicyPreviewParity:
    """Test policy_preview operation across surfaces."""

    def test_cli_policy_preview(self, cli_adapter: CLIAgentAuthServiceAdapter) -> None:
        """CLI policy_preview returns expected structure."""
        result = cli_adapter.policy_preview(
            agent_id="test-agent-cli",
            tool_name="test-tool",
            scopes=["actions.read"],
        )

        assert "decision" in result
        assert result["decision"] in ["ALLOW", "DENY", "CONSENT_REQUIRED"]

    def test_rest_policy_preview(self, rest_adapter: RestAgentAuthServiceAdapter) -> None:
        """REST policy_preview returns expected structure."""
        result = rest_adapter.policy_preview({
            "agent_id": "test-agent-rest",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })

        assert "decision" in result

    def test_mcp_policy_preview(self, mcp_adapter: MCPAgentAuthServiceAdapter) -> None:
        """MCP policy_preview returns expected structure."""
        result = mcp_adapter.policy_preview({
            "agent_id": "test-agent-mcp",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })

        assert "decision" in result

    def test_high_risk_scope_denial(
        self,
        cli_adapter: CLIAgentAuthServiceAdapter,
        rest_adapter: RestAgentAuthServiceAdapter,
        mcp_adapter: MCPAgentAuthServiceAdapter,
    ) -> None:
        """High-risk scopes trigger consistent denials across surfaces."""
        cli_result = cli_adapter.policy_preview(
            agent_id="test-agent",
            tool_name="sensitive-tool",
            scopes=["actions.replay"],
        )

        rest_result = rest_adapter.policy_preview({
            "agent_id": "test-agent",
            "tool_name": "sensitive-tool",
            "scopes": ["actions.replay"],
        })

        mcp_result = mcp_adapter.policy_preview({
            "agent_id": "test-agent",
            "tool_name": "sensitive-tool",
            "scopes": ["actions.replay"],
        })

        # All should deny high-risk scopes by default
        assert cli_result["decision"] == "DENY"
        assert rest_result["decision"] == "DENY"
        assert mcp_result["decision"] == "DENY"


class TestRevokeGrantParity:
    """Test revoke_grant operation across surfaces."""

    def test_cli_revoke_grant(self, cli_adapter: CLIAgentAuthServiceAdapter) -> None:
        """CLI revoke_grant succeeds."""
        # Create a grant first
        result = cli_adapter.ensure_grant(
            agent_id="test-agent-cli",
            tool_name="test-tool",
            scopes=["actions.read"],
        )
        grant_id = result["grant"]["grant_id"]

        # Revoke it
        revoke_result = cli_adapter.revoke_grant(
            grant_id=grant_id,
            revoked_by="test-admin",
            reason="test",
        )

        assert "success" in revoke_result
        assert revoke_result["success"] is True
        assert revoke_result["grant_id"] == grant_id

    def test_rest_revoke_grant(self, rest_adapter: RestAgentAuthServiceAdapter) -> None:
        """REST revoke_grant succeeds."""
        # Create a grant first
        result = rest_adapter.ensure_grant({
            "agent_id": "test-agent-rest",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })
        grant_id = result["grant"]["grant_id"]

        # Revoke it
        revoke_result = rest_adapter.revoke_grant(grant_id, {
            "revoked_by": "test-admin",
            "reason": "test",
        })

        assert "success" in revoke_result
        assert revoke_result["success"] is True

    def test_mcp_revoke_grant(self, mcp_adapter: MCPAgentAuthServiceAdapter) -> None:
        """MCP revoke succeeds."""
        # Create a grant first
        result = mcp_adapter.ensure_grant({
            "agent_id": "test-agent-mcp",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })
        grant_id = result["grant"]["grant_id"]

        # Revoke it
        revoke_result = mcp_adapter.revoke({
            "grant_id": grant_id,
            "revoked_by": "test-admin",
            "reason": "test",
        })

        assert "success" in revoke_result
        assert revoke_result["success"] is True


class TestAdapterConsistency:
    """Test that adapters produce consistent payload shapes."""

    def test_ensure_grant_payloads_match(
        self,
        cli_adapter: CLIAgentAuthServiceAdapter,
        rest_adapter: RestAgentAuthServiceAdapter,
        mcp_adapter: MCPAgentAuthServiceAdapter,
    ) -> None:
        """Ensure grant responses have matching shapes."""
        cli_result = cli_adapter.ensure_grant(
            agent_id="shape-test",
            tool_name="test-tool",
            scopes=["actions.read"],
        )

        rest_result = rest_adapter.ensure_grant({
            "agent_id": "shape-test",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })

        mcp_result = mcp_adapter.ensure_grant({
            "agent_id": "shape-test",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })

        assert set(cli_result.keys()) == set(rest_result.keys())
        assert set(rest_result.keys()) == set(mcp_result.keys())

    def test_policy_preview_payloads_match(
        self,
        cli_adapter: CLIAgentAuthServiceAdapter,
        rest_adapter: RestAgentAuthServiceAdapter,
        mcp_adapter: MCPAgentAuthServiceAdapter,
    ) -> None:
        """Policy preview responses have matching shapes."""
        cli_result = cli_adapter.policy_preview(
            agent_id="shape-test",
            tool_name="test-tool",
            scopes=["actions.read"],
        )

        rest_result = rest_adapter.policy_preview({
            "agent_id": "shape-test",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })

        mcp_result = mcp_adapter.policy_preview({
            "agent_id": "shape-test",
            "tool_name": "test-tool",
            "scopes": ["actions.read"],
        })

        assert set(cli_result.keys()) == set(rest_result.keys())
        assert set(rest_result.keys()) == set(mcp_result.keys())
