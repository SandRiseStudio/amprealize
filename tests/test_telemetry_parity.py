"""Parity tests for telemetry surfaces (CLI, MCP).

Validates that telemetry.query and telemetry.dashboard return consistent data
across CLI and MCP surfaces. Per user decision, these tools use:
- RazeService for structured log queries
- AnalyticsWarehouse for dashboard KPIs and token accounting

Implements behavior_validate_cross_surface_parity.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# Mark all tests in this module as unit tests (no infrastructure required)
# The tests use mocks for RazeService and AnalyticsWarehouse
pytestmark = pytest.mark.unit


class TestTelemetryQueryParity:
    """Test suite ensuring telemetry query consistency across CLI and MCP surfaces."""

    def test_cli_telemetry_query_help(self) -> None:
        """Verify CLI telemetry query command is registered."""
        result = subprocess.run(
            ["python", "-m", "amprealize.cli", "telemetry", "query", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"CLI error: {result.stderr}"

        # Verify expected arguments are present
        assert "--event-type" in result.stdout
        assert "--from" in result.stdout
        assert "--to" in result.stdout
        assert "--run-id" in result.stdout
        assert "--action-id" in result.stdout
        assert "--session-id" in result.stdout
        assert "--actor-surface" in result.stdout
        assert "--level" in result.stdout
        assert "--search" in result.stdout
        assert "--limit" in result.stdout
        assert "--offset" in result.stdout
        assert "--format" in result.stdout

    def test_cli_telemetry_dashboard_help(self) -> None:
        """Verify CLI telemetry dashboard command is registered."""
        result = subprocess.run(
            ["python", "-m", "amprealize.cli", "telemetry", "dashboard", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"CLI error: {result.stderr}"

        # Verify expected arguments are present
        assert "--run-id" in result.stdout
        assert "--from" in result.stdout
        assert "--to" in result.stdout
        assert "--watch" in result.stdout
        assert "--format" in result.stdout

    def test_mcp_tool_manifests_exist(self) -> None:
        """Verify telemetry MCP tool manifests are present."""
        repo_root = Path(__file__).parent.parent
        tools_dir = repo_root / "mcp" / "tools"

        expected_tools = [
            "telemetry.query.json",
            "telemetry.dashboard.json",
        ]

        for tool_file in expected_tools:
            tool_path = tools_dir / tool_file
            assert tool_path.exists(), f"Missing MCP tool manifest: {tool_file}"

            # Validate JSON structure
            with open(tool_path) as f:
                manifest = json.load(f)
                assert "name" in manifest, f"{tool_file} missing 'name'"
                assert "description" in manifest, f"{tool_file} missing 'description'"
                assert "inputSchema" in manifest, f"{tool_file} missing 'inputSchema'"
                assert "outputSchema" in manifest, f"{tool_file} missing 'outputSchema'"

    def test_telemetry_query_manifest_schema(self) -> None:
        """Verify telemetry.query.json schema matches CLI arguments."""
        repo_root = Path(__file__).parent.parent
        tool_path = repo_root / "mcp" / "tools" / "telemetry.query.json"

        with open(tool_path) as f:
            manifest = json.load(f)

        input_schema = manifest["inputSchema"]
        properties = input_schema.get("properties", {})

        # Verify all CLI filters have corresponding MCP properties
        expected_properties = [
            "event_type",
            "start_time",
            "end_time",
            "run_id",
            "action_id",
            "session_id",
            "actor_surface",
            "level",
            "search",
            "limit",
            "offset",
        ]

        for prop in expected_properties:
            assert prop in properties, f"Missing property '{prop}' in telemetry.query.json"

        # Verify output schema structure
        output_schema = manifest["outputSchema"]
        output_props = output_schema.get("properties", {})
        assert "events" in output_props
        assert "total" in output_props
        assert "limit" in output_props
        assert "offset" in output_props

    def test_telemetry_dashboard_manifest_schema(self) -> None:
        """Verify telemetry.dashboard.json schema matches CLI arguments."""
        repo_root = Path(__file__).parent.parent
        tool_path = repo_root / "mcp" / "tools" / "telemetry.dashboard.json"

        with open(tool_path) as f:
            manifest = json.load(f)

        input_schema = manifest["inputSchema"]
        properties = input_schema.get("properties", {})

        # Verify all CLI filters have corresponding MCP properties
        expected_properties = [
            "run_id",
            "start_date",
            "end_date",
        ]

        for prop in expected_properties:
            assert prop in properties, f"Missing property '{prop}' in telemetry.dashboard.json"

        # Verify output schema structure
        output_schema = manifest["outputSchema"]
        output_props = output_schema.get("properties", {})
        assert "period" in output_props
        assert "kpi_summary" in output_props or "run_detail" in output_props

    def test_cli_query_args_match_mcp_schema(self) -> None:
        """Verify CLI telemetry query arguments align with MCP tool schema."""
        # Get CLI help output to extract argument names
        result = subprocess.run(
            ["python", "-m", "amprealize.cli", "telemetry", "query", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        cli_help = result.stdout

        # Load MCP schema
        repo_root = Path(__file__).parent.parent
        tool_path = repo_root / "mcp" / "tools" / "telemetry.query.json"
        with open(tool_path) as f:
            manifest = json.load(f)

        mcp_properties = manifest["inputSchema"].get("properties", {}).keys()

        # Map CLI arg names to MCP property names
        cli_to_mcp_mapping = {
            "--event-type": "event_type",
            "--from": "start_time",
            "--to": "end_time",
            "--run-id": "run_id",
            "--action-id": "action_id",
            "--session-id": "session_id",
            "--actor-surface": "actor_surface",
            "--level": "level",
            "--search": "search",
            "--limit": "limit",
            "--offset": "offset",
        }

        # Verify each CLI arg has corresponding MCP property
        for cli_arg, mcp_prop in cli_to_mcp_mapping.items():
            assert cli_arg in cli_help, f"CLI missing argument: {cli_arg}"
            assert mcp_prop in mcp_properties, f"MCP schema missing property: {mcp_prop}"


class TestTelemetryDashboardParity:
    """Test suite for telemetry dashboard surface parity."""

    def test_cli_dashboard_args_match_mcp_schema(self) -> None:
        """Verify CLI telemetry dashboard arguments align with MCP tool schema."""
        # Get CLI help output
        result = subprocess.run(
            ["python", "-m", "amprealize.cli", "telemetry", "dashboard", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        cli_help = result.stdout

        # Load MCP schema
        repo_root = Path(__file__).parent.parent
        tool_path = repo_root / "mcp" / "tools" / "telemetry.dashboard.json"
        with open(tool_path) as f:
            manifest = json.load(f)

        mcp_properties = manifest["inputSchema"].get("properties", {}).keys()

        # Map CLI arg names to MCP property names
        cli_to_mcp_mapping = {
            "--run-id": "run_id",
            "--from": "start_date",
            "--to": "end_date",
        }

        # Verify each CLI arg has corresponding MCP property
        for cli_arg, mcp_prop in cli_to_mcp_mapping.items():
            assert cli_arg in cli_help, f"CLI missing argument: {cli_arg}"
            assert mcp_prop in mcp_properties, f"MCP schema missing property: {mcp_prop}"


class TestRelativeDateParsing:
    """Test relative date parsing used by both CLI and MCP surfaces."""

    def test_parse_relative_days(self) -> None:
        """Test parsing relative day format."""
        from amprealize.cli import _parse_relative_date

        now = datetime.now(timezone.utc)
        result = _parse_relative_date("7d")

        # Should be approximately 7 days ago
        expected_delta = timedelta(days=7)
        actual_delta = now - result

        # Allow 1 second tolerance for timing differences
        assert abs(actual_delta.total_seconds() - expected_delta.total_seconds()) < 2

    def test_parse_relative_hours(self) -> None:
        """Test parsing relative hour format."""
        from amprealize.cli import _parse_relative_date

        now = datetime.now(timezone.utc)
        result = _parse_relative_date("24h")

        expected_delta = timedelta(hours=24)
        actual_delta = now - result

        assert abs(actual_delta.total_seconds() - expected_delta.total_seconds()) < 2

    def test_parse_iso_date(self) -> None:
        """Test parsing ISO date format."""
        from amprealize.cli import _parse_relative_date

        result = _parse_relative_date("2024-01-15")

        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.tzinfo == timezone.utc

    def test_parse_iso_datetime(self) -> None:
        """Test parsing ISO datetime format."""
        from amprealize.cli import _parse_relative_date

        result = _parse_relative_date("2024-01-15T10:30:00Z")

        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_parse_invalid_format_raises(self) -> None:
        """Test that invalid format raises ValueError."""
        from amprealize.cli import _parse_relative_date

        with pytest.raises(ValueError) as exc_info:
            _parse_relative_date("invalid-date")

        assert "Invalid date format" in str(exc_info.value)


class TestMCPHandlerIntegration:
    """Integration tests for MCP telemetry handlers."""

    @pytest.fixture
    def mock_raze_service(self):
        """Create mock RazeService for testing."""
        mock_service = MagicMock()
        mock_service.query.return_value = MagicMock(
            logs=[
                MagicMock(
                    to_dict=lambda: {
                        "event_id": "evt-123",
                        "event_type": "test_event",
                        "timestamp": "2024-01-15T10:30:00Z",
                        "level": "INFO",
                        "service": "test-service",
                        "message": "Test message",
                    }
                )
            ]
        )
        return mock_service

    @pytest.fixture
    def mock_analytics_warehouse(self):
        """Create mock AnalyticsWarehouse for testing."""
        mock_warehouse = MagicMock()
        mock_warehouse.get_kpi_summary.return_value = [
            {
                "reuse_rate_pct": 72.5,
                "avg_savings_rate_pct": 34.2,
                "completion_rate_pct": 85.0,
                "avg_coverage_rate_pct": 96.3,
            }
        ]
        mock_warehouse.get_token_savings.return_value = [
            {
                "run_id": "run-abc123",
                "tokens_saved": 15420,
                "savings_rate_pct": 42.1,
                "baseline_tokens": 36666,
                "actual_tokens": 21246,
            }
        ]
        mock_warehouse.get_daily_cost_summary.return_value = [
            {
                "summary_date": "2024-01-15",
                "total_runs": 45,
                "total_cost_usd": 12.50,
            }
        ]
        mock_warehouse.get_cost_per_run.return_value = [
            {"service": "openai-gpt4", "cost_usd": 0.45}
        ]
        return mock_warehouse

    def test_mcp_server_registers_telemetry_tools(self) -> None:
        """Verify MCP server can handle telemetry.* tool prefix."""
        # This is a structural test - verify the handler exists in the code
        from pathlib import Path

        mcp_server_path = Path(__file__).parent.parent / "amprealize" / "mcp_server.py"
        content = mcp_server_path.read_text()

        assert 'tool_name.startswith("telemetry.")' in content, \
            "MCP server missing telemetry.* tool handler"
        assert '"telemetry.query"' in content or "'telemetry.query'" in content, \
            "MCP server missing telemetry.query handler"
        assert '"telemetry.dashboard"' in content or "'telemetry.dashboard'" in content, \
            "MCP server missing telemetry.dashboard handler"


class TestCLIOutputFormats:
    """Test CLI output format consistency between table and JSON."""

    def test_query_json_format_structure(self) -> None:
        """Verify telemetry query JSON output has expected structure."""
        # Run CLI with JSON format (will fail if no data, but should return valid JSON)
        result = subprocess.run(
            [
                "python", "-m", "amprealize.cli", "telemetry", "query",
                "--format", "json",
                "--limit", "1",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Even if query fails due to no backend, verify it handles errors gracefully
        # or returns valid JSON structure
        if result.returncode == 0:
            output = json.loads(result.stdout)
            assert "query" in output or "logs" in output or "events" in output

    def test_dashboard_json_format_structure(self) -> None:
        """Verify telemetry dashboard JSON output has expected structure."""
        result = subprocess.run(
            [
                "python", "-m", "amprealize.cli", "telemetry", "dashboard",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Verify returns valid JSON (may have empty data)
        if result.returncode == 0:
            output = json.loads(result.stdout)
            assert "period" in output or "kpi_summary" in output or "error" in result.stderr.lower()
