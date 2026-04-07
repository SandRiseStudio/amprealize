"""add_llm_credentials

Revision ID: add_llm_credentials
Revises: add_comments_and_status_mapping
Create Date: 2026-01-12

Behavior: behavior_migrate_postgres_schema

Adds:
1. auth.llm_credentials table for BYOK credential storage
2. Supports org and project scope credentials
3. Fernet-encrypted API key storage with key_prefix for display
4. Failure tracking for auto-disable on consecutive 401/403 errors
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "add_llm_credentials"
down_revision: Union[str, None] = "add_comments_and_status_mapping"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add llm_credentials table to auth schema."""

    # Create auth schema if not exists (idempotent)
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    # =========================================================================
    # auth.llm_credentials - BYOK credential storage
    # =========================================================================
    op.create_table(
        "llm_credentials",
        # Primary key
        sa.Column("id", sa.String(36), nullable=False),

        # Scope (org or project)
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

        # Provider info
        sa.Column(
            "provider",
            sa.String(32),
            nullable=False,
            comment="LLM provider: anthropic, openai, openrouter",
        ),
        sa.Column(
            "name",
            sa.String(255),
            nullable=False,
            comment="User-friendly name for the credential",
        ),

        # Credential storage (encrypted)
        sa.Column(
            "key_prefix",
            sa.String(16),
            nullable=False,
            comment="First 8 chars of API key for display (e.g., sk-****abcd)",
        ),
        sa.Column(
            "key_encrypted",
            sa.Text(),
            nullable=False,
            comment="Fernet-encrypted API key",
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
            comment="Last time credential was confirmed working",
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
            comment="Additional metadata (rate limits, custom endpoints, etc.)",
        ),

        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type", "scope_id", "provider",
            name="uq_llm_credentials_scope_provider",
        ),
        schema="auth",
    )

    # Indexes for common queries
    op.create_index(
        "idx_auth_llm_credentials_scope",
        "llm_credentials",
        ["scope_type", "scope_id"],
        schema="auth",
    )
    op.create_index(
        "idx_auth_llm_credentials_provider",
        "llm_credentials",
        ["provider"],
        schema="auth",
    )
    op.create_index(
        "idx_auth_llm_credentials_is_valid",
        "llm_credentials",
        ["is_valid"],
        schema="auth",
    )

    # =========================================================================
    # auth.llm_credential_audit_log - Audit trail for credential operations
    # =========================================================================
    op.create_table(
        "llm_credential_audit_log",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "credential_id",
            sa.String(36),
            nullable=False,
            comment="Reference to llm_credentials.id (no FK to preserve history after delete)",
        ),
        sa.Column(
            "action",
            sa.String(32),
            nullable=False,
            comment="Action: created, updated, deleted, used, failed, disabled, re-enabled",
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
            comment="Additional details (run_id, error_code, etc.)",
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
        "idx_auth_llm_credential_audit_log_credential",
        "llm_credential_audit_log",
        ["credential_id"],
        schema="auth",
    )
    op.create_index(
        "idx_auth_llm_credential_audit_log_action",
        "llm_credential_audit_log",
        ["action"],
        schema="auth",
    )
    op.create_index(
        "idx_auth_llm_credential_audit_log_created",
        "llm_credential_audit_log",
        ["created_at"],
        schema="auth",
    )


def downgrade() -> None:
    """Remove llm_credentials tables."""

    # Drop audit log first (references credentials)
    op.drop_index(
        "idx_auth_llm_credential_audit_log_created",
        table_name="llm_credential_audit_log",
        schema="auth",
    )
    op.drop_index(
        "idx_auth_llm_credential_audit_log_action",
        table_name="llm_credential_audit_log",
        schema="auth",
    )
    op.drop_index(
        "idx_auth_llm_credential_audit_log_credential",
        table_name="llm_credential_audit_log",
        schema="auth",
    )
    op.drop_table("llm_credential_audit_log", schema="auth")

    # Drop credentials table
    op.drop_index(
        "idx_auth_llm_credentials_is_valid",
        table_name="llm_credentials",
        schema="auth",
    )
    op.drop_index(
        "idx_auth_llm_credentials_provider",
        table_name="llm_credentials",
        schema="auth",
    )
    op.drop_index(
        "idx_auth_llm_credentials_scope",
        table_name="llm_credentials",
        schema="auth",
    )
    op.drop_table("llm_credentials", schema="auth")
