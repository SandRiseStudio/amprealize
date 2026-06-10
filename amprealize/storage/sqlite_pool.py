"""SQLite storage adapter implementing the same interface as PostgresPool.

Provides fully offline local storage using a single SQLite file at
``~/.amprealize/data/amprealize.db`` (or a custom path via config).  Designed for
the OSS single-user tier where PostgreSQL is not required.

Key differences from PostgresPool:
- No connection pooling — SQLite uses a single writer with WAL mode.
- JSONB columns stored as TEXT (use ``json_extract()`` for queries).
- Array columns stored as JSON arrays in TEXT columns.
- Timestamps stored as ISO-8601 TEXT strings.
- UUIDs stored as VARCHAR(36) TEXT.
- No native RLS — ``set_tenant_context`` stores context on the instance.
"""

from __future__ import annotations

import os
import random
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

__all__ = ["SQLitePool"]

_T = TypeVar("_T")

# ---------------------------------------------------------------------------
# Default path helpers
# ---------------------------------------------------------------------------

_AMPREALIZE_HOME = Path(os.environ.get("AMPREALIZE_HOME", "~/.amprealize")).expanduser()
_DEFAULT_DB_PATH = _AMPREALIZE_HOME / "data" / "amprealize.db"


def _resolve_db_path(dsn: Optional[str] = None) -> Path:
    """Resolve the SQLite database file path.

    Priority: explicit *dsn* parameter → ``AMPREALIZE_SQLITE_PATH`` env → config
    loader → default ``~/.amprealize/data/amprealize.db``.
    """
    if dsn is not None:
        # Strip ``sqlite:///`` prefix if present
        cleaned = dsn.replace("sqlite:///", "").replace("sqlite://", "")
        return Path(cleaned).expanduser()

    env_path = os.environ.get("AMPREALIZE_SQLITE_PATH")
    if env_path:
        return Path(env_path).expanduser()

    # Try config loader (may not be available)
    try:
        from amprealize.config.loader import get_config
        cfg = get_config()
        if cfg.storage.sqlite and cfg.storage.sqlite.path:
            return Path(str(cfg.storage.sqlite.path)).expanduser()
    except Exception:  # noqa: BLE001 — config loader is optional
        pass

    return _DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# SQLite-specific helpers
# ---------------------------------------------------------------------------

def _adapt_uuid(val: uuid.UUID) -> str:
    return str(val)


def _convert_uuid(val: bytes) -> str:
    return val.decode()


# Register adapters so ``sqlite3`` transparently handles UUID objects.
sqlite3.register_adapter(uuid.UUID, _adapt_uuid)
sqlite3.register_converter("UUID", _convert_uuid)


# ---------------------------------------------------------------------------
# Connection proxy (mirrors PostgresPool._ConnectionProxy)
# ---------------------------------------------------------------------------

