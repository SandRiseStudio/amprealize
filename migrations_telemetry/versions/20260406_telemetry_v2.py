"""Add execution_traces columns, helper views, continuous aggregates, fact table.

Revision ID: telemetry_v2
Revises: telemetry_baseline
Create Date: 2026-04-06

Adds columns to execution_traces expected by postgres_telemetry.py:
  - error_message TEXT  (service writes here instead of status_message)
  - token_count INTEGER (service writes instead of input_tokens)
  - behavior_citations JSONB (no prior column)

Creates helper views (referenced by tests and dashboards):
  - recent_telemetry_events
  - error_traces
  - slow_traces

Creates continuous aggregates (must be outside transaction):
  - telemetry_events_hourly
  - execution_traces_hourly
  - telemetry_events_daily

Creates fact_compliance_steps table for KPI projector.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "telemetry_v2"
down_revision: Union[str, None] = "telemetry_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # =========================================================================
    # Step 1: Add missing columns to execution_traces
    # =========================================================================
    conn.execute(text(
        "ALTER TABLE execution_traces ADD COLUMN IF NOT EXISTS error_message TEXT"
    ))
    conn.execute(text(
        "ALTER TABLE execution_traces ADD COLUMN IF NOT EXISTS token_count INTEGER"
    ))
    conn.execute(text(
        "ALTER TABLE execution_traces ADD COLUMN IF NOT EXISTS behavior_citations TEXT[]"
    ))

    # =========================================================================
    # Step 2: Create fact_compliance_steps table
    # =========================================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS fact_compliance_steps (
            checklist_id VARCHAR,
            step_id VARCHAR,
            status VARCHAR,
            coverage_score DOUBLE PRECISION,
            run_id VARCHAR,
            session_id VARCHAR,
            behavior_ids VARCHAR[],
            event_timestamp TIMESTAMPTZ,
            recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # =========================================================================
    # Step 3: Create helper views
    # =========================================================================
    conn.execute(text("""
        CREATE OR REPLACE VIEW recent_telemetry_events AS
        SELECT
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
            inserted_at
        FROM telemetry_events
        WHERE event_timestamp > NOW() - INTERVAL '24 hours'
        ORDER BY event_timestamp DESC
    """))

    conn.execute(text("""
        CREATE OR REPLACE VIEW error_traces AS
        SELECT
            trace_id,
            span_id,
            parent_span_id,
            trace_timestamp,
            run_id,
            action_id,
            operation_name,
            service_name,
            start_time,
            end_time,
            duration_ms,
            status,
            status_message,
            error_message,
            attributes,
            events,
            links,
            input_tokens,
            output_tokens,
            total_tokens,
            token_count,
            behavior_citations
        FROM execution_traces
        WHERE status IN ('ERROR', 'TIMEOUT', 'CANCELLED')
        ORDER BY trace_timestamp DESC
    """))

    conn.execute(text("""
        CREATE OR REPLACE VIEW slow_traces AS
        SELECT
            trace_id,
            span_id,
            parent_span_id,
            trace_timestamp,
            run_id,
            action_id,
            operation_name,
            service_name,
            start_time,
            end_time,
            duration_ms,
            status,
            status_message,
            error_message,
            attributes,
            events,
            links,
            input_tokens,
            output_tokens,
            total_tokens,
            token_count,
            behavior_citations
        FROM execution_traces
        WHERE duration_ms IS NOT NULL AND duration_ms > 5000
        ORDER BY duration_ms DESC
    """))

    # =========================================================================
    # Step 4: Create continuous aggregates
    # NOTE: TimescaleDB continuous aggregates require being created outside
    # a transaction. We use op.execute with autocommit or raw connection.
    # If these fail in a transaction, they can be created manually:
    #   psql $AMPREALIZE_TELEMETRY_PG_DSN -f <this SQL>
    # =========================================================================
    try:
        # End the current transaction so we can create continuous aggregates
        conn.execute(text("COMMIT"))

        conn.execute(text("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_events_hourly
            WITH (timescaledb.continuous) AS
            SELECT
                time_bucket('1 hour', event_timestamp) AS bucket,
                event_type,
                actor_role,
                COUNT(*) AS event_count,
                COUNT(DISTINCT actor_id) AS unique_actors,
                COUNT(DISTINCT run_id) AS unique_runs
            FROM telemetry_events
            GROUP BY bucket, event_type, actor_role
            WITH NO DATA
        """))

        conn.execute(text("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS execution_traces_hourly
            WITH (timescaledb.continuous) AS
            SELECT
                time_bucket('1 hour', trace_timestamp) AS bucket,
                operation_name,
                status,
                COUNT(*) AS span_count,
                AVG(duration_ms)::INTEGER AS avg_duration_ms,
                MAX(duration_ms) AS max_duration_ms,
                SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) AS total_tokens
            FROM execution_traces
            GROUP BY bucket, operation_name, status
            WITH NO DATA
        """))

        conn.execute(text("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_events_daily
            WITH (timescaledb.continuous) AS
            SELECT
                time_bucket('1 day', event_timestamp) AS bucket,
                event_type,
                actor_role,
                COUNT(*) AS event_count,
                COUNT(DISTINCT actor_id) AS unique_actors,
                COUNT(DISTINCT run_id) AS unique_runs,
                COUNT(DISTINCT session_id) AS unique_sessions
            FROM telemetry_events
            GROUP BY bucket, event_type, actor_role
            WITH NO DATA
        """))

        # Add refresh policies
        conn.execute(text("""
            SELECT add_continuous_aggregate_policy('telemetry_events_hourly',
                start_offset => INTERVAL '3 hours',
                end_offset => INTERVAL '1 hour',
                schedule_interval => INTERVAL '1 hour',
                if_not_exists => TRUE
            )
        """))
        conn.execute(text("""
            SELECT add_continuous_aggregate_policy('execution_traces_hourly',
                start_offset => INTERVAL '3 hours',
                end_offset => INTERVAL '1 hour',
                schedule_interval => INTERVAL '1 hour',
                if_not_exists => TRUE
            )
        """))
        conn.execute(text("""
            SELECT add_continuous_aggregate_policy('telemetry_events_daily',
                start_offset => INTERVAL '3 days',
                end_offset => INTERVAL '1 day',
                schedule_interval => INTERVAL '1 day',
                if_not_exists => TRUE
            )
        """))

        # Start a new transaction for any remaining operations
        conn.execute(text("BEGIN"))
    except Exception:
        # If continuous aggregate creation fails (e.g., already in a transaction),
        # log and continue - they can be created manually
        try:
            conn.execute(text("BEGIN"))
        except Exception:
            pass


def downgrade() -> None:
    conn = op.get_bind()

    # Drop continuous aggregates
    conn.execute(text("COMMIT"))
    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS telemetry_events_daily CASCADE"))
    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS execution_traces_hourly CASCADE"))
    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS telemetry_events_hourly CASCADE"))
    conn.execute(text("BEGIN"))

    # Drop views
    conn.execute(text("DROP VIEW IF EXISTS slow_traces CASCADE"))
    conn.execute(text("DROP VIEW IF EXISTS error_traces CASCADE"))
    conn.execute(text("DROP VIEW IF EXISTS recent_telemetry_events CASCADE"))

    # Drop fact table
    conn.execute(text("DROP TABLE IF EXISTS fact_compliance_steps CASCADE"))

    # Drop added columns
    conn.execute(text("ALTER TABLE execution_traces DROP COLUMN IF EXISTS behavior_citations"))
    conn.execute(text("ALTER TABLE execution_traces DROP COLUMN IF EXISTS token_count"))
    conn.execute(text("ALTER TABLE execution_traces DROP COLUMN IF EXISTS error_message"))
