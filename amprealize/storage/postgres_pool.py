"""Shared SQLAlchemy-powered PostgreSQL connection pooling utilities."""

from __future__ import annotations

import os
import random
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from amprealize.storage import postgres_metrics

# Import settings for multi-environment configuration
try:
    from amprealize.config.settings import settings
    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False

__all__ = ["PostgresPool"]

_T = TypeVar("_T")

# All application schemas in resolution order.  Every raw connection sets this
# as search_path so unqualified table names resolve correctly regardless of
# whether the caller explicitly calls set_tenant_context().
_APP_SEARCH_PATH = "board, auth, execution, behavior, workflow, consent, audit, compliance, credentials, messaging, research, public"

_POOL_CACHE: Dict[Tuple[str, int, int, int, int, int], Engine] = {}
_CACHE_LOCK = threading.Lock()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _is_cloud_dsn(dsn: str) -> bool:
    """Detect if DSN points to a known serverless/cloud PostgreSQL host."""
    cloud_hosts = ("neon.tech", "supabase.co", "timescaledb.io", "cockroachlabs.cloud")
    return any(h in dsn for h in cloud_hosts)


def _pool_config(dsn: str = "") -> Tuple[int, int, int, int, int]:
    """Get pool configuration from settings or environment variables.

    Cloud-hosted databases (e.g. Neon) idle connections after ~5 min,
    so pool_recycle is reduced and connect_timeout increased.
    """
    cloud = _is_cloud_dsn(dsn) or os.getenv("AMPREALIZE_CLOUD_DB", "").lower() in (
        "1",
        "true",
    )

    if SETTINGS_AVAILABLE:
        pool_size = settings.database.pool_size
        max_overflow = settings.database.max_overflow
        pool_timeout = settings.database.pool_timeout
        pool_recycle = _int_env(
            "AMPREALIZE_PG_POOL_RECYCLE", 270 if cloud else 1800
        )
        connect_timeout = _int_env(
            "AMPREALIZE_PG_CONNECT_TIMEOUT", 10 if cloud else 5
        )
    else:
        pool_size = _int_env("AMPREALIZE_PG_POOL_SIZE", 5 if cloud else 10)
        max_overflow = _int_env("AMPREALIZE_PG_POOL_MAX_OVERFLOW", 10 if cloud else 20)
        pool_timeout = _int_env("AMPREALIZE_PG_POOL_TIMEOUT", 30)
        pool_recycle = _int_env(
            "AMPREALIZE_PG_POOL_RECYCLE", 270 if cloud else 1800
        )
        connect_timeout = _int_env(
            "AMPREALIZE_PG_CONNECT_TIMEOUT", 10 if cloud else 5
        )
    return pool_size, max_overflow, pool_timeout, pool_recycle, connect_timeout


