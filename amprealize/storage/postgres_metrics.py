"""Prometheus metrics for PostgreSQL connection pooling and transactions.

This module provides instrumentation for:
- Connection pool utilization (active, idle, total connections)
- Transaction execution (attempts, retries, failures, duration)
- Query performance (slow queries, execution time)
- Service-level metrics (operations per second, error rates)

Usage:
    from amprealize.storage.postgres_metrics import register_pool_metrics, record_transaction

    # In service initialization
    register_pool_metrics(pool, service_name="behavior")

    # In transaction execution (already integrated via PostgresPool.run_transaction)
    with record_transaction(service_name="behavior", operation="create_draft"):
        ...
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Stub implementations for when prometheus_client is not installed
    class Counter:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def inc(self, *args, **kwargs): pass

    class Gauge:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def set(self, *args, **kwargs): pass
        def inc(self, *args, **kwargs): pass
        def dec(self, *args, **kwargs): pass

    class Histogram:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def observe(self, *args, **kwargs): pass
        def time(self): return self
        def __enter__(self): return self
        def __exit__(self, *args): pass

    def generate_latest(*args, **kwargs) -> bytes:  # type: ignore[misc]
        return b"# Prometheus client not installed\n"

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


# Connection pool metrics
pool_connections_active = Gauge(
    "amprealize_pool_connections_active",
    "Number of active connections in the pool",
    ["service"],
)

pool_connections_idle = Gauge(
    "amprealize_pool_connections_idle",
    "Number of idle connections in the pool",
    ["service"],
)

pool_connections_total = Gauge(
    "amprealize_pool_connections_total",
    "Total number of connections (active + idle)",
    ["service"],
)

pool_connections_overflow = Gauge(
    "amprealize_pool_connections_overflow",
    "Number of overflow connections (above pool_size)",
    ["service"],
)

pool_checkout_duration = Histogram(
    "amprealize_pool_checkout_duration_seconds",
    "Time spent checking out a connection from the pool",
    ["service"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

pool_checkout_timeouts_total = Counter(
    "amprealize_pool_checkout_timeouts_total",
    "Total number of connection checkout timeouts",
    ["service"],
)

# Transaction metrics
transaction_attempts_total = Counter(
    "amprealize_transaction_attempts_total",
    "Total number of transaction attempts",
    ["service", "operation"],
)

transaction_retries_total = Counter(
    "amprealize_transaction_retries_total",
    "Total number of transaction retries due to retriable errors",
    ["service", "operation"],
)

transaction_failures_total = Counter(
    "amprealize_transaction_failures_total",
    "Total number of transaction failures",
    ["service", "operation", "error_type"],
)

transaction_duration_seconds = Histogram(
    "amprealize_transaction_duration_seconds",
    "Transaction execution duration",
    ["service", "operation"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# Query metrics
query_duration_seconds = Histogram(
    "amprealize_query_duration_seconds",
    "Database query execution duration",
    ["service", "query_type"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

slow_queries_total = Counter(
    "amprealize_slow_queries_total",
    "Total number of slow queries (>1s)",
    ["service"],
)


def register_pool_metrics(engine: "Engine", service_name: str) -> None:
    """Register periodic collection of pool statistics.

    Args:
        engine: SQLAlchemy Engine instance
        service_name: Service identifier (e.g., "behavior", "workflow")
    """
    if not PROMETHEUS_AVAILABLE:
        return

    # SQLAlchemy pool metrics collection
    def update_pool_metrics() -> None:
        pool = engine.pool
        pool_connections_active.labels(service=service_name).set(pool.checkedout())
        pool_connections_idle.labels(service=service_name).set(
            pool.size() - pool.checkedout()
        )
        pool_connections_total.labels(service=service_name).set(pool.size())
        pool_connections_overflow.labels(service=service_name).set(
            pool.overflow() if hasattr(pool, "overflow") else 0
        )

    # Store update function for manual invocation (could add threading.Timer for periodic)
    setattr(engine, "_update_pool_metrics", update_pool_metrics)


def record_transaction_start(service_name: str, operation: str) -> None:
    """Record the start of a transaction attempt."""
    transaction_attempts_total.labels(service=service_name, operation=operation).inc()


def record_transaction_retry(service_name: str, operation: str) -> None:
    """Record a transaction retry due to retriable error."""
    transaction_retries_total.labels(service=service_name, operation=operation).inc()


def record_transaction_failure(
    service_name: str, operation: str, error_type: str
) -> None:
    """Record a transaction failure."""
    transaction_failures_total.labels(
        service=service_name, operation=operation, error_type=error_type
    ).inc()


@contextmanager
def record_transaction(service_name: str, operation: str):
    """Context manager to record transaction duration and outcome.

    Usage:
        with record_transaction("behavior", "create_draft"):
            # execute transaction
            pass
    """
    start = time.time()
    try:
        yield
    finally:
        duration = time.time() - start
        transaction_duration_seconds.labels(
            service=service_name, operation=operation
        ).observe(duration)


def record_query_duration(service_name: str, query_type: str, duration: float) -> None:
    """Record query execution duration.

    Args:
        service_name: Service identifier
        query_type: Query type (e.g., "SELECT", "INSERT", "UPDATE")
        duration: Query duration in seconds
    """
    query_duration_seconds.labels(service=service_name, query_type=query_type).observe(
        duration
    )

    if duration > 1.0:
        slow_queries_total.labels(service=service_name).inc()


def get_metrics() -> bytes:
    """Get current metrics in Prometheus exposition format.

    Returns:
        Metrics in text format suitable for /metrics endpoint
    """
    return generate_latest()


__all__ = [
    "register_pool_metrics",
    "record_transaction_start",
    "record_transaction_retry",
    "record_transaction_failure",
    "record_transaction",
    "record_query_duration",
    "get_metrics",
    "PROMETHEUS_AVAILABLE",
]
