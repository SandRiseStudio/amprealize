"""Make telemetry schema work on standard PostgreSQL (Neon-compatible).

Revision ID: neon_compat
Revises: telemetry_v2
Create Date: 2026-04-04

When the telemetry database is a standard PostgreSQL instance without
TimescaleDB (e.g. Neon serverless), the hypertable and continuous-aggregate
calls in earlier migrations will have failed silently.

This migration:
1. Detects whether TimescaleDB is available.
2. If *not* available, ensures the base tables and indexes exist as plain
   PostgreSQL tables (they were already created by the baseline migration
   before the create_hypertable call).
3. Re-creates the helper views from telemetry_v2 (idempotent).
4. Creates lightweight materialized-view aggregates that approximate the
   TimescaleDB continuous aggregates using date_trunc instead of
   time_bucket (works on vanilla PG).

This migration is fully idempotent and safe to run on both TimescaleDB
and vanilla PostgreSQL instances.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "neon_compat"
down_revision: Union[str, None] = "telemetry_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_timescaledb(conn) -> bool:
    """Check if TimescaleDB extension is installed and usable."""
    try:
        result = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
        )
        return result.scalar() is not None
    except Exception:
        return False


def upgrade() -> None:
    conn = op.get_bind()

    if _has_timescaledb(conn):
        # TimescaleDB present — nothing to do; existing migrations handle it.
        return

    # ------------------------------------------------------------------
    # Vanilla PostgreSQL path (Neon, etc.)
    # ------------------------------------------------------------------

    # The base tables + indexes were already created by the baseline
    # migration before the create_hypertable() call, so they should
    # exist.  But ensure the v2 columns are present too.
    conn.execute(text(
        "ALTER TABLE execution_traces ADD COLUMN IF NOT EXISTS error_message TEXT"
    ))
    conn.execute(text(
        "ALTER TABLE execution_traces ADD COLUMN IF NOT EXISTS token_count INTEGER"
    ))
    conn.execute(text(
        "ALTER TABLE execution_traces ADD COLUMN IF NOT EXISTS behavior_citations TEXT[]"
    ))

    # Ensure fact table
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

    # Re-create helper views (idempotent)
    conn.execute(text("""
        CREATE OR REPLACE VIEW recent_telemetry_events AS
        SELECT
            event_id, event_timestamp, event_type, actor_id, actor_role,
            actor_surface, run_id, action_id, session_id, payload, inserted_at
        FROM telemetry_events
        WHERE event_timestamp > NOW() - INTERVAL '24 hours'
        ORDER BY event_timestamp DESC
    """))

    conn.execute(text("""
        CREATE OR REPLACE VIEW error_traces AS
        SELECT *
        FROM execution_traces
        WHERE status IN ('ERROR', 'TIMEOUT', 'CANCELLED')
        ORDER BY trace_timestamp DESC
    """))

    conn.execute(text("""
        CREATE OR REPLACE VIEW slow_traces AS
        SELECT *
        FROM execution_traces
        WHERE duration_ms IS NOT NULL AND duration_ms > 5000
        ORDER BY duration_ms DESC
    """))

    # ------------------------------------------------------------------
    # Materialized-view aggregates (vanilla PG alternative to
    # TimescaleDB continuous aggregates).  Uses date_trunc instead of
    # time_bucket.  Must be refreshed manually or via cron/pg_cron.
    # ------------------------------------------------------------------
    conn.execute(text("COMMIT"))  # MVs can't be in a transaction on some PG configs

    conn.execute(text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_events_hourly AS
        SELECT
            date_trunc('hour', event_timestamp) AS bucket,
            event_type,
            actor_role,
            COUNT(*) AS event_count,
            COUNT(DISTINCT actor_id) AS unique_actors,
            COUNT(DISTINCT run_id) AS unique_runs
        FROM telemetry_events
        GROUP BY 1, event_type, actor_role
    """))

    conn.execute(text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS execution_traces_hourly AS
        SELECT
            date_trunc('hour', trace_timestamp) AS bucket,
            operation_name,
            status,
            COUNT(*) AS span_count,
            AVG(duration_ms)::INTEGER AS avg_duration_ms,
            MAX(duration_ms) AS max_duration_ms,
            SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) AS total_tokens
        FROM execution_traces
        GROUP BY 1, operation_name, status
    """))

    conn.execute(text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_events_daily AS
        SELECT
            date_trunc('day', event_timestamp) AS bucket,
            event_type,
            actor_role,
            COUNT(*) AS event_count,
            COUNT(DISTINCT actor_id) AS unique_actors,
            COUNT(DISTINCT run_id) AS unique_runs,
            COUNT(DISTINCT session_id) AS unique_sessions
        FROM telemetry_events
        GROUP BY 1, event_type, actor_role
    """))

    # Create unique indexes on the MVs so REFRESH CONCURRENTLY works
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_teh_bucket
            ON telemetry_events_hourly (bucket, event_type, actor_role)
    """))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_eth_bucket
            ON execution_traces_hourly (bucket, operation_name, status)
    """))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ted_bucket
            ON telemetry_events_daily (bucket, event_type, actor_role)
    """))

    conn.execute(text("BEGIN"))


def downgrade() -> None:
    conn = op.get_bind()

    if _has_timescaledb(conn):
        # TimescaleDB path: continuous aggregates are managed by earlier migrations.
        return

    conn.execute(text("COMMIT"))
    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS telemetry_events_daily CASCADE"))
    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS execution_traces_hourly CASCADE"))
    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS telemetry_events_hourly CASCADE"))
    conn.execute(text("BEGIN"))
