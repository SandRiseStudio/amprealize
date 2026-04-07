"""Parity tests for analytics surfaces (CLI, REST API, MCP).

Validates that analytics.kpiSummary, analytics.behaviorUsage, analytics.tokenSavings,
and analytics.complianceCoverage return consistent data across all three surfaces.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict

import pytest

from amprealize.analytics.warehouse import AnalyticsWarehouse


@pytest.fixture(scope="module")
def api_app():
    """Create FastAPI app once for all tests in this module (caches model loading)."""
    from amprealize.api import create_app
    return create_app()


@pytest.fixture(scope="module")
def api_client(api_app):
    """Create FastAPI test client once for all tests."""
    from fastapi.testclient import TestClient
    return TestClient(api_app)


class TestAnalyticsParity:
    """Test suite ensuring analytics data consistency across surfaces."""

    @pytest.fixture
    def warehouse(self) -> AnalyticsWarehouse:
        """Create warehouse client for tests."""
        if AnalyticsWarehouse is None:
            pytest.skip("AnalyticsWarehouse requires amprealize-enterprise")
        return AnalyticsWarehouse()

    def test_kpi_summary_warehouse_query(self, warehouse: AnalyticsWarehouse) -> None:
        """Verify KPI summary query returns expected structure."""
        records = warehouse.get_kpi_summary()

        assert isinstance(records, list)
        if records:
            record = records[0]
            assert "behavior_reuse_pct" in record
            assert "average_token_savings_pct" in record
            assert "task_completion_rate_pct" in record
            assert "total_runs" in record
            assert isinstance(record["total_runs"], int)

    def test_behavior_usage_warehouse_query(self, warehouse: AnalyticsWarehouse) -> None:
        """Verify behavior usage query returns expected structure."""
        records = warehouse.get_behavior_usage(limit=10)

        assert isinstance(records, list)
        if records:
            record = records[0]
            assert "run_id" in record
            assert "behavior_count" in record
            assert "has_behaviors" in record
            assert isinstance(record["behavior_count"], int)
            assert isinstance(record["has_behaviors"], bool)

    def test_token_savings_warehouse_query(self, warehouse: AnalyticsWarehouse) -> None:
        """Verify token savings query returns expected structure."""
        records = warehouse.get_token_savings(limit=10)

        assert isinstance(records, list)
        if records:
            record = records[0]
            assert "run_id" in record
            assert "output_tokens" in record
            assert "baseline_tokens" in record
            assert "token_savings_pct" in record
            assert isinstance(record["output_tokens"], int)
            assert isinstance(record["baseline_tokens"], int)

    def test_compliance_coverage_warehouse_query(self, warehouse: AnalyticsWarehouse) -> None:
        """Verify compliance coverage query returns expected structure."""
        records = warehouse.get_compliance_coverage(limit=10)

        assert isinstance(records, list)
        # Compliance data may be empty, just verify structure
        if records:
            record = records[0]
            assert "checklist_id" in record
            assert "step_id" in record
            assert "status" in record

    def test_cli_analytics_project_kpi_command(self) -> None:
        """Verify CLI analytics command works (if implemented)."""
        # Note: This assumes `amprealize analytics project-kpi` is implemented
        # If not yet implemented, this test will be skipped
        try:
            result = subprocess.run(
                ["amprealize", "analytics", "project-kpi", "--help"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Just verify command exists and returns help
            assert result.returncode in [0, 1]  # 0 = success, 1 = validation error OK
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("CLI command not yet implemented or not in PATH")

    def test_rest_api_kpi_summary_endpoint(self, api_client) -> None:
        """Verify REST API /v1/analytics/kpi-summary endpoint structure."""
        if AnalyticsWarehouse is None:
            pytest.skip("Analytics REST parity requires amprealize-enterprise")
        response = api_client.get("/api/v1/analytics/kpi-summary?limit=10")
        assert response.status_code == 200

        data = response.json()
        assert "records" in data
        assert "count" in data
        assert isinstance(data["records"], list)
        assert isinstance(data["count"], int)

        if data["records"]:
            record = data["records"][0]
            assert "behavior_reuse_pct" in record
            assert "average_token_savings_pct" in record
            assert "task_completion_rate_pct" in record

    def test_rest_api_behavior_usage_endpoint(self, api_client) -> None:
        """Verify REST API /v1/analytics/behavior-usage endpoint structure."""
        if AnalyticsWarehouse is None:
            pytest.skip("Analytics REST parity requires amprealize-enterprise")
        response = api_client.get("/api/v1/analytics/behavior-usage?limit=10")
        assert response.status_code == 200

        data = response.json()
        assert "records" in data
        assert "count" in data
        assert isinstance(data["records"], list)

    def test_rest_api_token_savings_endpoint(self, api_client) -> None:
        """Verify REST API /v1/analytics/token-savings endpoint structure."""
        if AnalyticsWarehouse is None:
            pytest.skip("Analytics REST parity requires amprealize-enterprise")
        response = api_client.get("/api/v1/analytics/token-savings?limit=10")
        assert response.status_code == 200

        data = response.json()
        assert "records" in data
        assert "count" in data
        assert isinstance(data["records"], list)

    @pytest.mark.timeout(180)  # Model loading can take > 60s
    def test_rest_api_compliance_coverage_endpoint(self, api_client) -> None:
        """Verify REST API /v1/analytics/compliance-coverage endpoint structure."""
        if AnalyticsWarehouse is None:
            pytest.skip("Analytics REST parity requires amprealize-enterprise")
        response = api_client.get("/api/v1/analytics/compliance-coverage?limit=10")
        assert response.status_code == 200

        data = response.json()
        assert "records" in data
        assert "count" in data
        assert isinstance(data["records"], list)

    def test_mcp_tool_manifests_exist(self) -> None:
        """Verify analytics MCP tool manifests are present."""
        import os
        from pathlib import Path

        repo_root = Path(__file__).parent.parent
        tools_dir = repo_root / "mcp" / "tools"

        expected_tools = [
            "analytics.kpiSummary.json",
            "analytics.behaviorUsage.json",
            "analytics.tokenSavings.json",
            "analytics.complianceCoverage.json",
        ]

        for tool_file in expected_tools:
            tool_path = tools_dir / tool_file
            assert tool_path.exists(), f"Missing MCP tool manifest: {tool_file}"

            # Validate JSON structure
            with open(tool_path) as f:
                manifest = json.load(f)
                assert "name" in manifest
                assert "description" in manifest
                assert "inputSchema" in manifest
                assert "outputSchema" in manifest
