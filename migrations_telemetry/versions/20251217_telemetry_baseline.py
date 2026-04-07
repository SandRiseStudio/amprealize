"""Telemetry TimescaleDB baseline schema

Revision ID: telemetry_baseline
Revises: None
Create Date: 2025-12-17

Behavior: behavior_migrate_postgres_schema

This migration establishes the TimescaleDB telemetry schema with:
- telemetry_events hypertable (7-day chunks, 90-day retention)
- execution_traces hypertable (7-day chunks, 90-day retention)
- Compression policies (7 days)
- Continuous aggregates (hourly and daily)

For existing databases with schema already applied:
    alembic -c alembic.telemetry.ini stamp telemetry_baseline

For new databases:
    alembic -c alembic.telemetry.ini upgrade head
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "telemetry_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create telemetry schema with TimescaleDB hypertables."""
    conn = op.get_bind()

    # =========================================================================
    # Step 1: Enable extensions
    # =========================================================================
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
    conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))

    # =========================================================================
    # Step 2: Create telemetry_events table
    # =========================================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS telemetry_events (
            event_id UUID NOT NULL,
            event_timestamp TIMESTAMPTZ NOT NULL,
            event_type TEXT NOT NULL,
            actor_id TEXT,
            actor_role TEXT,
            actor_surface TEXT,
            run_id TEXT,
            action_id TEXT,
            session_id TEXT,
            payload JSONB NOT NULL,
            inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT telemetry_events_pkey PRIMARY KEY (event_id, event_timestamp)
        )
    """))

    # Convert to hypertable (if not already)
    conn.execute(text("""
        SELECT create_hypertable(
            'telemetry_events',
            'event_timestamp',
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE,
            migrate_data => TRUE
        )
    """))

    # Create indexes
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_telemetry_events_type_time
            ON telemetry_events (event_type, event_timestamp DESC)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_telemetry_events_run_time
            ON telemetry_events (run_id, event_timestamp DESC)
            WHERE run_id IS NOT NULL
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_telemetry_events_actor_time
            ON telemetry_events (actor_id, event_timestamp DESC)
            WHERE actor_id IS NOT NULL
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_telemetry_events_session_time
            ON telemetry_events (session_id, event_timestamp DESC)
            WHERE session_id IS NOT NULL
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_telemetry_events_action_time
            ON telemetry_events (action_id, event_timestamp DESC)
            WHERE action_id IS NOT NULL
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_telemetry_events_payload_gin
            ON telemetry_events USING gin (payload jsonb_path_ops)
    """))

    # =========================================================================
    # Step 3: Create execution_traces table
    # =========================================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS execution_traces (
            trace_id UUID NOT NULL,
            span_id UUID NOT NULL,
            parent_span_id UUID,
            trace_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
            run_id TEXT,
            action_id TEXT,
            operation_name TEXT NOT NULL,
            service_name TEXT NOT NULL DEFAULT 'amprealize',
            start_time TIMESTAMPTZ NOT NULL,
            end_time TIMESTAMPTZ,
            duration_ms INTEGER GENERATED ALWAYS AS (
                CASE
                    WHEN end_time IS NOT NULL
                    THEN EXTRACT(MILLISECONDS FROM (end_time - start_time))::INTEGER
                    ELSE NULL
                END
            ) STORED,
            status TEXT NOT NULL DEFAULT 'OK',
            status_message TEXT,
            attributes JSONB DEFAULT '{}',
            events JSONB DEFAULT '[]',
            links JSONB DEFAULT '[]',
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER GENERATED ALWAYS AS (
                COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)
            ) STORED,
            CONSTRAINT execution_traces_pkey PRIMARY KEY (span_id, trace_timestamp)
        )
    """))

    # Convert to hypertable
    conn.execute(text("""
        SELECT create_hypertable(
            'execution_traces',
            'trace_timestamp',
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE,
            migrate_data => TRUE
        )
    """))

    # Create indexes for execution_traces
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_execution_traces_trace_id
            ON execution_traces (trace_id, trace_timestamp DESC)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_execution_traces_run_id
            ON execution_traces (run_id, trace_timestamp DESC)
            WHERE run_id IS NOT NULL
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_execution_traces_action_id
            ON execution_traces (action_id, trace_timestamp DESC)
            WHERE action_id IS NOT NULL
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_execution_traces_operation
            ON execution_traces (operation_name, trace_timestamp DESC)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_execution_traces_status
            ON execution_traces (status, trace_timestamp DESC)
            WHERE status IN ('ERROR', 'TIMEOUT', 'CANCELLED')
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_execution_traces_duration
            ON execution_traces (duration_ms DESC, trace_timestamp DESC)
            WHERE duration_ms IS NOT NULL
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_execution_traces_attributes_gin
            ON execution_traces USING gin (attributes jsonb_path_ops)
    """))

    # =========================================================================
    # Step 4: Configure compression
    # =========================================================================
    conn.execute(text("""
        ALTER TABLE telemetry_events SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'event_type, actor_role',
            timescaledb.compress_orderby = 'event_timestamp DESC'
        )
    """))
    conn.execute(text("""
        ALTER TABLE execution_traces SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'operation_name, status',
            timescaledb.compress_orderby = 'trace_timestamp DESC'
        )
    """))

    # Add compression policies (compress chunks older than 7 days)
    conn.execute(text("""
        SELECT add_compression_policy('telemetry_events', INTERVAL '7 days', if_not_exists => TRUE)
    """))
    conn.execute(text("""
        SELECT add_compression_policy('execution_traces', INTERVAL '7 days', if_not_exists => TRUE)
    """))

    # =========================================================================
    # Step 5: Configure retention policies (90 days)
    # =========================================================================
    conn.execute(text("""
        SELECT add_retention_policy('telemetry_events', INTERVAL '90 days', if_not_exists => TRUE)
    """))
    conn.execute(text("""
        SELECT add_retention_policy('execution_traces', INTERVAL '90 days', if_not_exists => TRUE)
    """))

    # =========================================================================
    # Step 6: Create continuous aggregates
    # =========================================================================
    # NOTE: Continuous aggregates must be created OUTSIDE a transaction.
    # Run these manually after migration:
    #
    #   psql $TELEMETRY_DATABASE_URL -f schema/telemetry_aggregates.sql
    #
    # Or create a separate migration with autocommit=True in env.py
    # See: https://docs.timescale.com/timescaledb/latest/how-to-guides/continuous-aggregates/
    pass


def downgrade() -> None:
    """Remove telemetry schema."""
    conn = op.get_bind()

    # Remove continuous aggregates (if they exist - created manually post-migration)
    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS telemetry_events_daily CASCADE"))
    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS execution_traces_hourly CASCADE"))
    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS telemetry_events_hourly CASCADE"))

    # Remove tables (drops hypertables and associated chunks)
    conn.execute(text("DROP TABLE IF EXISTS execution_traces CASCADE"))
    conn.execute(text("DROP TABLE IF EXISTS telemetry_events CASCADE"))
