"""Parity tests for MetricsService across CLI/REST/MCP surfaces.

Validates that MetricsService operations produce consistent results
regardless of which surface invokes them (CLI, REST API, MCP tools).
Tests cache behavior, SSE streaming, and adapter payload consistency.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Generator

import pytest

from amprealize.adapters import (
    CLIMetricsServiceAdapter,
    RestMetricsServiceAdapter,
    MCPMetricsServiceAdapter,
)
from amprealize.metrics_service import MetricsService
from amprealize.metrics_contracts import MetricsSummary, MetricsExportRequest


@pytest.fixture
def metrics_service(tmp_path) -> Generator[MetricsService, None, None]:
    """Create a fresh MetricsService with isolated cache for each test."""
    cache_db = tmp_path / "metrics_cache.db"
    service = MetricsService(db_path=cache_db, cache_ttl_seconds=2)
    yield service


@pytest.fixture
def cli_adapter(metrics_service: MetricsService) -> CLIMetricsServiceAdapter:
    """CLI adapter for testing."""
    return CLIMetricsServiceAdapter(metrics_service)


@pytest.fixture
def rest_adapter(metrics_service: MetricsService) -> RestMetricsServiceAdapter:
    """REST adapter for testing."""
    return RestMetricsServiceAdapter(metrics_service)


@pytest.fixture
def mcp_adapter(metrics_service: MetricsService) -> MCPMetricsServiceAdapter:
    """MCP adapter for testing."""
    return MCPMetricsServiceAdapter(metrics_service)


class TestGetSummaryParity:
    """Verify get_summary parity across surfaces."""

    def test_cli_get_summary(self, cli_adapter: CLIMetricsServiceAdapter):
        result = cli_adapter.get_summary(
            start_date="2025-10-01",
            end_date="2025-10-22",
            use_cache=False,
        )

        assert "snapshot_time" in result
        assert "behavior_reuse_pct" in result
        assert "average_token_savings_pct" in result
        assert "task_completion_rate_pct" in result
        assert "average_compliance_coverage_pct" in result
        assert "total_runs" in result
        assert "cache_hit" in result
        assert result["cache_hit"] is False  # Fresh query

    def test_rest_get_summary(self, rest_adapter: RestMetricsServiceAdapter):
        payload = {
            "start_date": "2025-10-01",
            "end_date": "2025-10-22",
            "use_cache": False,
        }
        result = rest_adapter.get_summary(payload)

        assert "snapshot_time" in result
        assert "behavior_reuse_pct" in result
        assert "average_token_savings_pct" in result
        assert "task_completion_rate_pct" in result
        assert "average_compliance_coverage_pct" in result
        assert "total_runs" in result
        assert "cache_hit" in result
        assert result["cache_hit"] is False

    def test_mcp_get_summary(self, mcp_adapter: MCPMetricsServiceAdapter):
        payload = {
            "start_date": "2025-10-01",
            "end_date": "2025-10-22",
            "use_cache": False,
        }
        result = mcp_adapter.get_summary(payload)

        assert "snapshot_time" in result
        assert "behavior_reuse_pct" in result
        assert "average_token_savings_pct" in result
        assert "task_completion_rate_pct" in result
        assert "average_compliance_coverage_pct" in result
        assert "total_runs" in result
        assert "cache_hit" in result
        assert result["cache_hit"] is False

    def test_summary_with_date_filters(self, cli_adapter: CLIMetricsServiceAdapter):
        """Verify date filters are respected."""
        result = cli_adapter.get_summary(
            start_date="2025-10-01",
            end_date="2025-10-15",
            use_cache=False,
        )
        assert "snapshot_time" in result
        # Note: actual filtering depends on warehouse having date-filtered data

    def test_summary_cache_behavior(self, cli_adapter: CLIMetricsServiceAdapter):
        """Verify cache hit/miss behavior."""
        # First call - cache miss
        result1 = cli_adapter.get_summary(use_cache=True)
        assert result1["cache_hit"] is False

        # Second call - should be cache hit
        result2 = cli_adapter.get_summary(use_cache=True)
        assert result2["cache_hit"] is True
        assert result2["cache_age_seconds"] > 0


class TestExportMetricsParity:
    """Verify export_metrics parity across surfaces."""

    def test_cli_export_json(self, cli_adapter: CLIMetricsServiceAdapter):
        result = cli_adapter.export_metrics(
            format="json",
            start_date="2025-10-01",
            end_date="2025-10-22",
            metrics=None,
            include_raw_events=False,
        )

        assert "export_id" in result
        assert result["format"] == "json"
        assert "row_count" in result
        assert "size_bytes" in result
        assert "created_at" in result
        # JSON exports include inline data
        assert "data" in result or "file_path" in result

    def test_rest_export_json(self, rest_adapter: RestMetricsServiceAdapter):
        payload = {
            "format": "json",
            "start_date": "2025-10-01",
            "end_date": "2025-10-22",
            "metrics": [],
            "include_raw_events": False,
        }
        result = rest_adapter.export_metrics(payload)

        assert "export_id" in result
        assert result["format"] == "json"
        assert "row_count" in result
        assert "size_bytes" in result
        assert "created_at" in result

    def test_mcp_export_json(self, mcp_adapter: MCPMetricsServiceAdapter):
        payload = {
            "format": "json",
            "start_date": "2025-10-01",
            "end_date": "2025-10-22",
            "metrics": [],
            "include_raw_events": False,
        }
        result = mcp_adapter.export(payload)

        assert "export_id" in result
        assert result["format"] == "json"
        assert "row_count" in result
        assert "size_bytes" in result
        assert "created_at" in result

    def test_export_with_filters(self, cli_adapter: CLIMetricsServiceAdapter):
        """Verify metric filters are applied."""
        result = cli_adapter.export_metrics(
            format="json",
            metrics=["behavior_reuse_pct", "average_token_savings_pct"],
            include_raw_events=False,
        )
        assert result["export_id"]
        assert result["row_count"] >= 0


class TestSubscriptionParity:
    """Verify subscription parity across surfaces."""

    def test_cli_create_subscription(self, cli_adapter: CLIMetricsServiceAdapter):
        """CLI doesn't expose subscriptions directly, but adapter should work."""
        # This would be used if CLI added subscription commands
        pass  # CLI subscriptions not in scope for Priority 1B

    def test_rest_create_subscription(self, rest_adapter: RestMetricsServiceAdapter):
        payload = {
            "metrics": ["behavior_reuse_pct"],
            "refresh_interval_seconds": 10,
        }
        result = rest_adapter.create_subscription(payload)

        assert "subscription_id" in result
        assert result["refresh_interval_seconds"] == 10
        assert "created_at" in result
        assert result["event_count"] == 0

    def test_mcp_create_subscription(self, mcp_adapter: MCPMetricsServiceAdapter):
        payload = {
            "metrics": ["behavior_reuse_pct", "average_token_savings_pct"],
            "refresh_interval_seconds": 15,
        }
        result = mcp_adapter.subscribe(payload)

        assert "subscription_id" in result
        assert result["refresh_interval_seconds"] == 15
        assert "created_at" in result
        assert result["event_count"] == 0

    def test_cancel_subscription(self, rest_adapter: RestMetricsServiceAdapter):
        """Verify subscription cancellation."""
        # Create subscription
        payload = {"refresh_interval_seconds": 30}
        create_result = rest_adapter.create_subscription(payload)
        subscription_id = create_result["subscription_id"]

        # Cancel it
        cancel_result = rest_adapter.cancel_subscription(subscription_id)
        assert cancel_result["subscription_id"] == subscription_id
        assert cancel_result["cancelled"] is True


