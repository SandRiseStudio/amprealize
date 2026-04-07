"""TimescaleDB sink for production log storage.

This sink uses TimescaleDB hypertables for efficient time-series log storage
with automatic partitioning and compression.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from raze.models import (
    LogAggregateRequest,
    LogAggregation,
    LogEvent,
    LogLevel,
    LogQueryRequest,
)
from raze.sinks.base import RazeSink


class TimescaleDBSink(RazeSink):
    """TimescaleDB sink for production log storage.

    Uses TimescaleDB hypertables for efficient time-series storage with:
    - Automatic partitioning by time (1-day chunks)
    - Native time-range queries optimized by chunk exclusion
    - JSONB context storage with indexing
    - Compression support for older data

    Requires the psycopg2 package: pip install raze[timescale]

    Example:
        sink = TimescaleDBSink(
            dsn="postgresql://user:pass@localhost:5432/logs",
            table_name="log_events",
        )
        service = RazeService(sink=sink)
    """

    def __init__(
        self,
        dsn: str,
        *,
        table_name: str = "log_events",
        connect_timeout: int = 10,
        pool_size: int = 5,
        auto_create_table: bool = True,
    ) -> None:
        """Initialize TimescaleDB sink.

        Args:
            dsn: PostgreSQL connection string.
            table_name: Name of the log events table.
            connect_timeout: Connection timeout in seconds.
            pool_size: Connection pool size.
            auto_create_table: Whether to auto-create table if missing.
        """
        try:
            import psycopg2
            from psycopg2 import pool as pg_pool
            from psycopg2.extras import Json, execute_values
        except ImportError as e:
            raise RuntimeError(
                "psycopg2 not installed. Install with: pip install raze[timescale]"
            ) from e

        self._dsn = dsn
        self._table_name = table_name
        self._lock = threading.Lock()

        # Create connection pool
        self._pool = pg_pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=pool_size,
            dsn=dsn,
            connect_timeout=connect_timeout,
        )

        # Store imports for later use
        self._Json = Json
        self._execute_values = execute_values

        if auto_create_table:
            self._ensure_table()

    def _ensure_table(self) -> None:
        """Create table and hypertable if they don't exist."""
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {self._table_name} (
            log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            schema_version TEXT NOT NULL DEFAULT 'v1',
            event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            level TEXT NOT NULL,
            service TEXT NOT NULL,
            message TEXT NOT NULL,
            run_id TEXT,
            action_id TEXT,
            session_id TEXT,
            actor_surface TEXT,
            context JSONB NOT NULL DEFAULT '{{}}',
            inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- Create indexes for common query patterns
        CREATE INDEX IF NOT EXISTS idx_{self._table_name}_timestamp
            ON {self._table_name} (event_timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_{self._table_name}_level
            ON {self._table_name} (level);
        CREATE INDEX IF NOT EXISTS idx_{self._table_name}_service
            ON {self._table_name} (service);
        CREATE INDEX IF NOT EXISTS idx_{self._table_name}_run_id
            ON {self._table_name} (run_id) WHERE run_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_{self._table_name}_session_id
            ON {self._table_name} (session_id) WHERE session_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_{self._table_name}_context
            ON {self._table_name} USING GIN (context);
        """

        hypertable_sql = f"""
        SELECT create_hypertable(
            '{self._table_name}',
            'event_timestamp',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        );
        """

        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(create_sql)
                try:
                    cur.execute(hypertable_sql)
                except Exception:
                    # TimescaleDB extension might not be installed
                    # Table will still work as regular PostgreSQL table
                    pass
            conn.commit()
        finally:
            self._pool.putconn(conn)

    def write(self, event: LogEvent) -> None:
        """Write a single log event."""
        self.write_batch([event])

    def write_batch(self, events: List[LogEvent]) -> None:
        """Write a batch of log events."""
        if not events:
            return

        insert_sql = f"""
        INSERT INTO {self._table_name} (
            log_id, schema_version, event_timestamp, level, service,
            message, run_id, action_id, session_id, actor_surface, context
        ) VALUES %s
        """

        values = [
            (
                event.log_id,
                event.schema_version,
                event.timestamp,
                event.level.value,
                event.service,
                event.message,
                event.run_id,
                event.action_id,
                event.session_id,
                event.actor_surface,
                self._Json(event.context),
            )
            for event in events
        ]

        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                self._execute_values(cur, insert_sql, values)
            conn.commit()
        finally:
            self._pool.putconn(conn)

    def query(self, request: LogQueryRequest) -> Tuple[List[LogEvent], int]:
        """Query logs with filters."""
        # Build WHERE clause
        conditions = [
            "event_timestamp >= %s",
            "event_timestamp <= %s",
        ]
        params: List[Any] = [request.start_time, request.end_time]

        if request.level is not None:
            # Filter by minimum level
            levels = [l.value for l in LogLevel if l >= request.level]
            conditions.append(f"level = ANY(%s)")
            params.append(levels)

        if request.levels is not None:
            conditions.append(f"level = ANY(%s)")
            params.append([l.value for l in request.levels])

        if request.service is not None:
            conditions.append("service = %s")
            params.append(request.service)

        if request.services is not None:
            conditions.append("service = ANY(%s)")
            params.append(request.services)

        if request.run_id is not None:
            conditions.append("run_id = %s")
            params.append(request.run_id)

        if request.action_id is not None:
            conditions.append("action_id = %s")
            params.append(request.action_id)

        if request.session_id is not None:
            conditions.append("session_id = %s")
            params.append(request.session_id)

        if request.actor_surface is not None:
            conditions.append("actor_surface = %s")
            params.append(request.actor_surface)

        if request.search is not None:
            conditions.append("(message ILIKE %s OR context::text ILIKE %s)")
            search_pattern = f"%{request.search}%"
            params.extend([search_pattern, search_pattern])

        if request.context_filters is not None:
            conditions.append("context @> %s")
            params.append(self._Json(request.context_filters))

        where_clause = " AND ".join(conditions)
        order = "DESC" if request.order == "desc" else "ASC"

        # Count query
        count_sql = f"""
        SELECT COUNT(*) FROM {self._table_name} WHERE {where_clause}
        """

        # Data query
        data_sql = f"""
        SELECT log_id, schema_version, event_timestamp, level, service,
               message, run_id, action_id, session_id, actor_surface, context
        FROM {self._table_name}
        WHERE {where_clause}
        ORDER BY event_timestamp {order}
        LIMIT %s OFFSET %s
        """

        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                # Get total count
                cur.execute(count_sql, params)
                total_count = cur.fetchone()[0]

                # Get data
                cur.execute(data_sql, params + [request.limit, request.offset])
                rows = cur.fetchall()

            events = [
                LogEvent(
                    log_id=str(row[0]),
                    schema_version=row[1],
                    timestamp=row[2],
                    level=LogLevel(row[3]),
                    service=row[4],
                    message=row[5],
                    run_id=row[6],
                    action_id=row[7],
                    session_id=row[8],
                    actor_surface=row[9],
                    context=row[10] or {},
                )
                for row in rows
            ]

            return events, total_count
        finally:
            self._pool.putconn(conn)

    def aggregate(self, request: LogAggregateRequest) -> Tuple[List[LogAggregation], int]:
        """Aggregate log statistics."""
        # Build WHERE clause
        conditions = [
            "event_timestamp >= %s",
            "event_timestamp <= %s",
        ]
        params: List[Any] = [request.start_time, request.end_time]

        if request.level is not None:
            levels = [l.value for l in LogLevel if l >= request.level]
            conditions.append(f"level = ANY(%s)")
            params.append(levels)

        if request.service is not None:
            conditions.append("service = %s")
            params.append(request.service)

        where_clause = " AND ".join(conditions)

        # Build GROUP BY
        group_cols = []
        for field in request.group_by:
            if field == "level":
                group_cols.append("level")
            elif field == "service":
                group_cols.append("service")
            elif field == "actor_surface":
                group_cols.append("COALESCE(actor_surface, 'unknown')")
            elif field == "run_id":
                group_cols.append("COALESCE(run_id, 'unknown')")

        if not group_cols:
            group_cols = ["level"]

        group_clause = ", ".join(group_cols)
        select_cols = ", ".join(group_cols)

        # Count query
        count_sql = f"""
        SELECT COUNT(*) FROM {self._table_name} WHERE {where_clause}
        """

        # Aggregate query
        agg_sql = f"""
        SELECT {select_cols}, COUNT(*) as cnt,
               MIN(event_timestamp) as first_ts,
               MAX(event_timestamp) as last_ts
        FROM {self._table_name}
        WHERE {where_clause}
        GROUP BY {group_clause}
        ORDER BY cnt DESC
        """

        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                # Get total count
                cur.execute(count_sql, params)
                total_count = cur.fetchone()[0]

                # Get aggregations
                cur.execute(agg_sql, params)
                rows = cur.fetchall()

            aggregations = []
            for row in rows:
                group_key = {}
                for i, field in enumerate(request.group_by):
                    group_key[field] = row[i]

                aggregations.append(
                    LogAggregation(
                        group_key=group_key,
                        count=row[len(request.group_by)],
                        first_timestamp=row[len(request.group_by) + 1],
                        last_timestamp=row[len(request.group_by) + 2],
                    )
                )

            return aggregations, total_count
        finally:
            self._pool.putconn(conn)

    def close(self) -> None:
        """Close all connections."""
        if self._pool:
            self._pool.closeall()
