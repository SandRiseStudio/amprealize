"""Tests for PostgreSQL TimescaleDB telemetry warehouse.

Validates hypertable configuration, compression/retention policies, execution
trace storage, and continuous aggregate functionality against the TimescaleDB
warehouse defined in schema/migrations/014_upgrade_telemetry_to_timescale.sql.

Behaviors referenced:
- behavior_align_storage_layers
- behavior_unify_execution_records
- behavior_instrument_metrics_pipeline
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest

# Conditional imports for PostgreSQL dependencies
pytest.importorskip("psycopg2")

from amprealize.storage.postgres_telemetry import (
    ExecutionSpan,
    PostgresTelemetryWarehouse,
    PostgresTelemetrySink,
)
from amprealize.telemetry import TelemetryEvent


@pytest.fixture
def pg_dsn() -> str:
    """Return PostgreSQL DSN from environment or skip if not configured."""
    dsn = os.environ.get("AMPREALIZE_TELEMETRY_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_TELEMETRY_PG_DSN not configured")
    return dsn


def _telemetry_tables_exist(dsn: str) -> bool:
    """Check whether the telemetry warehouse tables have been created."""
    try:
        import psycopg2
        with psycopg2.connect(dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT to_regclass('public.telemetry_events')"
                )
                return cur.fetchone()[0] is not None
    except Exception:
        return False


@pytest.fixture
def warehouse(pg_dsn: str) -> Generator[PostgresTelemetryWarehouse, None, None]:
    """Provide a connected PostgresTelemetryWarehouse instance."""
    if not _telemetry_tables_exist(pg_dsn):
        pytest.skip(
            "telemetry_events table not found — "
            "schema/migrations/014_create_telemetry_warehouse_timescale.sql not applied"
        )
    wh = PostgresTelemetryWarehouse(pg_dsn, connect_timeout=5)
    yield wh
    wh.close()


@pytest.fixture
def sink(pg_dsn: str) -> Generator[PostgresTelemetrySink, None, None]:
    """Provide a PostgresTelemetrySink instance."""
    if not _telemetry_tables_exist(pg_dsn):
        pytest.skip(
            "telemetry_events table not found — "
            "schema/migrations/014_create_telemetry_warehouse_timescale.sql not applied"
        )
    s = PostgresTelemetrySink(pg_dsn, connect_timeout=5)
    yield s
    s.close()


# ============================================================================
# Hypertable Validation Tests
# ============================================================================


def test_telemetry_events_hypertable_exists(warehouse: PostgresTelemetryWarehouse) -> None:
    """Verify telemetry_events hypertable exists with compression enabled."""
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT hypertable_name, num_chunks, compression_enabled
            FROM timescaledb_information.hypertables
            WHERE hypertable_name = 'telemetry_events'
            """
        )
        result = cur.fetchone()

    assert result is not None, "telemetry_events hypertable not found"
    hypertable_name, num_chunks, compression_enabled = result
    assert hypertable_name == "telemetry_events"
    assert compression_enabled is True, "Compression not enabled on telemetry_events"


def test_execution_traces_hypertable_exists(warehouse: PostgresTelemetryWarehouse) -> None:
    """Verify execution_traces hypertable exists with compression enabled."""
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT hypertable_name, num_chunks, compression_enabled
            FROM timescaledb_information.hypertables
            WHERE hypertable_name = 'execution_traces'
            """
        )
        result = cur.fetchone()

    assert result is not None, "execution_traces hypertable not found"
    hypertable_name, num_chunks, compression_enabled = result
    assert hypertable_name == "execution_traces"
    assert compression_enabled is True, "Compression not enabled on execution_traces"


# ============================================================================
# Compression/Retention Policy Tests
# ============================================================================


def test_compression_policies_exist(warehouse: PostgresTelemetryWarehouse) -> None:
    """Verify compression policies are configured for both hypertables."""
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id, config
            FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_compression'
            """
        )
        results = cur.fetchall()

    assert len(results) >= 2, "Expected at least 2 compression policies (telemetry_events, execution_traces)"

    # Verify 7-day compress_after threshold
    for job_id, config in results:
        assert "compress_after" in config, f"Job {job_id} missing compress_after config"
        assert "7 days" in config["compress_after"], f"Job {job_id} compress_after not 7 days"


