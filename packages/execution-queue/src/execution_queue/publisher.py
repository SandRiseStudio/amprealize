"""Queue publisher for enqueuing execution jobs.

Uses Redis Streams XADD to publish jobs to priority-based streams.
Supports tenant-aware priority boosting and backpressure monitoring.
"""

import logging
import os
from typing import Optional, TYPE_CHECKING

import redis.asyncio as redis

from execution_queue.models import ExecutionJob, Priority

if TYPE_CHECKING:
    from breakeramp.quota import QuotaService

logger = logging.getLogger(__name__)


class ExecutionQueuePublisher:
    """Publishes execution jobs to Redis Streams.

    Jobs are published to priority-specific streams:
    - amprealize:executions:high
    - amprealize:executions:normal
    - amprealize:executions:low

    Example:
        publisher = ExecutionQueuePublisher(redis_url="redis://localhost:6379")
        job = ExecutionJob.create(...)
        message_id = await publisher.enqueue(job)
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        redis_client: Optional[redis.Redis] = None,
        stream_prefix: str = "amprealize:executions",
        max_stream_length: int = 100000,
    ):
        """Initialize the publisher.

        Args:
            redis_url: Redis connection URL (default from REDIS_URL env)
            redis_client: Existing Redis client (takes precedence over URL)
            stream_prefix: Prefix for stream keys
            max_stream_length: Max entries per stream (older trimmed)
        """
        self._redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._redis: Optional[redis.Redis] = redis_client
        self._owns_redis = redis_client is None
        self._stream_prefix = stream_prefix
        self._max_stream_length = max_stream_length

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = redis.from_url(self._redis_url, decode_responses=False)
        return self._redis

    async def close(self) -> None:
        """Close Redis connection if we own it."""
        if self._redis and self._owns_redis:
            await self._redis.close()
            self._redis = None

    def _get_stream_key(self, priority: Priority) -> str:
        """Get the stream key for a priority level."""
        return f"{self._stream_prefix}:{priority.value}"

    async def enqueue(
        self,
        job: ExecutionJob,
        priority_override: Optional[Priority] = None,
    ) -> str:
        """Enqueue a job to the appropriate priority stream.

        Args:
            job: The execution job to enqueue
            priority_override: Override job's priority (for tenant boost)

        Returns:
            The Redis stream message ID

        Raises:
            redis.RedisError: If Redis operation fails
        """
        r = await self._get_redis()

        priority = priority_override or job.priority
        stream_key = self._get_stream_key(priority)

        # Serialize job to dictionary for Redis
        job_data = job.to_dict()

        # XADD with MAXLEN to prevent unbounded growth
        # Use ~ for approximate trimming (faster)
        message_id = await r.xadd(
            stream_key,
            job_data,
            maxlen=self._max_stream_length,
            approximate=True,
        )

        # Decode message_id if bytes
        if isinstance(message_id, bytes):
            message_id = message_id.decode("utf-8")

        logger.info(
            "Enqueued job",
            extra={
                "job_id": job.job_id,
                "run_id": job.run_id,
                "stream": stream_key,
                "message_id": message_id,
                "priority": priority.value,
                "scope": job.get_isolation_scope(),
            },
        )

        return message_id

    async def enqueue_with_tenant_boost(
        self,
        job: ExecutionJob,
        tenant_plan: str = "free",
    ) -> str:
        """Enqueue job with priority boost based on tenant plan.

        Higher-tier tenants get priority boosts:
        - enterprise: LOW → NORMAL, NORMAL → HIGH
        - pro: LOW → NORMAL
        - free: no boost

        Args:
            job: The execution job
            tenant_plan: Tenant's billing plan

        Returns:
            The Redis stream message ID
        """
        boosted_priority = self._apply_tenant_boost(job.priority, tenant_plan)
        return await self.enqueue(job, priority_override=boosted_priority)

    async def enqueue_with_quota_boost(
        self,
        job: ExecutionJob,
        quota_service: "QuotaService",
    ) -> str:
        """Enqueue job with priority boost from QuotaService.

        Resolves tenant's plan automatically and applies appropriate boost.
        This is the preferred method for production use.

        Args:
            job: The execution job
            quota_service: QuotaService for resolving limits

        Returns:
            The Redis stream message ID
        """
        # Get priority boost from quota service
        boost = await quota_service.get_priority_boost(
            user_id=job.user_id,
            org_id=job.org_id,
        )

        # Apply boost to priority
        boosted_priority = self._apply_priority_boost(job.priority, boost)

        logger.info(
            "Applying priority boost",
            extra={
                "job_id": job.job_id,
                "original_priority": job.priority.value,
                "boosted_priority": boosted_priority.value,
                "boost": boost,
                "scope": job.get_isolation_scope(),
            },
        )

        return await self.enqueue(job, priority_override=boosted_priority)

    def _apply_priority_boost(self, priority: Priority, boost: int) -> Priority:
        """Apply numeric boost to priority level.

        Priority values: LOW=0, NORMAL=1, HIGH=2
        Boost is added to current priority (clamped to valid range).

        Args:
            priority: Original priority
            boost: Integer boost value (0-5 typical)

        Returns:
            Boosted priority level
        """
        if boost <= 0:
            return priority

        # Priority enum values: low=0, normal=1, high=2
        priorities = [Priority.LOW, Priority.NORMAL, Priority.HIGH]
        current_idx = priorities.index(priority)
        boosted_idx = min(current_idx + boost, len(priorities) - 1)
        return priorities[boosted_idx]

    def _apply_tenant_boost(self, priority: Priority, tenant_plan: str) -> Priority:
        """Apply tenant-based priority boost."""
        if tenant_plan == "enterprise":
            if priority == Priority.LOW:
                return Priority.NORMAL
            if priority == Priority.NORMAL:
                return Priority.HIGH
        elif tenant_plan == "pro":
            if priority == Priority.LOW:
                return Priority.NORMAL
        return priority

    async def get_queue_depth(self, priority: Priority) -> int:
        """Get the current depth of a priority queue.

        Args:
            priority: Which priority queue to check

        Returns:
            Number of messages in the stream
        """
        r = await self._get_redis()
        stream_key = self._get_stream_key(priority)
        return await r.xlen(stream_key)

    async def get_all_queue_depths(self) -> dict[Priority, int]:
        """Get depths for all priority queues.

        Returns:
            Dict mapping priority to message count
        """
        r = await self._get_redis()
        depths = {}
        for priority in Priority:
            stream_key = self._get_stream_key(priority)
            depths[priority] = await r.xlen(stream_key)
        return depths

    async def get_pending_count(
        self,
        priority: Priority,
        consumer_group: str = "execution-workers",
    ) -> int:
        """Get count of messages claimed but not ACKed.

        This indicates jobs currently being processed by workers.

        Args:
            priority: Which priority queue
            consumer_group: Consumer group name

        Returns:
            Number of pending (in-progress) messages
        """
        r = await self._get_redis()
        stream_key = self._get_stream_key(priority)

        try:
            # XPENDING returns summary info
            info = await r.xpending(stream_key, consumer_group)
            if info and isinstance(info, dict):
                return info.get("pending", 0)
            elif info and isinstance(info, (list, tuple)) and len(info) > 0:
                return info[0] if isinstance(info[0], int) else 0
            return 0
        except redis.ResponseError:
            # Consumer group doesn't exist yet
            return 0
