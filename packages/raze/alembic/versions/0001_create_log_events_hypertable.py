"""Create log_events hypertable with compression

Revision ID: 0001
Revises: None
Create Date: 2025-01-13

This migration creates the log_events table as a TimescaleDB hypertable
with compression policies for efficient time-series log storage.

Converts from: packages/raze/schema/migrations/001_create_log_events.sql
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create log_events TimescaleDB hypertable with compression."""
    conn = op.get_bind()

    # Ensure TimescaleDB extension exists (idempotent)
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))

    # Create log_events table
    op.create_table(
        "log_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("service", sa.String(128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", sa.String(128), nullable=True),
        sa.Column("actor_surface", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("span_id", sa.String(32), nullable=True),
        sa.Column("parent_span_id", sa.String(32), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )

    # Convert to TimescaleDB hypertable
    conn.execute(sa.text("""
        SELECT create_hypertable(
            'log_events',
            'timestamp',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        )
    """))

    # Create indexes for common query patterns
    op.create_index(
        "idx_log_events_timestamp",
        "log_events",
        ["timestamp"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_log_events_level",
        "log_events",
        ["level", "timestamp"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_log_events_service",
        "log_events",
        ["service", "timestamp"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_log_events_run_id",
        "log_events",
        ["run_id", "timestamp"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_log_events_action_id",
        "log_events",
        ["action_id", "timestamp"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_log_events_trace_id",
        "log_events",
        ["trace_id", "timestamp"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_log_events_session_id",
        "log_events",
        ["session_id", "timestamp"],
        postgresql_using="btree",
    )

    # GIN index for JSONB context queries
    op.create_index(
        "idx_log_events_context_gin",
        "log_events",
        ["context"],
        postgresql_using="gin",
    )

    # Enable TimescaleDB compression
    conn.execute(sa.text("""
        ALTER TABLE log_events SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'service, level',
            timescaledb.compress_orderby = 'timestamp DESC'
        )
    """))

    # Add compression policy: compress chunks older than 7 days
    conn.execute(sa.text("""
        SELECT add_compression_policy(
            'log_events',
            INTERVAL '7 days',
            if_not_exists => TRUE
        )
    """))

    # Create convenience views
    conn.execute(sa.text("""
        CREATE OR REPLACE VIEW log_events_by_level AS
        SELECT
            time_bucket('1 hour', timestamp) AS bucket,
            level,
            service,
            COUNT(*) AS event_count
        FROM log_events
        WHERE timestamp > NOW() - INTERVAL '24 hours'
        GROUP BY bucket, level, service
        ORDER BY bucket DESC, event_count DESC
    """))

    conn.execute(sa.text("""
        CREATE OR REPLACE VIEW log_events_by_service AS
        SELECT
            time_bucket('1 hour', timestamp) AS bucket,
            service,
            level,
            COUNT(*) AS event_count,
            AVG(duration_ms) AS avg_duration_ms
        FROM log_events
        WHERE timestamp > NOW() - INTERVAL '24 hours'
        GROUP BY bucket, service, level
        ORDER BY bucket DESC, event_count DESC
    """))


def downgrade() -> None:
    """Downgrade database schema.

    Note: Raze migrations are marked as irreversible.
    """
    raise NotImplementedError(
        "Raze migrations are irreversible. "
        "Use backup/restore for rollback scenarios."
    )
