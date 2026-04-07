"""Dead letter queue handling.

Manages jobs that have exceeded retry limits, providing:
- DLQ inspection and stats
- Manual retry/requeue
- Purging old entries
"""

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import redis.asyncio as redis

from execution_queue.models import ExecutionJob, Priority

logger = logging.getLogger(__name__)


class DeadLetterHandler:
    """Handles dead letter queue operations.

    Jobs that exceed max retries are moved to the DLQ for:
    - Manual inspection and debugging
    - Manual retry after fixing issues
    - Purging after retention period

    Example:
        dlq = DeadLetterHandler(redis_url="redis://localhost:6379")

        # Get failed jobs
        jobs = await dlq.list_jobs(limit=10)

        # Retry a job
        await dlq.retry_job(job_id, priority=Priority.HIGH)

        # Purge old entries
        await dlq.purge(older_than_hours=24)
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        redis_client: Optional[redis.Redis] = None,
        stream_prefix: str = "amprealize:executions",
    ):
        """Initialize the handler.

        Args:
            redis_url: Redis connection URL
            redis_client: Existing Redis client
            stream_prefix: Prefix for stream keys
        """
        self._redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._redis: Optional[redis.Redis] = redis_client
        self._owns_redis = redis_client is None
        self._stream_prefix = stream_prefix

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

    def _get_dlq_key(self) -> str:
        """Get the dead letter queue stream key."""
        return f"{self._stream_prefix}:dlq"

    def _get_stream_key(self, priority: Priority) -> str:
        """Get stream key for a priority."""
        return f"{self._stream_prefix}:{priority.value}"

    async def get_count(self) -> int:
        """Get number of jobs in the DLQ."""
        r = await self._get_redis()
        return await r.xlen(self._get_dlq_key())

    async def list_jobs(
        self,
        limit: int = 100,
        start_id: str = "-",
        end_id: str = "+",
    ) -> List[Tuple[str, ExecutionJob]]:
        """List jobs in the DLQ.

        Args:
            limit: Max jobs to return
            start_id: Start reading from this ID (- for oldest)
            end_id: Stop reading at this ID (+ for newest)

        Returns:
            List of (message_id, job) tuples
        """
        r = await self._get_redis()
        dlq_key = self._get_dlq_key()

        entries = await r.xrange(dlq_key, min=start_id, max=end_id, count=limit)

        jobs = []
        for message_id, data in entries:
            if isinstance(message_id, bytes):
                message_id = message_id.decode("utf-8")
            job = ExecutionJob.from_dict(data)
            jobs.append((message_id, job))

        return jobs

    async def get_job(self, message_id: str) -> Optional[ExecutionJob]:
        """Get a specific job from the DLQ.

        Args:
            message_id: The Redis stream message ID

        Returns:
            The job, or None if not found
        """
        r = await self._get_redis()
        dlq_key = self._get_dlq_key()

        entries = await r.xrange(dlq_key, min=message_id, max=message_id, count=1)

        if entries:
            _, data = entries[0]
            return ExecutionJob.from_dict(data)

        return None

    async def retry_job(
        self,
        message_id: str,
        priority: Optional[Priority] = None,
        reset_retry_count: bool = True,
    ) -> Optional[str]:
        """Retry a job from the DLQ.

        Moves the job back to the appropriate priority queue
        and removes it from the DLQ.

        Args:
            message_id: DLQ message ID to retry
            priority: Override priority (default: use job's original)
            reset_retry_count: Reset retry count to 0

        Returns:
            New message ID in priority queue, or None if job not found
        """
        r = await self._get_redis()
        dlq_key = self._get_dlq_key()

        # Get the job
        job = await self.get_job(message_id)
        if not job:
            logger.warning(f"Job not found in DLQ: {message_id}")
            return None

        # Update for retry
        if reset_retry_count:
            job.retry_count = 0
            job.last_error = None

        # Determine target queue
        target_priority = priority or job.priority
        target_key = self._get_stream_key(target_priority)

        # Add to priority queue
        new_id = await r.xadd(target_key, job.to_dict())
        if isinstance(new_id, bytes):
            new_id = new_id.decode("utf-8")

        # Remove from DLQ
        await r.xdel(dlq_key, message_id)

        logger.info(
            f"Retried job from DLQ",
            extra={
                "job_id": job.job_id,
                "dlq_message_id": message_id,
                "new_message_id": new_id,
                "priority": target_priority.value,
            },
        )

        return new_id

    async def delete_job(self, message_id: str) -> bool:
        """Delete a job from the DLQ.

        Args:
            message_id: DLQ message ID to delete

        Returns:
            True if deleted, False if not found
        """
        r = await self._get_redis()
        dlq_key = self._get_dlq_key()

        deleted = await r.xdel(dlq_key, message_id)
        return deleted > 0

    async def purge(
        self,
        older_than_hours: int = 24,
    ) -> int:
        """Purge old jobs from the DLQ.

        Args:
            older_than_hours: Delete jobs older than this

        Returns:
            Number of jobs purged
        """
        r = await self._get_redis()
        dlq_key = self._get_dlq_key()

        # Calculate cutoff timestamp
        # Redis stream IDs are timestamp-based: <milliseconds>-<sequence>
        cutoff_ms = int(
            (datetime.now(timezone.utc).timestamp() - older_than_hours * 3600) * 1000
        )
        cutoff_id = f"{cutoff_ms}-0"

        # XTRIM MINID to remove entries older than cutoff
        # Note: XTRIM doesn't support MINID directly, use XRANGE + XDEL
        entries = await r.xrange(dlq_key, min="-", max=cutoff_id)

        if not entries:
            return 0

        message_ids = [entry[0] for entry in entries]
        # XDEL each entry
        deleted = 0
        for mid in message_ids:
            deleted += await r.xdel(dlq_key, mid)

        logger.info(
            f"Purged {deleted} jobs from DLQ",
            extra={"older_than_hours": older_than_hours},
        )

        return deleted

    async def get_stats(self) -> dict:
        """Get DLQ statistics.

        Returns:
            Dict with count, oldest entry, newest entry, etc.
        """
        r = await self._get_redis()
        dlq_key = self._get_dlq_key()

        count = await r.xlen(dlq_key)

        # Get oldest and newest
        oldest = await r.xrange(dlq_key, count=1)
        newest = await r.xrevrange(dlq_key, count=1)

        oldest_id = oldest[0][0].decode() if oldest else None
        newest_id = newest[0][0].decode() if newest else None

        # Parse timestamps from IDs
        def parse_timestamp(msg_id: Optional[str]) -> Optional[datetime]:
            if not msg_id:
                return None
            ts_ms = int(msg_id.split("-")[0])
            return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

        return {
            "count": count,
            "oldest_id": oldest_id,
            "newest_id": newest_id,
            "oldest_timestamp": parse_timestamp(oldest_id),
            "newest_timestamp": parse_timestamp(newest_id),
        }
