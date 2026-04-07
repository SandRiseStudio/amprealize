"""Add metrics service tables and trace analysis tables.

Revision ID: 20260406_metrics_trace
Revises: compliance_svc_v1
Create Date: 2026-04-06

These tables were previously created by manual SQL scripts
(012_create_metrics_service.sql, 013_create_trace_analysis.sql)
which have since been deleted. This migration recreates them
in the Alembic chain.

Metrics tables live in public schema (AMPREALIZE_METRICS_PG_DSN search_path=public).
Trace tables live in behavior schema (AMPREALIZE_TRACE_ANALYSIS_PG_DSN search_path=behavior).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = "20260406_metrics_trace"
down_revision = "compliance_svc_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # Metrics tables (public schema)
    # ---------------------------------------------------------------
    op.create_table(
        "metrics_snapshots",
        sa.Column("snapshot_id", UUID(as_uuid=False), nullable=False),
        sa.Column("snapshot_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("behavior_reuse_pct", sa.Numeric(), nullable=True),
        sa.Column("total_runs", sa.Integer(), nullable=True),
        sa.Column("runs_with_behaviors", sa.Integer(), nullable=True),
        sa.Column("average_token_savings_pct", sa.Numeric(), nullable=True),
        sa.Column("total_baseline_tokens", sa.BigInteger(), nullable=True),
        sa.Column("total_output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("task_completion_rate_pct", sa.Numeric(), nullable=True),
        sa.Column("completed_runs", sa.Integer(), nullable=True),
        sa.Column("failed_runs", sa.Integer(), nullable=True),
        sa.Column("average_compliance_coverage_pct", sa.Numeric(), nullable=True),
        sa.Column("total_compliance_events", sa.Integer(), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aggregation_type", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("snapshot_id", "snapshot_time"),
        schema="public",
    )
    op.create_index(
        "ix_metrics_snapshots_time",
        "metrics_snapshots",
        [sa.text("snapshot_time DESC")],
        schema="public",
    )

    op.create_table(
        "behavior_usage_events",
        sa.Column("event_id", UUID(as_uuid=False), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("behavior_id", sa.Text(), nullable=True),
        sa.Column("behavior_version", sa.Text(), nullable=True),
        sa.Column("citation_count", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("actor_role", sa.Text(), nullable=True),
        sa.Column("surface", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("event_id", "event_time"),
        schema="public",
    )

    op.create_table(
        "token_usage_events",
        sa.Column("event_id", UUID(as_uuid=False), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("baseline_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("token_savings_pct", sa.Numeric(), nullable=True),
        sa.Column("bci_enabled", sa.Boolean(), nullable=True),
        sa.Column("behavior_count", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("surface", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("event_id", "event_time"),
        schema="public",
    )

    op.create_table(
        "completion_events",
        sa.Column("event_id", UUID(as_uuid=False), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Numeric(), nullable=True),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("surface", sa.Text(), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("event_id", "event_time"),
        schema="public",
    )

    op.create_table(
        "compliance_events",
        sa.Column("event_id", UUID(as_uuid=False), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("checklist_id", sa.Text(), nullable=True),
        sa.Column("coverage_score", sa.Numeric(), nullable=True),
        sa.Column("total_steps", sa.Integer(), nullable=True),
        sa.Column("completed_steps", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("surface", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("event_id", "event_time"),
        schema="public",
    )

    # ---------------------------------------------------------------
    # Trace analysis tables (behavior schema)
    # ---------------------------------------------------------------
    op.create_table(
        "trace_patterns",
        sa.Column("pattern_id", UUID(as_uuid=False), nullable=False, primary_key=True),
        sa.Column("sequence", JSONB(), nullable=False),
        sa.Column("frequency", sa.Integer(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extracted_from_runs", JSONB(), nullable=True),
        sa.Column("frequency_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("token_savings_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("applicability_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("overall_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        schema="behavior",
    )
    op.create_index(
        "ix_trace_patterns_frequency",
        "trace_patterns",
        ["frequency"],
        schema="behavior",
    )
    op.create_index(
        "ix_trace_patterns_overall_score",
        "trace_patterns",
        ["overall_score"],
        schema="behavior",
    )

    op.create_table(
        "pattern_occurrences",
        sa.Column("occurrence_id", UUID(as_uuid=False), nullable=False),
        sa.Column("occurrence_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pattern_id", UUID(as_uuid=False), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("start_step_index", sa.Integer(), nullable=False),
        sa.Column("end_step_index", sa.Integer(), nullable=False),
        sa.Column("context_before", JSONB(), nullable=True),
        sa.Column("context_after", JSONB(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("occurrence_id", "occurrence_time"),
        sa.ForeignKeyConstraint(
            ["pattern_id"],
            ["behavior.trace_patterns.pattern_id"],
            ondelete="CASCADE",
        ),
        schema="behavior",
    )

    op.create_table(
        "extraction_jobs",
        sa.Column("job_id", UUID(as_uuid=False), nullable=False, primary_key=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runs_analyzed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("patterns_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        schema="behavior",
    )

    # ---------------------------------------------------------------
    # fact_compliance_steps (public schema, used by telemetry projector)
    # ---------------------------------------------------------------
    op.create_table(
        "fact_compliance_steps",
        sa.Column("checklist_id", sa.String(), nullable=True),
        sa.Column("step_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("coverage_score", sa.Float(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("behavior_ids", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        schema="public",
    )


def downgrade() -> None:
    # Trace analysis tables
    op.drop_table("extraction_jobs", schema="behavior")
    op.drop_table("pattern_occurrences", schema="behavior")
    op.drop_index("ix_trace_patterns_overall_score", table_name="trace_patterns", schema="behavior")
    op.drop_index("ix_trace_patterns_frequency", table_name="trace_patterns", schema="behavior")
    op.drop_table("trace_patterns", schema="behavior")

    # Metrics tables
    op.drop_table("compliance_events", schema="public")
    op.drop_table("completion_events", schema="public")
    op.drop_table("token_usage_events", schema="public")
    op.drop_table("behavior_usage_events", schema="public")
    op.drop_index("ix_metrics_snapshots_time", table_name="metrics_snapshots", schema="public")
    op.drop_table("metrics_snapshots", schema="public")

    # fact_compliance_steps
    op.drop_table("fact_compliance_steps", schema="public")
