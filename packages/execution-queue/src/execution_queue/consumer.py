"""Queue consumer for processing execution jobs.

Uses Redis Streams XREADGROUP for reliable, at-least-once delivery
with consumer groups for horizontal scaling.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional

import redis.asyncio as redis

from execution_queue.models import ExecutionJob, ExecutionResult, ExecutionStatus, Priority

logger = logging.getLogger(__name__)

# Type alias for job handler
JobHandler = Callable[[ExecutionJob], Awaitable[ExecutionResult]]


class ExecutionQueueConsumer:
    """Consumes execution jobs from Redis Streams.

    Uses consumer groups (XREADGROUP) for:
    - At-least-once delivery
    - Horizontal scaling across workers
    - Pending message recovery on restart

    Workers are expected to:
    1. Claim a job via consume()
    2. Process it (provision workspace, run agent, cleanup)
    3. Call ack() on success or nack() on failure

    Example:
        consumer = ExecutionQueueConsumer(
            redis_url="redis://localhost:6379",
            consumer_group="execution-workers",
            consumer_name="worker-1",
        )

        async def handle(job: ExecutionJob) -> ExecutionResult:
            # ... execute ...
            return ExecutionResult(...)

        await consumer.consume(handle)
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        redis_client: Optional[redis.Redis] = None,
        consumer_group: str = "execution-workers",
        consumer_name: Optional[str] = None,
        group_name: Optional[str] = None,
        worker_id: Optional[str] = None,
        stream_prefix: str = "amprealize:executions",
        block_ms: int = 5000,
        batch_size: int = 1,
        max_retries: int = 3,
    ):
        """Initialize the consumer.

        Args:
            redis_url: Redis connection URL
            redis_client: Existing Redis client
            consumer_group: Consumer group name for XREADGROUP
            consumer_name: Unique name for this consumer (default: auto-generated)
            group_name: Backward-compatible alias for consumer_group
            worker_id: Backward-compatible alias for consumer_name
            stream_prefix: Prefix for stream keys
            block_ms: Milliseconds to block waiting for messages
            batch_size: Max messages to read per XREADGROUP call
            max_retries: Max retries before sending to DLQ
        """
        if group_name is not None:
            consumer_group = group_name
        if worker_id is not None:
            consumer_name = worker_id

        self._redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._redis: Optional[redis.Redis] = redis_client
        self._owns_redis = redis_client is None
        self._consumer_group = consumer_group
        self._consumer_name = consumer_name or f"worker-{os.getpid()}"
        self._stream_prefix = stream_prefix
        self._block_ms = block_ms
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._running = False
        self._current_job: Optional[ExecutionJob] = None
        self._claimed_messages: Dict[str, tuple[str, ExecutionJob]] = {}
        self._created_at = datetime.now(timezone.utc)

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

    def _get_dlq_key(self) -> str:
        """Get the dead letter queue stream key."""
        return f"{self._stream_prefix}:dlq"

    async def _ensure_consumer_groups(self) -> None:
        """Create consumer groups if they don't exist."""
        r = await self._get_redis()

        for priority in Priority:
            stream_key = self._get_stream_key(priority)
            try:
                # XGROUP CREATE with MKSTREAM creates stream if needed
                await r.xgroup_create(
                    stream_key,
                    self._consumer_group,
                    id="0",  # Read from beginning for new groups
                    mkstream=True,
                )
                logger.info(f"Created consumer group {self._consumer_group} on {stream_key}")
            except redis.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    # Group already exists, that's fine
                    pass
                else:
                    raise

    async def consume(
        self,
        handler: JobHandler,
        priorities: Optional[List[Priority]] = None,
    ) -> None:
        """Start consuming jobs from the queue.

        This is a blocking call that runs until stop() is called.
        Jobs are read in priority order (high → normal → low).

        Args:
            handler: Async function to process each job
            priorities: Which priorities to consume (default: all)
        """
        self._running = True
        priorities = priorities or [Priority.HIGH, Priority.NORMAL, Priority.LOW]

        await self._ensure_consumer_groups()

        # Build stream list for XREADGROUP (priority order)
        streams = {self._get_stream_key(p): ">" for p in priorities}

        logger.info(
            f"Consumer {self._consumer_name} starting",
            extra={
                "consumer_group": self._consumer_group,
                "streams": list(streams.keys()),
            },
        )

        # First, recover any pending messages from dead workers
        await self._recover_pending(handler, priorities)

        r = await self._get_redis()

        while self._running:
            try:
                # XREADGROUP with BLOCK for efficient polling
                # Returns: [[stream_key, [(message_id, {field: value}), ...]]]
                results = await r.xreadgroup(
                    self._consumer_group,
                    self._consumer_name,
                    streams,
                    count=self._batch_size,
                    block=self._block_ms,
                )

                if not results:
                    continue

                for stream_key, messages in results:
                    for message_id, data in messages:
                        await self._process_message(
                            handler,
                            stream_key,
                            message_id,
                            data,
                        )

            except asyncio.CancelledError:
                logger.info(f"Consumer {self._consumer_name} cancelled")
                break
            except redis.ConnectionError as e:
                logger.error(f"Redis connection error: {e}, reconnecting...")
                await asyncio.sleep(1)
                self._redis = None  # Force reconnect
            except Exception as e:
                logger.exception(f"Unexpected error in consumer loop: {e}")
                await asyncio.sleep(1)

        logger.info(f"Consumer {self._consumer_name} stopped")

    async def _process_message(
        self,
        handler: JobHandler,
        stream_key: bytes | str,
        message_id: bytes | str,
        data: dict,
    ) -> None:
        """Process a single message from the stream."""
        if isinstance(stream_key, bytes):
            stream_key = stream_key.decode("utf-8")
        if isinstance(message_id, bytes):
            message_id = message_id.decode("utf-8")

        try:
            job = ExecutionJob.from_dict(data)
            self._current_job = job

            logger.info(
                f"Processing job {job.job_id}",
                extra={
                    "job_id": job.job_id,
                    "run_id": job.run_id,
                    "stream": stream_key,
                    "message_id": message_id,
                    "retry_count": job.retry_count,
                },
            )

            # Execute the handler
            started_at = datetime.now(timezone.utc)
            result = await handler(job)

            # ACK on success
            if result.status == ExecutionStatus.SUCCESS:
                await self.ack(stream_key, message_id)
                logger.info(
                    f"Job {job.job_id} completed successfully",
                    extra={
                        "job_id": job.job_id,
                        "duration_seconds": result.duration_seconds,
                    },
                )
            else:
                # NACK on failure - will retry or move to DLQ
                await self.nack(
                    stream_key,
                    message_id,
                    job,
                    result.error_message or "Unknown error",
                )

        except Exception as e:
            logger.exception(f"Error processing job: {e}")
            # Try to NACK if we have job info
            if self._current_job:
                await self.nack(
                    stream_key,
                    message_id,
                    self._current_job,
                    str(e),
                )
        finally:
            self._current_job = None

    async def ack(self, stream_key: str, message_id: str) -> None:
        """Acknowledge successful processing of a message.

        Removes the message from the pending entries list.
        """
        r = await self._get_redis()
        await r.xack(stream_key, self._consumer_group, message_id)
        self._claimed_messages.pop(message_id, None)

    async def claim_job(
        self,
        timeout_ms: Optional[int] = None,
        priorities: Optional[List[Priority]] = None,
    ) -> Optional[ExecutionJob]:
        """Claim a single job from the queue.

        This preserves the older one-shot consumer API that integration tests and
        downstream callers still use.
        """
        await self._ensure_consumer_groups()
        priorities = priorities or [Priority.HIGH, Priority.NORMAL, Priority.LOW]
        r = await self._get_redis()
        deadline = None
        if timeout_ms is not None:
            deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)

        while True:
            streams = {self._get_stream_key(priority): ">" for priority in priorities}
            block_ms = self._block_ms if deadline is None else max(1, int((deadline - asyncio.get_running_loop().time()) * 1000))
            if deadline is not None and block_ms <= 0:
                return None

            results = await r.xreadgroup(
                self._consumer_group,
                self._consumer_name,
                streams,
                count=1,
                block=block_ms,
            )
            if not results:
                return None

            for stream_key, messages in results:
                if not messages:
                    continue

                for message_id, data in messages:
                    stream_name = stream_key.decode("utf-8") if isinstance(stream_key, bytes) else str(stream_key)
                    message_name = message_id.decode("utf-8") if isinstance(message_id, bytes) else str(message_id)
                    job = ExecutionJob.from_dict(data)

                    if job.submitted_at < self._created_at:
                        logger.info(
                            "Skipping stale job claimed by one-shot helper",
                            extra={
                                "job_id": job.job_id,
                                "stream": stream_name,
                                "message_id": message_name,
                                "submitted_at": job.submitted_at.isoformat(),
                                "consumer_created_at": self._created_at.isoformat(),
                            },
                        )
                        await self.ack(stream_name, message_name)
                        continue

                    self._current_job = job
                    self._claimed_messages[message_name] = (stream_name, job)
                    return job

            if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                return None

    async def ack_job(
        self,
        message_id: str,
        stream_key: str,
        result: ExecutionResult,
    ) -> None:
        """Acknowledge or requeue a previously claimed job.

        Backward-compatible helper used by older integration tests.
        """
        claimed = self._claimed_messages.get(message_id)
        job = claimed[1] if claimed is not None else self._current_job
        if result.status == ExecutionStatus.SUCCESS:
            await self.ack(stream_key, message_id)
            return
        if job is None:
            await self.ack(stream_key, message_id)
            return
        await self.nack(stream_key, message_id, job, result.error_message or "Unknown error")

    async def nack(
        self,
        stream_key: str,
        message_id: str,
        job: ExecutionJob,
        error: str,
    ) -> None:
        """Handle failed message processing.

        If retries remain, updates job and leaves it for reprocessing.
        Otherwise, moves to dead letter queue.
        """
        r = await self._get_redis()

        job.retry_count += 1
        job.last_error = error

        if job.retry_count >= self._max_retries:
            # Move to dead letter queue
            logger.warning(
                f"Job {job.job_id} exceeded max retries, moving to DLQ",
                extra={
                    "job_id": job.job_id,
                    "retry_count": job.retry_count,
                    "last_error": error,
                },
            )

            dlq_key = self._get_dlq_key()
            await r.xadd(dlq_key, job.to_dict())

            # ACK to remove from original stream
            await r.xack(stream_key, self._consumer_group, message_id)
            self._claimed_messages.pop(message_id, None)
        else:
            # Leave in pending for retry (will be picked up by recovery)
            logger.info(
                f"Job {job.job_id} failed, will retry ({job.retry_count}/{self._max_retries})",
                extra={
                    "job_id": job.job_id,
                    "retry_count": job.retry_count,
                    "error": error,
                },
            )

    async def _recover_pending(
        self,
        handler: JobHandler,
        priorities: List[Priority],
    ) -> None:
        """Recover pending messages from dead workers on startup.

        Claims messages that have been pending too long (worker died)
        and reprocesses them.
        """
        r = await self._get_redis()
        claim_min_idle_ms = 60000  # 1 minute idle = stale

        for priority in priorities:
            stream_key = self._get_stream_key(priority)

            try:
                # XAUTOCLAIM claims idle messages
                # Returns: (next_start_id, [(message_id, data), ...], [deleted_ids])
                while True:
                    result = await r.xautoclaim(
                        stream_key,
                        self._consumer_group,
                        self._consumer_name,
                        min_idle_time=claim_min_idle_ms,
                        start_id="0-0",
                        count=10,
                    )

                    if not result or len(result) < 2:
                        break

                    _, messages, *_ = result

                    if not messages:
                        break

                    for message_id, data in messages:
                        if data:  # Skip deleted messages
                            logger.info(
                                f"Recovering pending message {message_id}",
                                extra={"stream": stream_key, "message_id": message_id},
                            )
                            await self._process_message(
                                handler,
                                stream_key,
                                message_id,
                                data,
                            )

            except redis.ResponseError as e:
                if "NOGROUP" in str(e):
                    # Consumer group doesn't exist, will be created
                    pass
                else:
                    logger.warning(f"Error recovering pending messages: {e}")

    def stop(self) -> None:
        """Signal the consumer to stop after current job."""
        self._running = False

    @property
    def current_job(self) -> Optional[ExecutionJob]:
        """Get the job currently being processed, if any."""
        return self._current_job


def create_signal_handler(consumer: ExecutionQueueConsumer) -> Callable:
    """Create a signal handler for graceful shutdown."""
    def handler(signum: int, frame: any) -> None:
        logger.info(f"Received signal {signum}, stopping consumer...")
        consumer.stop()
    return handler