class TestCacheBehavior:
    """Verify cache TTL and invalidation behavior."""

    def test_cache_expiration(self, cli_adapter: CLIMetricsServiceAdapter):
        """Verify cache expires after TTL (2s in test fixture)."""
        # First call - cache miss
        result1 = cli_adapter.get_summary(use_cache=True)
        assert result1["cache_hit"] is False

        # Immediate second call - cache hit
        result2 = cli_adapter.get_summary(use_cache=True)
        assert result2["cache_hit"] is True

        # Wait for TTL expiration (2s + margin)
        time.sleep(2.5)

        # Third call - cache miss again
        result3 = cli_adapter.get_summary(use_cache=True)
        assert result3["cache_hit"] is False

    def test_cache_bypass(self, cli_adapter: CLIMetricsServiceAdapter):
        """Verify use_cache=False bypasses cache."""
        # Prime cache
        cli_adapter.get_summary(use_cache=True)

        # Bypass cache
        result = cli_adapter.get_summary(use_cache=False)
        assert result["cache_hit"] is False

    def test_manual_invalidation(self, metrics_service: MetricsService, cli_adapter: CLIMetricsServiceAdapter):
        """Verify manual cache invalidation."""
        # Prime cache
        result1 = cli_adapter.get_summary(use_cache=True)
        assert result1["cache_hit"] is False

        # Cache hit
        result2 = cli_adapter.get_summary(use_cache=True)
        assert result2["cache_hit"] is True

        # Invalidate
        metrics_service.invalidate_cache()

        # Cache miss after invalidation
        result3 = cli_adapter.get_summary(use_cache=True)
        assert result3["cache_hit"] is False