def test_retention_policies_exist(warehouse: PostgresTelemetryWarehouse) -> None:
    """Verify retention policies are configured for 90-day hot storage."""
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id, config
            FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_retention'
            """
        )
        results = cur.fetchall()

    assert len(results) >= 2, "Expected at least 2 retention policies (telemetry_events, execution_traces)"

    # Verify 90-day drop_after threshold
    for job_id, config in results:
        assert "drop_after" in config, f"Job {job_id} missing drop_after config"
        assert "90 days" in config["drop_after"], f"Job {job_id} drop_after not 90 days"


# ============================================================================
# Continuous Aggregate Tests
# ============================================================================


def test_continuous_aggregates_exist(warehouse: PostgresTelemetryWarehouse) -> None:
    """Verify all continuous aggregates are created."""
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT view_name, materialized_only
            FROM timescaledb_information.continuous_aggregates
            ORDER BY view_name
            """
        )
        results = cur.fetchall()

    view_names = {row[0] for row in results}
    expected = {
        "telemetry_events_hourly",
        "execution_traces_hourly",
        "telemetry_events_daily",
    }

    assert expected.issubset(view_names), f"Missing continuous aggregates: {expected - view_names}"


def test_continuous_aggregate_refresh_policies_exist(warehouse: PostgresTelemetryWarehouse) -> None:
    """Verify refresh policies are configured for continuous aggregates."""
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id, config
            FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_refresh_continuous_aggregate'
            """
        )
        results = cur.fetchall()

    assert len(results) >= 3, "Expected at least 3 refresh policies (hourly events, hourly traces, daily events)"


# ============================================================================
# Helper View Tests
# ============================================================================


def test_helper_views_exist(warehouse: PostgresTelemetryWarehouse) -> None:
    """Verify helper views for dashboards are created."""
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT viewname
            FROM pg_views
            WHERE schemaname = 'public'
                AND viewname IN ('recent_telemetry_events', 'error_traces', 'slow_traces')
            ORDER BY viewname
            """
        )
        results = cur.fetchall()

    view_names = {row[0] for row in results}
    expected = {"recent_telemetry_events", "error_traces", "slow_traces"}

    assert expected == view_names, f"Missing or extra helper views: expected {expected}, got {view_names}"


# ============================================================================
# Telemetry Event Storage Tests
# ============================================================================


def test_write_telemetry_event(warehouse: PostgresTelemetryWarehouse) -> None:
    """Test writing a telemetry event to the hypertable."""
    event_id = str(uuid.uuid4())
    event = TelemetryEvent(
        event_id=event_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type="test_event",
        actor={"id": "test_actor", "role": "STRATEGIST", "surface": "api"},
        run_id=str(uuid.uuid4()),
        action_id=None,
        session_id=str(uuid.uuid4()),
        payload={"test_key": "test_value", "count": 42},
    )

    warehouse.write_event(event)

    # Verify event stored
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, event_type, payload FROM telemetry_events WHERE event_id = %s",
            (event_id,),
        )
        result = cur.fetchone()

    assert result is not None, "Event not found in telemetry_events"
    stored_id, stored_type, stored_payload = result
    assert str(stored_id) == event_id
    assert stored_type == "test_event"
    assert stored_payload["test_key"] == "test_value"
    assert stored_payload["count"] == 42


def test_sink_write_telemetry_event(sink: PostgresTelemetrySink) -> None:
    """Test telemetry event writing via sink interface."""
    event_id = str(uuid.uuid4())
    event = TelemetryEvent(
        event_id=event_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type="sink_test_event",
        actor={"id": "sink_actor", "role": "TEACHER", "surface": "cli"},
        run_id=None,
        action_id=None,
        session_id=None,
        payload={"sink_test": True},
    )

    sink.write(event)

    # Verify via warehouse connection
    conn = sink._warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, event_type FROM telemetry_events WHERE event_id = %s",
            (event_id,),
        )
        result = cur.fetchone()

    assert result is not None
    assert str(result[0]) == event_id
    assert result[1] == "sink_test_event"


# ============================================================================
# Execution Trace Storage Tests
# ============================================================================


