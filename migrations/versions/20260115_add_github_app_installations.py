"""add_github_app_installations

Revision ID: add_github_app_installations
Revises: add_github_credentials
Create Date: 2026-01-15

Behavior: behavior_migrate_postgres_schema

Adds:
1. auth.github_app_installations table for GitHub App installation tracking
2. Supports org and project scope installations (multiple projects can share one installation)
3. Fernet-encrypted token cache for installation access tokens
4. Repository selection tracking (all or selected repos)
5. Permission tracking for compliance validation

Note: Webhooks are NOT implemented initially - we handle errors gracefully.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "add_github_app_installations"
down_revision: Union[str, None] = "add_github_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add github_app_installations table to auth schema."""

    # Create auth schema if not exists (idempotent)
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    # =========================================================================
    # auth.github_app_installations - GitHub App installation tracking
    # =========================================================================
    op.create_table(
        "github_app_installations",
        # Primary key (UUID)
        sa.Column("id", sa.String(36), nullable=False),

        # GitHub App installation info (from GitHub)
        sa.Column(
            "installation_id",
            sa.BigInteger,
            nullable=False,
            comment="GitHub App installation ID",
        ),
        sa.Column(
            "app_id",
            sa.BigInteger,
            nullable=True,
            comment="GitHub App ID (for multi-app support)",
        ),
        sa.Column(
            "account_type",
            sa.String(16),
            nullable=False,
            comment="GitHub account type: 'User' or 'Organization'",
        ),
        sa.Column(
            "account_login",
            sa.String(255),
            nullable=False,
            comment="GitHub username or org name",
        ),
        sa.Column(
            "account_id",
            sa.BigInteger,
            nullable=False,
            comment="GitHub account ID",
        ),
        sa.Column(
            "account_avatar_url",
            sa.Text(),
            nullable=True,
            comment="GitHub account avatar URL for display",
        ),

        # Scope - which Amprealize entity this installation is linked to
        # Multiple projects can link to the same installation
        sa.Column(
            "scope_type",
            sa.String(16),
            nullable=False,
            comment="Scope type: 'org' or 'project'",
        ),
        sa.Column(
            "scope_id",
            sa.String(36),
            nullable=False,
            comment="org_id or project_id",
        ),

        # Repository access configuration
        sa.Column(
            "repository_selection",
            sa.String(16),
            nullable=True,
            comment="Repository access: 'all' or 'selected'",
        ),
        sa.Column(
            "selected_repository_ids",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
            comment="List of repository IDs if selection is 'selected'",
        ),

        # Permissions granted by user during installation
        sa.Column(
            "permissions",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="Permissions object from GitHub (e.g., {contents: 'write'})",
        ),

        # Events the app is subscribed to (optional, for webhook handling)
        sa.Column(
            "events",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
            comment="Events subscribed to (e.g., ['push', 'pull_request'])",
        ),

        # Cached installation access token (encrypted, short-lived)
        sa.Column(
            "cached_token_encrypted",
            sa.Text(),
            nullable=True,
            comment="Fernet-encrypted cached installation access token",
        ),
        sa.Column(
            "cached_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Expiration time of cached token (usually 1 hour)",
        ),

        # Status tracking
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default="true",
            nullable=False,
            comment="Whether installation is active (set to false on uninstall)",
        ),
        sa.Column(
            "suspended_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the installation was suspended (if applicable)",
        ),
        sa.Column(
            "suspended_reason",
            sa.Text(),
            nullable=True,
            comment="Reason for suspension",
        ),

        # Audit fields
        sa.Column(
            "installed_by",
            sa.String(36),
            nullable=True,
            comment="Amprealize user ID who linked this installation",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),

        # Metadata for extensibility
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="Additional metadata (e.g., target_type, html_url)",
        ),

        # Primary key
        sa.PrimaryKeyConstraint("id"),

        schema="auth",
    )

    # Indexes for common queries
    # Note: installation_id is NOT unique because same installation can be linked to multiple projects
    op.create_index(
        "idx_github_app_installations_installation_id",
        "github_app_installations",
        ["installation_id"],
        schema="auth",
    )
    op.create_index(
        "idx_github_app_installations_scope",
        "github_app_installations",
        ["scope_type", "scope_id"],
        schema="auth",
    )
    op.create_index(
        "idx_github_app_installations_account",
        "github_app_installations",
        ["account_login"],
        schema="auth",
    )
    op.create_index(
        "idx_github_app_installations_active",
        "github_app_installations",
        ["is_active"],
        schema="auth",
        postgresql_where=sa.text("is_active = true"),
    )

    # =========================================================================
    # auth.github_app_installation_links - Many-to-many: projects to installations
    # Allows multiple projects to share the same GitHub App installation
    # =========================================================================
    op.create_table(
        "github_app_installation_links",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "installation_id",
            sa.BigInteger,
            nullable=False,
            comment="GitHub App installation ID",
        ),
        sa.Column(
            "scope_type",
            sa.String(16),
            nullable=False,
            comment="Scope type: 'org' or 'project'",
        ),
        sa.Column(
            "scope_id",
            sa.String(36),
            nullable=False,
            comment="org_id or project_id",
        ),
        sa.Column(
            "linked_by",
            sa.String(36),
            nullable=True,
            comment="Amprealize user who linked this",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # Unique constraint: one link per scope
        sa.UniqueConstraint("scope_type", "scope_id", name="uq_github_app_link_scope"),
        schema="auth",
    )

    op.create_index(
        "idx_github_app_links_installation",
        "github_app_installation_links",
        ["installation_id"],
        schema="auth",
    )


def downgrade() -> None:
    """Remove GitHub App installation tables."""
    op.drop_table("github_app_installation_links", schema="auth")
    op.drop_table("github_app_installations", schema="auth")
