"""Tests for execution metrics module."""

import sys
import os
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# Add amprealize to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "amprealize"))


class TestMetricsHelperFunctions:
    """Tests for metrics helper functions (work whether prometheus is available or not)."""

    def test_record_job_processed_no_error(self):
        """record_job_processed doesn't error."""
        from amprealize.execution_metrics import record_job_processed

        # Should not raise even if prometheus not available
        record_job_processed(status="success", scope="org:123")
        record_job_processed(status="failure", scope="user:456")

    def test_record_job_duration_no_error(self):
        """record_job_duration doesn't error."""
        from amprealize.execution_metrics import record_job_duration

        record_job_duration(scope="org:123", duration_seconds=45.5)

    def test_set_jobs_in_progress_no_error(self):
        """set_jobs_in_progress doesn't error."""
        from amprealize.execution_metrics import set_jobs_in_progress

        set_jobs_in_progress(worker_id="worker-1", count=1)
        set_jobs_in_progress(worker_id="worker-1", count=0)

    def test_update_queue_depth_no_error(self):
        """update_queue_depth doesn't error."""
        from amprealize.execution_metrics import update_queue_depth

        update_queue_depth(priority="high", depth=10)
        update_queue_depth(priority="normal", depth=5)
        update_queue_depth(priority="low", depth=2)

    def test_update_queue_pending_no_error(self):
        """update_queue_pending doesn't error."""
        from amprealize.execution_metrics import update_queue_pending

        update_queue_pending(priority="high", pending=3)

    def test_record_workspace_provisioned_no_error(self):
        """record_workspace_provisioned doesn't error."""
        from amprealize.execution_metrics import record_workspace_provisioned

        record_workspace_provisioned(scope="org:123")

    def test_set_active_workspaces_no_error(self):
        """set_active_workspaces doesn't error."""
        from amprealize.execution_metrics import set_active_workspaces

        set_active_workspaces(scope="org:123", count=5)

    def test_record_workspace_cleaned_no_error(self):
        """record_workspace_cleaned doesn't error."""
        from amprealize.execution_metrics import record_workspace_cleaned

        record_workspace_cleaned(scope="org:123", reason="success")
        record_workspace_cleaned(scope="user:456", reason="zombie")

    def test_record_zombies_reaped_no_error(self):
        """record_zombies_reaped doesn't error."""
        from amprealize.execution_metrics import record_zombies_reaped

        record_zombies_reaped(count=3)

    def test_record_reaper_run_no_error(self):
        """record_reaper_run doesn't error."""
        from amprealize.execution_metrics import record_reaper_run

        record_reaper_run()

    def test_record_reaper_error_no_error(self):
        """record_reaper_error doesn't error."""
        from amprealize.execution_metrics import record_reaper_error

        record_reaper_error()

    def test_record_quota_check_no_error(self):
        """record_quota_check doesn't error."""
        from amprealize.execution_metrics import record_quota_check

        record_quota_check(scope="org:123", allowed=True)
        record_quota_check(scope="org:123", allowed=False)

    def test_set_quota_usage_no_error(self):
        """set_quota_usage doesn't error."""
        from amprealize.execution_metrics import set_quota_usage

        set_quota_usage(scope="org:123", count=3)

    def test_set_worker_info_no_error(self):
        """set_worker_info doesn't error."""
        from amprealize.execution_metrics import set_worker_info

        set_worker_info(
            worker_id="worker-1",
            consumer_group="execution-workers",
            version="1.0.0",
        )


class TestMetricsAvailability:
    """Tests for prometheus availability detection."""

    def test_prometheus_available_exported(self):
        """PROMETHEUS_AVAILABLE is exported."""
        from amprealize.execution_metrics import PROMETHEUS_AVAILABLE

        # Should be a boolean
        assert isinstance(PROMETHEUS_AVAILABLE, bool)


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = AsyncMock()
        redis.xlen = AsyncMock(return_value=10)
        redis.xpending = AsyncMock(return_value={"pending": 5})
        return redis

    @pytest.mark.asyncio
    async def test_collect_queue_metrics(self, mock_redis):
        """MetricsCollector collects queue metrics."""
        from amprealize.execution_metrics import MetricsCollector, PROMETHEUS_AVAILABLE

        collector = MetricsCollector(
            redis_client=mock_redis,
            stream_prefix="amprealize:executions",
            consumer_group="test-workers",
        )

        # Should not error
        await collector.collect()

        # Should call xlen for each priority if prometheus is available
        if PROMETHEUS_AVAILABLE:
            assert mock_redis.xlen.call_count == 3
        else:
            # When prometheus not available, collect returns early
            assert mock_redis.xlen.call_count == 0

    @pytest.mark.asyncio
    async def test_collect_handles_errors(self, mock_redis):
        """MetricsCollector handles Redis errors gracefully."""
        from amprealize.execution_metrics import MetricsCollector

        mock_redis.xlen = AsyncMock(side_effect=Exception("Redis down"))

        collector = MetricsCollector(redis_client=mock_redis)

        # Should not raise
        await collector.collect()


class TestMetricsWithPrometheus:
    """Tests that verify metrics work with prometheus_client."""

    @pytest.fixture
    def prometheus_available(self):
        """Check if prometheus_client is installed."""
        try:
            import prometheus_client
            return True
        except ImportError:
            pytest.skip("prometheus_client not installed")
            return False

    def test_jobs_processed_counter(self, prometheus_available):
        """JOBS_PROCESSED counter increments."""
        from amprealize.execution_metrics import PROMETHEUS_AVAILABLE

        if PROMETHEUS_AVAILABLE:
            from amprealize.execution_metrics import JOBS_PROCESSED

            # Get initial value
            initial = JOBS_PROCESSED.labels(
                status="success", scope="test:1"
            )._value.get()

            # Increment
            JOBS_PROCESSED.labels(status="success", scope="test:1").inc()

            # Check incremented
            final = JOBS_PROCESSED.labels(
                status="success", scope="test:1"
            )._value.get()

            assert final == initial + 1

    def test_jobs_in_progress_gauge(self, prometheus_available):
        """JOBS_IN_PROGRESS gauge sets value."""
        from amprealize.execution_metrics import PROMETHEUS_AVAILABLE

        if PROMETHEUS_AVAILABLE:
            from amprealize.execution_metrics import JOBS_IN_PROGRESS

            JOBS_IN_PROGRESS.labels(worker_id="test-worker").set(5)
            value = JOBS_IN_PROGRESS.labels(worker_id="test-worker")._value.get()

            assert value == 5

    def test_job_duration_histogram(self, prometheus_available):
        """JOB_DURATION histogram observes values."""
        from amprealize.execution_metrics import PROMETHEUS_AVAILABLE

        if PROMETHEUS_AVAILABLE:
            from amprealize.execution_metrics import JOB_DURATION

            # Observe a duration
            JOB_DURATION.labels(scope="test:1").observe(45.5)

            # Should not error (histogram internally tracks sum and count)
            sum_val = JOB_DURATION.labels(scope="test:1")._sum.get()
            assert sum_val >= 45.5