def test_start_end_span_basic(warehouse: PostgresTelemetryWarehouse) -> None:
    """Test basic span lifecycle: start -> end."""
    trace_id = str(uuid.uuid4())
    span_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    # Start span
    span = warehouse.start_span(
        trace_id=trace_id,
        span_id=span_id,
        operation_name="test_operation",
        service_name="test_service",
        run_id=run_id,
        attributes={"test_attr": "value"},
    )

    assert span.span_id == span_id
    assert span.trace_id == trace_id
    assert span.status == "RUNNING"

    # Verify span in database (RUNNING)
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT span_id, status, operation_name FROM execution_traces WHERE span_id = %s",
            (span_id,),
        )
        result = cur.fetchone()

    assert result is not None
    assert str(result[0]) == span_id
    assert result[1] == "RUNNING"
    assert result[2] == "test_operation"

    # End span
    warehouse.end_span(
        span,
        status="SUCCESS",
        token_count=150,
        behavior_citations=["behavior_test_1", "behavior_test_2"],
    )

    assert span.status == "SUCCESS"
    assert span.token_count == 150

    # Verify span updated (SUCCESS)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, end_time, token_count, behavior_citations, duration_ms
            FROM execution_traces
            WHERE span_id = %s
            """,
            (span_id,),
        )
        result = cur.fetchone()

    assert result is not None
    status, end_time, token_count, behavior_citations, duration_ms = result
    assert status == "SUCCESS"
    assert end_time is not None
    assert token_count == 150
    assert set(behavior_citations) == {"behavior_test_1", "behavior_test_2"}
    assert duration_ms is not None and duration_ms >= 0


def test_span_with_error(warehouse: PostgresTelemetryWarehouse) -> None:
    """Test span completion with ERROR status."""
    trace_id = str(uuid.uuid4())
    span_id = str(uuid.uuid4())

    span = warehouse.start_span(
        trace_id=trace_id,
        span_id=span_id,
        operation_name="failing_operation",
        service_name="amprealize",
    )

    warehouse.end_span(
        span,
        status="ERROR",
        error_message="Test error occurred",
    )

    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, error_message FROM execution_traces WHERE span_id = %s",
            (span_id,),
        )
        result = cur.fetchone()

    assert result is not None
    status, error_message = result
    assert status == "ERROR"
    assert error_message == "Test error occurred"


def test_nested_spans(warehouse: PostgresTelemetryWarehouse) -> None:
    """Test parent-child span relationships."""
    trace_id = str(uuid.uuid4())
    parent_span_id = str(uuid.uuid4())
    child_span_id = str(uuid.uuid4())

    # Start parent span
    parent_span = warehouse.start_span(
        trace_id=trace_id,
        span_id=parent_span_id,
        operation_name="parent_operation",
        service_name="amprealize",
    )

    # Start child span
    child_span = warehouse.start_span(
        trace_id=trace_id,
        span_id=child_span_id,
        operation_name="child_operation",
        service_name="amprealize",
        parent_span_id=parent_span_id,
    )

    # End both spans
    warehouse.end_span(child_span, status="SUCCESS")
    warehouse.end_span(parent_span, status="SUCCESS")

    # Verify parent-child relationship
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT span_id, parent_span_id, operation_name
            FROM execution_traces
            WHERE trace_id = %s
            ORDER BY operation_name
            """,
            (trace_id,),
        )
        results = cur.fetchall()

    assert len(results) == 2
    child_row = next(r for r in results if r[2] == "child_operation")
    assert child_row[1] is not None
    assert str(child_row[1]) == parent_span_id


def test_span_via_sink(sink: PostgresTelemetrySink) -> None:
    """Test span lifecycle via sink interface."""
    trace_id = str(uuid.uuid4())
    span_id = str(uuid.uuid4())

    span = sink.start_span(
        trace_id=trace_id,
        span_id=span_id,
        operation_name="sink_operation",
        service_name="amprealize",
    )

    sink.end_span(span, status="SUCCESS", token_count=200)

    conn = sink._warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, token_count FROM execution_traces WHERE span_id = %s",
            (span_id,),
        )
        result = cur.fetchone()

    assert result is not None
    assert result[0] == "SUCCESS"
    assert result[1] == 200


# ============================================================================
# Time-Series Query Performance Tests
# ============================================================================


def test_recent_telemetry_events_view(warehouse: PostgresTelemetryWarehouse) -> None:
    """Test recent_telemetry_events helper view returns last 7 days."""
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM recent_telemetry_events")
        count = cur.fetchone()[0]

    # Should not raise errors (view exists and is queryable)
    assert count >= 0


def test_error_traces_view(warehouse: PostgresTelemetryWarehouse) -> None:
    """Test error_traces helper view filters ERROR/TIMEOUT/CANCELLED spans."""
    # Create an error span
    trace_id = str(uuid.uuid4())
    span_id = str(uuid.uuid4())

    span = warehouse.start_span(
        trace_id=trace_id,
        span_id=span_id,
        operation_name="error_test",
        service_name="amprealize",
    )
    warehouse.end_span(span, status="ERROR", error_message="Test error for view")

    # Query error_traces view
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT span_id, error_message
            FROM error_traces
            WHERE span_id = %s
            """,
            (span_id,),
        )
        result = cur.fetchone()

    assert result is not None, "Error span not found in error_traces view"
    assert result[1] == "Test error for view"


def test_slow_traces_view(warehouse: PostgresTelemetryWarehouse) -> None:
    """Test slow_traces helper view (P99+ latency spans)."""
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM slow_traces")
        count = cur.fetchone()[0]

    # Should not raise errors (view exists and is queryable)
    assert count >= 0


# ============================================================================
# Index Validation Tests
# ============================================================================


def test_telemetry_events_indexes_exist(warehouse: PostgresTelemetryWarehouse) -> None:
    """Verify partition-pruned indexes exist on telemetry_events."""
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'telemetry_events'
            ORDER BY indexname
            """
        )
        indexes = [row[0] for row in cur.fetchall()]

    expected_indexes = [
        "telemetry_events_pkey",  # Composite PK (event_id, event_timestamp)
        "idx_telemetry_events_type_time",
        "idx_telemetry_events_run_time",
        "idx_telemetry_events_actor_time",
        "idx_telemetry_events_session_time",
        "idx_telemetry_events_action_time",
        "idx_telemetry_events_payload_gin",
    ]

    for expected_idx in expected_indexes:
        assert expected_idx in indexes, f"Missing index: {expected_idx}"


