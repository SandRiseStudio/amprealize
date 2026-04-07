"""add_user_github_links

Revision ID: add_user_github_links
Revises: ad1244ed2cf6
Create Date: 2026-01-15

Behavior: behavior_migrate_postgres_schema

Adds:
1. auth.user_project_github_links - Per-user-per-project GitHub credential linking
2. auth.user_github_preferences - User default GitHub settings across projects

Design decisions:
- GitHub App installations are SHAREABLE across users (team can share one install)
- PATs are PERSONAL (user's own token shouldn't be shared with teammates)
- User-project links let each user choose which credential to use per project
- Default preference allows "use my default for new projects"
- Audit granularity: Per-run with operation summary in metadata
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "add_user_github_links"
down_revision: Union[str, None] = "ad1244ed2cf6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add user-project GitHub links and preferences tables."""

    # Create auth schema if not exists (idempotent)
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    # =========================================================================
    # auth.user_project_github_links - Per-user-per-project GitHub credential links
    # =========================================================================
    # This table allows each user to specify which GitHub credential (PAT or App)
    # they want to use for a specific project. When an agent runs on behalf of
    # a user, the system resolves their linked credential first.
    op.create_table(
        "user_project_github_links",
        # Primary key (UUID)
        sa.Column("id", sa.String(36), nullable=False),

        # User and project scope
        sa.Column(
            "user_id",
            sa.String(36),
            nullable=False,
            comment="Amprealize user ID",
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            nullable=False,
            comment="Project this link applies to",
        ),

        # Link type determines which credential source to use
        sa.Column(
            "link_type",
            sa.String(16),
            nullable=False,
            comment="Type of credential: 'pat' (personal access token) or 'app' (GitHub App)",
        ),

        # For PAT links: reference to user's PAT credential
        # Note: PATs are personal - each user can have their own PAT for a project
        sa.Column(
            "github_credential_id",
            sa.String(36),
            nullable=True,
            comment="References credentials.github_credentials.id for PAT links",
        ),

        # For App links: reference to GitHub App installation
        # Note: App installations are shareable - user links to a shared installation
        sa.Column(
            "installation_link_id",
            sa.String(36),
            nullable=True,
            comment="References auth.github_app_installation_links.id for App links",
        ),

        # User preference flag - which credential to use when both are available
        sa.Column(
            "is_preferred",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="Whether this is the preferred credential when multiple are linked",
        ),

        # Priority ordering (lower = higher priority, allows fine-grained control)
        sa.Column(
            "priority",
            sa.Integer(),
            server_default="100",
            nullable=False,
            comment="Priority for resolution (lower = higher priority, default 100)",
        ),

        # Audit fields
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
            comment="Additional metadata (e.g., reason for link, auto-linked flag)",
        ),

        # Primary key
        sa.PrimaryKeyConstraint("id"),

        # Unique constraint: one link per user/project/type combination
        sa.UniqueConstraint(
            "user_id", "project_id", "link_type",
            name="uq_user_project_github_link_type"
        ),

        # Check constraint: must have either credential_id or installation_link_id
        sa.CheckConstraint(
            "(link_type = 'pat' AND github_credential_id IS NOT NULL AND installation_link_id IS NULL) OR "
            "(link_type = 'app' AND installation_link_id IS NOT NULL AND github_credential_id IS NULL)",
            name="ck_github_link_type_reference"
        ),

        schema="auth",
    )

    # Indexes for common queries
    op.create_index(
        "idx_user_project_github_links_user",
        "user_project_github_links",
        ["user_id"],
        schema="auth",
    )
    op.create_index(
        "idx_user_project_github_links_project",
        "user_project_github_links",
        ["project_id"],
        schema="auth",
    )
    op.create_index(
        "idx_user_project_github_links_user_project",
        "user_project_github_links",
        ["user_id", "project_id"],
        schema="auth",
    )
    op.create_index(
        "idx_user_project_github_links_resolution",
        "user_project_github_links",
        ["user_id", "project_id", "priority"],
        schema="auth",
    )

    # =========================================================================
    # auth.user_github_preferences - User-level default GitHub settings
    # =========================================================================
    # Stores user preferences for GitHub credentials across all projects,
    # including "use my default for new projects" setting.
    op.create_table(
        "user_github_preferences",
        # Primary key (UUID)
        sa.Column("id", sa.String(36), nullable=False),

        # User this preference belongs to
        sa.Column(
            "user_id",
            sa.String(36),
            nullable=False,
            comment="Amprealize user ID",
        ),

        # Default credential settings
        sa.Column(
            "default_pat_credential_id",
            sa.String(36),
            nullable=True,
            comment="User's default PAT credential to use for new projects",
        ),
        sa.Column(
            "default_app_installation_id",
            sa.String(36),
            nullable=True,
            comment="User's default GitHub App installation ID for new projects",
        ),

        # Auto-linking preference
        sa.Column(
            "auto_link_new_projects",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="Whether to auto-link default credential to new projects",
        ),

        # Preference for which type to use when both are available
        sa.Column(
            "prefer_app_over_pat",
            sa.Boolean(),
            server_default="true",
            nullable=False,
            comment="When both App and PAT are available, prefer App (more secure)",
        ),

        # Audit fields
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

        # Metadata
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="Additional user preferences",
        ),

        # Primary key
        sa.PrimaryKeyConstraint("id"),

        # Unique: one preference record per user
        sa.UniqueConstraint("user_id", name="uq_user_github_preferences_user"),

        schema="auth",
    )

    op.create_index(
        "idx_user_github_preferences_user",
        "user_github_preferences",
        ["user_id"],
        schema="auth",
    )

    # =========================================================================
    # auth.github_credential_usage_log - Audit log for credential usage in runs
    # =========================================================================
    # Per-run audit with operation summary in metadata (as requested)
    op.create_table(
        "github_credential_usage_log",
        # Primary key (UUID)
        sa.Column("id", sa.String(36), nullable=False),

        # What run used this credential
        sa.Column(
            "run_id",
            sa.String(36),
            nullable=False,
            comment="The run that used this credential",
        ),

        # Who triggered the run
        sa.Column(
            "triggering_user_id",
            sa.String(36),
            nullable=True,
            comment="User who triggered the run (null for scheduled/automated runs)",
        ),

        # Which credential was resolved and used
        sa.Column(
            "resolved_source",
            sa.String(32),
            nullable=False,
            comment="Source of resolved token: user_app, user_pat, project_app, project_pat, org_app, org_pat, platform",
        ),
        sa.Column(
            "credential_id",
            sa.String(36),
            nullable=True,
            comment="ID of the credential/installation used (null for platform)",
        ),

        # Project context
        sa.Column(
            "project_id",
            sa.String(36),
            nullable=False,
            comment="Project ID for this run",
        ),
        sa.Column(
            "org_id",
            sa.String(36),
            nullable=True,
            comment="Organization ID if applicable",
        ),

        # Operation summary (per-run with summary as requested)
        sa.Column(
            "operations",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="Summary of operations: {branches_created: 1, commits_made: 5, prs_opened: 1}",
        ),

        # Outcome
        sa.Column(
            "success",
            sa.Boolean(),
            nullable=False,
            comment="Whether credential usage was successful",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="Error message if failed",
        ),

        # Timestamp
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),

        # Metadata
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="Additional context (rate limits, duration, etc.)",
        ),

        # Primary key
        sa.PrimaryKeyConstraint("id"),

        schema="auth",
    )

    # Indexes for audit queries
    op.create_index(
        "idx_github_credential_usage_run",
        "github_credential_usage_log",
        ["run_id"],
        schema="auth",
    )
    op.create_index(
        "idx_github_credential_usage_user",
        "github_credential_usage_log",
        ["triggering_user_id"],
        schema="auth",
    )
    op.create_index(
        "idx_github_credential_usage_project",
        "github_credential_usage_log",
        ["project_id"],
        schema="auth",
    )
    op.create_index(
        "idx_github_credential_usage_credential",
        "github_credential_usage_log",
        ["credential_id"],
        schema="auth",
    )
    op.create_index(
        "idx_github_credential_usage_created",
        "github_credential_usage_log",
        ["created_at"],
        schema="auth",
    )


def downgrade() -> None:
    """Remove user GitHub links and preferences tables."""
    op.drop_table("github_credential_usage_log", schema="auth")
    op.drop_table("user_github_preferences", schema="auth")
    op.drop_table("user_project_github_links", schema="auth")
