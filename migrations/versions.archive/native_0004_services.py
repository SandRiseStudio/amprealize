"""Services: reflection, collaboration, authentication

Revision ID: native_0004_services
Revises: native_0003_compliance
Create Date: 2025-01-13

Behavior: behavior_migrate_postgres_schema

This migration creates service infrastructure:
- 020_create_reflection_service.sql (pattern extraction, behavior candidates)
- 021_create_collaboration_service.sql (workspaces, documents)
- 022_create_auth_service.sql (internal users, sessions)
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "native_0004_services"
down_revision: Union[str, None] = "native_0003_compliance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create service infrastructure tables."""
    conn = op.get_bind()

    # =========================================================================
    # 020: Reflection Service
    # =========================================================================

    # reflection_patterns - extracted patterns from agent traces
    op.create_table(
        "reflection_patterns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("pattern_type", sa.String(64), nullable=False),  # success, failure, optimization
        sa.Column("trigger_conditions", postgresql.JSONB(), nullable=True),
        sa.Column("observed_steps", postgresql.JSONB(), nullable=True),
        sa.Column("frequency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("first_observed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("last_observed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("is_converted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("behavior_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["behavior_id"], ["behaviors.id"], ondelete="SET NULL"),
    )

    op.create_index("idx_reflection_patterns_type", "reflection_patterns", ["pattern_type"])
    op.create_index("idx_reflection_patterns_frequency", "reflection_patterns", ["frequency"])
    op.create_index("idx_reflection_patterns_confidence", "reflection_patterns", ["confidence"])
    op.create_index("idx_reflection_patterns_converted", "reflection_patterns", ["is_converted"])

    # behavior_candidates - proposed behaviors from reflection
    op.create_table(
        "behavior_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("pattern_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("proposed_triggers", postgresql.JSONB(), nullable=True),
        sa.Column("proposed_steps", postgresql.JSONB(), nullable=True),
        sa.Column("proposed_role", sa.String(32), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("validation_status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("validated_by", sa.String(128), nullable=True),
        sa.Column("validated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("converted_behavior_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("historical_validation", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pattern_id"], ["reflection_patterns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["converted_behavior_id"], ["behaviors.id"], ondelete="SET NULL"),
    )

    op.create_index("idx_behavior_candidates_pattern_id", "behavior_candidates", ["pattern_id"])
    op.create_index("idx_behavior_candidates_status", "behavior_candidates", ["validation_status"])
    op.create_index("idx_behavior_candidates_confidence", "behavior_candidates", ["confidence_score"])

    # reflection_sessions - individual reflection runs
    op.create_table(
        "reflection_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_type", sa.String(64), nullable=False),  # trace_analysis, pattern_extraction, etc.
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("input_traces", postgresql.JSONB(), nullable=True),
        sa.Column("patterns_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_proposed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
    )

    op.create_index("idx_reflection_sessions_run_id", "reflection_sessions", ["run_id"])
    op.create_index("idx_reflection_sessions_status", "reflection_sessions", ["status"])
    op.create_index("idx_reflection_sessions_type", "reflection_sessions", ["session_type"])

    # pattern_observations - link between patterns and traces
    op.create_table(
        "pattern_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pattern_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observation_data", postgresql.JSONB(), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pattern_id"], ["reflection_patterns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["reflection_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"], ondelete="SET NULL"),
    )

    op.create_index("idx_pattern_observations_pattern_id", "pattern_observations", ["pattern_id"])
    op.create_index("idx_pattern_observations_session_id", "pattern_observations", ["session_id"])
    op.create_index("idx_pattern_observations_run_id", "pattern_observations", ["run_id"])
    op.create_index("idx_pattern_observations_observed_at", "pattern_observations", ["observed_at"])

    # =========================================================================
    # 021: Collaboration Service
    # =========================================================================

    # collaboration_workspaces
    op.create_table(
        "collaboration_workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("workspace_type", sa.String(64), nullable=False, server_default="'default'"),
        sa.Column("settings", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_collab_workspaces_name", "collaboration_workspaces", ["name"])
    op.create_index("idx_collab_workspaces_type", "collaboration_workspaces", ["workspace_type"])
    op.create_index("idx_collab_workspaces_active", "collaboration_workspaces", ["is_active"])

    # workspace_members
    op.create_table(
        "workspace_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="'member'"),  # owner, admin, member, viewer
        sa.Column("permissions", postgresql.JSONB(), nullable=True),
        sa.Column("joined_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("invited_by", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["collaboration_workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
    )

    op.create_index("idx_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
    op.create_index("idx_workspace_members_user_id", "workspace_members", ["user_id"])
    op.create_index("idx_workspace_members_role", "workspace_members", ["role"])

    # collaboration_documents
    op.create_table(
        "collaboration_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("document_type", sa.String(64), nullable=False),  # prd, architecture, behavior, etc.
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_format", sa.String(32), nullable=False, server_default="'markdown'"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="'draft'"),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("last_edited_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["collaboration_workspaces.id"], ondelete="CASCADE"),
    )

    op.create_index("idx_collab_documents_workspace_id", "collaboration_documents", ["workspace_id"])
    op.create_index("idx_collab_documents_type", "collaboration_documents", ["document_type"])
    op.create_index("idx_collab_documents_status", "collaboration_documents", ["status"])

    # document_versions for versioning
    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["collaboration_documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "version", name="uq_document_versions_document_version"),
    )

    op.create_index("idx_document_versions_document_id", "document_versions", ["document_id"])

    # =========================================================================
    # 022: Auth Service (internal authentication)
    # =========================================================================

    # internal_users table
    op.create_table(
        "internal_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="'user'"),  # admin, user, service
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("verification_token", sa.String(128), nullable=True),
        sa.Column("verification_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_internal_users_email"),
    )

    op.create_index("idx_internal_users_email", "internal_users", ["email"])
    op.create_index("idx_internal_users_role", "internal_users", ["role"])
    op.create_index("idx_internal_users_active", "internal_users", ["is_active"])

    # password_reset_tokens
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(256), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["internal_users.id"], ondelete="CASCADE"),
    )

    op.create_index("idx_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("idx_password_reset_tokens_expires", "password_reset_tokens", ["expires_at"])

    # internal_sessions
    op.create_table(
        "internal_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_token_hash", sa.String(256), nullable=False),
        sa.Column("refresh_token_hash", sa.String(256), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("device_info", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_activity_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["internal_users.id"], ondelete="CASCADE"),
    )

    op.create_index("idx_internal_sessions_user_id", "internal_sessions", ["user_id"])
    op.create_index("idx_internal_sessions_active", "internal_sessions", ["is_active"])
    op.create_index("idx_internal_sessions_expires", "internal_sessions", ["expires_at"])


def downgrade() -> None:
    """Downgrade database schema.

    Note: Services migrations are marked as irreversible.
    """
    raise NotImplementedError(
        "Services migrations are irreversible. "
        "Use backup/restore for rollback scenarios."
    )
