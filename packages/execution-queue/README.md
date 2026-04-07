# execution-queue

Redis Streams-based execution queue for Amprealize agent workloads.

## Overview

This package provides a reliable, scalable execution queue for decoupling agent execution from API request handling. It uses Redis Streams with consumer groups for:

- **Horizontal scaling**: Multiple workers can consume from the same queue
- **At-least-once delivery**: Failed jobs can be retried or moved to dead letter queue
- **Priority queues**: High/normal/low priority with tenant-based boost
- **Backpressure**: Queue depth monitoring to prevent overload

## Installation

```bash
pip install execution-queue

# With metrics support
pip install execution-queue[metrics]

# For development
pip install execution-queue[dev]
```

## Quick Start

### Publishing Jobs

```python
from execution_queue import ExecutionQueuePublisher, ExecutionJob, Priority

publisher = ExecutionQueuePublisher(redis_url="redis://localhost:6379")

job = ExecutionJob(
    job_id="job-123",
    run_id="run-456",
    work_item_id="wi-789",
    agent_id="agent-abc",
    priority=Priority.NORMAL,
    user_id="user-123",
    org_id="org-456",  # Optional - None for user-owned projects
    project_id="proj-789",
    timeout_seconds=600,
    payload={"key": "value"},
)

message_id = await publisher.enqueue(job)
print(f"Enqueued: {message_id}")
```

### Consuming Jobs

```python
from execution_queue import ExecutionQueueConsumer

consumer = ExecutionQueueConsumer(
    redis_url="redis://localhost:6379",
    consumer_group="execution-workers",
    consumer_name="worker-1",
)

async def handle_job(job: ExecutionJob) -> None:
    print(f"Processing: {job.job_id}")
    # ... execute agent ...

await consumer.consume(handle_job)
```

### Backpressure

```python
depth = await publisher.get_queue_depth(Priority.NORMAL)
if depth > 1000:
    raise QueueFullError("Queue at capacity, try again later")
```

## Architecture

```
┌─────────────┐     XADD      ┌──────────────────────────────┐
│  API/MCP    │──────────────▶│  amprealize:executions:normal   │
│  (Publisher)│               │  (Redis Stream)              │
└─────────────┘               └──────────────┬───────────────┘
                                             │ XREADGROUP
                              ┌──────────────┼──────────────┐
                              ▼              ▼              ▼
                        ┌──────────┐  ┌──────────┐  ┌──────────┐
                        │ Worker 1 │  │ Worker 2 │  │ Worker N │
                        │(Consumer)│  │(Consumer)│  │(Consumer)│
                        └──────────┘  └──────────┘  └──────────┘
```

## Stream Keys

| Priority | Stream Key |
|----------|------------|
| HIGH | `amprealize:executions:high` |
| NORMAL | `amprealize:executions:normal` |
| LOW | `amprealize:executions:low` |
| Dead Letter | `amprealize:executions:dlq` |

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `EXECUTION_QUEUE_PREFIX` | `amprealize:executions` | Stream key prefix |
| `EXECUTION_CONSUMER_GROUP` | `execution-workers` | Consumer group name |
| `EXECUTION_BLOCK_MS` | `5000` | XREADGROUP block timeout |
| `EXECUTION_MAX_RETRIES` | `3` | Max retries before DLQ |

## Metrics (Optional)

When installed with `[metrics]`, exports Prometheus metrics:

- `execution_queue_jobs_enqueued_total` - Jobs enqueued by priority
- `execution_queue_jobs_processed_total` - Jobs processed by status
- `execution_queue_depth` - Current queue depth by priority
- `execution_queue_processing_seconds` - Job processing duration

## License

MIT
