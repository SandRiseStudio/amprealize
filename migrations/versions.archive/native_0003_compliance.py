"""Compliance: audit logs, WORM storage, policies, behavior feedback

Revision ID: native_0003_compliance
Revises: native_0002_agent_metrics
Create Date: 2025-01-13

Behavior: behavior_migrate_postgres_schema

This migration creates compliance infrastructure:
- 016_create_audit_log_worm.sql
- 017_add_compliance_policies.sql
- 018_create_behavior_effectiveness.sql
- 019_audit_log_weekly_partitioning.sql

Features:
- Partitioned audit_log_events table by week
- WORM (Write-Once-Read-Many) archive table
- Compliance policies with enforcement
- Behavior feedback and benchmarks
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "native_0003_compliance"
down_revision: Union[str, None] = "native_0002_agent_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create compliance and audit infrastructure."""
    conn = op.get_bind()

    # =========================================================================
    # 016: Create audit_log_events (partitioned by week)
    # =========================================================================

    # Create partitioned audit_log_events table
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS audit_log_events (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            event_type VARCHAR(64) NOT NULL,
            actor_type VARCHAR(32) NOT NULL,
            actor_id VARCHAR(128) NOT NULL,
            resource_type VARCHAR(64) NOT NULL,
            resource_id UUID NULL,
            action VARCHAR(64) NOT NULL,
            outcome VARCHAR(32) NOT NULL DEFAULT 'success',
            run_id UUID NULL,
            action_id UUID NULL,
            session_id VARCHAR(128) NULL,
            actor_surface VARCHAR(64) NULL,
            ip_address INET NULL,
            user_agent TEXT NULL,
            before_state JSONB NULL,
            after_state JSONB NULL,
            metadata JSONB NULL,
            compliance_flags JSONB NULL,
            hash_chain VARCHAR(128) NULL,
            PRIMARY KEY (id, event_timestamp)
        ) PARTITION BY RANGE (event_timestamp);
    """))

    # Create initial partitions for the next 4 weeks
    conn.execute(sa.text("""
        DO $$
        DECLARE
            partition_date DATE;
            partition_name TEXT;
            start_date DATE;
            end_date DATE;
        BEGIN
            FOR i IN 0..3 LOOP
                partition_date := date_trunc('week', CURRENT_DATE + (i * 7));
                start_date := partition_date;
                end_date := partition_date + INTERVAL '7 days';
                partition_name := 'audit_log_events_' || to_char(partition_date, 'IYYY_IW');

                IF NOT EXISTS (
                    SELECT 1 FROM pg_tables
                    WHERE tablename = partition_name
                ) THEN
                    EXECUTE format(
                        'CREATE TABLE %I PARTITION OF audit_log_events
                         FOR VALUES FROM (%L) TO (%L)',
                        partition_name, start_date, end_date
                    );
                END IF;
            END LOOP;
        END $$;
    """))

    # Create indexes on partitioned table
    op.create_index("idx_audit_log_events_timestamp", "audit_log_events", ["event_timestamp"])
    op.create_index("idx_audit_log_events_type", "audit_log_events", ["event_type"])
    op.create_index("idx_audit_log_events_actor", "audit_log_events", ["actor_type", "actor_id"])
    op.create_index("idx_audit_log_events_resource", "audit_log_events", ["resource_type", "resource_id"])
    op.create_index("idx_audit_log_events_run_id", "audit_log_events", ["run_id"])
    op.create_index("idx_audit_log_events_action_id", "audit_log_events", ["action_id"])
    op.create_index("idx_audit_log_events_session_id", "audit_log_events", ["session_id"])
    op.create_index("idx_audit_log_events_metadata_gin", "audit_log_events", ["metadata"], postgresql_using="gin")

    # =========================================================================
    # 016: WORM Archive table
    # =========================================================================
    op.create_table(
        "audit_log_archives",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("partition_name", sa.String(128), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("event_count", sa.BigInteger(), nullable=False),
        sa.Column("archive_hash", sa.String(128), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=True),
        sa.Column("storage_provider", sa.String(64), nullable=True),
        sa.Column("compressed_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("retention_until", sa.Date(), nullable=False),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("locked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(128), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("partition_name", name="uq_audit_log_archives_partition"),
    )

    op.create_index("idx_audit_log_archives_week", "audit_log_archives", ["week_start", "week_end"])
    op.create_index("idx_audit_log_archives_retention", "audit_log_archives", ["retention_until"])

    # Function to automatically create new partitions
    conn.execute(sa.text("""
        CREATE OR REPLACE FUNCTION create_audit_log_partition()
        RETURNS TRIGGER AS $$
        DECLARE
            partition_date DATE;
            partition_name TEXT;
            start_date DATE;
            end_date DATE;
        BEGIN
            partition_date := date_trunc('week', NEW.event_timestamp);
            start_date := partition_date;
            end_date := partition_date + INTERVAL '7 days';
            partition_name := 'audit_log_events_' || to_char(partition_date, 'IYYY_IW');

            IF NOT EXISTS (
                SELECT 1 FROM pg_tables
                WHERE tablename = partition_name
            ) THEN
                EXECUTE format(
                    'CREATE TABLE %I PARTITION OF audit_log_events
                     FOR VALUES FROM (%L) TO (%L)',
                    partition_name, start_date, end_date
                );
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """))

    # =========================================================================
    # 017: Compliance Policies
    # =========================================================================
    op.create_table(
        "compliance_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("policy_type", sa.String(64), nullable=False),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("enforcement", sa.String(32), nullable=False, server_default="'warn'"),  # warn, block, audit
        sa.Column("applies_to", postgresql.JSONB(), nullable=True),  # resources, actors, etc.
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_compliance_policies_name"),
    )

    op.create_index("idx_compliance_policies_type", "compliance_policies", ["policy_type"])
    op.create_index("idx_compliance_policies_active", "compliance_policies", ["is_active"])
    op.create_index("idx_compliance_policies_priority", "compliance_policies", ["priority"])

    # Policy violations log
    op.create_table(
        "compliance_violations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("violation_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False, server_default="'medium'"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", sa.String(128), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("resolution_status", sa.String(32), nullable=False, server_default="'open'"),
        sa.Column("resolved_by", sa.String(128), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["policy_id"], ["compliance_policies.id"], ondelete="CASCADE"),
    )

    op.create_index("idx_compliance_violations_policy_id", "compliance_violations", ["policy_id"])
    op.create_index("idx_compliance_violations_severity", "compliance_violations", ["severity"])
    op.create_index("idx_compliance_violations_status", "compliance_violations", ["resolution_status"])
    op.create_index("idx_compliance_violations_created_at", "compliance_violations", ["created_at"])

    # =========================================================================
    # 018: Behavior Effectiveness (feedback, benchmarks, usage)
    # =========================================================================

    # behavior_feedback table
    op.create_table(
        "behavior_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("behavior_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("behavior_version", sa.Integer(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("feedback_type", sa.String(32), nullable=False),  # thumbs_up, thumbs_down, correction
        sa.Column("rating", sa.Integer(), nullable=True),  # 1-5 scale
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("suggested_improvement", sa.Text(), nullable=True),
        sa.Column("given_by", sa.String(128), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["behavior_id"], ["behaviors.id"], ondelete="CASCADE"),
    )

    op.create_index("idx_behavior_feedback_behavior_id", "behavior_feedback", ["behavior_id"])
    op.create_index("idx_behavior_feedback_type", "behavior_feedback", ["feedback_type"])
    op.create_index("idx_behavior_feedback_rating", "behavior_feedback", ["rating"])
    op.create_index("idx_behavior_feedback_created_at", "behavior_feedback", ["created_at"])

    # behavior_benchmarks table
    op.create_table(
        "behavior_benchmarks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("behavior_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("behavior_version", sa.Integer(), nullable=False),
        sa.Column("benchmark_name", sa.String(128), nullable=False),
        sa.Column("benchmark_date", sa.Date(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("success_rate", sa.Float(), nullable=False),
        sa.Column("avg_tokens_saved", sa.Float(), nullable=True),
        sa.Column("avg_latency_ms", sa.Float(), nullable=True),
        sa.Column("accuracy_score", sa.Float(), nullable=True),
        sa.Column("precision_score", sa.Float(), nullable=True),
        sa.Column("recall_score", sa.Float(), nullable=True),
        sa.Column("f1_score", sa.Float(), nullable=True),
        sa.Column("methodology", postgresql.JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["behavior_id"], ["behaviors.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("behavior_id", "benchmark_name", "benchmark_date", name="uq_behavior_benchmarks_behavior_name_date"),
    )

    op.create_index("idx_behavior_benchmarks_behavior_id", "behavior_benchmarks", ["behavior_id"])
    op.create_index("idx_behavior_benchmarks_date", "behavior_benchmarks", ["benchmark_date"])

    # behavior_usage aggregated stats
    op.create_table(
        "behavior_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("behavior_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=True),  # 0-23, NULL for daily aggregates
        sa.Column("invocations", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("successes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("failures", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_tokens_saved", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_latency_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("unique_runs", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("unique_sessions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["behavior_id"], ["behaviors.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("behavior_id", "date", "hour", name="uq_behavior_usage_behavior_date_hour"),
    )

    op.create_index("idx_behavior_usage_behavior_id", "behavior_usage", ["behavior_id"])
    op.create_index("idx_behavior_usage_date", "behavior_usage", ["date"])


def downgrade() -> None:
    """Downgrade database schema.

    Note: Compliance migrations are marked as irreversible.
    """
    raise NotImplementedError(
        "Compliance migrations are irreversible. "
        "Use backup/restore for rollback scenarios."
    )
