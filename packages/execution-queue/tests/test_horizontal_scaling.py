"""Tests for horizontal scaling scenarios.

These tests verify that the execution queue and worker infrastructure
supports horizontal scaling with multiple workers.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add execution-queue package to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from execution_queue import (
    ExecutionJob,
    ExecutionQueueConsumer,
    ExecutionResult,
    ExecutionStatus,
    Priority,
)


class TestConsumerGroups:
    """Tests for consumer group functionality."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = AsyncMock()
        redis.xgroup_create = AsyncMock()
        redis.xreadgroup = AsyncMock(return_value=[])
        redis.xack = AsyncMock()
        redis.xautoclaim = AsyncMock(return_value=(None, [], []))
        return redis

    @pytest.mark.asyncio
    async def test_consumer_creates_groups_on_start(self, mock_redis):
        """Consumer creates consumer groups for all priorities."""
        consumer = ExecutionQueueConsumer(
            redis_client=mock_redis,
            consumer_group="test-workers",
            consumer_name="worker-1",
        )

        await consumer._ensure_consumer_groups()

        # Should create groups for high, normal, low priorities
        assert mock_redis.xgroup_create.call_count == 3

    @pytest.mark.asyncio
    async def test_consumer_handles_existing_groups(self, mock_redis):
        """Consumer handles BUSYGROUP error gracefully."""
        from redis import ResponseError

        mock_redis.xgroup_create = AsyncMock(
            side_effect=ResponseError("BUSYGROUP Consumer Group name already exists")
        )

        consumer = ExecutionQueueConsumer(
            redis_client=mock_redis,
            consumer_group="test-workers",
        )

        # Should not raise
        await consumer._ensure_consumer_groups()

    def test_consumer_auto_generates_name(self):
        """Consumer generates unique name if not provided."""
        consumer1 = ExecutionQueueConsumer(redis_url="redis://localhost")
        consumer2 = ExecutionQueueConsumer(redis_url="redis://localhost")

        # Should be unique (includes PID)
        assert "worker-" in consumer1._consumer_name
        assert consumer1._consumer_name == consumer2._consumer_name  # Same PID

    def test_consumer_accepts_custom_name(self):
        """Consumer accepts custom consumer name."""
        consumer = ExecutionQueueConsumer(
            redis_url="redis://localhost",
            consumer_name="my-worker-1",
        )

        assert consumer._consumer_name == "my-worker-1"

    def test_consumer_accepts_custom_group(self):
        """Consumer accepts custom consumer group."""
        consumer = ExecutionQueueConsumer(
            redis_url="redis://localhost",
            consumer_group="my-workers",
        )

        assert consumer._consumer_group == "my-workers"


class TestMultipleConsumers:
    """Tests simulating multiple consumers in a group."""

    @pytest.fixture
    def sample_job(self):
        """Create a sample job."""
        return ExecutionJob(
            job_id="job-1",
            run_id="run-1",
            work_item_id="wi-1",
            agent_id="agent-1",
            user_id="user-1",
            priority=Priority.NORMAL,
            timeout_seconds=300,
        )

    def test_consumers_can_share_group(self):
        """Multiple consumers can share the same group."""
        consumer1 = ExecutionQueueConsumer(
            redis_url="redis://localhost",
            consumer_group="shared-workers",
            consumer_name="worker-1",
        )
        consumer2 = ExecutionQueueConsumer(
            redis_url="redis://localhost",
            consumer_group="shared-workers",
            consumer_name="worker-2",
        )

        # Same group, different names
        assert consumer1._consumer_group == consumer2._consumer_group
        assert consumer1._consumer_name != consumer2._consumer_name

    def test_consumers_can_use_different_groups(self):
        """Consumers can use different groups for isolation."""
        consumer1 = ExecutionQueueConsumer(
            redis_url="redis://localhost",
            consumer_group="tenant-a-workers",
        )
        consumer2 = ExecutionQueueConsumer(
            redis_url="redis://localhost",
            consumer_group="tenant-b-workers",
        )

        assert consumer1._consumer_group != consumer2._consumer_group


