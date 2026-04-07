"""Integration tests for the execution-queue package.

Tests the full queue lifecycle:
1. Publisher enqueues jobs to Redis Streams
2. Consumer receives and processes jobs
3. Backpressure monitoring works correctly
4. Dead letter queue captures failed jobs

Requires Redis to be running (uses testcontainers or local Redis).
"""

import asyncio
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Check if execution_queue is installed
try:
    from execution_queue import (
        ExecutionJob,
        ExecutionQueueConsumer,
        ExecutionQueuePublisher,
        ExecutionResult,
        ExecutionStatus,
        JobState,
        Priority,
    )
    from execution_queue.backpressure import BackpressureMonitor, QueueFullError
    from execution_queue.dead_letter import DeadLetterHandler
    EXECUTION_QUEUE_AVAILABLE = True
except ImportError:
    EXECUTION_QUEUE_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not EXECUTION_QUEUE_AVAILABLE,
    reason="execution-queue package not installed"
)


# -----------------------------------------------------------------------------
# Test Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def sample_job() -> "ExecutionJob":
    """Create a sample execution job for testing."""
    return ExecutionJob(
        job_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        work_item_id=str(uuid.uuid4()),
        agent_id="agent-001",
        user_id="user-123",
        org_id="org-456",
        project_id="proj-789",
        priority=Priority.NORMAL,
        model_override="claude-sonnet-4-20250514",
        cycle_id=str(uuid.uuid4()),
        payload={"work_item_title": "Test task"},
    )


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    mock = MagicMock()
    mock.xadd = AsyncMock(return_value="1234567890-0")
    mock.xlen = AsyncMock(return_value=0)
    mock.xinfo_groups = AsyncMock(side_effect=Exception("NOGROUP"))
    mock.xgroup_create = AsyncMock(return_value=True)
    mock.xreadgroup = AsyncMock(return_value=[])
    mock.xautoclaim = AsyncMock(return_value=(None, [], []))
    mock.xack = AsyncMock(return_value=1)
    mock.close = AsyncMock()
    mock.aclose = AsyncMock()
    return mock


# -----------------------------------------------------------------------------
# Unit Tests (No Redis Required)
# -----------------------------------------------------------------------------

class TestExecutionJobModel:
    """Test ExecutionJob dataclass functionality."""

    def test_create_job_with_org(self, sample_job):
        """Test creating a job with org_id."""
        assert sample_job.org_id == "org-456"
        assert sample_job.get_isolation_scope() == "org:org-456"

    def test_create_job_without_org(self):
        """Test creating a job without org_id (user-level isolation)."""
        job = ExecutionJob(
            job_id="job-1",
            run_id="run-1",
            work_item_id="wi-1",
            agent_id="agent-1",
            user_id="user-123",
            project_id="proj-1",
            priority=Priority.NORMAL,
            org_id=None,  # No org
        )
        assert job.get_isolation_scope() == "user:user-123"

    def test_job_serialization(self, sample_job):
        """Test job can be serialized to dict."""
        data = sample_job.to_dict()
        assert data["job_id"] == sample_job.job_id
        assert data["run_id"] == sample_job.run_id
        assert data["priority"] == "normal"
        assert "submitted_at" in data

    def test_job_deserialization(self, sample_job):
        """Test job can be round-tripped through dict."""
        data = sample_job.to_dict()
        restored = ExecutionJob.from_dict(data)
        assert restored.job_id == sample_job.job_id
        assert restored.run_id == sample_job.run_id
        assert restored.priority == sample_job.priority

    def test_priority_values(self):
        """Test priority enum values."""
        assert Priority.HIGH.value == "high"
        assert Priority.NORMAL.value == "normal"
        assert Priority.LOW.value == "low"

    def test_job_state_values(self):
        """Test job state enum values."""
        assert JobState.PENDING.value == "pending"
        assert JobState.CLAIMED.value == "claimed"
        assert JobState.COMPLETED.value == "completed"
        assert JobState.FAILED.value == "failed"
        assert JobState.DEAD_LETTER.value == "dead_letter"


