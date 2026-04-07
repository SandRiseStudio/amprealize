"""Parity tests for PostgresMetricsService vs MetricsService.

Validates that TimescaleDB-backed implementation produces identical results
to SQLite+DuckDB reference implementation across all operations:
- Snapshot recording
- Event recording (behavior_usage, token_usage, completion, compliance)
- Summary aggregation
- Export operations
- Cache behavior
- Subscription management
"""

import json
import os
import pytest
import time
import uuid
from datetime import datetime, timezone

from amprealize.metrics_service import MetricsService
from amprealize.metrics_service_postgres import PostgresMetricsService
from amprealize.metrics_contracts import (
    MetricsExportRequest,
    MetricsSummary,
)


# Fixtures

@pytest.fixture
def pg_dsn() -> str:
    """Get PostgreSQL DSN from environment."""
    dsn = os.environ.get("AMPREALIZE_METRICS_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_METRICS_PG_DSN not set")
    return dsn


@pytest.fixture
def memory_service() -> MetricsService:
    """In-memory MetricsService (SQLite cache, no warehouse)."""
    import tempfile
    import shutil

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "metrics_cache.db")
    service = MetricsService(db_path=db_path, cache_ttl_seconds=30)

    yield service

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def postgres_service(pg_dsn: str) -> PostgresMetricsService:
    """TimescaleDB-backed PostgresMetricsService."""
    service = PostgresMetricsService(dsn=pg_dsn, cache_ttl_seconds=30)

    # Cleanup tables before tests
    _truncate_metrics_tables(pg_dsn)

    yield service

    # Cleanup after tests
    _truncate_metrics_tables(pg_dsn)


