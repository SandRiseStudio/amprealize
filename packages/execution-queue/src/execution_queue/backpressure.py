"""Backpressure monitoring for queue health.

Provides mechanisms to prevent queue overload by monitoring
depth and rejecting new jobs when at capacity.
"""

import logging
from typing import Dict, Optional

from execution_queue.models import Priority
from execution_queue.publisher import ExecutionQueuePublisher

logger = logging.getLogger(__name__)


class QueueFullError(Exception):
    """Raised when queue is at capacity and cannot accept new jobs."""

    def __init__(
        self,
        message: str = "Queue at capacity",
        priority: Optional[Priority] = None,
        current_depth: Optional[int] = None,
        max_depth: Optional[int] = None,
    ):
        super().__init__(message)
        self.priority = priority
        self.current_depth = current_depth
        self.max_depth = max_depth


class BackpressureMonitor:
    """Monitors queue depth and enforces backpressure limits.

    Prevents queue overload by tracking depth across priority levels
    and raising QueueFullError when limits are exceeded.

    Example:
        monitor = BackpressureMonitor(publisher, max_depth=1000)

        # Before enqueuing
        await monitor.check_capacity(Priority.NORMAL)  # Raises if full
        await publisher.enqueue(job)

        # Or use guarded enqueue
        await monitor.enqueue_with_backpressure(job)
    """

    def __init__(
        self,
        publisher: ExecutionQueuePublisher,
        max_depth_per_priority: Optional[Dict[Priority, int]] = None,
        max_total_depth: int = 10000,
    ):
        """Initialize the monitor.

        Args:
            publisher: Queue publisher to monitor
            max_depth_per_priority: Max depth per priority (default: 1000 each)
            max_total_depth: Max total depth across all priorities
        """
        self._publisher = publisher
        self._max_per_priority = max_depth_per_priority or {
            Priority.HIGH: 500,
            Priority.NORMAL: 1000,
            Priority.LOW: 2000,
        }
        self._max_total = max_total_depth

    async def check_capacity(self, priority: Priority) -> None:
        """Check if queue has capacity for a new job.

        Args:
            priority: The priority queue to check

        Raises:
            QueueFullError: If queue is at capacity
        """
        current = await self._publisher.get_queue_depth(priority)
        max_depth = self._max_per_priority.get(priority, 1000)

        if current >= max_depth:
            logger.warning(
                f"Queue {priority.value} at capacity",
                extra={
                    "priority": priority.value,
                    "current_depth": current,
                    "max_depth": max_depth,
                },
            )
            raise QueueFullError(
                f"Queue {priority.value} at capacity ({current}/{max_depth})",
                priority=priority,
                current_depth=current,
                max_depth=max_depth,
            )

    async def check_total_capacity(self) -> None:
        """Check if total queue depth is within limits.

        Raises:
            QueueFullError: If total queue depth exceeds limit
        """
        depths = await self._publisher.get_all_queue_depths()
        total = sum(depths.values())

        if total >= self._max_total:
            logger.warning(
                "Total queue depth at capacity",
                extra={
                    "total_depth": total,
                    "max_total": self._max_total,
                    "depths_by_priority": {p.value: d for p, d in depths.items()},
                },
            )
            raise QueueFullError(
                f"Total queue depth at capacity ({total}/{self._max_total})",
                current_depth=total,
                max_depth=self._max_total,
            )

    async def get_health_status(self) -> Dict:
        """Get queue health status for monitoring.

        Returns:
            Dict with depth info and health indicators
        """
        depths = await self._publisher.get_all_queue_depths()
        total = sum(depths.values())

        return {
            "healthy": total < self._max_total * 0.8,
            "warning": total >= self._max_total * 0.8 and total < self._max_total,
            "critical": total >= self._max_total,
            "total_depth": total,
            "max_total": self._max_total,
            "depths_by_priority": {
                p.value: {
                    "current": d,
                    "max": self._max_per_priority.get(p, 1000),
                    "utilization": d / self._max_per_priority.get(p, 1000),
                }
                for p, d in depths.items()
            },
        }

    async def enqueue_with_backpressure(
        self,
        job,  # ExecutionJob - avoiding circular import
        check_total: bool = True,
    ) -> str:
        """Enqueue a job with backpressure checks.

        Args:
            job: The job to enqueue
            check_total: Also check total depth (default: True)

        Returns:
            Redis stream message ID

        Raises:
            QueueFullError: If queue is at capacity
        """
        await self.check_capacity(job.priority)

        if check_total:
            await self.check_total_capacity()

        return await self._publisher.enqueue(job)