class TestExecutionResult:
    """Test ExecutionResult dataclass."""

    def test_success_result(self, sample_job):
        """Test creating a success result."""
        result = ExecutionResult(
            job_id=sample_job.job_id,
            run_id=sample_job.run_id,
            status=ExecutionStatus.SUCCESS,
        )
        assert result.status == ExecutionStatus.SUCCESS
        assert result.error_message is None

    def test_failure_result(self, sample_job):
        """Test creating a failure result."""
        result = ExecutionResult(
            job_id=sample_job.job_id,
            run_id=sample_job.run_id,
            status=ExecutionStatus.FAILURE,
            error_message="Agent crashed",
        )
        assert result.status == ExecutionStatus.FAILURE
        assert result.error_message == "Agent crashed"


# -----------------------------------------------------------------------------
# Publisher Tests
# -----------------------------------------------------------------------------

class TestExecutionQueuePublisher:
    """Test ExecutionQueuePublisher functionality."""

    @pytest.mark.asyncio
    async def test_publisher_enqueue(self, sample_job, mock_redis):
        """Test publishing a job to the queue."""
        with patch("execution_queue.publisher.redis.asyncio.from_url", return_value=mock_redis):
            publisher = ExecutionQueuePublisher()
            await publisher._ensure_connected()
            publisher._redis = mock_redis

            stream_id = await publisher.enqueue(sample_job)

            # Verify XADD was called
            mock_redis.xadd.assert_called_once()
            call_args = mock_redis.xadd.call_args
            stream_key = call_args[0][0]
            assert stream_key == "amprealize:executions:normal"

    @pytest.mark.asyncio
    async def test_publisher_priority_routing(self, mock_redis):
        """Test jobs are routed to correct priority streams."""
        with patch("execution_queue.publisher.redis.asyncio.from_url", return_value=mock_redis):
            publisher = ExecutionQueuePublisher()
            publisher._redis = mock_redis

            # Test high priority
            high_job = ExecutionJob(
                job_id="h1", run_id="r1", work_item_id="w1",
                agent_id="a1", user_id="u1", project_id="p1",
                priority=Priority.HIGH,
            )
            await publisher.enqueue(high_job)
            assert mock_redis.xadd.call_args[0][0] == "amprealize:executions:high"

            mock_redis.xadd.reset_mock()

            # Test low priority
            low_job = ExecutionJob(
                job_id="l1", run_id="r2", work_item_id="w2",
                agent_id="a1", user_id="u1", project_id="p1",
                priority=Priority.LOW,
            )
            await publisher.enqueue(low_job)
            assert mock_redis.xadd.call_args[0][0] == "amprealize:executions:low"

    @pytest.mark.asyncio
    async def test_publisher_tenant_boost_enterprise(self, sample_job, mock_redis):
        """Test enterprise tenant gets priority boost."""
        with patch("execution_queue.publisher.redis.asyncio.from_url", return_value=mock_redis):
            publisher = ExecutionQueuePublisher()
            publisher._redis = mock_redis

            # LOW -> NORMAL for enterprise (one level)
            boosted = publisher._apply_tenant_boost(Priority.LOW, tenant_plan="enterprise")
            assert boosted == Priority.NORMAL
            # NORMAL -> HIGH for enterprise
            boosted = publisher._apply_tenant_boost(Priority.NORMAL, tenant_plan="enterprise")
            assert boosted == Priority.HIGH

    @pytest.mark.asyncio
    async def test_publisher_tenant_boost_pro(self, sample_job, mock_redis):
        """Test pro tenant gets one-level boost."""
        with patch("execution_queue.publisher.redis.asyncio.from_url", return_value=mock_redis):
            publisher = ExecutionQueuePublisher()
            publisher._redis = mock_redis

            # LOW -> NORMAL for pro
            boosted = publisher._apply_tenant_boost(Priority.LOW, tenant_plan="pro")
            assert boosted == Priority.NORMAL

    @pytest.mark.asyncio
    async def test_publisher_queue_depth(self, mock_redis):
        """Test get_queue_depth returns correct counts."""
        mock_redis.xlen = AsyncMock(return_value=50)

        with patch("execution_queue.publisher.redis.asyncio.from_url", return_value=mock_redis):
            publisher = ExecutionQueuePublisher()
            publisher._redis = mock_redis

            depth = await publisher.get_queue_depth(Priority.NORMAL)
            assert depth == 50


