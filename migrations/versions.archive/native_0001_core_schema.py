"""Core schema: telemetry, behaviors, workflows, actions, runs, checklists

Revision ID: native_0001_core_schema
Revises: 0006_legacy_sql_026_031
Create Date: 2025-01-13

Behavior: behavior_migrate_postgres_schema

This migration creates the core Amprealize schema using native SQLAlchemy operations.
It consolidates SQL files 001-006 from schema/migrations/:
- 001_create_telemetry_warehouse.sql
- 002_create_behavior_service.sql
- 003_create_workflow_service.sql
- 004_create_action_service.sql
- 005_create_run_service.sql
- 006_create_compliance_service.sql

IMPORTANT: This is meant to replace the hybrid SQL approach. For existing databases
with the schema already applied via SQL files, stamp this revision:
    alembic stamp native_0001_core_schema
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "native_0001_core_schema"
down_revision: Union[str, None] = "0006_legacy_sql_026_031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create core schema tables."""
    conn = op.get_bind()

    # =========================================================================
    # 001: Telemetry Warehouse
    # =========================================================================

    # Create telemetry_events table
    op.create_table(
        "telemetry_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("service", sa.String(128), nullable=False),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", sa.String(128), nullable=True),
        sa.Column("actor_surface", sa.String(64), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_telemetry_events_timestamp", "telemetry_events", ["timestamp"])
    op.create_index("idx_telemetry_events_type", "telemetry_events", ["event_type"])
    op.create_index("idx_telemetry_events_service", "telemetry_events", ["service"])
    op.create_index("idx_telemetry_events_action_id", "telemetry_events", ["action_id"])
    op.create_index("idx_telemetry_events_run_id", "telemetry_events", ["run_id"])

    # Fact tables for aggregated analytics
    op.create_table(
        "fact_behavior_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("behavior_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("behavior_name", sa.String(128), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_tokens_saved", sa.Float(), nullable=True),
        sa.Column("total_tokens_saved", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("behavior_id", "date", name="uq_fact_behavior_usage_behavior_date"),
    )

    op.create_table(
        "fact_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("metric_name", sa.String(128), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("dimensions", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "metric_name", name="uq_fact_daily_metrics_date_name"),
    )

    # =========================================================================
    # 002: Behavior Service
    # =========================================================================

    # behaviors table
    op.create_table(
        "behaviors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("triggers", postgresql.JSONB(), nullable=True),
        sa.Column("steps", postgresql.JSONB(), nullable=True),
        sa.Column("role", sa.String(32), nullable=True),  # student, teacher, strategist
        sa.Column("confidence_threshold", sa.Float(), nullable=True, server_default="0.8"),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_deprecated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deprecation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_behaviors_name"),
    )

    op.create_index("idx_behaviors_category", "behaviors", ["category"])
    op.create_index("idx_behaviors_role", "behaviors", ["role"])
    op.create_index("idx_behaviors_is_active", "behaviors", ["is_active"])
    op.create_index("idx_behaviors_keywords_gin", "behaviors", ["keywords"], postgresql_using="gin")

    # behavior_versions for audit trail
    op.create_table(
        "behavior_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("behavior_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("triggers", postgresql.JSONB(), nullable=True),
        sa.Column("steps", postgresql.JSONB(), nullable=True),
        sa.Column("role", sa.String(32), nullable=True),
        sa.Column("confidence_threshold", sa.Float(), nullable=True),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["behavior_id"], ["behaviors.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("behavior_id", "version", name="uq_behavior_versions_behavior_version"),
    )

    op.create_index("idx_behavior_versions_behavior_id", "behavior_versions", ["behavior_id"])

    # =========================================================================
    # 003: Workflow Service
    # =========================================================================

    # workflow_templates table
    op.create_table(
        "workflow_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("triggers", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_workflow_templates_name"),
    )

    # workflow_template_versions for audit
    op.create_table(
        "workflow_template_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("triggers", postgresql.JSONB(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["template_id"], ["workflow_templates.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("template_id", "version", name="uq_workflow_template_versions_template_version"),
    )

    # workflow_runs table
    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("template_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("current_step", sa.Integer(), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["template_id"], ["workflow_templates.id"], ondelete="SET NULL"),
    )

    op.create_index("idx_workflow_runs_template_id", "workflow_runs", ["template_id"])
    op.create_index("idx_workflow_runs_status", "workflow_runs", ["status"])
    op.create_index("idx_workflow_runs_created_at", "workflow_runs", ["created_at"])

    # =========================================================================
    # 004: Action Service
    # =========================================================================

    # actions table
    op.create_table(
        "actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("behaviors_applied", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("tokens_saved", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["parent_action_id"], ["actions.id"], ondelete="SET NULL"),
    )

    op.create_index("idx_actions_run_id", "actions", ["run_id"])
    op.create_index("idx_actions_status", "actions", ["status"])
    op.create_index("idx_actions_action_type", "actions", ["action_type"])
    op.create_index("idx_actions_created_at", "actions", ["created_at"])
    op.create_index("idx_actions_parent_action_id", "actions", ["parent_action_id"])
    op.create_index("idx_actions_behaviors_gin", "actions", ["behaviors_applied"], postgresql_using="gin")

    # replays table for action replay/debugging
    op.create_table(
        "replays",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replay_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("original_input", postgresql.JSONB(), nullable=True),
        sa.Column("modified_input", postgresql.JSONB(), nullable=True),
        sa.Column("replay_output", postgresql.JSONB(), nullable=True),
        sa.Column("comparison", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"], ondelete="CASCADE"),
    )

    op.create_index("idx_replays_action_id", "replays", ["action_id"])
    op.create_index("idx_replays_status", "replays", ["status"])

    # =========================================================================
    # 005: Run Service
    # =========================================================================

    # runs table
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", sa.String(128), nullable=True),
        sa.Column("actor_surface", sa.String(64), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("total_actions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_actions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_actions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens_used", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens_saved", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
    )

    op.create_index("idx_runs_status", "runs", ["status"])
    op.create_index("idx_runs_session_id", "runs", ["session_id"])
    op.create_index("idx_runs_actor_surface", "runs", ["actor_surface"])
    op.create_index("idx_runs_created_at", "runs", ["created_at"])
    op.create_index("idx_runs_workflow_run_id", "runs", ["workflow_run_id"])

    # Add FK from actions to runs (deferred due to circular dep)
    op.create_foreign_key(
        "fk_actions_run_id",
        "actions",
        "runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # run_steps table for step-level tracking
    op.create_table(
        "run_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("run_id", "step_number", name="uq_run_steps_run_step"),
    )

    op.create_index("idx_run_steps_run_id", "run_steps", ["run_id"])
    op.create_index("idx_run_steps_status", "run_steps", ["status"])

    # =========================================================================
    # 006: Compliance Service (basic checklists)
    # =========================================================================

    # checklists table
    op.create_table(
        "checklists",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
    )

    op.create_index("idx_checklists_run_id", "checklists", ["run_id"])
    op.create_index("idx_checklists_status", "checklists", ["status"])
    op.create_index("idx_checklists_is_template", "checklists", ["is_template"])

    # checklist_steps table
    op.create_table(
        "checklist_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("checklist_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("behavior_ref", sa.String(128), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("checked_by", sa.String(128), nullable=True),
        sa.Column("checked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["checklist_id"], ["checklists.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("checklist_id", "step_number", name="uq_checklist_steps_checklist_step"),
    )

    op.create_index("idx_checklist_steps_checklist_id", "checklist_steps", ["checklist_id"])
    op.create_index("idx_checklist_steps_status", "checklist_steps", ["status"])


def downgrade() -> None:
    """Downgrade database schema.

    Note: Core schema migrations are marked as irreversible.
    """
    raise NotImplementedError(
        "Core schema migrations are irreversible. "
        "Use backup/restore for rollback scenarios."
    )