def _get_engine(dsn: str) -> Engine:
    config = _pool_config(dsn)
    key = (dsn, *config)
    with _CACHE_LOCK:
        engine = _POOL_CACHE.get(key)
        if engine is None:
            pool_size, max_overflow, pool_timeout, pool_recycle, connect_timeout = config
            engine = create_engine(
                dsn,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
                pool_recycle=pool_recycle,
                pool_pre_ping=True,
                connect_args={"connect_timeout": connect_timeout},
                future=True,
            )

            # Set search_path once when a physical connection is first created
            # (not on every checkout).  This eliminates a ~75ms neon round-trip
            # that was previously paid on every connection() call.
            @event.listens_for(engine, "connect")
            def _set_search_path(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute(f"SET search_path = {_APP_SEARCH_PATH}")
                cursor.close()
                dbapi_conn.commit()

            _POOL_CACHE[key] = engine
        return engine


class _ConnectionProxy:
    def __init__(self, pool: "PostgresPool", *, autocommit: bool) -> None:
        self._pool = pool
        self._autocommit = autocommit

    @contextmanager
    def cursor(self, *args, **kwargs):
        with self._pool.connection(autocommit=self._autocommit) as conn:
            with conn.cursor(*args, **kwargs) as cur:
                yield cur

    def commit(self) -> None:  # noqa: D401 - proxy commit for compatibility
        """No-op commit placeholder for autocommit connections."""
        return None

    def rollback(self) -> None:
        """No-op rollback placeholder for autocommit connections."""
        return None


class PostgresPool:
    """Lightweight wrapper around SQLAlchemy engine for pooled connections."""

    def __init__(
        self,
        dsn: Optional[str] = None,
        service_name: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> None:
        """Initialize PostgresPool with DSN from parameter, settings, or environment.

        Args:
            dsn: PostgreSQL DSN string. If None, falls back to settings.database.postgres_url
            service_name: Optional service name for metrics tracking
            schema: Optional schema name (reserved for future multi-schema support)
        """
        # Resolve DSN from multiple sources (parameter > settings > error)
        resolved_dsn: str
        if dsn is None:
            if SETTINGS_AVAILABLE:
                resolved_dsn = settings.database.postgres_url  # type: ignore[possibly-unbound]
            else:
                raise ValueError(
                    "PostgresPool requires dsn parameter or settings module "
                    "(install pydantic-settings and configure DATABASE__POSTGRES_URL)"
                )
        else:
            resolved_dsn = dsn

        self._dsn = resolved_dsn
        self._engine = _get_engine(resolved_dsn)
        self._service_name = service_name or "postgres"
        self._schema = schema  # Reserved for future multi-schema support

        # Register Prometheus metrics collection if available
        if service_name and postgres_metrics.PROMETHEUS_AVAILABLE:
            postgres_metrics.register_pool_metrics(self._engine, service_name)

    @contextmanager
    def connection(self, *, autocommit: bool = True):
        """Acquire a raw psycopg2 connection with optional autocommit.

        The connection's ``search_path`` is automatically set to include all
        application schemas so unqualified table names (e.g. ``runs``,
        ``actions``) resolve correctly regardless of the PostgreSQL default.
        """
        with self._engine.connect() as connection:
            raw = connection.connection
            previous_autocommit = getattr(raw, "autocommit", False)
            try:
                if hasattr(raw, "autocommit"):
                    raw.autocommit = autocommit
                # search_path is set once per physical connection via the
                # SQLAlchemy "connect" event (see _get_engine), so we do
                # NOT need to SET it on every checkout.
                yield raw
                # Always commit before returning connection to pool
                # Even in autocommit mode, ensure any pending statements are flushed
                if hasattr(raw, "commit") and not hasattr(raw, "_closed"):
                    raw.commit()
            except Exception:
                if hasattr(raw, "rollback"):
                    raw.rollback()
                raise
            finally:
                if hasattr(raw, "autocommit"):
                    raw.autocommit = previous_autocommit

    def proxy(self, *, autocommit: bool = True) -> _ConnectionProxy:
        """Return a compatibility proxy exposing cursor()/commit() helpers."""
        return _ConnectionProxy(self, autocommit=autocommit)

    def run_transaction(
        self,
        operation: str,
        *,
        service_prefix: str = "postgres",
        actor: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        executor: Callable[[Any], _T],
        telemetry: Optional[Any] = None,
        max_attempts: int = 3,
        base_retry_delay: float = 0.05,
    ) -> _T:
        """Execute a database transaction with retry + telemetry instrumentation.

        Args:
            operation: Human-readable operation name for logging (e.g., "create_action")
            service_prefix: Service name for telemetry events (e.g., "action", "behavior")
            actor: Optional actor metadata dict for telemetry
            metadata: Optional additional payload for telemetry
            executor: Callable receiving a connection and returning the result
            telemetry: Optional TelemetryClient instance for event emission
            max_attempts: Maximum retry attempts (default: 3)
            base_retry_delay: Base delay in seconds, exponentially increased per retry (default: 0.05s)

        Returns:
            The result from the executor callable

        Raises:
            Exception: The last exception encountered if all retries exhausted
        """
        payload_base: Dict[str, Any] = dict(metadata or {})
        last_exception: Optional[Exception] = None

        # Record transaction attempt for Prometheus
        postgres_metrics.record_transaction_start(self._service_name, operation)

        start_time = time.time()
        for attempt in range(1, max_attempts + 1):
            try:
                with self.connection(autocommit=False) as conn:
                    if telemetry:
                        telemetry.emit_event(
                            event_type=f"{service_prefix}_transaction_start",
                            payload={
                                "operation": operation,
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                                **payload_base,
                            },
                            actor=actor,
                        )

                    result = executor(conn)

                    if telemetry:
                        telemetry.emit_event(
                            event_type=f"{service_prefix}_transaction_commit",
                            payload={
                                "operation": operation,
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                                **payload_base,
                            },
                            actor=actor,
                        )

                    # Record successful transaction duration
                    duration = time.time() - start_time
                    postgres_metrics.transaction_duration_seconds.labels(
                        service=self._service_name, operation=operation
                    ).observe(duration)

                    return result
            except Exception as exc:  # noqa: BLE001 - propagate after telemetry
                last_exception = exc
                if self._is_retryable_pg_error(exc) and attempt < max_attempts:
                    # Record retry for Prometheus
                    postgres_metrics.record_transaction_retry(self._service_name, operation)

                    if telemetry:
                        telemetry.emit_event(
                            event_type=f"{service_prefix}_transaction_retry",
                            payload={
                                "operation": operation,
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                                "error": str(exc),
                                **payload_base,
                            },
                            actor=actor,
                        )
                    # Exponential backoff with jitter
                    delay = base_retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.01)
                    time.sleep(delay)
                    continue

                # Record failure for Prometheus
                error_type = type(exc).__name__
                postgres_metrics.record_transaction_failure(
                    self._service_name, operation, error_type
                )

                if telemetry:
                    telemetry.emit_event(
                        event_type=f"{service_prefix}_transaction_failure",
                        payload={
                            "operation": operation,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "error": str(exc),
                            **payload_base,
                        },
                        actor=actor,
                    )
                raise

        if last_exception is not None:
            raise last_exception
        raise RuntimeError(f"Transaction '{operation}' terminated without executing")

    @staticmethod
    def _is_retryable_pg_error(exc: Exception) -> bool:
        """Check if a PostgreSQL error is retryable (deadlock or serialization failure)."""
        # Check for PostgreSQL error codes: 40P01 (deadlock), 40001 (serialization failure)
        pgcode = getattr(exc, "pgcode", None)
        if pgcode and pgcode in {"40P01", "40001"}:
            return True

        # Fallback to message inspection for non-psycopg2 exceptions
        message = str(exc).lower()
        return "deadlock detected" in message or "could not serialize access" in message

    def set_tenant_context(
        self,
        conn: Any,
        org_id: Optional[str],
        user_id: Optional[str],
    ) -> None:
        """Set PostgreSQL session variables for row-level security (RLS).

        Args:
            conn: Active database connection
            org_id: Organization ID to set as current_org_id
            user_id: User ID to set as current_user_id
        """
        with conn.cursor() as cur:
            # search_path is set once per physical connection via the
            # SQLAlchemy "connect" event — no need to re-SET here.

            # Set org context for RLS policies
            if org_id:
                cur.execute("SET LOCAL app.current_org_id = %s", (org_id,))
            else:
                cur.execute("RESET app.current_org_id")

            # Set user context for audit/RLS
            if user_id:
                cur.execute("SET LOCAL app.current_user_id = %s", (user_id,))
            else:
                cur.execute("RESET app.current_user_id")

    def run_query(
        self,
        operation: str,
        *,
        service_prefix: str = "postgres",
        actor: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        executor: Callable[[Any], _T],
        telemetry: Optional[Any] = None,
    ) -> _T:
        """Execute a read-only query with telemetry instrumentation (no retry/transaction).

        This is a simplified version of run_transaction for SELECT operations
        that don't require transaction semantics or retry logic.

        Args:
            operation: Human-readable operation name for logging (e.g., "get_board")
            service_prefix: Service name for telemetry events (e.g., "board", "action")
            actor: Optional actor metadata dict for telemetry
            metadata: Optional additional payload for telemetry
            executor: Callable receiving a connection and returning the result
            telemetry: Optional TelemetryClient instance for event emission

        Returns:
            The result from the executor callable
        """
        payload_base: Dict[str, Any] = dict(metadata or {})

        postgres_metrics.record_transaction_start(self._service_name, operation)
        start_time = time.time()

        try:
            # Use autocommit=False so SET LOCAL search_path (set by
            # set_tenant_context) persists across all statements in
            # the executor – autocommit=True would auto-commit each
            # statement individually, losing LOCAL settings.
            with self.connection(autocommit=False) as conn:
                if telemetry:
                    telemetry.emit_event(
                        event_type=f"{service_prefix}_query_start",
                        payload={"operation": operation, **payload_base},
                        actor=actor,
                    )

                result = executor(conn)

                duration = time.time() - start_time
                postgres_metrics.transaction_duration_seconds.labels(
                    service=self._service_name, operation=operation
                ).observe(duration)

                if telemetry:
                    telemetry.emit_event(
                        event_type=f"{service_prefix}_query_complete",
                        payload={"operation": operation, "duration_ms": duration * 1000, **payload_base},
                        actor=actor,
                    )

                return result
        except Exception as exc:
            error_type = type(exc).__name__
            postgres_metrics.record_transaction_failure(self._service_name, operation, error_type)

            if telemetry:
                telemetry.emit_event(
                    event_type=f"{service_prefix}_query_failure",
                    payload={"operation": operation, "error": str(exc), **payload_base},
                    actor=actor,
                )
            raise

    def get_pool_stats(self) -> Dict[str, Any]:
        """Get current connection pool statistics.

        Returns:
            Dictionary with pool metrics including:
            - checked_out: Number of connections currently in use
            - pool_size: Total number of connections in pool
            - overflow: Number of overflow connections (above pool_size)
            - available: Number of idle connections available
        """
        pool = self._engine.pool
        checked_out = pool.checkedout()
        pool_size = pool.size()
        overflow = pool.overflow() if hasattr(pool, "overflow") else 0

        # Update Prometheus metrics
        if hasattr(self._engine, "_update_pool_metrics"):
            self._engine._update_pool_metrics()  # type: ignore[attr-defined]

        return {
            "service": self._service_name,
            "checked_out": checked_out,
            "pool_size": pool_size,
            "overflow": overflow,
            "available": pool_size - checked_out,
        }

    def close(self) -> None:
        """Dispose underlying engine connections."""
        self._engine.dispose()
