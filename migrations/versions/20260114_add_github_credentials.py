"""add_github_credentials

Revision ID: add_github_credentials
Revises: add_execution_mode_to_projects
Create Date: 2026-01-14

Behavior: behavior_migrate_postgres_schema

Adds:
1. auth.github_credentials table for BYOK GitHub PAT storage
2. Supports org and project scope credentials (one per scope)
3. Fernet-encrypted token storage with token_prefix for display
4. Auto-detection of token type (classic, fine-grained, app)
5. Rate limit tracking for PR creation operations
6. Failure tracking for auto-disable on consecutive failures
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "add_github_credentials"
down_revision: Union[str, None] = "add_execution_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add github_credentials table to auth schema."""

    # Create auth schema if not exists (idempotent)
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    # =========================================================================
    # auth.github_credentials - BYOK GitHub PAT storage
    # =========================================================================
    op.create_table(
        "github_credentials",
        # Primary key
        sa.Column("id", sa.String(36), nullable=False),

        # Scope (org or project) - only ONE GitHub credential per scope
        sa.Column(
            "scope_type",
            sa.String(16),
            nullable=False,
            comment="Credential scope: 'org' or 'project'",
        ),
        sa.Column(
            "scope_id",
            sa.String(36),
            nullable=False,
            comment="org_id or project_id depending on scope_type",
        ),

        # Token info
        sa.Column(
            "token_type",
            sa.String(32),
            nullable=False,
            comment="Token type: 'classic' (ghp_), 'fine_grained' (github_pat_), 'app' (ghs_)",
        ),
        sa.Column(
            "name",
            sa.String(255),
            nullable=False,
            comment="User-friendly name for the credential",
        ),

        # Credential storage (encrypted)
        sa.Column(
            "token_prefix",
            sa.String(24),
            nullable=False,
            comment="First chars of token for display (e.g., ghp_xxxx****)",
        ),
        sa.Column(
            "token_encrypted",
            sa.Text(),
            nullable=False,
            comment="Fernet-encrypted GitHub token",
        ),

        # Validation state
        sa.Column(
            "is_valid",
            sa.Boolean(),
            server_default="true",
            nullable=False,
            comment="False if credential has been auto-disabled due to failures",
        ),
        sa.Column(
            "failure_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Consecutive 401/403 failures (resets on success)",
        ),

        # GitHub-specific metadata (scopes and rate limits)
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.String(64)),
            nullable=True,
            comment="OAuth scopes granted to this token (from X-OAuth-Scopes header)",
        ),
        sa.Column(
            "rate_limit",
            sa.Integer(),
            nullable=True,
            comment="Rate limit ceiling (from X-RateLimit-Limit)",
        ),
        sa.Column(
            "rate_limit_remaining",
            sa.Integer(),
            nullable=True,
            comment="Rate limit remaining (from X-RateLimit-Remaining)",
        ),
        sa.Column(
            "rate_limit_reset",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Rate limit reset time (from X-RateLimit-Reset)",
        ),

        # Usage tracking
        sa.Column(
            "last_used_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Last time this credential was used for an API call",
        ),
        sa.Column(
            "last_validated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Last time credential was validated against GitHub API",
        ),

        # GitHub user info (populated on validation)
        sa.Column(
            "github_username",
            sa.String(64),
            nullable=True,
            comment="GitHub username associated with this token",
        ),
        sa.Column(
            "github_user_id",
            sa.Integer(),
            nullable=True,
            comment="GitHub user ID associated with this token",
        ),

        # Audit fields
        sa.Column(
            "created_by",
            sa.String(36),
            nullable=False,
            comment="User ID who created this credential",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),

        # Metadata (for future extensions)
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="Additional metadata (allowed repos, custom API base, etc.)",
        ),

        # Constraints
        sa.PrimaryKeyConstraint("id"),
        # Only ONE GitHub credential per scope (unlike LLM which is per provider)
        sa.UniqueConstraint(
            "scope_type", "scope_id",
            name="uq_github_credentials_scope",
        ),
        schema="auth",
    )

    # Indexes for common queries
    op.create_index(
        "idx_auth_github_credentials_scope",
        "github_credentials",
        ["scope_type", "scope_id"],
        schema="auth",
    )
    op.create_index(
        "idx_auth_github_credentials_is_valid",
        "github_credentials",
        ["is_valid"],
        schema="auth",
    )
    op.create_index(
        "idx_auth_github_credentials_token_type",
        "github_credentials",
        ["token_type"],
        schema="auth",
    )

    # =========================================================================
    # auth.github_credential_audit_log - Audit trail for credential operations
    # =========================================================================
    op.create_table(
        "github_credential_audit_log",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "credential_id",
            sa.String(36),
            nullable=False,
            comment="Reference to github_credentials.id (no FK to preserve history after delete)",
        ),
        sa.Column(
            "action",
            sa.String(32),
            nullable=False,
            comment="Action: created, updated, deleted, used, failed, disabled, re-enabled, validated",
        ),
        sa.Column(
            "actor_id",
            sa.String(36),
            nullable=True,
            comment="User or service principal who performed the action",
        ),
        sa.Column(
            "actor_type",
            sa.String(16),
            nullable=False,
            server_default="user",
            comment="Actor type: user, service, system",
        ),
        sa.Column(
            "details",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="Additional details (run_id, error_code, rate_limits, etc.)",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="auth",
    )

    op.create_index(
        "idx_auth_github_credential_audit_log_credential",
        "github_credential_audit_log",
        ["credential_id"],
        schema="auth",
    )
    op.create_index(
        "idx_auth_github_credential_audit_log_action",
        "github_credential_audit_log",
        ["action"],
        schema="auth",
    )
    op.create_index(
        "idx_auth_github_credential_audit_log_created",
        "github_credential_audit_log",
        ["created_at"],
        schema="auth",
    )


def downgrade() -> None:
    """Remove github_credentials tables."""

    # Drop audit log first (references credentials)
    op.drop_index(
        "idx_auth_github_credential_audit_log_created",
        table_name="github_credential_audit_log",
        schema="auth",
    )
    op.drop_index(
        "idx_auth_github_credential_audit_log_action",
        table_name="github_credential_audit_log",
        schema="auth",
    )
    op.drop_index(
        "idx_auth_github_credential_audit_log_credential",
        table_name="github_credential_audit_log",
        schema="auth",
    )
    op.drop_table("github_credential_audit_log", schema="auth")

    # Drop credentials table
    op.drop_index(
        "idx_auth_github_credentials_token_type",
        table_name="github_credentials",
        schema="auth",
    )
    op.drop_index(
        "idx_auth_github_credentials_is_valid",
        table_name="github_credentials",
        schema="auth",
    )
    op.drop_index(
        "idx_auth_github_credentials_scope",
        table_name="github_credentials",
        schema="auth",
    )
    op.drop_table("github_credentials", schema="auth")