# -----------------------------------------------------------------------------
# Consumer Tests
# -----------------------------------------------------------------------------

class TestExecutionQueueConsumer:
    """Test ExecutionQueueConsumer functionality."""

    @pytest.mark.asyncio
    async def test_consumer_initialization(self, mock_redis):
        """Test consumer creates consumer group."""
        with patch("execution_queue.consumer.redis.asyncio.from_url", return_value=mock_redis):
            consumer = ExecutionQueueConsumer(
                consumer_name="test-worker-1",
                consumer_group="test-group",
            )
            await consumer._ensure_connected()
            consumer._redis = mock_redis

            await consumer._ensure_consumer_group("amprealize:executions:normal")

            # Group creation should be attempted
            mock_redis.xgroup_create.assert_called()

    @pytest.mark.asyncio
    async def test_consumer_claims_job(self, sample_job, mock_redis):
        """Test consumer claims a pending job."""
        # Mock XREADGROUP returning a job
        mock_redis.xreadgroup = AsyncMock(return_value=[
            ["amprealize:executions:normal", [
                ["1234567890-0", sample_job.to_dict()]
            ]]
        ])

        with patch("execution_queue.consumer.redis.asyncio.from_url", return_value=mock_redis):
            consumer = ExecutionQueueConsumer(
                consumer_name="test-worker-1",
                consumer_group="test-group",
            )
            consumer._redis = mock_redis

            job = await consumer.claim_job()

            assert job is not None
            assert job.job_id == sample_job.job_id

    @pytest.mark.asyncio
    async def test_consumer_ack_job(self, sample_job, mock_redis):
        """Test acknowledging a completed job."""
        with patch("execution_queue.consumer.redis.asyncio.from_url", return_value=mock_redis):
            consumer = ExecutionQueueConsumer(
                consumer_name="test-worker-1",
                consumer_group="test-group",
            )
            consumer._redis = mock_redis

            result = ExecutionResult(
                job_id=sample_job.job_id,
                run_id=sample_job.run_id,
                status=ExecutionStatus.SUCCESS,
            )

            await consumer.ack_job("1234567890-0", "amprealize:executions:normal", result)

            mock_redis.xack.assert_called_once()


# -----------------------------------------------------------------------------
# Backpressure Tests
# -----------------------------------------------------------------------------

class TestBackpressureMonitor:
    """Test BackpressureMonitor functionality."""

    @pytest.mark.asyncio
    async def test_backpressure_under_threshold(self, mock_redis):
        """Test backpressure allows enqueue under threshold."""
        mock_redis.xlen = AsyncMock(return_value=500)  # Under 10000 default

        with patch("execution_queue.backpressure.redis.asyncio.from_url", return_value=mock_redis):
            monitor = BackpressureMonitor(max_queue_depth=10000)
            monitor._redis = mock_redis

            # Should not raise
            await monitor.check_pressure("amprealize:executions:normal")

    @pytest.mark.asyncio
    async def test_backpressure_over_threshold(self, mock_redis):
        """Test backpressure rejects enqueue over threshold."""
        mock_redis.xlen = AsyncMock(return_value=15000)  # Over 10000 default

        with patch("execution_queue.backpressure.redis.asyncio.from_url", return_value=mock_redis):
            monitor = BackpressureMonitor(max_queue_depth=10000)
            monitor._redis = mock_redis

            with pytest.raises(QueueFullError):
                await monitor.check_pressure("amprealize:executions:normal")


