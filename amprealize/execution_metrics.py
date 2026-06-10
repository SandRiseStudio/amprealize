"""Prometheus metrics for execution worker monitoring.

This module defines Prometheus metrics for monitoring the execution queue
and worker performance. Metrics include:

- Job processing counts (success, failure, timeout)
- Currently executing jobs gauge
- Job duration histograms
- Queue depth gauges
- Zombie cleanup metrics

Usage:
    from amprealize.execution_metrics import (
        record_job_processed,
        record_job_duration,
        set_jobs_in_progress,
        update_queue_depth,
    )

    # Record job completion
    record_job_processed(status="success", scope="org:123")
    record_job_duration(scope="org:123", duration_seconds=45.5)

    # Update gauges
    set_jobs_in_progress(worker_id="worker-1", count=2)
    update_queue_depth(priority="high", depth=15)

For FastAPI integration:
    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Try to import prometheus_client, but make it optional
try:
    from prometheus_client import Counter, Gauge, Histogram, Info

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.info("prometheus_client not installed, metrics will be no-ops")


# Define metrics (only if prometheus is available)
if PROMETHEUS_AVAILABLE:
    # === Job Processing Metrics ===

    JOBS_PROCESSED = Counter(
        "amprealize_execution_jobs_processed_total",
        "Total execution jobs processed",
        ["status", "scope"],
    )

    JOBS_IN_PROGRESS = Gauge(
        "amprealize_execution_jobs_in_progress",
        "Currently executing jobs",
        ["worker_id"],
    )

    JOB_DURATION = Histogram(
        "amprealize_execution_job_duration_seconds",
        "Time spent executing jobs",
        ["scope"],
        buckets=[10, 60, 300, 600, 1800, 3600],  # 10s, 1m, 5m, 10m, 30m, 1h
    )

    # === Queue Metrics ===

    QUEUE_DEPTH = Gauge(
        "amprealize_execution_queue_depth",
        "Number of jobs waiting in queue",
        ["priority"],
    )

    QUEUE_PENDING = Gauge(
        "amprealize_execution_queue_pending",
        "Number of jobs pending acknowledgement",
        ["priority"],
    )

    # === Workspace/Container Metrics ===

    WORKSPACES_ACTIVE = Gauge(
        "amprealize_workspaces_active",
        "Currently active workspaces",
        ["scope"],
    )

    WORKSPACES_PROVISIONED = Counter(
        "amprealize_workspaces_provisioned_total",
        "Total workspaces provisioned",
        ["scope"],
    )

    WORKSPACES_CLEANED = Counter(
        "amprealize_workspaces_cleaned_total",
        "Total workspaces cleaned up",
        ["scope", "reason"],  # reason: success, failure, zombie
    )

    # === Zombie Reaper Metrics ===

    ZOMBIES_REAPED = Counter(
        "amprealize_zombies_reaped_total",
        "Total zombie workspaces reaped",
    )

    REAPER_RUNS = Counter(
        "amprealize_reaper_runs_total",
        "Total zombie reaper runs",
    )

    REAPER_ERRORS = Counter(
        "amprealize_reaper_errors_total",
        "Total zombie reaper errors",
    )

    # === Quota Metrics ===

    QUOTA_CHECKS = Counter(
        "amprealize_quota_checks_total",
        "Total quota checks performed",
        ["scope", "result"],  # result: allowed, rejected
    )

    QUOTA_USAGE = Gauge(
        "amprealize_quota_usage",
        "Current quota usage (concurrent workspaces)",
        ["scope"],
    )

    # === Worker Info ===

    WORKER_INFO = Info(
        "amprealize_execution_worker",
        "Execution worker information",
    )


# === Helper Functions ===
# These are safe to call whether prometheus is available or not


def record_job_processed(status: str, scope: str) -> None:
    """Record a job completion.

    Args:
        status: success, failure, timeout, cancelled
        scope: Isolation scope (e.g., "org:123" or "user:456")
    """
    if PROMETHEUS_AVAILABLE:
        JOBS_PROCESSED.labels(status=status, scope=scope).inc()


def record_job_duration(scope: str, duration_seconds: float) -> None:
    """Record job execution duration.

    Args:
        scope: Isolation scope
        duration_seconds: How long the job took
    """
    if PROMETHEUS_AVAILABLE:
        JOB_DURATION.labels(scope=scope).observe(duration_seconds)


def set_jobs_in_progress(worker_id: str, count: int) -> None:
    """Set the number of jobs currently being processed by a worker.

    Args:
        worker_id: Worker identifier
        count: Number of jobs in progress (usually 0 or 1)
    """
    if PROMETHEUS_AVAILABLE:
        JOBS_IN_PROGRESS.labels(worker_id=worker_id).set(count)


def update_queue_depth(priority: str, depth: int) -> None:
    """Update the queue depth for a priority level.

    Args:
        priority: high, normal, low
        depth: Number of jobs waiting
    """
    if PROMETHEUS_AVAILABLE:
        QUEUE_DEPTH.labels(priority=priority).set(depth)


def update_queue_pending(priority: str, pending: int) -> None:
    """Update the pending message count for a priority level.

    Args:
        priority: high, normal, low
        pending: Number of messages pending acknowledgement
    """
    if PROMETHEUS_AVAILABLE:
        QUEUE_PENDING.labels(priority=priority).set(pending)


def record_workspace_provisioned(scope: str) -> None:
    """Record a workspace being provisioned."""
    if PROMETHEUS_AVAILABLE:
        WORKSPACES_PROVISIONED.labels(scope=scope).inc()


def set_active_workspaces(scope: str, count: int) -> None:
    """Set the number of active workspaces for a scope."""
    if PROMETHEUS_AVAILABLE:
        WORKSPACES_ACTIVE.labels(scope=scope).set(count)


def record_workspace_cleaned(scope: str, reason: str) -> None:
    """Record a workspace being cleaned up.

    Args:
        scope: Isolation scope
        reason: success, failure, zombie, timeout
    """
    if PROMETHEUS_AVAILABLE:
        WORKSPACES_CLEANED.labels(scope=scope, reason=reason).inc()


def record_zombies_reaped(count: int) -> None:
    """Record zombie workspaces being reaped."""
    if PROMETHEUS_AVAILABLE:
        ZOMBIES_REAPED.inc(count)


def record_reaper_run() -> None:
    """Record a zombie reaper run."""
    if PROMETHEUS_AVAILABLE:
        REAPER_RUNS.inc()


def record_reaper_error() -> None:
    """Record a zombie reaper error."""
    if PROMETHEUS_AVAILABLE:
        REAPER_ERRORS.inc()


def record_quota_check(scope: str, allowed: bool) -> None:
    """Record a quota check.

    Args:
        scope: Isolation scope
        allowed: Whether the request was allowed
    """
    if PROMETHEUS_AVAILABLE:
        result = "allowed" if allowed else "rejected"
        QUOTA_CHECKS.labels(scope=scope, result=result).inc()


def set_quota_usage(scope: str, count: int) -> None:
    """Set current quota usage for a scope."""
    if PROMETHEUS_AVAILABLE:
        QUOTA_USAGE.labels(scope=scope).set(count)


def set_worker_info(
    worker_id: str,
    consumer_group: str,
    version: str = "1.0.0",
) -> None:
    """Set worker info labels.

    Args:
        worker_id: Unique worker identifier
        consumer_group: Redis consumer group name
        version: Worker version
    """
    if PROMETHEUS_AVAILABLE:
        WORKER_INFO.info({
            "worker_id": worker_id,
            "consumer_group": consumer_group,
            "version": version,
        })


class MetricsCollector:
    """Helper class for collecting queue metrics from Redis.

    Run this periodically to update queue depth gauges.

    Example:
        collector = MetricsCollector(redis_client, "amprealize:executions")
        await collector.collect()
    """

    def __init__(
        self,
        redis_client,
        stream_prefix: str = "amprealize:executions",
        consumer_group: str = "execution-workers",
    ):
        self._redis = redis_client
        self._stream_prefix = stream_prefix
        self._consumer_group = consumer_group

    async def collect(self) -> None:
        """Collect and update queue metrics."""
        if not PROMETHEUS_AVAILABLE:
            return

        for priority in ["high", "normal", "low"]:
            stream_key = f"{self._stream_prefix}:{priority}"

            try:
                # Get stream length (queue depth)
                length = await self._redis.xlen(stream_key)
                update_queue_depth(priority, length)

                # Get pending count
                try:
                    info = await self._redis.xpending(stream_key, self._consumer_group)
                    if info:
                        pending = info.get("pending", 0) if isinstance(info, dict) else (info[0] if info else 0)
                        update_queue_pending(priority, pending)
                except Exception:
                    pass  # Group might not exist yet

            except Exception as e:
                logger.debug(f"Failed to collect metrics for {stream_key}: {e}")


# Export availability flag
__all__ = [
    "PROMETHEUS_AVAILABLE",
    "record_job_processed",
    "record_job_duration",
    "set_jobs_in_progress",
    "update_queue_depth",
    "update_queue_pending",
    "record_workspace_provisioned",
    "set_active_workspaces",
    "record_workspace_cleaned",
    "record_zombies_reaped",
    "record_reaper_run",
    "record_reaper_error",
    "record_quota_check",
    "set_quota_usage",
    "set_worker_info",
    "MetricsCollector",
]