class TestPendingRecovery:
    """Tests for pending message recovery."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = AsyncMock()
        redis.xgroup_create = AsyncMock()
        redis.xreadgroup = AsyncMock(return_value=[])
        redis.xack = AsyncMock()
        redis.xautoclaim = AsyncMock(return_value=(None, [], []))
        return redis

    @pytest.mark.asyncio
    async def test_recovery_claims_idle_messages(self, mock_redis):
        """Recovery claims messages that have been idle too long."""
        from redis import ResponseError

        # Simulate stale messages
        stale_job = ExecutionJob(
            job_id="stale-1",
            run_id="run-stale",
            work_item_id="wi-1",
            agent_id="agent-1",
            user_id="user-1",
            project_id="proj-1",
            priority=Priority.NORMAL,
            timeout_seconds=300,
        )

        mock_redis.xautoclaim = AsyncMock(
            side_effect=[
                (None, [("msg-1", stale_job.to_dict())], []),
                (None, [], []),
            ]
        )

        handler_called = []

        async def handler(job):
            handler_called.append(job.job_id)
            return ExecutionResult(
                job_id=job.job_id,
                run_id=job.run_id,
                status=ExecutionStatus.SUCCESS,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )

        consumer = ExecutionQueueConsumer(
            redis_client=mock_redis,
            consumer_group="test-workers",
        )

        # Mock the group creation to not fail
        mock_redis.xgroup_create = AsyncMock(
            side_effect=ResponseError("BUSYGROUP")
        )

        await consumer._recover_pending(handler, [Priority.NORMAL])

        # Should have processed the stale job
        assert "stale-1" in handler_called

    @pytest.mark.asyncio
    async def test_recovery_handles_no_pending(self, mock_redis):
        """Recovery handles case with no pending messages."""
        mock_redis.xautoclaim = AsyncMock(return_value=(None, [], []))

        handler = AsyncMock()

        consumer = ExecutionQueueConsumer(
            redis_client=mock_redis,
            consumer_group="test-workers",
        )

        # Should not raise
        await consumer._recover_pending(handler, [Priority.NORMAL])

        # Handler should not be called
        handler.assert_not_called()


class TestConsumerStopBehavior:
    """Tests for graceful consumer shutdown."""

    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.xgroup_create = AsyncMock()
        redis.xreadgroup = AsyncMock(return_value=[])
        redis.xautoclaim = AsyncMock(return_value=(None, [], []))
        redis.close = AsyncMock()
        return redis

    def test_stop_sets_flag(self, mock_redis):
        """stop() sets the _running flag to False."""
        consumer = ExecutionQueueConsumer(redis_client=mock_redis)
        consumer._running = True

        consumer.stop()

        assert consumer._running is False

    @pytest.mark.asyncio
    async def test_close_releases_redis(self, mock_redis):
        """close() releases Redis connection."""
        consumer = ExecutionQueueConsumer(redis_client=mock_redis)
        consumer._owns_redis = True
        consumer._redis = mock_redis

        await consumer.close()

        mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_skips_injected_redis(self, mock_redis):
        """close() doesn't close injected Redis client."""
        consumer = ExecutionQueueConsumer(redis_client=mock_redis)
        # When redis_client is passed, _owns_redis is False
        consumer._owns_redis = False

        await consumer.close()

        mock_redis.close.assert_not_called()


class TestConsumerPriorityOrdering:
    """Tests for priority-ordered consumption."""

    def test_default_priorities(self):
        """Consumer consumes all priorities by default."""
        consumer = ExecutionQueueConsumer(redis_url="redis://localhost")

        # Default stream prefix
        assert consumer._stream_prefix == "amprealize:executions"

        # Check stream keys are generated correctly
        assert consumer._get_stream_key(Priority.HIGH) == "amprealize:executions:high"
        assert consumer._get_stream_key(Priority.NORMAL) == "amprealize:executions:normal"
        assert consumer._get_stream_key(Priority.LOW) == "amprealize:executions:low"

    def test_custom_stream_prefix(self):
        """Consumer accepts custom stream prefix."""
        consumer = ExecutionQueueConsumer(
            redis_url="redis://localhost",
            stream_prefix="tenant-a:executions",
        )

        assert consumer._get_stream_key(Priority.HIGH) == "tenant-a:executions:high"

    def test_dlq_key(self):
        """Consumer has correct DLQ key."""
        consumer = ExecutionQueueConsumer(
            redis_url="redis://localhost",
            stream_prefix="amprealize:executions",
        )

        assert consumer._get_dlq_key() == "amprealize:executions:dlq"


class TestWorkerScalingPatterns:
    """Integration-style tests for worker scaling patterns."""

    def test_worker_config_from_env(self):
        """WorkerConfig loads from environment variables."""
        from amprealize.execution_worker import WorkerConfig

        with patch.dict(os.environ, {
            "REDIS_URL": "redis://custom:6379",
            "EXECUTION_CONSUMER_GROUP": "my-workers",
            "EXECUTION_CONSUMER_NAME": "worker-5",
            "HEARTBEAT_INTERVAL": "15",
        }):
            config = WorkerConfig.from_env()

            assert config.redis_url == "redis://custom:6379"
            assert config.consumer_group == "my-workers"
            assert config.consumer_name == "worker-5"
            assert config.heartbeat_interval_seconds == 15

    def test_worker_default_config(self):
        """WorkerConfig has sensible defaults."""
        from amprealize.execution_worker import WorkerConfig

        config = WorkerConfig()

        assert config.consumer_group == "execution-workers"
        assert config.heartbeat_interval_seconds == 30
        assert config.max_retries == 3
        assert config.provision_workspace is True
