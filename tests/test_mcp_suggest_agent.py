"""Tests for MCP board.suggestAgent tool."""

import json
import pytest
from unittest.mock import patch, MagicMock

from amprealize.adapters import MCPTaskAssignmentAdapter
from amprealize.services.assignment_service import AssignmentService
from amprealize.boards.contracts import (
    SuggestAgentRequest,
    SuggestAgentResponse,
    AgentSuggestion,
    AgentWorkload,
)


@pytest.mark.unit
class TestMCPSuggestAgent:
    """Test MCP board.suggestAgent tool wiring."""

    @pytest.mark.skip(reason="MCPTaskAssignmentAdapter.suggest_agent not yet implemented — suggest_agent lives on RestAssignmentAdapter")
    def test_mcp_adapter_has_suggest_agent(self):
        """Verify MCPTaskAssignmentAdapter has suggest_agent method."""
        service = AssignmentService()
        adapter = MCPTaskAssignmentAdapter(service=service)
        assert hasattr(adapter, "suggest_agent")
        assert callable(adapter.suggest_agent)

    @pytest.mark.skip(reason="MCPTaskAssignmentAdapter.suggest_agent not yet implemented")
    def test_mcp_adapter_accepts_payload(self):
        """Test MCPTaskAssignmentAdapter.suggest_agent accepts dict payload."""
        service = AssignmentService()
        adapter = MCPTaskAssignmentAdapter(service=service)

        # Create a mock response
        mock_response = SuggestAgentResponse(
            suggestions=[
                AgentSuggestion(
                    agent_id="agent-001",
                    agent_name="Test Agent",
                    score=0.85,
                    behavior_match_score=0.9,
                    workload_score=0.8,
                    current_workload=AgentWorkload(
                        agent_id="agent-001",
                        agent_name="Test Agent",
                        active_items=2,
                        allowed_behaviors=["behavior_coding", "behavior_testing"],
                    ),
                    matched_behaviors=["behavior_coding"],
                    reason="High behavior match with low workload",
                )
            ],
            assignable_id="feature-123",
            assignable_type="feature",
            required_behaviors=["behavior_coding"],
            total_eligible_agents=5,
        )

        # Patch the service's suggest_agent
        with patch.object(service, "suggest_agent", return_value=mock_response):
            result = adapter.suggest_agent({
                "assignable_id": "feature-123",
                "assignable_type": "feature",
                "required_behaviors": ["behavior_coding"],
                "max_suggestions": 3,
            })

        assert isinstance(result, dict)
        assert "suggestions" in result
        assert result["assignable_id"] == "feature-123"
        assert len(result["suggestions"]) == 1

    def test_tool_manifest_exists(self):
        """Verify board.suggestAgent tool manifest exists and is valid."""
        from pathlib import Path

        manifest_path = Path(__file__).parent.parent / "mcp" / "tools" / "board.suggestAgent.json"
        assert manifest_path.exists(), "board.suggestAgent.json manifest not found"

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["name"] == "board.suggestAgent"
        assert "inputSchema" in manifest
        assert "outputSchema" in manifest
        assert "assignable_id" in manifest["inputSchema"]["required"]
        assert "assignable_type" in manifest["inputSchema"]["required"]

    def test_tool_manifest_schema(self):
        """Verify tool manifest has correct input schema."""
        from pathlib import Path

        manifest_path = Path(__file__).parent.parent / "mcp" / "tools" / "board.suggestAgent.json"
        with open(manifest_path) as f:
            manifest = json.load(f)

        input_schema = manifest["inputSchema"]
        props = input_schema["properties"]

        # Check required params
        assert "assignable_id" in props
        assert props["assignable_id"]["type"] == "string"

        assert "assignable_type" in props
        assert props["assignable_type"]["enum"] == ["feature", "task"]

        # Check optional params
        assert "required_behaviors" in props
        assert props["required_behaviors"]["type"] == "array"

        assert "max_suggestions" in props
        assert props["max_suggestions"]["minimum"] == 1
        assert props["max_suggestions"]["maximum"] == 10


@pytest.mark.unit
class TestCLIMCPParity:
    """Test CLI and MCP have consistent behavior."""

    @pytest.mark.skip(reason="CLITaskAssignmentAdapter.surface not yet implemented")
    def test_cli_and_mcp_use_same_request_model(self):
        """Verify CLI and MCP adapters use the same SuggestAgentRequest."""
        from amprealize.adapters import CLITaskAssignmentAdapter, MCPTaskAssignmentAdapter

        # Both adapters should construct SuggestAgentRequest internally
        service = AssignmentService()
        cli_adapter = CLITaskAssignmentAdapter(service=service)
        mcp_adapter = MCPTaskAssignmentAdapter(service=service)

        # CLI uses keyword args, MCP uses dict payload
        # Both should work with the same underlying service
        assert cli_adapter.surface == "cli"
        assert mcp_adapter.surface == "mcp"
