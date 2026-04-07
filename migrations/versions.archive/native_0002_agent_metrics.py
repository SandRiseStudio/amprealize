"""Agent, metrics, and behavior extensions

Revision ID: native_0002_agent_metrics
Revises: native_0001_core_schema
Create Date: 2025-01-13

Behavior: behavior_migrate_postgres_schema

This migration creates agent orchestration, metrics (TimescaleDB), and behavior
extension tables. It consolidates SQL files:
- 007_extend_replays_metadata.sql
- 008_optimize_behavior_indexes.sql
- 009_refactor_workflow_schema.sql
- 010_create_behavior_embeddings.sql
- 011_create_agent_orchestrator.sql
- 012_create_metrics_service.sql
- 013_create_trace_analysis.sql
- 014_create_telemetry_warehouse_timescale.sql
- 015_add_behavior_namespace.sql

Requires: TimescaleDB extension, pgvector extension
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "native_0002_agent_metrics"
down_revision: Union[str, None] = "native_0001_core_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create agent, metrics, and behavior extension tables."""
    conn = op.get_bind()

    # =========================================================================
    # Extensions
    # =========================================================================
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # =========================================================================
    # 007: Extend replays with metadata
    # =========================================================================
    op.add_column("replays", sa.Column("metadata", postgresql.JSONB(), nullable=True))
    op.add_column("replays", sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True))
    op.add_column("replays", sa.Column("notes", sa.Text(), nullable=True))

    # =========================================================================
    # 008: Optimize behavior indexes
    # =========================================================================
    # Add trigram index for behavior name search
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    op.create_index(
        "idx_behaviors_name_trgm",
        "behaviors",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "idx_behaviors_description_trgm",
        "behaviors",
        ["description"],
        postgresql_using="gin",
        postgresql_ops={"description": "gin_trgm_ops"},
    )

    # =========================================================================
    # 009: Refactor workflow schema (add workflow_step_runs)
    # =========================================================================
    op.create_table(
        "workflow_step_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("workflow_run_id", "step_index", name="uq_workflow_step_runs_workflow_step"),
    )
    op.create_index("idx_workflow_step_runs_workflow_run_id", "workflow_step_runs", ["workflow_run_id"])

    # =========================================================================
    # 010: Create behavior embeddings (pgvector)
    # =========================================================================
    op.create_table(
        "behavior_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("behavior_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("behavior_version", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(64), nullable=False, server_default="'text-embedding-3-small'"),
        sa.Column("embedding", sa.Column("embedding", sa.Text(), nullable=False)),  # vector(1024) via raw SQL
        sa.Column("text_hash", sa.String(64), nullable=False),  # SHA256 of embedded text
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["behavior_id"], ["behaviors.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("behavior_id", "behavior_version", "embedding_model", name="uq_behavior_embeddings_behavior_version_model"),
    )

    # Use raw SQL to create the vector column and index (pgvector specific)
    conn.execute(sa.text("ALTER TABLE behavior_embeddings DROP COLUMN IF EXISTS embedding"))
    conn.execute(sa.text("ALTER TABLE behavior_embeddings ADD COLUMN embedding vector(1024) NOT NULL"))
    conn.execute(sa.text("""
        CREATE INDEX idx_behavior_embeddings_embedding_ivfflat
        ON behavior_embeddings USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """))

    op.create_index("idx_behavior_embeddings_behavior_id", "behavior_embeddings", ["behavior_id"])
    op.create_index("idx_behavior_embeddings_model", "behavior_embeddings", ["embedding_model"])

    # =========================================================================
    # 011: Create agent orchestrator
    # =========================================================================

    # Create agent_status enum
    conn.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE agent_status AS ENUM ('idle', 'busy', 'error', 'offline');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """))

    # agent_personas table
    op.create_table(
        "agent_personas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("role", sa.String(32), nullable=False),  # student, teacher, strategist
        sa.Column("capabilities", postgresql.JSONB(), nullable=True),
        sa.Column("default_behaviors", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_agent_personas_name"),
    )

    op.create_index("idx_agent_personas_role", "agent_personas", ["role"])
    op.create_index("idx_agent_personas_is_active", "agent_personas", ["is_active"])

    # agent_assignments table
    op.create_table(
        "agent_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("unassigned_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="'active'"),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["persona_id"], ["agent_personas.id"], ondelete="CASCADE"),
    )

    op.create_index("idx_agent_assignments_run_id", "agent_assignments", ["run_id"])
    op.create_index("idx_agent_assignments_persona_id", "agent_assignments", ["persona_id"])
    op.create_index("idx_agent_assignments_status", "agent_assignments", ["status"])

    # agent_switch_events table for tracking role transitions
    op.create_table(
        "agent_switch_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_persona_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("to_persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("switched_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_persona_id"], ["agent_personas.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_persona_id"], ["agent_personas.id"], ondelete="CASCADE"),
    )

    op.create_index("idx_agent_switch_events_run_id", "agent_switch_events", ["run_id"])
    op.create_index("idx_agent_switch_events_switched_at", "agent_switch_events", ["switched_at"])

    # =========================================================================
    # 012-014: Metrics Service (TimescaleDB hypertables)
    # =========================================================================

    # metrics_snapshots hypertable
    op.create_table(
        "metrics_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("metric_name", sa.String(128), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("dimensions", postgresql.JSONB(), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )

    conn.execute(sa.text("""
        SELECT create_hypertable(
            'metrics_snapshots',
            'timestamp',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        )
    """))

    op.create_index("idx_metrics_snapshots_metric_name", "metrics_snapshots", ["metric_name", "timestamp"])
    op.create_index("idx_metrics_snapshots_run_id", "metrics_snapshots", ["run_id", "timestamp"])

    # behavior_usage_events hypertable
    op.create_table(
        "behavior_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("behavior_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("behavior_name", sa.String(128), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("tokens_saved", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )

    conn.execute(sa.text("""
        SELECT create_hypertable(
            'behavior_usage_events',
            'timestamp',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        )
    """))

    op.create_index("idx_behavior_usage_events_behavior_id", "behavior_usage_events", ["behavior_id", "timestamp"])
    op.create_index("idx_behavior_usage_events_behavior_name", "behavior_usage_events", ["behavior_name", "timestamp"])
    op.create_index("idx_behavior_usage_events_run_id", "behavior_usage_events", ["run_id", "timestamp"])

    # token_usage_events hypertable
    op.create_table(
        "token_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )

    conn.execute(sa.text("""
        SELECT create_hypertable(
            'token_usage_events',
            'timestamp',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        )
    """))

    op.create_index("idx_token_usage_events_run_id", "token_usage_events", ["run_id", "timestamp"])
    op.create_index("idx_token_usage_events_model", "token_usage_events", ["model", "timestamp"])

    # Enable compression on hypertables
    conn.execute(sa.text("""
        ALTER TABLE metrics_snapshots SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'metric_name',
            timescaledb.compress_orderby = 'timestamp DESC'
        )
    """))
    conn.execute(sa.text("SELECT add_compression_policy('metrics_snapshots', INTERVAL '7 days', if_not_exists => TRUE)"))

    conn.execute(sa.text("""
        ALTER TABLE behavior_usage_events SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'behavior_name',
            timescaledb.compress_orderby = 'timestamp DESC'
        )
    """))
    conn.execute(sa.text("SELECT add_compression_policy('behavior_usage_events', INTERVAL '7 days', if_not_exists => TRUE)"))

    conn.execute(sa.text("""
        ALTER TABLE token_usage_events SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'model',
            timescaledb.compress_orderby = 'timestamp DESC'
        )
    """))
    conn.execute(sa.text("SELECT add_compression_policy('token_usage_events', INTERVAL '7 days', if_not_exists => TRUE)"))

    # =========================================================================
    # 015: Add behavior namespace
    # =========================================================================
    op.add_column("behaviors", sa.Column("namespace", sa.String(64), nullable=True))
    op.create_index("idx_behaviors_namespace", "behaviors", ["namespace"])

    # Update unique constraint to include namespace
    op.drop_constraint("uq_behaviors_name", "behaviors", type_="unique")
    op.create_unique_constraint("uq_behaviors_namespace_name", "behaviors", ["namespace", "name"])


def downgrade() -> None:
    """Downgrade database schema.

    Note: Agent/metrics migrations are marked as irreversible.
    """
    raise NotImplementedError(
        "Agent/metrics migrations are irreversible. "
        "Use backup/restore for rollback scenarios."
    )