class _CursorWrapper:
    """Wrap ``sqlite3.Cursor`` so it can be used as a context manager.

    psycopg2 cursors support ``with conn.cursor() as cur:`` but the stdlib
    ``sqlite3.Cursor`` does not.  This thin wrapper adds ``__enter__`` /
    ``__exit__`` so that ``BoardService`` (and any other code using the
    psycopg2 pattern) works unchanged on SQLite.
    """

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "sqlite3.Cursor":
        return self._cursor

    def __exit__(self, *exc: Any) -> None:
        self._cursor.close()

    # Forward attribute access so callers can also use the wrapper directly
    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class _TransactionConnectionWrapper:
    """Wrap a raw ``sqlite3.Connection`` so ``.cursor()`` returns a
    context-manager-compatible cursor.

    Used by ``run_transaction`` / ``run_query`` to make the executor callback
    compatible with code written for psycopg2 (``with conn.cursor() as cur:``).
    All other attribute accesses are forwarded to the underlying connection.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def cursor(self, *args: Any, **kwargs: Any) -> _CursorWrapper:
        return _CursorWrapper(self._conn.cursor(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class _ConnectionProxy:
    """Compatibility proxy matching PostgresPool._ConnectionProxy."""

    def __init__(self, pool: "SQLitePool", *, autocommit: bool) -> None:
        self._pool = pool
        self._autocommit = autocommit

    @contextmanager
    def cursor(self, *args, **kwargs):
        with self._pool.connection(autocommit=self._autocommit) as conn:
            cur = conn.cursor()
            try:
                yield cur
            finally:
                cur.close()

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Main adapter
# ---------------------------------------------------------------------------

class SQLitePool:
    """Lightweight SQLite adapter matching the PostgresPool public interface.

    Safe for single-process use.  The underlying connection uses WAL journal
    mode for better concurrent-read performance and a busy-timeout so that
    ``SQLITE_BUSY`` is retried internally by the driver before surfacing.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        service_name: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> None:
        self._db_path = _resolve_db_path(dsn)
        self._service_name = service_name or "sqlite"
        self._schema = schema  # informational — SQLite has no schemas

        # Ensure parent directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Thread-local storage for connections
        self._local = threading.local()
        self._lock = threading.Lock()

        # Tenant context (no native RLS in SQLite)
        self._tenant_org_id: Optional[str] = None
        self._tenant_user_id: Optional[str] = None

        # Stats tracking
        self._checked_out = 0
        self._total_connections = 0

        # Eagerly create the file and enable WAL + pragmas
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        """Return a thread-local connection, creating one if needed."""
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                str(self._db_path),
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False,
                timeout=30,  # busy-timeout in seconds
            )
            conn.row_factory = sqlite3.Row
            # Performance pragmas
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute("PRAGMA synchronous = NORMAL")
            self._local.conn = conn
            with self._lock:
                self._total_connections += 1
        return conn

    def _init_db(self) -> None:
        """Create the database file and run schema initialisation."""
        conn = self._get_connection()
        # Ensure migrations tracking table exists
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _migrations ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  version INTEGER NOT NULL UNIQUE,"
            "  name TEXT NOT NULL,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Public API — matches PostgresPool
    # ------------------------------------------------------------------

    @contextmanager
    def connection(self, *, autocommit: bool = True):
        """Acquire a raw ``sqlite3.Connection``.

        When *autocommit* is ``True`` the connection's ``isolation_level`` is
        set to ``None`` (autocommit).  Otherwise it uses ``DEFERRED``
        transactions.
        """
        conn = self._get_connection()
        prev_isolation = conn.isolation_level
        with self._lock:
            self._checked_out += 1
        try:
            conn.isolation_level = None if autocommit else "DEFERRED"
            yield conn
            if not autocommit:
                conn.commit()
        except Exception:
            if not autocommit:
                conn.rollback()
            raise
        finally:
            conn.isolation_level = prev_isolation
            with self._lock:
                self._checked_out -= 1

    def proxy(self, *, autocommit: bool = True) -> _ConnectionProxy:
        """Return a compatibility proxy exposing ``cursor()``/``commit()``."""
        return _ConnectionProxy(self, autocommit=autocommit)

    def run_transaction(
        self,
        operation: str,
        *,
        service_prefix: str = "sqlite",
        actor: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        executor: Callable[[Any], _T],
        telemetry: Optional[Any] = None,
        max_attempts: int = 3,
        base_retry_delay: float = 0.05,
    ) -> _T:
        """Execute *executor* inside a transaction with optional retry on SQLITE_BUSY."""
        payload_base: Dict[str, Any] = dict(metadata or {})
        last_exception: Optional[Exception] = None

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

                    result = executor(_TransactionConnectionWrapper(conn))

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
                    return result
            except Exception as exc:  # noqa: BLE001
                last_exception = exc
                if self._is_retryable_sqlite_error(exc) and attempt < max_attempts:
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
                    delay = base_retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.01)
                    time.sleep(delay)
                    continue

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
    def _is_retryable_sqlite_error(exc: Exception) -> bool:
        """Return ``True`` for transient SQLite locking errors."""
        if isinstance(exc, sqlite3.OperationalError):
            msg = str(exc).lower()
            return "database is locked" in msg or "database table is locked" in msg
        return False

    def set_tenant_context(
        self,
        conn: Any,
        org_id: Optional[str],
        user_id: Optional[str],
    ) -> None:
        """Store tenant context on the instance (no native RLS in SQLite)."""
        self._tenant_org_id = org_id
        self._tenant_user_id = user_id

    def run_query(
        self,
        operation: str,
        *,
        service_prefix: str = "sqlite",
        actor: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        executor: Callable[[Any], _T],
        telemetry: Optional[Any] = None,
    ) -> _T:
        """Execute a read-only query with optional telemetry (no retry)."""
        payload_base: Dict[str, Any] = dict(metadata or {})
        start_time = time.time()

        try:
            with self.connection(autocommit=True) as conn:
                if telemetry:
                    telemetry.emit_event(
                        event_type=f"{service_prefix}_query_start",
                        payload={"operation": operation, **payload_base},
                        actor=actor,
                    )

                result = executor(_TransactionConnectionWrapper(conn))

                duration = time.time() - start_time
                if telemetry:
                    telemetry.emit_event(
                        event_type=f"{service_prefix}_query_complete",
                        payload={
                            "operation": operation,
                            "duration_ms": duration * 1000,
                            **payload_base,
                        },
                        actor=actor,
                    )
                return result
        except Exception as exc:
            if telemetry:
                telemetry.emit_event(
                    event_type=f"{service_prefix}_query_failure",
                    payload={"operation": operation, "error": str(exc), **payload_base},
                    actor=actor,
                )
            raise

    def get_pool_stats(self) -> Dict[str, Any]:
        """Return connection statistics (simplified for SQLite)."""
        return {
            "service": self._service_name,
            "checked_out": self._checked_out,
            "pool_size": self._total_connections,
            "overflow": 0,
            "available": max(0, self._total_connections - self._checked_out),
        }

    def close(self) -> None:
        """Close the thread-local connection if open."""
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
            with self._lock:
                self._total_connections = max(0, self._total_connections - 1)

    # ------------------------------------------------------------------
    # Schema migration helpers
    # ------------------------------------------------------------------

    def get_applied_migrations(self) -> List[int]:
        """Return sorted list of migration versions already applied."""
        with self.connection(autocommit=True) as conn:
            rows = conn.execute(
                "SELECT version FROM _migrations ORDER BY version"
            ).fetchall()
            return [r[0] for r in rows]

    def apply_migration(self, version: int, name: str, sql: str) -> None:
        """Apply a single migration DDL and record it."""
        with self.connection(autocommit=False) as conn:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO _migrations (version, name) VALUES (?, ?)",
                (version, name),
            )

    @property
    def db_path(self) -> Path:
        """Return the resolved database file path."""
        return self._db_path
