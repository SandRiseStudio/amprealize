"""Add owner_id column to projects table for personal projects.

Personal projects are projects that belong to a user directly without
being part of an organization. This enables users to work on the platform
without requiring an organization.

Revision ID: add_personal_projects
Revises: add_token_vault
Create Date: 2026-01-22

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "add_personal_projects"
down_revision = "add_token_vault"
branch_labels = None
depends_on = None


def upgrade():
    """Add owner_id column and update constraints for personal projects."""

    # Add owner_id column to projects table (nullable to allow existing data)
    op.add_column(
        "projects",
        sa.Column("owner_id", sa.String(255), nullable=True),
        schema="auth"
    )

    # Add archived_at column for soft deletes (referenced in list_personal_projects)
    op.add_column(
        "projects",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        schema="auth"
    )

    # Add index for owner_id lookups (personal projects)
    op.create_index(
        "ix_projects_owner_id",
        "projects",
        ["owner_id"],
        schema="auth"
    )

    # Add partial index for active personal projects
    op.execute("""
        CREATE INDEX ix_projects_personal_active
        ON auth.projects (owner_id)
        WHERE owner_id IS NOT NULL AND archived_at IS NULL
    """)

    # Add check constraint: either org_id OR owner_id must be set, but not both
    # This ensures projects are either org-owned OR personal, never both
    op.execute("""
        ALTER TABLE auth.projects
        ADD CONSTRAINT ck_projects_ownership_xor
        CHECK (
            (org_id IS NOT NULL AND owner_id IS NULL) OR
            (org_id IS NULL AND owner_id IS NOT NULL)
        )
    """)

    # Update existing projects that have NULL org_id to fail the constraint
    # by assigning them to their creator (created_by) as owner
    # But first, we need to make org_id nullable if it isn't
    op.execute("""
        UPDATE auth.projects
        SET owner_id = created_by
        WHERE org_id IS NULL AND created_by IS NOT NULL
    """)


def downgrade():
    """Remove owner_id column and related constraints."""

    # Drop the XOR constraint
    op.execute("""
        ALTER TABLE auth.projects
        DROP CONSTRAINT IF EXISTS ck_projects_ownership_xor
    """)

    # Drop indexes
    op.execute("DROP INDEX IF EXISTS auth.ix_projects_personal_active")
    op.drop_index("ix_projects_owner_id", table_name="projects", schema="auth")

    # Drop columns
    op.drop_column("projects", "archived_at", schema="auth")
    op.drop_column("projects", "owner_id", schema="auth")