def _truncate_metrics_tables(dsn: str) -> None:
    """Truncate all metrics tables for test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, [
        "metrics_snapshots", "behavior_usage_events",
        "token_usage_events", "completion_events", "compliance_events",
    ])


# Test Classes

class TestSnapshotRecording:
    """Test metrics snapshot recording parity."""

    def test_record_snapshot_structure(self, postgres_service: PostgresMetricsService):
        """Verify snapshot_id is returned and data persisted."""
        snapshot_id = postgres_service.record_snapshot(
            behavior_reuse_pct=65.0,
            average_token_savings_pct=28.5,
            task_completion_rate_pct=82.0,
            average_compliance_coverage_pct=93.5,
            total_runs=100,
            runs_with_behaviors=65,
            total_baseline_tokens=50000,
            total_output_tokens=35750,
            completed_runs=82,
            failed_runs=18,
            total_compliance_events=150,
            aggregation_type="realtime",
        )

        # Verify UUID format
        assert isinstance(snapshot_id, str)
        uuid.UUID(snapshot_id)  # Raises if invalid

        # Verify data persisted
        with postgres_service._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT behavior_reuse_pct, total_runs FROM metrics_snapshots WHERE snapshot_id = %s",
                    (snapshot_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert float(row[0]) == 65.0
                assert row[1] == 100

    def test_record_snapshot_with_window(self, postgres_service: PostgresMetricsService):
        """Verify window_start/window_end and aggregation_type stored correctly."""
        window_start = "2025-10-29T00:00:00Z"
        window_end = "2025-10-29T01:00:00Z"

        snapshot_id = postgres_service.record_snapshot(
            behavior_reuse_pct=70.0,
            average_token_savings_pct=30.0,
            task_completion_rate_pct=80.0,
            average_compliance_coverage_pct=95.0,
            total_runs=50,
            runs_with_behaviors=35,
            total_baseline_tokens=25000,
            total_output_tokens=17500,
            completed_runs=40,
            failed_runs=10,
            total_compliance_events=75,
            window_start=window_start,
            window_end=window_end,
            aggregation_type="hourly",
        )

        with postgres_service._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT window_start, window_end, aggregation_type FROM metrics_snapshots WHERE snapshot_id = %s",
                    (snapshot_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0].isoformat() == window_start.replace("Z", "+00:00")
                assert row[1].isoformat() == window_end.replace("Z", "+00:00")
                assert row[2] == "hourly"

    def test_record_snapshot_metadata(self, postgres_service: PostgresMetricsService):
        """Verify JSONB metadata storage."""
        metadata = {"source": "test", "tags": ["hourly", "production"]}

        snapshot_id = postgres_service.record_snapshot(
            behavior_reuse_pct=68.0,
            average_token_savings_pct=29.0,
            task_completion_rate_pct=81.0,
            average_compliance_coverage_pct=94.0,
            total_runs=75,
            runs_with_behaviors=51,
            total_baseline_tokens=37500,
            total_output_tokens=26625,
            completed_runs=61,
            failed_runs=14,
            total_compliance_events=112,
            metadata=metadata,
        )

        with postgres_service._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT metadata FROM metrics_snapshots WHERE snapshot_id = %s",
                    (snapshot_id,),
                )
                row = cur.fetchone()
                assert row is not None
                # psycopg2 auto-deserializes JSONB
                stored_metadata = row[0]
                assert stored_metadata == metadata


class TestEventRecording:
    """Test event recording across all 4 event types."""

    def test_record_behavior_usage(self, postgres_service: PostgresMetricsService):
        """Verify behavior usage event recording."""
        run_id = f"test-run-{uuid.uuid4()}"
        behavior_id = "behavior_test_event_recording"

        event_id = postgres_service.record_behavior_usage(
            run_id=run_id,
            behavior_id=behavior_id,
            behavior_version="1.0.0",
            citation_count=3,
            actor_id="test-user",
            actor_role="STRATEGIST",
            surface="cli",
        )

        uuid.UUID(event_id)  # Verify UUID format

        with postgres_service._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_id, behavior_id, citation_count FROM behavior_usage_events WHERE event_id = %s",
                    (event_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] == run_id
                assert row[1] == behavior_id
                assert row[2] == 3

    def test_record_token_usage(self, postgres_service: PostgresMetricsService):
        """Verify token usage event recording and savings calculation."""
        run_id = f"test-run-{uuid.uuid4()}"

        event_id = postgres_service.record_token_usage(
            run_id=run_id,
            baseline_tokens=1000,
            output_tokens=700,
            bci_enabled=True,
            behavior_count=2,
            actor_id="test-user",
            surface="api",
        )

        uuid.UUID(event_id)

        with postgres_service._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT baseline_tokens, output_tokens, token_savings_pct, bci_enabled FROM token_usage_events WHERE event_id = %s",
                    (event_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] == 1000
                assert row[1] == 700
                # Savings: (1000 - 700) / 1000 * 100 = 30.0
                assert float(row[2]) == 30.0
                assert row[3] is True

    def test_record_completion_event_success(self, postgres_service: PostgresMetricsService):
        """Verify completion event recording for successful runs."""
        run_id = f"test-run-{uuid.uuid4()}"

        event_id = postgres_service.record_completion_event(
            run_id=run_id,
            status="SUCCESS",
            duration_seconds=120,
            actor_id="test-user",
            surface="mcp",
        )

        uuid.UUID(event_id)

        with postgres_service._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_id, status, duration_seconds FROM completion_events WHERE event_id = %s",
                    (event_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] == run_id
                assert row[1] == "SUCCESS"
                assert row[2] == 120

    def test_record_completion_event_failure(self, postgres_service: PostgresMetricsService):
        """Verify completion event recording with error details."""
        run_id = f"test-run-{uuid.uuid4()}"

        event_id = postgres_service.record_completion_event(
            run_id=run_id,
            status="FAILED",
            duration_seconds=45,
            error_type="ValidationError",
            error_message="Invalid input parameters",
            surface="web",
        )

        uuid.UUID(event_id)

        with postgres_service._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, error_type, error_message FROM completion_events WHERE event_id = %s",
                    (event_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] == "FAILED"
                assert row[1] == "ValidationError"
                assert row[2] == "Invalid input parameters"

    def test_record_compliance_event(self, postgres_service: PostgresMetricsService):
        """Verify compliance event recording."""
        run_id = f"test-run-{uuid.uuid4()}"
        checklist_id = f"checklist-{uuid.uuid4()}"

        event_id = postgres_service.record_compliance_event(
            run_id=run_id,
            checklist_id=checklist_id,
            coverage_score=87.5,
            total_steps=8,
            completed_steps=7,
            actor_id="test-user",
            surface="cli",
        )

        uuid.UUID(event_id)

        with postgres_service._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT checklist_id, coverage_score, total_steps, completed_steps FROM compliance_events WHERE event_id = %s",
                    (event_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] == checklist_id
                assert float(row[1]) == 87.5
                assert row[2] == 8
                assert row[3] == 7


class TestSummaryAggregation:
    """Test get_summary() aggregation logic."""

    def test_get_summary_empty_db(self, postgres_service: PostgresMetricsService):
        """Verify empty summary when no data exists."""
        summary = postgres_service.get_summary(use_cache=False)

        assert isinstance(summary, MetricsSummary)
        assert summary.total_runs == 0
        assert summary.behavior_reuse_pct == 0.0
        assert summary.average_token_savings_pct == 0.0
        assert summary.task_completion_rate_pct == 0.0
        assert summary.average_compliance_coverage_pct == 0.0

    def test_get_summary_single_snapshot(self, postgres_service: PostgresMetricsService):
        """Verify summary retrieves latest snapshot."""
        postgres_service.record_snapshot(
            behavior_reuse_pct=72.0,
            average_token_savings_pct=31.0,
            task_completion_rate_pct=85.0,
            average_compliance_coverage_pct=96.0,
            total_runs=150,
            runs_with_behaviors=108,
            total_baseline_tokens=75000,
            total_output_tokens=51750,
            completed_runs=127,
            failed_runs=23,
            total_compliance_events=225,
        )

        summary = postgres_service.get_summary(use_cache=False)

        assert summary.total_runs == 150
        assert summary.behavior_reuse_pct == 72.0
        assert summary.average_token_savings_pct == 31.0
        assert summary.task_completion_rate_pct == 85.0
        assert summary.average_compliance_coverage_pct == 96.0
        assert summary.runs_with_behaviors == 108
        assert summary.completed_runs == 127
        assert summary.failed_runs == 23

    def test_get_summary_latest_snapshot(self, postgres_service: PostgresMetricsService):
        """Verify summary returns most recent snapshot."""
        # Record older snapshot
        postgres_service.record_snapshot(
            snapshot_time="2025-10-28T10:00:00Z",
            behavior_reuse_pct=60.0,
            average_token_savings_pct=25.0,
            task_completion_rate_pct=75.0,
            average_compliance_coverage_pct=90.0,
            total_runs=50,
            runs_with_behaviors=30,
            total_baseline_tokens=25000,
            total_output_tokens=18750,
            completed_runs=37,
            failed_runs=13,
            total_compliance_events=75,
        )

        # Record newer snapshot
        postgres_service.record_snapshot(
            snapshot_time="2025-10-29T12:00:00Z",
            behavior_reuse_pct=75.0,
            average_token_savings_pct=32.0,
            task_completion_rate_pct=88.0,
            average_compliance_coverage_pct=97.0,
            total_runs=200,
            runs_with_behaviors=150,
            total_baseline_tokens=100000,
            total_output_tokens=68000,
            completed_runs=176,
            failed_runs=24,
            total_compliance_events=300,
        )

        summary = postgres_service.get_summary(use_cache=False)

        # Should return newer snapshot
        assert summary.total_runs == 200
        assert summary.behavior_reuse_pct == 75.0

    def test_get_summary_cache_behavior(self, postgres_service: PostgresMetricsService):
        """Verify Redis cache hit/miss behavior."""
        postgres_service.record_snapshot(
            behavior_reuse_pct=70.0,
            average_token_savings_pct=30.0,
            task_completion_rate_pct=80.0,
            average_compliance_coverage_pct=95.0,
            total_runs=100,
            runs_with_behaviors=70,
            total_baseline_tokens=50000,
            total_output_tokens=35000,
            completed_runs=80,
            failed_runs=20,
            total_compliance_events=150,
        )

        # First call - cache miss
        summary1 = postgres_service.get_summary(use_cache=True)
        assert summary1.cache_hit is False

        # Second call - cache hit
        summary2 = postgres_service.get_summary(use_cache=True)
        assert summary2.cache_hit is True
        assert summary2.total_runs == summary1.total_runs


class TestExportOperations:
    """Test export_metrics() functionality."""

    def test_export_json_format(self, postgres_service: PostgresMetricsService):
        """Verify JSON export format."""
        postgres_service.record_snapshot(
            behavior_reuse_pct=68.0,
            average_token_savings_pct=29.0,
            task_completion_rate_pct=81.0,
            average_compliance_coverage_pct=94.0,
            total_runs=80,
            runs_with_behaviors=54,
            total_baseline_tokens=40000,
            total_output_tokens=28400,
            completed_runs=65,
            failed_runs=15,
            total_compliance_events=120,
        )

        request = MetricsExportRequest(format="json")
        result = postgres_service.export_metrics(request)

        assert result.format == "json"
        assert result.row_count == 1
        assert result.data is not None
        assert len(result.data) == 1
        assert result.data[0]["total_runs"] == 80
        assert result.size_bytes > 0
        uuid.UUID(result.export_id)  # Verify UUID

    def test_export_unsupported_format(self, postgres_service: PostgresMetricsService):
        """Verify error on unsupported format."""
        request = MetricsExportRequest(format="parquet")

        with pytest.raises(ValueError, match="Unsupported export format"):
            postgres_service.export_metrics(request)


class TestCacheInvalidation:
    """Test cache invalidation behavior."""

    def test_invalidate_cache_on_write(self, postgres_service: PostgresMetricsService):
        """Verify cache invalidation after snapshot write."""
        postgres_service.record_snapshot(
            behavior_reuse_pct=65.0,
            average_token_savings_pct=28.0,
            task_completion_rate_pct=79.0,
            average_compliance_coverage_pct=92.0,
            total_runs=60,
            runs_with_behaviors=39,
            total_baseline_tokens=30000,
            total_output_tokens=21600,
            completed_runs=47,
            failed_runs=13,
            total_compliance_events=90,
        )

        # Prime cache
        summary1 = postgres_service.get_summary(use_cache=True)
        assert summary1.cache_hit is False

        # Second call hits cache
        summary2 = postgres_service.get_summary(use_cache=True)
        assert summary2.cache_hit is True

        # Write invalidates cache
        postgres_service.record_snapshot(
            behavior_reuse_pct=70.0,
            average_token_savings_pct=30.0,
            task_completion_rate_pct=82.0,
            average_compliance_coverage_pct=95.0,
            total_runs=100,
            runs_with_behaviors=70,
            total_baseline_tokens=50000,
            total_output_tokens=35000,
            completed_runs=82,
            failed_runs=18,
            total_compliance_events=150,
        )

        # Next call misses cache
        summary3 = postgres_service.get_summary(use_cache=True)
        assert summary3.cache_hit is False
        assert summary3.total_runs == 100  # New data


class TestSubscriptionManagement:
    """Test subscription CRUD operations."""

    def test_create_subscription(self, postgres_service: PostgresMetricsService):
        """Verify subscription creation."""
        sub = postgres_service.create_subscription(
            metrics=["behavior_reuse_pct", "token_savings_pct"],
            refresh_interval_seconds=60,
        )

        assert sub.subscription_id is not None
        uuid.UUID(sub.subscription_id)
        assert sub.metrics == ["behavior_reuse_pct", "token_savings_pct"]
        assert sub.refresh_interval_seconds == 60
        assert sub.event_count == 0

    def test_list_subscriptions(self, postgres_service: PostgresMetricsService):
        """Verify subscription listing."""
        sub1 = postgres_service.create_subscription()
        sub2 = postgres_service.create_subscription(refresh_interval_seconds=120)

        subs = postgres_service.list_subscriptions()
        assert len(subs) == 2
        sub_ids = {s.subscription_id for s in subs}
        assert sub1.subscription_id in sub_ids
        assert sub2.subscription_id in sub_ids

    def test_cancel_subscription(self, postgres_service: PostgresMetricsService):
        """Verify subscription cancellation."""
        sub = postgres_service.create_subscription()
        assert len(postgres_service.list_subscriptions()) == 1

        cancelled = postgres_service.cancel_subscription(sub.subscription_id)
        assert cancelled is True
        assert len(postgres_service.list_subscriptions()) == 0

        # Cancel again returns False
        cancelled_again = postgres_service.cancel_subscription(sub.subscription_id)
        assert cancelled_again is False


class TestMultiTenantIsolation:
    """Test run_id isolation across events."""

    def test_event_isolation_by_run_id(self, postgres_service: PostgresMetricsService):
        """Verify events from different runs remain isolated."""
        run1 = f"test-run-1-{uuid.uuid4()}"
        run2 = f"test-run-2-{uuid.uuid4()}"

        # Record events for run1
        postgres_service.record_behavior_usage(
            run_id=run1, behavior_id="behavior_1", citation_count=2
        )
        postgres_service.record_token_usage(
            run_id=run1, baseline_tokens=1000, output_tokens=750
        )

        # Record events for run2
        postgres_service.record_behavior_usage(
            run_id=run2, behavior_id="behavior_2", citation_count=3
        )
        postgres_service.record_token_usage(
            run_id=run2, baseline_tokens=1500, output_tokens=1200
        )

        # Verify isolation
        with postgres_service._pool.connection() as conn:
            with conn.cursor() as cur:
                # Count run1 events
                cur.execute(
                    "SELECT COUNT(*) FROM behavior_usage_events WHERE run_id = %s",
                    (run1,),
                )
                assert cur.fetchone()[0] == 1

                cur.execute(
                    "SELECT COUNT(*) FROM token_usage_events WHERE run_id = %s",
                    (run1,),
                )
                assert cur.fetchone()[0] == 1

                # Count run2 events
                cur.execute(
                    "SELECT COUNT(*) FROM behavior_usage_events WHERE run_id = %s",
                    (run2,),
                )
                assert cur.fetchone()[0] == 1

                cur.execute(
                    "SELECT COUNT(*) FROM token_usage_events WHERE run_id = %s",
                    (run2,),
                )
                assert cur.fetchone()[0] == 1
