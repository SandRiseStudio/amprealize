"""PostgreSQL-backed telemetry warehouse helpers.

This module provides a ``TelemetrySink`` implementation that persists events
emitted through :class:`amprealize.telemetry.TelemetryClient` into the PostgreSQL
warehouse defined in ``schema/migrations/001_create_telemetry_warehouse.sql``.

Events are stored in the append-only ``telemetry_events`` table and projected
into the fact tables that power the PRD KPI dashboards.  The warehouse exposes
materialised views for the headline metrics, and callers can invoke
``refresh_prd_metric_views`` to update them after large batches of events are
imported.

The implementation intentionally keeps dependencies optional – ``psycopg2`` is
only imported when the sink is instantiated, preserving compatibility for
installations that do not require PostgreSQL support.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Iterator, List, MutableSequence, Optional, Sequence, Tuple

_RUN_SUMMARY_COLUMNS = (
    "run_id",
    "started_at",
    "last_event_at",
    "record_count",
    "failed_record_count",
    "generation_count",
    "tool_call_count",
    "span_count",
    "primary_trace_id",
    "project_id",
    "work_item_id",
    "surface",
)
_CONVERSATION_SUMMARY_COLUMNS = (
    "conversation_id",
    "started_at",
    "last_event_at",
    "record_count",
    "trace_count",
    "generation_count",
    "tool_call_count",
    "project_id",
    "surface",
)
_SPAN_TREE_COLUMNS = (
    "record_id",
    "record_timestamp",
    "trace_id",
    "span_id",
    "parent_span_id",
    "name",
    "status",
    "kind",
    "depth",
)

from amprealize.telemetry import TelemetryEvent, TelemetrySink
from amprealize.execution_observability import sanitize_observability_payload
from amprealize.surfaces import normalize_actor_surface

__all__ = [
    "PostgresTelemetrySink",
    "PostgresTelemetryWarehouse",
    "ExecutionSpan",
    "telemetry_event_from_telemetry_events_row",
]


def telemetry_event_from_telemetry_events_row(
    row: Sequence[Any],
) -> Tuple[TelemetryEvent, datetime, Dict[str, str]]:
    """Build a :class:`TelemetryEvent` + projection inputs from a ``telemetry_events`` row.

    Expects column order:
    ``event_id, event_timestamp, event_type, actor_id, actor_role, actor_surface,
    run_id, action_id, session_id, payload``.
    """

    (
        event_id,
        event_timestamp,
        event_type,
        actor_id,
        actor_role,
        actor_surface,
        run_id,
        action_id,
        session_id,
        payload,
    ) = row

    if isinstance(payload, str):
        payload_dict: Dict[str, Any] = json.loads(payload)
    elif isinstance(payload, dict):
        payload_dict = dict(payload)
    elif payload is None:
        payload_dict = {}
    else:
        payload_dict = dict(payload)

    ts = event_timestamp
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))

    actor: Dict[str, str] = {
        "id": str(actor_id) if actor_id is not None else "",
        "role": str(actor_role) if actor_role is not None else "",
        "surface": normalize_actor_surface(str(actor_surface) if actor_surface else None)
        or "api",
    }

    ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    event = TelemetryEvent(
        event_id=str(event_id),
        timestamp=ts_iso,
        event_type=str(event_type),
        actor=actor,
        run_id=str(run_id) if run_id is not None else None,
        action_id=str(action_id) if action_id is not None else None,
        session_id=str(session_id) if session_id is not None else None,
        payload=payload_dict,
    )
    return event, ts, actor


@dataclass
class ExecutionSpan:
    """Represents an execution trace span for distributed tracing.

    Spans track individual operations within a workflow execution, providing
    visibility into performance, errors, and behavior citations.
    """
    span_id: str
    trace_id: str
    operation_name: str
    service_name: str
    start_time: datetime
    trace_timestamp: datetime
    parent_span_id: Optional[str] = None
    run_id: Optional[str] = None
    action_id: Optional[str] = None
    end_time: Optional[datetime] = None
    status: str = "RUNNING"  # RUNNING, SUCCESS, ERROR, TIMEOUT, CANCELLED
    error_message: Optional[str] = None
    token_count: Optional[int] = None
    behavior_citations: Optional[List[str]] = None
    attributes: Optional[Dict[str, Any]] = None
    events: Optional[List[Dict[str, Any]]] = None
    links: Optional[List[Dict[str, Any]]] = None


class PostgresTelemetryWarehouse:
    """Helper responsible for writing telemetry data into PostgreSQL.

    Uses shared PostgresPool for connection management with pooling,
    health checks, and automatic reconnection.

    Parameters
    ----------
    dsn:
        Connection string in the form
        ``postgresql://user:password@host:port/database``.
    connect_timeout:
        Optional connection timeout passed to psycopg2.  Defaults to 5 seconds.
        Note: This is now handled by PostgresPool via AMPREALIZE_PG_CONNECT_TIMEOUT.
    """

    def __init__(self, dsn: str, *, connect_timeout: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout = connect_timeout
        self._connect()

    def _connect(self) -> None:
        try:
            import psycopg2  # type: ignore[import-not-found]
            from psycopg2.extras import Json  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "psycopg2 is required for Postgres telemetry support. Install with "
                "`pip install psycopg2-binary`."
            ) from exc

        self._psycopg2 = psycopg2
        self._json_wrapper = Json

        # Use shared PostgresPool for connection management
        from amprealize.storage.postgres_pool import PostgresPool
        self._pool = PostgresPool(self._dsn, service_name="telemetry")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def write_event(self, event: TelemetryEvent) -> None:
        """Persist a telemetry event and update fact tables as needed."""

        ts = self._parse_timestamp(event.timestamp)
        actor = dict(event.actor or {})
        actor_surface = normalize_actor_surface(actor.get("surface"))
        actor["surface"] = actor_surface

        event_id = self._coerce_uuid(event.event_id)
        payload_json = self._json_wrapper(event.payload)

        with self._pool.connection(autocommit=True) as conn:
            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO telemetry_events (
                        event_id,
                        event_timestamp,
                        event_type,
                        actor_id,
                        actor_role,
                        actor_surface,
                        run_id,
                        action_id,
                        session_id,
                        payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id, event_timestamp) DO NOTHING
                    """,
                    (
                        str(event_id),
                        ts,
                        event.event_type,
                        actor.get("id"),
                        actor.get("role"),
                        actor_surface,
                        event.run_id,
                        event.action_id,
                        event.session_id,
                        payload_json,
                    ),
                )

        # Project event into fact tables (uses separate connection)
        with self._pool.connection(autocommit=True) as conn:
            self._project_event(conn, event, ts, actor)

    def write_events(self, events: Iterable[TelemetryEvent]) -> None:
        """Convenience helper for batch ingestion."""

        for event in events:
            self.write_event(event)

    def replay_stored_event_projection(
        self,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
    ) -> None:
        """Re-run :meth:`_project_event` without writing to ``telemetry_events``.

        Use after schema upgrades or to repair missing ``observability_records``
        projections. Idempotent where inserts use ``ON CONFLICT DO NOTHING`` /
        upserts.
        """

        with self._pool.connection(autocommit=True) as conn:
            self._project_event(conn, event, ts, actor)

    def replay_event_projections_from_telemetry_table(
        self,
        *,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """Replay warehouse projection for rows already in ``telemetry_events``.

        Parameters
        ----------
        since, until:
            Optional bounds on ``event_timestamp`` (inclusive).
        limit, offset:
            Pagination for large stores.
        dry_run:
            If True, only count how many rows would be replayed in this page; do not write.

        Returns
        -------
        dict
            ``matched`` (rows in this page), ``processed``, ``dry_run`` (0 or 1).
        """

        conditions: List[str] = []
        params: List[Any] = []
        if since is not None:
            conditions.append("event_timestamp >= %s")
            params.append(since)
        if until is not None:
            conditions.append("event_timestamp <= %s")
            params.append(until)
        where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        lim = int(limit) if limit is not None else 2**31 - 1
        off = max(0, int(offset))
        page_params = list(params) + [lim, off]

        inner = (
            "SELECT event_id, event_timestamp, event_type, actor_id, actor_role, "
            "actor_surface, run_id, action_id, session_id, payload "
            f"FROM telemetry_events {where_sql} "
            "ORDER BY event_timestamp ASC, event_id ASC "
            "LIMIT %s OFFSET %s"
        )

        if dry_run:
            count_sql = f"SELECT COUNT(*) FROM ({inner}) AS replay_page"
            with self._pool.connection(autocommit=True) as conn:
                with self._cursor(conn) as cur:
                    cur.execute(count_sql, page_params)
                    row = cur.fetchone()
                    matched = int(row[0]) if row else 0
            return {"matched": matched, "processed": 0, "dry_run": 1}

        processed = 0
        with self._pool.connection(autocommit=True) as conn:
            with self._cursor(conn) as cur:
                cur.execute(inner, page_params)
                rows = cur.fetchall()
            matched = len(rows)
            for row in rows:
                ev, ts, actor = telemetry_event_from_telemetry_events_row(row)
                self._project_event(conn, ev, ts, actor)
                processed += 1

        return {"matched": matched, "processed": processed, "dry_run": 0}

    def start_span(
        self,
        trace_id: str,
        span_id: str,
        operation_name: str,
        service_name: str = "amprealize",
        *,
        parent_span_id: Optional[str] = None,
        run_id: Optional[str] = None,
        action_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> ExecutionSpan:
        """Start a new execution trace span.

        Creates a span in RUNNING state and inserts it into execution_traces table.
        Call end_span() to mark completion and record duration/status.

        Parameters
        ----------
        trace_id:
            Unique identifier for the entire trace (typically one per workflow run).
        span_id:
            Unique identifier for this specific span.
        operation_name:
            Human-readable operation name (e.g., "BehaviorService.retrieve", "ActionService.execute").
        service_name:
            Service/component name (defaults to "amprealize").
        parent_span_id:
            Optional parent span ID for nested operations.
        run_id:
            Optional workflow run ID for correlation with telemetry_events.
        action_id:
            Optional action ID for correlation with action registry.
        attributes:
            Optional metadata dictionary (stored as JSONB).

        Returns
        -------
        ExecutionSpan
            The created span object. Store this to call end_span() later.
        """
        now = datetime.now(timezone.utc)
        trace_timestamp = now
        resolved_parent_span_id = parent_span_id

        with self._pool.connection(autocommit=True) as conn:
            with self._cursor(conn) as cur:
                if parent_span_id:
                    parent_trace_ts = self._lookup_parent_trace_timestamp(cur, parent_span_id)
                    if parent_trace_ts is not None:
                        trace_timestamp = parent_trace_ts
                    else:
                        # Parent span has not been persisted yet; fall back to treating this span as a root
                        resolved_parent_span_id = None

                cur.execute(
                    """
                    INSERT INTO execution_traces (
                        span_id,
                        trace_id,
                        trace_timestamp,
                        parent_span_id,
                        run_id,
                        action_id,
                        operation_name,
                        service_name,
                        start_time,
                        status,
                        attributes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (span_id, trace_timestamp) DO NOTHING
                    """,
                    (
                        span_id,
                        trace_id,
                        trace_timestamp,
                        resolved_parent_span_id,
                        run_id,
                        action_id,
                        operation_name,
                        service_name,
                        now,
                        "RUNNING",
                        self._json_wrapper(attributes or {}),
                    ),
                )

        span = ExecutionSpan(
            span_id=span_id,
            trace_id=trace_id,
            operation_name=operation_name,
            service_name=service_name,
            start_time=now,
            trace_timestamp=trace_timestamp,
            parent_span_id=resolved_parent_span_id,
            run_id=run_id,
            action_id=action_id,
            status="RUNNING",
            attributes=attributes,
        )

        return span

    def end_span(
        self,
        span: ExecutionSpan,
        *,
        status: str = "SUCCESS",
        error_message: Optional[str] = None,
        token_count: Optional[int] = None,
        behavior_citations: Optional[List[str]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Complete an execution trace span.

        Updates the span with end_time, final status, and optional metadata.
        The duration_ms column is automatically calculated as a GENERATED column.

        Parameters
        ----------
        span:
            The span object returned from start_span().
        status:
            Final status (SUCCESS, ERROR, TIMEOUT, CANCELLED). Defaults to SUCCESS.
        error_message:
            Optional error description if status is ERROR/TIMEOUT/CANCELLED.
        token_count:
            Optional token count for LLM operations.
        behavior_citations:
            Optional list of behavior IDs referenced during this operation.
        events:
            Optional list of span events (structured log entries with timestamps).
        links:
            Optional list of links to other spans/traces.
        """
        now = datetime.now(timezone.utc)

        with self._pool.connection(autocommit=True) as conn:
            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    UPDATE execution_traces
                    SET end_time = %s,
                        status = %s,
                        error_message = %s,
                        token_count = %s,
                        behavior_citations = %s,
                        events = %s,
                        links = %s
                    WHERE span_id = %s
                        AND trace_timestamp = %s
                    """,
                    (
                        now,
                        status,
                        error_message,
                        token_count,
                        behavior_citations if behavior_citations else None,
                        self._json_wrapper(events) if events else None,
                        self._json_wrapper(links) if links else None,
                        span.span_id,
                        span.trace_timestamp,
                    ),
                )

        # Update local span object
        span.end_time = now
        span.status = status
        span.error_message = error_message
        span.token_count = token_count
        span.behavior_citations = behavior_citations
        span.events = events
        span.links = links

    def refresh_metric_views(self) -> None:
        with self._pool.connection(autocommit=True) as conn:
            with self._cursor(conn) as cur:
                cur.execute("SELECT refresh_prd_metric_views();")

    def query_events(
        self,
        *,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        actor_surface: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query telemetry events with filtering.

        Parameters
        ----------
        event_type : Filter by event type (exact match).
        since : Start of time window (ISO 8601 or relative e.g. '7d').
        until : End of time window (ISO 8601).
        run_id / session_id : Correlation filters.
        actor_surface : Surface filter (web, cli, vscode, mcp, api).
        limit : Max results, capped at 1000.
        offset : Pagination offset.

        Returns a list of event dicts suitable for JSON serialisation.
        """
        limit = min(max(limit, 1), 1000)
        offset = max(offset, 0)

        conditions: List[str] = []
        params: List[Any] = []

        if event_type:
            conditions.append("event_type = %s")
            params.append(event_type)
        if run_id:
            conditions.append("run_id = %s")
            params.append(run_id)
        if session_id:
            conditions.append("session_id = %s")
            params.append(session_id)
        if actor_surface:
            conditions.append("actor_surface = %s")
            params.append(normalize_actor_surface(actor_surface))
        if since:
            ts = self._parse_relative_or_iso(since)
            conditions.append("event_timestamp >= %s")
            params.append(ts)
        if until:
            ts = self._parse_relative_or_iso(until)
            conditions.append("event_timestamp <= %s")
            params.append(ts)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"""
            SELECT event_id, event_timestamp, event_type,
                   actor_id, actor_role, actor_surface,
                   run_id, action_id, session_id, payload
            FROM telemetry_events
            {where}
            ORDER BY event_timestamp DESC
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])

        rows: List[Dict[str, Any]] = []
        with self._pool.connection(autocommit=True) as conn:
            with self._cursor(conn) as cur:
                cur.execute(sql, params)
                for row in cur.fetchall():
                    rows.append({
                        "event_id": str(row[0]),
                        "timestamp": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
                        "event_type": row[2],
                        "actor": {"id": row[3], "role": row[4], "surface": row[5]},
                        "run_id": row[6],
                        "action_id": row[7],
                        "session_id": row[8],
                        "payload": row[9] if isinstance(row[9], dict) else {},
                    })
        return rows

    def query_run_summaries(
        self,
        *,
        project_id: str,
        run_id: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query ``observability_run_summary`` for a single project (warehouse views)."""

        limit = min(max(limit, 1), 500)
        offset = max(offset, 0)
        conditions: List[str] = ["project_id = %s"]
        params: List[Any] = [project_id]
        if run_id:
            conditions.append("run_id = %s")
            params.append(run_id)
        if since:
            conditions.append("last_event_at >= %s")
            params.append(self._parse_relative_or_iso(since))
        if until:
            conditions.append("started_at <= %s")
            params.append(self._parse_relative_or_iso(until))
        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT
                run_id,
                started_at,
                last_event_at,
                record_count,
                failed_record_count,
                generation_count,
                tool_call_count,
                span_count,
                primary_trace_id,
                project_id,
                work_item_id,
                surface
            FROM observability_run_summary
            WHERE {where_clause}
            ORDER BY last_event_at DESC NULLS LAST
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        return self._fetch_observability_rows(sql, params, _RUN_SUMMARY_COLUMNS)

    def query_conversation_summaries(
        self,
        *,
        project_id: str,
        conversation_id: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query ``observability_conversation_summary`` for a single project."""

        limit = min(max(limit, 1), 500)
        offset = max(offset, 0)
        conditions: List[str] = ["project_id = %s"]
        params: List[Any] = [project_id]
        if conversation_id:
            conditions.append("conversation_id = %s")
            params.append(conversation_id)
        if since:
            conditions.append("last_event_at >= %s")
            params.append(self._parse_relative_or_iso(since))
        if until:
            conditions.append("started_at <= %s")
            params.append(self._parse_relative_or_iso(until))
        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT
                conversation_id,
                started_at,
                last_event_at,
                record_count,
                trace_count,
                generation_count,
                tool_call_count,
                project_id,
                surface
            FROM observability_conversation_summary
            WHERE {where_clause}
            ORDER BY last_event_at DESC NULLS LAST
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        return self._fetch_observability_rows(sql, params, _CONVERSATION_SUMMARY_COLUMNS)

    def query_span_tree(
        self,
        *,
        project_id: str,
        trace_id: str,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Return ordered span rows for a trace, scoped to ``project_id``."""

        limit = min(max(limit, 1), 2000)
        sql = """
            SELECT
                w.record_id,
                w.record_timestamp,
                w.trace_id,
                w.span_id,
                w.parent_span_id,
                w.name,
                w.status,
                w.kind,
                w.depth
            FROM observability_span_tree w
            WHERE w.trace_id = %s
              AND EXISTS (
                  SELECT 1
                  FROM observability_records o
                  WHERE o.trace_id = w.trace_id
                    AND o.project_id = %s
                  LIMIT 1
              )
            ORDER BY w.depth, w.record_timestamp
            LIMIT %s
        """
        return self._fetch_observability_rows(
            sql,
            [trace_id, project_id, limit],
            _SPAN_TREE_COLUMNS,
        )

    def _fetch_observability_rows(
        self,
        sql: str,
        params: Sequence[Any],
        columns: Sequence[str],
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        try:
            with self._pool.connection(autocommit=True) as conn:
                with self._cursor(conn) as cur:
                    cur.execute(sql, list(params))
                    for raw in cur.fetchall():
                        row: Dict[str, Any] = {}
                        for idx, key in enumerate(columns):
                            value = raw[idx]
                            if value is None:
                                row[key] = None
                            elif hasattr(value, "isoformat"):
                                row[key] = value.isoformat()
                            elif isinstance(value, uuid.UUID):
                                row[key] = str(value)
                            else:
                                row[key] = value
                        rows.append(row)
        except Exception:
            # Missing views/tables (migrations not applied) or connection errors — treat as empty.
            return []
        return rows

    @staticmethod
    def _parse_relative_or_iso(value: str) -> datetime:
        """Parse an ISO timestamp string or a relative duration like '7d', '24h'."""
        import re as _re
        m = _re.fullmatch(r"(\d+)([dhms])", value.strip())
        if m:
            amount, unit = int(m.group(1)), m.group(2)
            delta = {"d": timedelta(days=amount), "h": timedelta(hours=amount),
                     "m": timedelta(minutes=amount), "s": timedelta(seconds=amount)}[unit]
            return datetime.now(timezone.utc) - delta
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def close(self) -> None:
        """Close the connection pool (no-op with shared PostgresPool)."""
        # PostgresPool is shared across the application, so we don't close it
        pass

    def _ensure_connection(self):
        """Provide a pooled connection proxy for tests and admin checks."""
        return self._pool.proxy(autocommit=True)

    @contextmanager
    def _cursor(self, conn) -> Iterator[Any]:
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(timezone.utc)

    @staticmethod
    def _coerce_uuid(value: Optional[str]) -> uuid.UUID:
        if not value:
            return uuid.uuid4()
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError):
            return uuid.uuid4()

    @staticmethod
    def _coerce_int(value: Optional[object]) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Optional[object]) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_string_list(value: Optional[object]) -> List[str]:
        result: MutableSequence[str] = []
        if isinstance(value, str):
            if value:
                result.append(value)
        elif isinstance(value, Sequence):
            for item in value:
                if isinstance(item, str) and item:
                    result.append(item)
        return list(dict.fromkeys(result))  # De-dupe while preserving order

    @staticmethod
    def _lookup_parent_trace_timestamp(cursor, parent_span_id: str) -> Optional[datetime]:
        cursor.execute(
            """
            SELECT trace_timestamp
            FROM execution_traces
            WHERE span_id = %s
            ORDER BY trace_timestamp DESC
            LIMIT 1
            """,
            (parent_span_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return row[0]

    def _project_event(self, conn, event: TelemetryEvent, ts: datetime, actor: dict) -> None:
        payload = dict(event.payload)
        event_type = event.event_type
        run_id = event.run_id or payload.get("run_id")

        if event_type == "plan_created" and run_id:
            behavior_ids = self._normalize_string_list(payload.get("behavior_ids"))
            baseline_tokens = self._coerce_int(payload.get("baseline_tokens"))
            template_id = payload.get("template_id")
            template_name = payload.get("template_name")

            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO fact_behavior_usage (
                        run_id,
                        template_id,
                        template_name,
                        behavior_ids,
                        behavior_count,
                        has_behaviors,
                        baseline_tokens,
                        actor_surface,
                        actor_role,
                        first_plan_timestamp
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE
                        SET template_id = COALESCE(EXCLUDED.template_id, fact_behavior_usage.template_id),
                            template_name = COALESCE(EXCLUDED.template_name, fact_behavior_usage.template_name),
                            behavior_ids = EXCLUDED.behavior_ids,
                            behavior_count = EXCLUDED.behavior_count,
                            has_behaviors = EXCLUDED.has_behaviors,
                            baseline_tokens = COALESCE(EXCLUDED.baseline_tokens, fact_behavior_usage.baseline_tokens),
                            actor_surface = COALESCE(EXCLUDED.actor_surface, fact_behavior_usage.actor_surface),
                            actor_role = COALESCE(EXCLUDED.actor_role, fact_behavior_usage.actor_role),
                            first_plan_timestamp = COALESCE(fact_behavior_usage.first_plan_timestamp, EXCLUDED.first_plan_timestamp)
                    """,
                    (
                        run_id,
                        template_id,
                        template_name,
                        self._json_wrapper(behavior_ids),
                        len(behavior_ids),
                        bool(behavior_ids),
                        baseline_tokens,
                        actor.get("surface"),
                        actor.get("role"),
                        ts,
                    ),
                )

        elif event_type == "execution_update" and run_id:
            template_id = payload.get("template_id")
            output_tokens = self._coerce_int(payload.get("output_tokens"))
            baseline_tokens = self._coerce_int(payload.get("baseline_tokens"))
            token_savings_pct = self._coerce_float(payload.get("token_savings_pct"))
            status = payload.get("status")
            actor_surface = actor.get("surface")
            actor_role = actor.get("role")

            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO fact_token_savings (
                        run_id,
                        template_id,
                        output_tokens,
                        baseline_tokens,
                        token_savings_pct
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE
                        SET template_id = COALESCE(EXCLUDED.template_id, fact_token_savings.template_id),
                            output_tokens = COALESCE(EXCLUDED.output_tokens, fact_token_savings.output_tokens),
                            baseline_tokens = COALESCE(EXCLUDED.baseline_tokens, fact_token_savings.baseline_tokens),
                            token_savings_pct = COALESCE(EXCLUDED.token_savings_pct, fact_token_savings.token_savings_pct)
                    """,
                    (
                        run_id,
                        template_id,
                        output_tokens,
                        baseline_tokens,
                        token_savings_pct,
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO fact_execution_status (
                        run_id,
                        template_id,
                        status,
                        actor_surface,
                        actor_role,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE
                        SET template_id = COALESCE(EXCLUDED.template_id, fact_execution_status.template_id),
                            status = COALESCE(EXCLUDED.status, fact_execution_status.status),
                            actor_surface = COALESCE(EXCLUDED.actor_surface, fact_execution_status.actor_surface),
                            actor_role = COALESCE(EXCLUDED.actor_role, fact_execution_status.actor_role),
                            updated_at = EXCLUDED.updated_at
                    """,
                    (
                        run_id,
                        template_id,
                        status,
                        actor_surface,
                        actor_role,
                        ts,
                    ),
                )

        elif event_type == "compliance_step_recorded":
            checklist_id = payload.get("checklist_id")
            step_id = payload.get("step_id")
            status = payload.get("status")
            coverage_score = self._coerce_float(payload.get("coverage_score"))
            session_id = event.session_id or payload.get("session_id")
            behaviors = self._normalize_string_list(payload.get("behavior_ids"))

            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO fact_compliance_steps (
                        checklist_id,
                        step_id,
                        status,
                        coverage_score,
                        run_id,
                        session_id,
                        behavior_ids,
                        event_timestamp
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        checklist_id,
                        step_id,
                        status,
                        coverage_score,
                        run_id,
                        session_id,
                        behaviors if behaviors else None,
                        ts,
                    ),
                )

        elif event_type == "behavior_retrieved":
            behaviors = self._normalize_string_list(payload.get("behavior_ids"))
            session_id = event.session_id or payload.get("session_id")
            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO fact_compliance_steps (
                        checklist_id,
                        step_id,
                        status,
                        coverage_score,
                        run_id,
                        session_id,
                        behavior_ids,
                        event_timestamp
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        None,
                        None,
                        "BEHAVIOR_RETRIEVAL",
                        None,
                        run_id,
                        session_id,
                        behaviors if behaviors else None,
                        ts,
                    ),
                )

        elif event_type in {
            "reflection.candidate_extracted",
            "reflection.candidate_approved",
            "reflection.candidate_rejected",
        }:
            self._project_behavior_candidate_record(
                conn=conn,
                event=event,
                ts=ts,
                actor=actor,
                payload=payload,
                run_id=run_id,
            )

        elif event_type.startswith("execution.gateway."):
            self._project_execution_gateway_record(
                conn=conn,
                event=event,
                ts=ts,
                actor=actor,
                payload=payload,
                run_id=run_id,
            )

        elif event_type == "execution.llm.completed":
            self._project_execution_llm_generation_record(
                conn=conn,
                event=event,
                ts=ts,
                actor=actor,
                payload=payload,
                run_id=run_id,
            )

        elif event_type.startswith("execution.worker."):
            self._project_worker_observability(
                conn, event, ts, actor, payload, run_id,
            )

        elif event_type.startswith("execution.phase."):
            self._project_phase_observability(
                conn, event, ts, actor, payload, run_id,
            )

        elif event_type.startswith("execution.tool."):
            self._project_execution_tool_observability(
                conn, event, ts, actor, payload, run_id,
            )

        elif event_type.startswith("behaviors."):
            self._project_behaviors_observability(
                conn, event, ts, actor, payload, run_id,
            )

        elif event_type.startswith("llm.generation."):
            self._project_llm_generation_observability(
                conn, event, ts, actor, payload, run_id,
            )

        elif event_type.startswith("chat.") or event_type == "conversation_reply.generated":
            self._project_chat_observability(
                conn, event, ts, actor, payload, run_id,
            )

    def _trace_span_ids_for_execution(
        self,
        payload: Dict[str, Any],
        run_id: Optional[str],
        event: TelemetryEvent,
        *,
        suffix: str,
    ) -> tuple[str, str]:
        """Resolve stable trace_id and span_id strings for execution telemetry."""
        eo = self._execution_observability(payload)
        trace_id = (
            self._string_value(eo.get("trace_id"))
            or (self._string_value(run_id) and f"run:{run_id}")
            or str(event.event_id)
        )
        span_id = (
            self._string_value(eo.get("span_id"))
            or f"{suffix}:{event.event_id}"
        )
        return trace_id, span_id

    def _resolve_trace_span_parent(
        self,
        payload: Dict[str, Any],
        run_id: Optional[str],
        event: TelemetryEvent,
        *,
        suffix: str,
    ) -> tuple[str, str, Optional[str]]:
        """Prefer explicit chat/execution trace IDs; fall back to EO + run-based IDs."""

        trace_id = self._string_value(payload.get("trace_id"))
        span_id = self._string_value(payload.get("span_id"))
        parent_span_id = self._string_value(payload.get("parent_span_id"))
        chat_trace = payload.get("chat_trace")
        if isinstance(chat_trace, dict):
            trace_id = trace_id or self._string_value(chat_trace.get("trace_id"))
            span_id = span_id or self._string_value(chat_trace.get("span_id"))
            parent_span_id = parent_span_id or self._string_value(chat_trace.get("parent_span_id"))
        if trace_id and span_id:
            return trace_id, span_id, parent_span_id
        trace_id2, span_id2 = self._trace_span_ids_for_execution(
            payload, run_id, event, suffix=suffix,
        )
        return trace_id2, span_id2, parent_span_id

    @staticmethod
    def _eo_or_payload_str(
        eo: Dict[str, Any], payload: Dict[str, Any], key: str,
    ) -> Optional[str]:
        return PostgresTelemetryWarehouse._string_value(
            eo.get(key),
        ) or PostgresTelemetryWarehouse._string_value(payload.get(key))

    @staticmethod
    def _infer_observability_status(event_type: str) -> str:
        if event_type.endswith(".started"):
            return "started"
        if event_type.endswith(".failed"):
            return "failed"
        if event_type.endswith(".denied"):
            return "denied"
        return "completed"

    def _append_observability_record(
        self,
        conn: Any,
        *,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
        run_id: Optional[str],
        eo: Dict[str, Any],
        trace_id: str,
        span_id: str,
        parent_span_id: Optional[str],
        kind: str,
        name: str,
        status: str,
        sensitivity: str,
        data_class: str,
        phase: Optional[str],
        model_id: Optional[str],
        tool_call_id: Optional[str],
        behavior_id: Optional[str],
        attributes: Dict[str, Any],
        retention_days: int = 1095,
    ) -> None:
        """Insert one row into observability_records (canonical envelope storage)."""

        surface = (
            self._string_value(eo.get("surface"))
            or actor.get("surface")
            or self._string_value(payload.get("surface"))
            or "api"
        )
        project_id = self._eo_or_payload_str(eo, payload, "project_id")
        org_id = self._eo_or_payload_str(eo, payload, "org_id")
        work_item_id = self._eo_or_payload_str(eo, payload, "work_item_id")
        cycle_id = self._eo_or_payload_str(eo, payload, "cycle_id")
        message_id = (
            self._eo_or_payload_str(eo, payload, "message_id")
            or self._string_value(payload.get("user_message_id"))
        )
        conversation_id = (
            self._eo_or_payload_str(eo, payload, "conversation_id")
            or event.session_id
        )
        payload_json = sanitize_observability_payload(payload)
        retention_until = ts + timedelta(days=retention_days)
        correlation = {
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "run_id": self._string_value(run_id),
            "cycle_id": cycle_id,
            "work_item_id": work_item_id,
            "project_id": project_id,
            "org_id": org_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "surface": surface,
            "phase": phase,
            "queue_job_id": self._string_value(eo.get("queue_job_id")),
        }

        with self._cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO observability_records (
                    record_id,
                    record_timestamp,
                    kind,
                    name,
                    status,
                    sensitivity,
                    trace_id,
                    span_id,
                    parent_span_id,
                    org_id,
                    project_id,
                    conversation_id,
                    message_id,
                    run_id,
                    cycle_id,
                    work_item_id,
                    action_id,
                    tool_call_id,
                    llm_call_id,
                    behavior_id,
                    actor_id,
                    actor_role,
                    surface,
                    permission_action,
                    model_id,
                    queue_job_id,
                    phase,
                    correlation,
                    attributes,
                    payload,
                    data_class,
                    retention_until,
                    archived_after,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (record_id, record_timestamp) DO NOTHING
                """,
                (
                    event.event_id,
                    ts,
                    kind,
                    name,
                    status,
                    sensitivity,
                    trace_id,
                    span_id,
                    parent_span_id,
                    org_id,
                    project_id,
                    conversation_id,
                    message_id,
                    self._string_value(run_id),
                    cycle_id,
                    work_item_id,
                    event.action_id,
                    tool_call_id,
                    None,
                    behavior_id,
                    actor.get("id"),
                    actor.get("role"),
                    surface,
                    None,
                    model_id,
                    self._string_value(eo.get("queue_job_id")),
                    phase,
                    self._json_wrapper(correlation),
                    self._json_wrapper(sanitize_observability_payload(attributes)),
                    self._json_wrapper(payload_json),
                    data_class,
                    retention_until,
                    None,
                ),
            )

    def _project_execution_gateway_record(
        self,
        *,
        conn: Any,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
        run_id: Optional[str],
    ) -> None:
        """Project execution gateway events into observability_records (event kind)."""
        eo = self._execution_observability(payload)
        trace_id, span_id, _parent = self._resolve_trace_span_parent(
            payload, run_id, event, suffix=f"gateway:{event.event_type}",
        )
        status_map = {
            "execution.gateway.started": "started",
            "execution.gateway.enqueued": "completed",
            "execution.gateway.completed": "completed",
            "execution.gateway.failed": "failed",
        }
        status = status_map.get(event.event_type, "completed")
        self._append_observability_record(
            conn,
            event=event,
            ts=ts,
            actor=actor,
            payload=payload,
            run_id=run_id,
            eo=eo,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            kind="event",
            name=event.event_type,
            status=status,
            sensitivity="metadata",
            data_class="metadata_trace",
            phase=None,
            model_id=self._string_value(payload.get("model_id")),
            tool_call_id=None,
            behavior_id=None,
            attributes={"gateway_event": event.event_type},
        )

    def _project_worker_observability(
        self,
        conn: Any,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
        run_id: Optional[str],
    ) -> None:
        eo = self._execution_observability(payload)
        trace_id, span_id, parent = self._resolve_trace_span_parent(
            payload, run_id, event, suffix=event.event_type,
        )
        status = self._infer_observability_status(event.event_type)
        self._append_observability_record(
            conn,
            event=event,
            ts=ts,
            actor=actor,
            payload=payload,
            run_id=run_id,
            eo=eo,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent,
            kind="event",
            name=event.event_type,
            status=status,
            sensitivity="metadata",
            data_class="metadata_trace",
            phase=None,
            model_id=None,
            tool_call_id=None,
            behavior_id=None,
            attributes={"job_id": payload.get("job_id")},
        )

    def _project_phase_observability(
        self,
        conn: Any,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
        run_id: Optional[str],
    ) -> None:
        eo = self._execution_observability(payload)
        trace_id, span_id, parent = self._resolve_trace_span_parent(
            payload, run_id, event, suffix=event.event_type,
        )
        status = self._string_value(payload.get("status")) or self._infer_observability_status(
            event.event_type,
        )
        phase = self._string_value(payload.get("phase"))
        self._append_observability_record(
            conn,
            event=event,
            ts=ts,
            actor=actor,
            payload=payload,
            run_id=run_id,
            eo=eo,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent,
            kind="event",
            name=event.event_type,
            status=status,
            sensitivity="metadata",
            data_class="metadata_trace",
            phase=phase,
            model_id=None,
            tool_call_id=None,
            behavior_id=None,
            attributes={
                "phase": phase,
                "tool_call_count": payload.get("tool_call_count"),
            },
        )

    def _project_execution_tool_business_outcome_observability(
        self,
        conn: Any,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
        run_id: Optional[str],
    ) -> None:
        eo = self._execution_observability(payload)
        trace_id, span_id, parent = self._resolve_trace_span_parent(
            payload, run_id, event, suffix=event.event_type,
        )
        call_id = self._string_value(payload.get("call_id"))
        self._append_observability_record(
            conn,
            event=event,
            ts=ts,
            actor=actor,
            payload=payload,
            run_id=run_id,
            eo=eo,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent,
            kind="outcome",
            name=event.event_type,
            status="completed",
            sensitivity="summary",
            data_class="metadata_trace",
            phase=self._string_value(payload.get("phase")),
            model_id=None,
            tool_call_id=call_id,
            behavior_id=None,
            attributes={
                "outcome_type": payload.get("outcome_type"),
                "resource_type": payload.get("resource_type"),
                "resource_id": payload.get("resource_id"),
                "outcome_ref": payload.get("outcome_ref"),
            },
        )
        self._maybe_insert_observability_outcome_typed(
            conn,
            record_id=event.event_id,
            ts=ts,
            trace_id=trace_id,
            span_id=span_id,
            run_id=self._string_value(run_id),
            work_item_id=self._eo_or_payload_str(eo, payload, "work_item_id"),
            outcome_type=self._string_value(payload.get("outcome_type")),
            outcome_ref=self._string_value(payload.get("outcome_ref")),
            resource_type=self._string_value(payload.get("resource_type")),
            resource_id=self._string_value(payload.get("resource_id")),
            status="completed",
        )

    def _project_execution_tool_observability(
        self,
        conn: Any,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
        run_id: Optional[str],
    ) -> None:
        if event.event_type == "execution.tool.business_outcome":
            self._project_execution_tool_business_outcome_observability(
                conn, event, ts, actor, payload, run_id,
            )
            return

        eo = self._execution_observability(payload)
        trace_id, span_id, parent = self._resolve_trace_span_parent(
            payload, run_id, event, suffix=event.event_type,
        )
        tool_name = self._string_value(payload.get("tool_name"))
        call_id = self._string_value(payload.get("call_id"))
        phase = self._string_value(payload.get("phase"))
        if event.event_type == "execution.tool.performance":
            row_status = self._string_value(payload.get("status")) or "completed"
            sensitivity = "metadata"
            data_class = "metadata_trace"
        elif event.event_type in ("execution.tool.failed", "execution.tool.denied"):
            row_status = self._infer_observability_status(event.event_type)
            sensitivity = "restricted"
            data_class = "metadata_trace"
        else:
            row_status = self._infer_observability_status(event.event_type)
            sensitivity = "summary"
            data_class = "summary"

        self._append_observability_record(
            conn,
            event=event,
            ts=ts,
            actor=actor,
            payload=payload,
            run_id=run_id,
            eo=eo,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent,
            kind="tool_call",
            name=event.event_type,
            status=row_status,
            sensitivity=sensitivity,
            data_class=data_class,
            phase=phase,
            model_id=None,
            tool_call_id=call_id,
            behavior_id=None,
            attributes={"tool_name": tool_name},
        )

        if event.event_type in {
            "execution.tool.completed",
            "execution.tool.performance",
            "execution.tool.failed",
            "execution.tool.denied",
        }:
            elapsed = self._coerce_int(payload.get("elapsed_ms"))
            self._maybe_insert_observability_tool_typed(
                conn,
                record_id=event.event_id,
                ts=ts,
                trace_id=trace_id,
                span_id=span_id,
                run_id=self._string_value(run_id),
                work_item_id=self._eo_or_payload_str(eo, payload, "work_item_id"),
                tool_name=tool_name,
                call_id=call_id,
                elapsed_ms=float(elapsed) if elapsed is not None else None,
                status=row_status,
                input_summary=payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {},
                output_summary=(
                    {"preview": payload.get("output_preview")}
                    if payload.get("output_preview") is not None
                    else {}
                ),
            )

    def _project_llm_generation_observability(
        self,
        conn: Any,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
        run_id: Optional[str],
    ) -> None:
        eo = self._execution_observability(payload)
        trace_id, span_id, parent = self._resolve_trace_span_parent(
            payload, run_id, event, suffix=event.event_type,
        )
        model_id = self._string_value(payload.get("model_id") or eo.get("model_id"))
        status = "failed" if event.event_type.endswith(".failed") else "completed"
        latency_ms = self._coerce_int(payload.get("latency_ms"))
        input_tokens = self._coerce_int(payload.get("input_tokens"))
        output_tokens = self._coerce_int(payload.get("output_tokens"))
        cost_usd = self._coerce_float(payload.get("cost_usd"))
        error_class = self._string_value(payload.get("error_class")) if status == "failed" else None
        self._append_observability_record(
            conn,
            event=event,
            ts=ts,
            actor=actor,
            payload=payload,
            run_id=run_id,
            eo=eo,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent,
            kind="generation",
            name=event.event_type,
            status=status,
            sensitivity="summary",
            data_class="summary",
            phase=None,
            model_id=model_id,
            tool_call_id=None,
            behavior_id=None,
            attributes={
                "provider": payload.get("provider"),
                "operation": payload.get("operation"),
            },
        )
        self._maybe_insert_observability_generation_typed(
            conn,
            record_id=event.event_id,
            ts=ts,
            trace_id=trace_id,
            span_id=span_id,
            run_id=self._string_value(run_id),
            work_item_id=self._eo_or_payload_str(eo, payload, "work_item_id"),
            model_id=model_id,
            provider=self._string_value(payload.get("provider")),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            status=status,
            error_class=error_class,
        )

    def _project_behaviors_observability(
        self,
        conn: Any,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
        run_id: Optional[str],
    ) -> None:
        """Project behaviors.* product telemetry into observability_records."""

        session = event.session_id
        trace_id = self._string_value(payload.get("trace_id"))
        span_id = self._string_value(payload.get("span_id"))
        if not trace_id:
            trace_id = f"behaviors:{session}" if session else f"behaviors:{event.event_id}"
        if not span_id:
            span_id = event.event_type
        eo: Dict[str, Any] = {}
        status = (
            "failed"
            if event.event_type.endswith(".failed")
            else self._infer_observability_status(event.event_type)
        )
        self._append_observability_record(
            conn,
            event=event,
            ts=ts,
            actor=actor,
            payload=payload,
            run_id=run_id,
            eo=eo,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            kind="event",
            name=event.event_type,
            status=status,
            sensitivity="metadata",
            data_class="metadata_trace",
            phase="behaviors",
            model_id=None,
            tool_call_id=None,
            behavior_id=None,
            attributes={
                "results": payload.get("results"),
                "behaviors_found": payload.get("behaviors_found"),
                "recommended_count": payload.get("recommended_count"),
            },
        )

    def _project_chat_observability(
        self,
        conn: Any,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
        run_id: Optional[str],
    ) -> None:
        eo = self._execution_observability(payload)
        trace_id, span_id, parent = self._resolve_trace_span_parent(
            payload, run_id, event, suffix=event.event_type,
        )
        et = event.event_type
        if et.startswith("chat.trace."):
            kind = "trace"
        elif et.startswith("chat.span."):
            kind = "span"
        else:
            kind = "event"
        status = self._string_value(payload.get("status")) or self._infer_observability_status(et)
        if et == "conversation_reply.generated":
            status = "completed"
        self._append_observability_record(
            conn,
            event=event,
            ts=ts,
            actor=actor,
            payload=payload,
            run_id=run_id,
            eo=eo,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent,
            kind=kind,
            name=et,
            status=status,
            sensitivity="metadata",
            data_class="metadata_trace",
            phase=self._string_value(payload.get("phase")),
            model_id=self._string_value(payload.get("planner_model_id")),
            tool_call_id=None,
            behavior_id=None,
            attributes={"span_name": payload.get("span_name")},
        )

    def _project_execution_llm_generation_record(
        self,
        *,
        conn: Any,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
        run_id: Optional[str],
    ) -> None:
        """Project execution.llm.completed into observability_records and observability_generations."""
        eo = self._execution_observability(payload)
        trace_id, span_id = self._trace_span_ids_for_execution(
            payload, run_id, event, suffix="execution.llm",
        )
        model_id = self._string_value(payload.get("model_id") or eo.get("model_id"))
        surface = (
            self._string_value(eo.get("surface"))
            or actor.get("surface")
            or "api"
        )
        input_tokens = self._coerce_int(payload.get("input_tokens"))
        output_tokens = self._coerce_int(payload.get("output_tokens"))
        cost_usd = self._coerce_float(payload.get("cost_usd"))
        duration_ms = self._coerce_int(payload.get("duration_ms"))
        phase = self._string_value(payload.get("phase"))
        payload_json = sanitize_observability_payload(payload)
        retention_until = ts + timedelta(days=1095)
        correlation = {
            "trace_id": trace_id,
            "span_id": span_id,
            "run_id": self._string_value(run_id),
            "cycle_id": self._string_value(eo.get("cycle_id")),
            "work_item_id": self._string_value(eo.get("work_item_id")),
            "project_id": self._string_value(eo.get("project_id")),
            "org_id": self._string_value(eo.get("org_id")),
            "conversation_id": self._string_value(eo.get("conversation_id")),
            "message_id": self._string_value(eo.get("message_id")),
            "surface": surface,
            "phase": phase,
            "queue_job_id": self._string_value(eo.get("queue_job_id")),
        }
        conversation_id = self._string_value(eo.get("conversation_id")) or event.session_id
        attributes = {
            "phase": phase,
            "response_model_id": payload.get("response_model_id"),
            "tool_call_count": payload.get("tool_call_count"),
        }

        with self._cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO observability_records (
                    record_id,
                    record_timestamp,
                    kind,
                    name,
                    status,
                    sensitivity,
                    trace_id,
                    span_id,
                    parent_span_id,
                    org_id,
                    project_id,
                    conversation_id,
                    message_id,
                    run_id,
                    cycle_id,
                    work_item_id,
                    action_id,
                    tool_call_id,
                    llm_call_id,
                    behavior_id,
                    actor_id,
                    actor_role,
                    surface,
                    permission_action,
                    model_id,
                    queue_job_id,
                    phase,
                    correlation,
                    attributes,
                    payload,
                    data_class,
                    retention_until,
                    archived_after,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (record_id, record_timestamp) DO NOTHING
                """,
                (
                    event.event_id,
                    ts,
                    "generation",
                    "execution.llm.completed",
                    "completed",
                    "summary",
                    trace_id,
                    span_id,
                    None,
                    self._string_value(eo.get("org_id")),
                    self._string_value(eo.get("project_id")),
                    conversation_id,
                    self._string_value(eo.get("message_id")),
                    self._string_value(run_id),
                    self._string_value(eo.get("cycle_id")),
                    self._string_value(eo.get("work_item_id")),
                    event.action_id,
                    None,
                    None,
                    None,
                    actor.get("id"),
                    actor.get("role"),
                    surface,
                    None,
                    model_id,
                    self._string_value(eo.get("queue_job_id")),
                    phase,
                    self._json_wrapper(correlation),
                    self._json_wrapper(sanitize_observability_payload(attributes)),
                    self._json_wrapper(payload_json),
                    "summary",
                    retention_until,
                    None,
                ),
            )

        self._maybe_insert_observability_generation_typed(
            conn,
            record_id=event.event_id,
            ts=ts,
            trace_id=trace_id,
            span_id=span_id,
            run_id=self._string_value(run_id),
            work_item_id=self._string_value(eo.get("work_item_id")),
            model_id=model_id,
            provider=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=duration_ms,
            status="completed",
            error_class=None,
        )

    def _maybe_insert_observability_generation_typed(
        self,
        conn: Any,
        *,
        record_id: str,
        ts: datetime,
        trace_id: str,
        span_id: str,
        run_id: Optional[str],
        work_item_id: Optional[str],
        model_id: Optional[str],
        provider: Optional[str],
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        cost_usd: Optional[float],
        latency_ms: Optional[int],
        status: str,
        error_class: Optional[str] = None,
    ) -> None:
        """Insert into observability_generations when the typed table exists (telemetry migration)."""
        try:
            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO observability_generations (
                        record_id,
                        record_timestamp,
                        trace_id,
                        span_id,
                        run_id,
                        work_item_id,
                        provider,
                        model_id,
                        input_tokens,
                        output_tokens,
                        cost_usd,
                        latency_ms,
                        first_token_latency_ms,
                        credential_scope,
                        status,
                        error_class,
                        attributes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (record_id, record_timestamp) DO NOTHING
                    """,
                    (
                        record_id,
                        ts,
                        trace_id,
                        span_id,
                        run_id,
                        work_item_id,
                        provider,
                        model_id,
                        input_tokens,
                        output_tokens,
                        cost_usd,
                        float(latency_ms) if latency_ms is not None else None,
                        None,
                        None,
                        status,
                        error_class,
                        self._json_wrapper({}),
                    ),
                )
        except Exception:
            # Typed projection table may be absent on older telemetry DBs; canonical rows remain.
            pass

    def _maybe_insert_observability_tool_typed(
        self,
        conn: Any,
        *,
        record_id: str,
        ts: datetime,
        trace_id: str,
        span_id: str,
        run_id: Optional[str],
        work_item_id: Optional[str],
        tool_name: Optional[str],
        call_id: Optional[str],
        elapsed_ms: Optional[float],
        status: str,
        input_summary: Dict[str, Any],
        output_summary: Dict[str, Any],
    ) -> None:
        try:
            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO observability_tool_calls (
                        record_id,
                        record_timestamp,
                        trace_id,
                        span_id,
                        run_id,
                        work_item_id,
                        tool_name,
                        call_id,
                        elapsed_ms,
                        status,
                        target_resource_type,
                        target_resource_id,
                        input_summary,
                        output_summary,
                        attributes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (record_id, record_timestamp) DO NOTHING
                    """,
                    (
                        record_id,
                        ts,
                        trace_id,
                        span_id,
                        run_id,
                        work_item_id,
                        tool_name,
                        call_id,
                        elapsed_ms,
                        status,
                        None,
                        None,
                        self._json_wrapper(input_summary or {}),
                        self._json_wrapper(output_summary or {}),
                        self._json_wrapper({}),
                    ),
                )
        except Exception:
            pass

    def _maybe_insert_observability_outcome_typed(
        self,
        conn: Any,
        *,
        record_id: str,
        ts: datetime,
        trace_id: str,
        span_id: str,
        run_id: Optional[str],
        work_item_id: Optional[str],
        outcome_type: Optional[str],
        outcome_ref: Optional[str],
        resource_type: Optional[str],
        resource_id: Optional[str],
        status: str,
    ) -> None:
        try:
            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO observability_outcomes (
                        record_id,
                        record_timestamp,
                        trace_id,
                        span_id,
                        run_id,
                        work_item_id,
                        outcome_type,
                        outcome_ref,
                        resource_type,
                        resource_id,
                        status,
                        attributes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (record_id, record_timestamp) DO NOTHING
                    """,
                    (
                        record_id,
                        ts,
                        trace_id,
                        span_id,
                        run_id,
                        work_item_id,
                        outcome_type,
                        outcome_ref,
                        resource_type,
                        resource_id,
                        status,
                        self._json_wrapper({}),
                    ),
                )
        except Exception:
            pass

    def record_completed_execution_trace(
        self,
        *,
        trace_id: str,
        span_id: str,
        run_id: Optional[str],
        operation_name: str,
        duration_ms: int,
        service_name: str = "amprealize",
        input_tokens: int = 0,
        output_tokens: int = 0,
        status: str = "OK",
        status_message: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        action_id: Optional[str] = None,
    ) -> None:
        """Insert a completed execution_traces row in one shot (for LLM phase metrics)."""
        tid = self._coerce_uuid(trace_id)
        sid = self._coerce_uuid(span_id)
        end = datetime.now(timezone.utc)
        start = end - timedelta(milliseconds=max(int(duration_ms or 0), 0))
        trace_ts = end

        with self._pool.connection(autocommit=True) as conn:
            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO execution_traces (
                        trace_id,
                        span_id,
                        trace_timestamp,
                        parent_span_id,
                        run_id,
                        action_id,
                        operation_name,
                        service_name,
                        start_time,
                        end_time,
                        status,
                        status_message,
                        attributes,
                        input_tokens,
                        output_tokens
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (span_id, trace_timestamp) DO NOTHING
                    """,
                    (
                        str(tid),
                        str(sid),
                        trace_ts,
                        None,
                        run_id,
                        action_id,
                        operation_name,
                        service_name,
                        start,
                        end,
                        status,
                        status_message,
                        self._json_wrapper(attributes or {}),
                        input_tokens or 0,
                        output_tokens or 0,
                    ),
                )

    def _project_behavior_candidate_record(
        self,
        *,
        conn: Any,
        event: TelemetryEvent,
        ts: datetime,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
        run_id: Optional[str],
    ) -> None:
        """Project reflection candidate telemetry into canonical observability records."""
        execution_observability = self._execution_observability(payload)
        source_trace_ids = self._normalize_string_list(payload.get("source_trace_ids"))
        candidate_id = payload.get("candidate_id") or payload.get("candidate_slug") or event.event_id
        trace_id = (
            source_trace_ids[0]
            if source_trace_ids
            else self._string_value(execution_observability.get("trace_id"))
            or self._string_value(run_id)
            or f"candidate:{candidate_id}"
        )
        span_id = f"candidate:{candidate_id}:{event.event_id}"
        surface = (
            self._string_value(execution_observability.get("surface"))
            or actor.get("surface")
            or "api"
        )
        status = "denied" if event.event_type == "reflection.candidate_rejected" else "completed"
        payload_json = sanitize_observability_payload(payload)
        retention_until = ts + timedelta(days=1095)
        correlation = {
            "trace_id": trace_id,
            "span_id": span_id,
            "run_id": run_id,
            "cycle_id": self._string_value(execution_observability.get("cycle_id")),
            "work_item_id": self._string_value(execution_observability.get("work_item_id")),
            "project_id": self._string_value(execution_observability.get("project_id")),
            "org_id": self._string_value(execution_observability.get("org_id")),
            "conversation_id": self._string_value(execution_observability.get("conversation_id")),
            "message_id": self._string_value(execution_observability.get("message_id")),
            "surface": surface,
            "phase": self._string_value(execution_observability.get("phase")),
            "queue_job_id": self._string_value(execution_observability.get("queue_job_id")),
        }
        attributes = {
            "candidate_id": self._string_value(candidate_id),
            "source_trace_ids": source_trace_ids,
            "reviewer_role": payload.get("reviewer_role"),
            "rejection_reason": payload.get("rejection_reason"),
            "pattern_id": payload.get("pattern_id"),
            "behavior_id": payload.get("behavior_id"),
            "auto_approved": payload.get("auto_approved"),
            "confidence": payload.get("confidence"),
            "quality_scores": payload.get("quality_scores"),
            "extraction_job_id": payload.get("extraction_job_id"),
        }

        with self._cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO observability_records (
                    record_id,
                    record_timestamp,
                    kind,
                    name,
                    status,
                    sensitivity,
                    trace_id,
                    span_id,
                    parent_span_id,
                    org_id,
                    project_id,
                    conversation_id,
                    message_id,
                    run_id,
                    cycle_id,
                    work_item_id,
                    action_id,
                    tool_call_id,
                    llm_call_id,
                    behavior_id,
                    actor_id,
                    actor_role,
                    surface,
                    permission_action,
                    model_id,
                    queue_job_id,
                    phase,
                    correlation,
                    attributes,
                    payload,
                    data_class,
                    retention_until,
                    archived_after,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (record_id, record_timestamp) DO NOTHING
                """,
                (
                    event.event_id,
                    ts,
                    "behavior_candidate",
                    event.event_type,
                    status,
                    "summary",
                    trace_id,
                    span_id,
                    None,
                    self._string_value(execution_observability.get("org_id")),
                    self._string_value(execution_observability.get("project_id")),
                    self._string_value(execution_observability.get("conversation_id")),
                    self._string_value(execution_observability.get("message_id")),
                    self._string_value(run_id),
                    self._string_value(execution_observability.get("cycle_id")),
                    self._string_value(execution_observability.get("work_item_id")),
                    event.action_id,
                    None,
                    None,
                    self._string_value(payload.get("behavior_id")),
                    actor.get("id"),
                    actor.get("role"),
                    surface,
                    None,
                    None,
                    self._string_value(execution_observability.get("queue_job_id")),
                    self._string_value(execution_observability.get("phase")),
                    self._json_wrapper(correlation),
                    self._json_wrapper(sanitize_observability_payload(attributes)),
                    self._json_wrapper(payload_json),
                    "behavior_mining_feature",
                    retention_until,
                    None,
                ),
            )

    @staticmethod
    def _execution_observability(payload: Dict[str, Any]) -> Dict[str, Any]:
        value = payload.get("execution_observability")
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _string_value(value: Optional[object]) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value or None
        return str(value)


class PostgresTelemetrySink(TelemetrySink):
    """A :class:`TelemetrySink` implementation that writes to PostgreSQL.

    Supports both telemetry event ingestion and distributed execution tracing
    via the TimescaleDB-backed execution_traces hypertable.
    """

    def __init__(self, dsn: str, *, connect_timeout: int = 5) -> None:
        self._warehouse = PostgresTelemetryWarehouse(dsn, connect_timeout=connect_timeout)

    def write(self, event: TelemetryEvent) -> None:
        self._warehouse.write_event(event)

    def start_span(
        self,
        trace_id: str,
        span_id: str,
        operation_name: str,
        service_name: str = "amprealize",
        *,
        parent_span_id: Optional[str] = None,
        run_id: Optional[str] = None,
        action_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> ExecutionSpan:
        """Start a new execution trace span. See PostgresTelemetryWarehouse.start_span()."""
        return self._warehouse.start_span(
            trace_id=trace_id,
            span_id=span_id,
            operation_name=operation_name,
            service_name=service_name,
            parent_span_id=parent_span_id,
            run_id=run_id,
            action_id=action_id,
            attributes=attributes,
        )

    def end_span(
        self,
        span: ExecutionSpan,
        *,
        status: str = "SUCCESS",
        error_message: Optional[str] = None,
        token_count: Optional[int] = None,
        behavior_citations: Optional[List[str]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Complete an execution trace span. See PostgresTelemetryWarehouse.end_span()."""
        self._warehouse.end_span(
            span=span,
            status=status,
            error_message=error_message,
            token_count=token_count,
            behavior_citations=behavior_citations,
            events=events,
            links=links,
        )

    def refresh_metric_views(self) -> None:
        self._warehouse.refresh_metric_views()

    def query_events(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """Query telemetry events. Delegates to warehouse."""
        return self._warehouse.query_events(**kwargs)

    def query_run_summaries(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """Query ``observability_run_summary``. Delegates to warehouse."""

        return self._warehouse.query_run_summaries(**kwargs)

    def query_conversation_summaries(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """Query ``observability_conversation_summary``. Delegates to warehouse."""

        return self._warehouse.query_conversation_summaries(**kwargs)

    def query_span_tree(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """Query ``observability_span_tree`` for a trace. Delegates to warehouse."""

        return self._warehouse.query_span_tree(**kwargs)

    def record_completed_execution_trace(self, **kwargs: Any) -> None:
        """Insert a completed execution_traces row via the warehouse."""

        self._warehouse.record_completed_execution_trace(**kwargs)

    def close(self) -> None:
        self._warehouse.close()