def test_execution_traces_indexes_exist(warehouse: PostgresTelemetryWarehouse) -> None:
    """Verify partition-pruned indexes exist on execution_traces."""
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'execution_traces'
            ORDER BY indexname
            """
        )
        indexes = [row[0] for row in cur.fetchall()]

    expected_indexes = [
        "execution_traces_pkey",  # Composite PK (span_id, trace_timestamp)
        "idx_execution_traces_trace_id",
        "idx_execution_traces_run_id",
        "idx_execution_traces_action_id",
        "idx_execution_traces_operation",
        "idx_execution_traces_status",
        "idx_execution_traces_duration",
        "idx_execution_traces_attributes_gin",
    ]

    for expected_idx in expected_indexes:
        assert expected_idx in indexes, f"Missing index: {expected_idx}"


# ============================================================================
# Integration Tests
# ============================================================================


def test_full_workflow_trace(warehouse: PostgresTelemetryWarehouse) -> None:
    """Integration test: full workflow with events + spans."""
    trace_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    # Emit workflow start event
    start_event = TelemetryEvent(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type="workflow_started",
        actor={"id": "integration_test", "role": "STRATEGIST", "surface": "api"},
        run_id=run_id,
        action_id=None,
        session_id=session_id,
        payload={"workflow_name": "integration_test"},
    )
    warehouse.write_event(start_event)

    # Start workflow span
    workflow_span = warehouse.start_span(
        trace_id=trace_id,
        span_id=str(uuid.uuid4()),
        operation_name="execute_workflow",
        service_name="amprealize",
        run_id=run_id,
    )

    # Start sub-operation span
    sub_span = warehouse.start_span(
        trace_id=trace_id,
        span_id=str(uuid.uuid4()),
        operation_name="behavior_retrieval",
        service_name="amprealize",
        parent_span_id=workflow_span.span_id,
        run_id=run_id,
        attributes={"query": "test query"},
    )

    # Emit behavior retrieved event
    behavior_event = TelemetryEvent(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type="behavior_retrieved",
        actor={"id": "integration_test", "role": "STRATEGIST", "surface": "api"},
        run_id=run_id,
        action_id=None,
        session_id=session_id,
        payload={"behavior_ids": ["behavior_1", "behavior_2"], "count": 2},
    )
    warehouse.write_event(behavior_event)

    # End sub-span
    warehouse.end_span(
        sub_span,
        status="SUCCESS",
        token_count=50,
        behavior_citations=["behavior_1", "behavior_2"],
    )

    # End workflow span
    warehouse.end_span(
        workflow_span,
        status="SUCCESS",
        token_count=300,
    )

    # Emit workflow completed event
    complete_event = TelemetryEvent(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type="workflow_completed",
        actor={"id": "integration_test", "role": "STRATEGIST", "surface": "api"},
        run_id=run_id,
        action_id=None,
        session_id=session_id,
        payload={"status": "SUCCESS", "total_tokens": 300},
    )
    warehouse.write_event(complete_event)

    # Verify events
    conn = warehouse._ensure_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM telemetry_events WHERE run_id = %s",
            (run_id,),
        )
        event_count = cur.fetchone()[0]

    assert event_count >= 3, "Expected at least 3 events for workflow"

    # Verify spans
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM execution_traces WHERE trace_id = %s",
            (trace_id,),
        )
        span_count = cur.fetchone()[0]

    assert span_count == 2, "Expected 2 spans (workflow + sub-operation)"

    # Verify behavior citations
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT operation_name, behavior_citations
            FROM execution_traces
            WHERE trace_id = %s
                AND behavior_citations IS NOT NULL
            """,
            (trace_id,),
        )
        result = cur.fetchone()

    assert result is not None
    assert result[0] == "behavior_retrieval"
    assert set(result[1]) == {"behavior_1", "behavior_2"}