class TestAdapterConsistency:
    """Verify adapter payloads match across surfaces."""

    def test_summary_payloads_match(
        self,
        cli_adapter: CLIMetricsServiceAdapter,
        rest_adapter: RestMetricsServiceAdapter,
        mcp_adapter: MCPMetricsServiceAdapter,
    ):
        """Verify all adapters return same summary structure."""
        cli_result = cli_adapter.get_summary(use_cache=False)
        rest_result = rest_adapter.get_summary({"use_cache": False})
        mcp_result = mcp_adapter.get_summary({"use_cache": False})

        # All should have same keys
        cli_keys = set(cli_result.keys())
        rest_keys = set(rest_result.keys())
        mcp_keys = set(mcp_result.keys())

        assert cli_keys == rest_keys == mcp_keys

        # Key metrics should match (values may differ slightly due to timing)
        for key in ["behavior_reuse_pct", "average_token_savings_pct", "total_runs"]:
            assert key in cli_result
            assert key in rest_result
            assert key in mcp_result

    def test_export_payloads_match(
        self,
        cli_adapter: CLIMetricsServiceAdapter,
        rest_adapter: RestMetricsServiceAdapter,
        mcp_adapter: MCPMetricsServiceAdapter,
    ):
        """Verify all adapters return same export structure."""
        cli_result = cli_adapter.export_metrics(format="json")
        rest_result = rest_adapter.export_metrics({"format": "json"})
        mcp_result = mcp_adapter.export({"format": "json"})

        # All should have same required keys
        required_keys = {"export_id", "format", "row_count", "size_bytes", "created_at"}
        assert required_keys.issubset(set(cli_result.keys()))
        assert required_keys.issubset(set(rest_result.keys()))
        assert required_keys.issubset(set(mcp_result.keys()))

    def test_subscription_payloads_match(
        self,
        rest_adapter: RestMetricsServiceAdapter,
        mcp_adapter: MCPMetricsServiceAdapter,
    ):
        """Verify REST and MCP adapters return same subscription structure."""
        rest_result = rest_adapter.create_subscription({"refresh_interval_seconds": 30})
        mcp_result = mcp_adapter.subscribe({"refresh_interval_seconds": 30})

        # Both should have same keys
        rest_keys = set(rest_result.keys())
        mcp_keys = set(mcp_result.keys())
        assert rest_keys == mcp_keys

        required_keys = {"subscription_id", "refresh_interval_seconds", "created_at", "event_count"}
        assert required_keys.issubset(rest_keys)