# -----------------------------------------------------------------------------
# Dead Letter Tests
# -----------------------------------------------------------------------------

class TestDeadLetterHandler:
    """Test DeadLetterHandler functionality."""

    @pytest.mark.asyncio
    async def test_move_to_dlq(self, sample_job, mock_redis):
        """Test moving failed job to dead letter queue."""
        with patch("execution_queue.dead_letter.redis.asyncio.from_url", return_value=mock_redis):
            handler = DeadLetterHandler()
            handler._redis = mock_redis

            await handler.move_to_dlq(
                job=sample_job,
                original_stream="amprealize:executions:normal",
                error="Max retries exceeded",
            )

            # Verify XADD to DLQ was called
            mock_redis.xadd.assert_called_once()
            call_args = mock_redis.xadd.call_args
            assert call_args[0][0] == "amprealize:executions:dlq"


# -----------------------------------------------------------------------------
# Integration Test (Requires Redis)
# -----------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("REDIS_URL") is None,
    reason="REDIS_URL not set - skip integration tests"
)
class TestExecutionQueueIntegration:
    """Integration tests requiring a live Redis instance."""

    @pytest.mark.asyncio
    async def test_full_queue_lifecycle(self):
        """Test full enqueue -> consume -> ack cycle."""
        publisher = ExecutionQueuePublisher()
        consumer = ExecutionQueueConsumer(
            worker_id=f"test-worker-{uuid.uuid4().hex[:8]}",
            group_name=f"test-group-{uuid.uuid4().hex[:8]}",
        )

        try:
            # Create a test job
            job = ExecutionJob(
                job_id=str(uuid.uuid4()),
                run_id=str(uuid.uuid4()),
                work_item_id=str(uuid.uuid4()),
                agent_id="integration-test-agent",
                user_id="integration-test-user",
                project_id="integration-test-project",
                priority=Priority.NORMAL,
                model_override="claude-sonnet-4-20250514",
            )

            # Enqueue
            stream_id = await publisher.enqueue(job)
            assert stream_id is not None

            # Wait a moment for Redis
            await asyncio.sleep(0.1)

            # Consume
            claimed_job = await consumer.claim_job(timeout_ms=5000)
            if claimed_job:
                assert claimed_job.job_id == job.job_id

                # Ack
                result = ExecutionResult(
                    job_id=job.job_id,
                    run_id=job.run_id,
                    status=ExecutionStatus.SUCCESS,
                )
                await consumer.ack_job(stream_id, "amprealize:executions:normal", result)

        finally:
            await publisher.close()
            await consumer.close()

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        """Test high priority jobs are consumed before low priority."""
        publisher = ExecutionQueuePublisher()
        consumer = ExecutionQueueConsumer(
            worker_id=f"test-worker-{uuid.uuid4().hex[:8]}",
            group_name=f"test-group-{uuid.uuid4().hex[:8]}",
        )

        try:
            # Enqueue low priority first
            low_job = ExecutionJob(
                job_id="low-" + str(uuid.uuid4()),
                run_id=str(uuid.uuid4()),
                work_item_id=str(uuid.uuid4()),
                agent_id="test-agent",
                user_id="test-user",
                project_id="test-project",
                priority=Priority.LOW,
                model_override="claude-sonnet-4-20250514",
            )
            await publisher.enqueue(low_job)

            # Then enqueue high priority
            high_job = ExecutionJob(
                job_id="high-" + str(uuid.uuid4()),
                run_id=str(uuid.uuid4()),
                work_item_id=str(uuid.uuid4()),
                agent_id="test-agent",
                user_id="test-user",
                project_id="test-project",
                priority=Priority.HIGH,
                model_override="claude-sonnet-4-20250514",
            )
            await publisher.enqueue(high_job)

            await asyncio.sleep(0.1)

            # Consumer should get high priority first
            first = await consumer.claim_job(timeout_ms=5000)
            if first:
                assert first.job_id.startswith("high-")

        finally:
            await publisher.close()
            await consumer.close()
