"""Unified schema baseline for Modular Monolith architecture (Pure Python - No SQL)

Revision ID: schema_baseline
Revises: None
Create Date: 2025-12-16

Behavior: behavior_migrate_postgres_schema

This migration establishes the Modular Monolith database architecture with:
- 7 domain schemas in a single PostgreSQL database
- Cross-schema foreign keys enabled
- pgvector extension for embeddings

This is a pure Python migration - NO external SQL files are loaded.

For existing databases: stamp this revision to skip execution
    alembic stamp schema_baseline

For new databases: run normally
    alembic upgrade head

Schemas:
- auth: users, sessions, organizations, api_keys
- board: boards, columns, work_items, sprints
- behavior: behaviors, behavior_embeddings, behavior_executions
- execution: runs, actions, run_steps, replays
- workflow: workflow_templates, workflow_runs, workflow_steps
- consent: consents, consent_scopes
- audit: audit_log (append-only)
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "schema_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Domain schemas
SCHEMAS = ["auth", "board", "behavior", "execution", "workflow", "consent", "audit"]


def upgrade() -> None:
    """Create schema-based architecture."""
    conn = op.get_bind()

    # =========================================================================
    # STEP 1: Create all schemas
    # =========================================================================
    for schema in SCHEMAS:
        conn.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))

    # =========================================================================
    # STEP 2: Enable extensions
    # =========================================================================
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

    # pgvector - for behavior embeddings (optional, use savepoint to avoid aborting transaction)
    try:
        # Check if vector extension is available before trying to create it
        result = conn.execute(sa.text(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
        ))
        if result.fetchone():
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:
        pass  # May not be available in all environments

    # =========================================================================
    # SCHEMA: auth
    # =========================================================================

    # auth.organizations
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("plan", sa.String(64), server_default="free"),
        sa.Column("status", sa.String(64), server_default="active"),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("settings", postgresql.JSONB(), server_default="{}"),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        schema="auth",
    )

    # auth.users
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),  # NULL for OAuth-only
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("email_verified", sa.Boolean(), server_default="false"),
        sa.Column("email_verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        schema="auth",
    )
    op.create_index("idx_auth_users_email", "users", ["email"], schema="auth")

    # auth.org_memberships
    op.create_table(
        "org_memberships",
        sa.Column("membership_id", sa.String(36), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(64), server_default="member"),
        sa.Column("invited_by", sa.String(36), nullable=True),
        sa.Column("invited_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("membership_id"),
        sa.ForeignKeyConstraint(["org_id"], ["auth.organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_memberships_org_user"),
        schema="auth",
    )
    op.create_index("idx_auth_org_memberships_user", "org_memberships", ["user_id"], schema="auth")

    # auth.projects
    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=True),  # NULL for personal projects
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(64), server_default="private"),
        sa.Column("local_project_path", sa.Text(), nullable=True),
        sa.Column("settings", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("project_id"),
        sa.ForeignKeyConstraint(["org_id"], ["auth.organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["auth.users.id"], ondelete="SET NULL"),
        schema="auth",
    )
    op.create_index("idx_auth_projects_org", "projects", ["org_id"], schema="auth")

    # auth.project_memberships
    op.create_table(
        "project_memberships",
        sa.Column("membership_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(64), server_default="member"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("membership_id"),
        sa.ForeignKeyConstraint(["project_id"], ["auth.projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_memberships_project_user"),
        schema="auth",
    )
    op.create_index("idx_auth_project_memberships_user", "project_memberships", ["user_id"], schema="auth")
    op.create_index("idx_auth_project_memberships_project", "project_memberships", ["project_id"], schema="auth")

    # auth.subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("plan", sa.String(64), server_default="free"),
        sa.Column("status", sa.String(64), server_default="active"),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("current_period_start", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("subscription_id"),
        sa.ForeignKeyConstraint(["org_id"], ["auth.organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        schema="auth",
    )
    op.create_index("idx_auth_subscriptions_org", "subscriptions", ["org_id"], schema="auth")
    op.create_index("idx_auth_subscriptions_user", "subscriptions", ["user_id"], schema="auth")

    # auth.sessions
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("device_info", postgresql.JSONB(), server_default="{}"),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        schema="auth",
    )
    op.create_index("idx_auth_sessions_user", "sessions", ["user_id"], schema="auth")
    op.create_index("idx_auth_sessions_token_hash", "sessions", ["token_hash"], schema="auth")
    op.create_index("idx_auth_sessions_expires", "sessions", ["expires_at"], schema="auth")

    # auth.api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),  # First 8 chars for display
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["auth.organizations.id"], ondelete="CASCADE"),
        schema="auth",
    )
    op.create_index("idx_auth_api_keys_user", "api_keys", ["user_id"], schema="auth")
    op.create_index("idx_auth_api_keys_key_hash", "api_keys", ["key_hash"], schema="auth")

    # auth.federated_identities
    op.create_table(
        "federated_identities",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),  # github, google, etc.
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(255), nullable=True),
        sa.Column("provider_username", sa.String(255), nullable=True),
        sa.Column("provider_display_name", sa.String(255), nullable=True),
        sa.Column("provider_avatar_url", sa.Text(), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("scopes", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("raw_profile", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_federated_provider_user"),
        schema="auth",
    )
    op.create_index("idx_auth_federated_user", "federated_identities", ["user_id"], schema="auth")

    # auth.mfa_devices
    op.create_table(
        "mfa_devices",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("device_type", sa.String(50), server_default="totp"),
        sa.Column("device_name", sa.String(255), nullable=True),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("backup_codes_encrypted", sa.Text(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), server_default="false"),
        sa.Column("is_primary", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        schema="auth",
    )
    op.create_index("idx_auth_mfa_user", "mfa_devices", ["user_id"], schema="auth")

    # =========================================================================
    # SCHEMA: behavior
    # =========================================================================

    # behavior.behaviors
    op.create_table(
        "behaviors",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("namespace", sa.String(64), server_default="default"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("triggers", postgresql.JSONB(), server_default="[]"),
        sa.Column("steps", postgresql.JSONB(), server_default="[]"),
        sa.Column("role", sa.String(32), nullable=True),  # student, teacher, strategist
        sa.Column("confidence_threshold", sa.Float(), server_default="0.8"),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("is_deprecated", sa.Boolean(), server_default="false"),
        sa.Column("deprecation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "namespace", "name", name="uq_behaviors_org_ns_name"),
        sa.ForeignKeyConstraint(["org_id"], ["auth.organizations.id"], ondelete="CASCADE"),
        schema="behavior",
    )
    op.create_index("idx_behavior_behaviors_name", "behaviors", ["name"], schema="behavior")
    op.create_index("idx_behavior_behaviors_category", "behaviors", ["category"], schema="behavior")
    op.create_index("idx_behavior_behaviors_role", "behaviors", ["role"], schema="behavior")
    op.create_index("idx_behavior_behaviors_keywords_gin", "behaviors", ["keywords"],
                    postgresql_using="gin", schema="behavior")

    # behavior.behavior_versions
    op.create_table(
        "behavior_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("behavior_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("triggers", postgresql.JSONB(), server_default="[]"),
        sa.Column("steps", postgresql.JSONB(), server_default="[]"),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["behavior_id"], ["behavior.behaviors.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("behavior_id", "version", name="uq_behavior_versions_bv"),
        schema="behavior",
    )
    op.create_index("idx_behavior_versions_behavior", "behavior_versions", ["behavior_id"], schema="behavior")

    # behavior.behavior_embeddings
    op.create_table(
        "behavior_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("behavior_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("behavior_version", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(64), server_default="'text-embedding-3-small'"),
        sa.Column("embedding_data", sa.Text(), nullable=False),  # Store as text, cast to vector in queries
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["behavior_id"], ["behavior.behaviors.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("behavior_id", "behavior_version", "embedding_model", name="uq_embeddings_bvm"),
        schema="behavior",
    )

    # behavior.behavior_executions (tracking behavior usage)
    op.create_table(
        "behavior_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("behavior_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("tokens_saved", sa.Integer(), nullable=True),
        sa.Column("context", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["behavior_id"], ["behavior.behaviors.id"], ondelete="CASCADE"),
        schema="behavior",
    )
    op.create_index("idx_behavior_executions_behavior", "behavior_executions", ["behavior_id"], schema="behavior")
    op.create_index("idx_behavior_executions_created", "behavior_executions", ["created_at"], schema="behavior")

    # behavior.reflection_patterns (extracted patterns from trace analysis)
    op.create_table(
        "reflection_patterns",
        sa.Column("pattern_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("pattern_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("frequency", sa.Integer(), server_default="1"),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("pattern_id"),
        schema="behavior",
    )
    op.create_index("idx_reflection_patterns_run", "reflection_patterns", ["run_id"], schema="behavior")
    op.create_index("idx_reflection_patterns_type", "reflection_patterns", ["pattern_type"], schema="behavior")
    op.create_index("idx_reflection_patterns_confidence", "reflection_patterns", ["confidence"], schema="behavior")

    # behavior.behavior_candidates (proposed behaviors from reflection)
    op.create_table(
        "behavior_candidates",
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("pattern_id", sa.String(64), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("triggers", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("steps", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("status", sa.String(32), server_default="'proposed'"),
        sa.Column("role", sa.String(32), server_default="'student'"),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("historical_validation", postgresql.JSONB(), nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("merged_behavior_id", sa.String(64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.ForeignKeyConstraint(["pattern_id"], ["behavior.reflection_patterns.pattern_id"], ondelete="SET NULL"),
        schema="behavior",
    )
    op.create_index("idx_behavior_candidates_status", "behavior_candidates", ["status"], schema="behavior")
    op.create_index("idx_behavior_candidates_confidence", "behavior_candidates", ["confidence"], schema="behavior")
    op.create_index("idx_behavior_candidates_keywords_gin", "behavior_candidates", ["keywords"],
                    postgresql_using="gin", schema="behavior")

    # behavior.reflection_sessions (tracks reflection analysis sessions)
    op.create_table(
        "reflection_sessions",
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("session_type", sa.String(32), server_default="'automatic'"),
        sa.Column("patterns_extracted", sa.Integer(), server_default="0"),
        sa.Column("candidates_generated", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(32), server_default="'pending'"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("session_id"),
        schema="behavior",
    )
    op.create_index("idx_reflection_sessions_run", "reflection_sessions", ["run_id"], schema="behavior")
    op.create_index("idx_reflection_sessions_status", "reflection_sessions", ["status"], schema="behavior")

    # behavior.pattern_observations (tracks pattern occurrences for 3+ threshold)
    op.create_table(
        "pattern_observations",
        sa.Column("observation_id", sa.String(64), nullable=False),
        sa.Column("pattern_hash", sa.String(64), nullable=False),
        sa.Column("pattern_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("line_range", sa.String(32), nullable=True),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("observation_id"),
        schema="behavior",
    )
    op.create_index("idx_pattern_observations_hash", "pattern_observations", ["pattern_hash"], schema="behavior")
    op.create_index("idx_pattern_observations_run", "pattern_observations", ["run_id"], schema="behavior")

    # =========================================================================
    # SCHEMA: execution
    # =========================================================================

    # execution.runs
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), server_default="'pending'"),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", sa.String(128), nullable=True),
        sa.Column("actor_surface", sa.String(64), nullable=True),
        sa.Column("context", postgresql.JSONB(), server_default="{}"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("total_actions", sa.Integer(), server_default="0"),
        sa.Column("completed_actions", sa.Integer(), server_default="0"),
        sa.Column("failed_actions", sa.Integer(), server_default="0"),
        sa.Column("total_tokens_used", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens_saved", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["auth.organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["auth.projects.project_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="SET NULL"),
        schema="execution",
    )
    op.create_index("idx_execution_runs_status", "runs", ["status"], schema="execution")
    op.create_index("idx_execution_runs_session", "runs", ["session_id"], schema="execution")
    op.create_index("idx_execution_runs_created", "runs", ["created_at"], schema="execution")
    op.create_index("idx_execution_runs_org", "runs", ["org_id"], schema="execution")

    # execution.actions
    op.create_table(
        "actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="'pending'"),
        sa.Column("input_data", postgresql.JSONB(), server_default="{}"),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("behaviors_applied", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("tokens_saved", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["execution.runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_action_id"], ["execution.actions.id"], ondelete="SET NULL"),
        schema="execution",
    )
    op.create_index("idx_execution_actions_run", "actions", ["run_id"], schema="execution")
    op.create_index("idx_execution_actions_status", "actions", ["status"], schema="execution")
    op.create_index("idx_execution_actions_type", "actions", ["action_type"], schema="execution")
    op.create_index("idx_execution_actions_created", "actions", ["created_at"], schema="execution")

    # execution.run_steps
    op.create_table(
        "run_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), server_default="'pending'"),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["execution.runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_id"], ["execution.actions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("run_id", "step_number", name="uq_run_steps_run_step"),
        schema="execution",
    )
    op.create_index("idx_execution_run_steps_run", "run_steps", ["run_id"], schema="execution")

    # execution.replays
    op.create_table(
        "replays",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replay_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="'pending'"),
        sa.Column("original_input", postgresql.JSONB(), nullable=True),
        sa.Column("modified_input", postgresql.JSONB(), nullable=True),
        sa.Column("replay_output", postgresql.JSONB(), nullable=True),
        sa.Column("comparison", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("tags", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["action_id"], ["execution.actions.id"], ondelete="CASCADE"),
        schema="execution",
    )
    op.create_index("idx_execution_replays_action", "replays", ["action_id"], schema="execution")

    # execution.agent_personas
    op.create_table(
        "agent_personas",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), server_default="{}"),
        sa.Column("default_behaviors", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["auth.organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "name", name="uq_agent_personas_org_name"),
        schema="execution",
    )

    # execution.agent_assignments
    op.create_table(
        "agent_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("unassigned_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), server_default="'active'"),
        sa.Column("context", postgresql.JSONB(), server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["execution.runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["persona_id"], ["execution.agent_personas.id"], ondelete="CASCADE"),
        schema="execution",
    )
    op.create_index("idx_execution_assignments_run", "agent_assignments", ["run_id"], schema="execution")

    # =========================================================================
    # SCHEMA: workflow
    # =========================================================================

    # workflow.workflow_templates
    op.create_table(
        "workflow_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("triggers", postgresql.JSONB(), server_default="[]"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["auth.organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "name", name="uq_workflow_templates_org_name"),
        schema="workflow",
    )

    # workflow.workflow_runs
    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("template_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), server_default="'pending'"),
        sa.Column("current_step", sa.Integer(), nullable=True),
        sa.Column("context", postgresql.JSONB(), server_default="{}"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["template_id"], ["workflow.workflow_templates.id"], ondelete="SET NULL"),
        schema="workflow",
    )
    op.create_index("idx_workflow_runs_template", "workflow_runs", ["template_id"], schema="workflow")
    op.create_index("idx_workflow_runs_status", "workflow_runs", ["status"], schema="workflow")

    # workflow.workflow_step_runs
    op.create_table(
        "workflow_step_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), server_default="'pending'"),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow.workflow_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workflow_run_id", "step_index", name="uq_workflow_steps_run_idx"),
        schema="workflow",
    )
    op.create_index("idx_workflow_step_runs_run", "workflow_step_runs", ["workflow_run_id"], schema="workflow")

    # workflow.task_cycles (GEP)
    op.create_table(
        "task_cycles",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(255), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("current_phase", sa.String(32), server_default="'PLANNING'"),
        sa.Column("status", sa.String(32), server_default="'active'"),
        sa.Column("acceptance_criteria", postgresql.JSONB(), server_default="[]"),
        sa.Column("timeout_config", postgresql.JSONB(), server_default='{"clarification_timeout_hours": 24, "architecture_timeout_hours": 48, "verification_timeout_hours": 48, "policy": "pause_with_notification"}'),
        sa.Column("test_iteration", sa.Integer(), server_default="0"),
        sa.Column("max_test_iterations", sa.Integer(), server_default="5"),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["auth.organizations.id"], ondelete="SET NULL"),
        schema="workflow",
    )
    op.create_index("idx_workflow_task_cycles_task", "task_cycles", ["task_id"], schema="workflow")
    op.create_index("idx_workflow_task_cycles_phase", "task_cycles", ["current_phase"], schema="workflow")

    # =========================================================================
    # SCHEMA: board
    # =========================================================================

    # board.boards
    op.create_table(
        "boards",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("settings", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["auth.organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["auth.projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["auth.users.id"], ondelete="SET NULL"),
        schema="board",
    )
    op.create_index("idx_board_boards_org", "boards", ["org_id"], schema="board")
    op.create_index("idx_board_boards_project", "boards", ["project_id"], schema="board")

    # board.columns
    op.create_table(
        "columns",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("board_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("wip_limit", sa.Integer(), nullable=True),
        sa.Column("color", sa.String(32), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["board_id"], ["board.boards.id"], ondelete="CASCADE"),
        schema="board",
    )
    op.create_index("idx_board_columns_board", "columns", ["board_id"], schema="board")

    # board.work_items
    op.create_table(
        "work_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("board_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("column_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("item_type", sa.String(64), server_default="'task'"),
        sa.Column("status", sa.String(64), server_default="'open'"),
        sa.Column("priority", sa.Integer(), server_default="0"),
        sa.Column("position", sa.Integer(), server_default="0"),
        sa.Column("assignee_id", sa.String(36), nullable=True),
        sa.Column("reporter_id", sa.String(36), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("labels", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("due_date", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["board_id"], ["board.boards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["column_id"], ["board.columns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assignee_id"], ["auth.users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reporter_id"], ["auth.users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["execution.runs.id"], ondelete="SET NULL"),
        schema="board",
    )
    op.create_index("idx_board_work_items_board", "work_items", ["board_id"], schema="board")
    op.create_index("idx_board_work_items_column", "work_items", ["column_id"], schema="board")
    op.create_index("idx_board_work_items_assignee", "work_items", ["assignee_id"], schema="board")
    op.create_index("idx_board_work_items_status", "work_items", ["status"], schema="board")

    # board.sprints
    op.create_table(
        "sprints",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("board_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), server_default="'planning'"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["board_id"], ["board.boards.id"], ondelete="CASCADE"),
        schema="board",
    )
    op.create_index("idx_board_sprints_board", "sprints", ["board_id"], schema="board")

    # board.collaboration_workspaces
    op.create_table(
        "collaboration_workspaces",
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("workspace_type", sa.String(32), server_default="'shared'"),
        sa.Column("settings", postgresql.JSONB(), server_default="{}"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("workspace_id"),
        sa.ForeignKeyConstraint(["owner_id"], ["auth.users.id"], ondelete="CASCADE"),
        schema="board",
    )
    op.create_index("idx_collab_workspaces_owner", "collaboration_workspaces", ["owner_id"], schema="board")

    # board.workspace_members
    op.create_table(
        "workspace_members",
        sa.Column("member_id", sa.String(64), nullable=False),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(32), server_default="'editor'"),
        sa.Column("permissions", postgresql.JSONB(), server_default="{}"),
        sa.Column("joined_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("last_active_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.PrimaryKeyConstraint("member_id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["board.collaboration_workspaces.workspace_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_ws_user"),
        schema="board",
    )
    op.create_index("idx_workspace_members_workspace", "workspace_members", ["workspace_id"], schema="board")
    op.create_index("idx_workspace_members_user", "workspace_members", ["user_id"], schema="board")

    # board.collaboration_documents
    op.create_table(
        "collaboration_documents",
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), server_default="''"),
        sa.Column("document_type", sa.String(32), server_default="'text'"),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("locked_by", sa.String(36), nullable=True),
        sa.Column("locked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("lock_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("last_edited_by", sa.String(36), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("document_id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["board.collaboration_workspaces.workspace_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["auth.users.id"], ondelete="SET NULL"),
        schema="board",
    )
    op.create_index("idx_collab_documents_workspace", "collaboration_documents", ["workspace_id"], schema="board")
    op.create_index("idx_collab_documents_type", "collaboration_documents", ["document_type"], schema="board")

    # board.document_versions
    op.create_table(
        "document_versions",
        sa.Column("version_id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("edited_by", sa.String(36), nullable=False),
        sa.Column("edit_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("version_id"),
        sa.ForeignKeyConstraint(["document_id"], ["board.collaboration_documents.document_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_versions_doc_ver"),
        schema="board",
    )
    op.create_index("idx_document_versions_document", "document_versions", ["document_id"], schema="board")

    # board.active_cursors (real-time cursor positions)
    op.create_table(
        "active_cursors",
        sa.Column("cursor_id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("position_line", sa.Integer(), server_default="0"),
        sa.Column("position_column", sa.Integer(), server_default="0"),
        sa.Column("selection_start_line", sa.Integer(), nullable=True),
        sa.Column("selection_start_column", sa.Integer(), nullable=True),
        sa.Column("selection_end_line", sa.Integer(), nullable=True),
        sa.Column("selection_end_column", sa.Integer(), nullable=True),
        sa.Column("color", sa.String(32), nullable=True),
        sa.Column("last_updated", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("cursor_id"),
        sa.ForeignKeyConstraint(["document_id"], ["board.collaboration_documents.document_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "user_id", name="uq_active_cursors_doc_user"),
        schema="board",
    )
    op.create_index("idx_active_cursors_document", "active_cursors", ["document_id"], schema="board")

    # board.pending_edits (queued edits for conflict resolution)
    op.create_table(
        "pending_edits",
        sa.Column("edit_id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("position_start", sa.Integer(), nullable=False),
        sa.Column("position_end", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), server_default="'pending'"),
        sa.Column("conflict_resolution", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("applied_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("edit_id"),
        sa.ForeignKeyConstraint(["document_id"], ["board.collaboration_documents.document_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        schema="board",
    )
    op.create_index("idx_pending_edits_document", "pending_edits", ["document_id"], schema="board")
    op.create_index("idx_pending_edits_status", "pending_edits", ["status"], schema="board")

    # board.collaboration_events (activity stream)
    op.create_table(
        "collaboration_events",
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_data", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("event_id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["board.collaboration_workspaces.workspace_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["board.collaboration_documents.document_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        schema="board",
    )
    op.create_index("idx_collab_events_workspace", "collaboration_events", ["workspace_id"], schema="board")
    op.create_index("idx_collab_events_document", "collaboration_events", ["document_id"], schema="board")
    op.create_index("idx_collab_events_type", "collaboration_events", ["event_type"], schema="board")
    op.create_index("idx_collab_events_created", "collaboration_events", ["created_at"], schema="board")

    # =========================================================================
    # SCHEMA: consent
    # =========================================================================

    # consent.consent_scopes
    op.create_table(
        "consent_scopes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(32), server_default="'low'"),
        sa.Column("requires_mfa", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_consent_scopes_name"),
        schema="consent",
    )

    # consent.consents
    op.create_table(
        "consents",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=False),
        sa.Column("granted_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("context", postgresql.JSONB(), server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_id"], ["consent.consent_scopes.id"], ondelete="CASCADE"),
        schema="consent",
    )
    op.create_index("idx_consent_consents_user", "consents", ["user_id"], schema="consent")
    op.create_index("idx_consent_consents_scope", "consents", ["scope_id"], schema="consent")

    # =========================================================================
    # SCHEMA: audit
    # =========================================================================

    # audit.audit_log (append-only)
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),  # user, system, agent
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="'success'"),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        schema="audit",
    )
    op.create_index("idx_audit_log_event_type", "audit_log", ["event_type"], schema="audit")
    op.create_index("idx_audit_log_actor", "audit_log", ["actor_type", "actor_id"], schema="audit")
    op.create_index("idx_audit_log_resource", "audit_log", ["resource_type", "resource_id"], schema="audit")
    op.create_index("idx_audit_log_created", "audit_log", ["created_at"], schema="audit")
    op.create_index("idx_audit_log_org", "audit_log", ["org_id"], schema="audit")

    # audit.checklists (compliance checklists)
    op.create_table(
        "checklists",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(32), server_default="'pending'"),
        sa.Column("is_template", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["auth.organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["execution.runs.id"], ondelete="SET NULL"),
        schema="audit",
    )
    op.create_index("idx_audit_checklists_run", "checklists", ["run_id"], schema="audit")
    op.create_index("idx_audit_checklists_status", "checklists", ["status"], schema="audit")

    # audit.checklist_steps
    op.create_table(
        "checklist_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("checklist_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), server_default="'pending'"),
        sa.Column("is_required", sa.Boolean(), server_default="true"),
        sa.Column("behavior_ref", sa.String(128), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), server_default="{}"),
        sa.Column("checked_by", sa.String(128), nullable=True),
        sa.Column("checked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["checklist_id"], ["audit.checklists.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("checklist_id", "step_number", name="uq_checklist_steps_cl_step"),
        schema="audit",
    )
    op.create_index("idx_audit_checklist_steps_cl", "checklist_steps", ["checklist_id"], schema="audit")

    # =========================================================================
    # STEP 3: Add cross-schema FK from execution.runs to workflow.workflow_runs
    # =========================================================================
    op.create_foreign_key(
        "fk_runs_workflow_run",
        "runs",
        "workflow_runs",
        ["workflow_run_id"],
        ["id"],
        source_schema="execution",
        referent_schema="workflow",
        ondelete="SET NULL",
    )

    # =========================================================================
    # STEP 4: Add cross-schema FK for behavior_executions
    # =========================================================================
    op.create_foreign_key(
        "fk_behavior_exec_run",
        "behavior_executions",
        "runs",
        ["run_id"],
        ["id"],
        source_schema="behavior",
        referent_schema="execution",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_behavior_exec_action",
        "behavior_executions",
        "actions",
        ["action_id"],
        ["id"],
        source_schema="behavior",
        referent_schema="execution",
        ondelete="SET NULL",
    )

    # Log completion
    conn.execute(sa.text("""
        DO $$
        BEGIN
            RAISE NOTICE 'Schema baseline migration completed successfully';
            RAISE NOTICE 'Created schemas: auth, board, behavior, execution, workflow, consent, audit';
        END $$;
    """))


def downgrade() -> None:
    """Drop all schemas (destructive!)."""
    conn = op.get_bind()

    # Drop schemas in reverse dependency order
    for schema in reversed(SCHEMAS):
        conn.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
