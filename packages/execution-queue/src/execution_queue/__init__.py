"""Execution queue package for Amprealize agent workloads.

This package provides Redis Streams-based job queuing with:
- Priority queues (high/normal/low)
- Consumer groups for horizontal scaling
- Dead letter queue for failed jobs
- Backpressure via queue depth monitoring
"""

from execution_queue.models import (
    ExecutionJob,
    ExecutionResult,
    ExecutionStatus,
    Priority,
    JobState,
)
from execution_queue.publisher import ExecutionQueuePublisher
from execution_queue.consumer import ExecutionQueueConsumer
from execution_queue.backpressure import BackpressureMonitor, QueueFullError
from execution_queue.dead_letter import DeadLetterHandler

__all__ = [
    # Models
    "ExecutionJob",
    "ExecutionResult",
    "ExecutionStatus",
    "Priority",
    "JobState",
    # Publisher
    "ExecutionQueuePublisher",
    # Consumer
    "ExecutionQueueConsumer",
    # Backpressure
    "BackpressureMonitor",
    "QueueFullError",
    # Dead Letter
    "DeadLetterHandler",
]

__version__ = "0.1.0"
