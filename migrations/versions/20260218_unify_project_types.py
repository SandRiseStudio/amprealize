"""Unify personal and org project types.

Drop the XOR constraint that forces projects to be EITHER org-owned OR
user-owned. Projects now always have an owner_id and optionally have an
org_id. This eliminates the dual-store pattern and simplifies the codebase.

Revision ID: 20260218_unify_projects
Revises: 20260217_display_numbers
Create Date: 2026-02-18

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "20260218_unify_projects"
down_revision = "20260217_display_numbers"
branch_labels = None
depends_on = None


def upgrade():
    """Unify project types: owner_id always required, org_id optional."""

    # 1. Drop the XOR constraint that prevents both org_id and owner_id from being set
    op.execute("""
        ALTER TABLE auth.projects
        DROP CONSTRAINT IF EXISTS ck_projects_ownership_xor
    """)

    # 2. Backfill: set owner_id = created_by for any rows where owner_id is NULL
    op.execute("""
        UPDATE auth.projects
        SET owner_id = created_by
        WHERE owner_id IS NULL AND created_by IS NOT NULL
    """)

    # 3. Make owner_id NOT NULL now that all rows have a value
    op.alter_column(
        "projects",
        "owner_id",
        nullable=False,
        schema="auth",
    )

    # 4. Backfill created_by from owner_id for any rows where created_by is NULL
    op.execute("""
        UPDATE auth.projects
        SET created_by = owner_id
        WHERE created_by IS NULL AND owner_id IS NOT NULL
    """)

    # 5. Add project_membership rows for projects that don't have one for the owner
    op.execute("""
        INSERT INTO auth.project_memberships (membership_id, project_id, user_id, role, created_at, updated_at)
        SELECT
            'pmem-' || substr(md5(p.project_id || p.owner_id), 1, 12),
            p.project_id,
            p.owner_id,
            'owner',
            COALESCE(p.created_at, NOW()),
            COALESCE(p.created_at, NOW())
        FROM auth.projects p
        WHERE NOT EXISTS (
            SELECT 1 FROM auth.project_memberships pm
            WHERE pm.project_id = p.project_id AND pm.user_id = p.owner_id
        )
    """)


def downgrade():
    """Restore XOR constraint and make owner_id nullable."""

    # Make owner_id nullable again
    op.alter_column(
        "projects",
        "owner_id",
        nullable=True,
        schema="auth",
    )

    # Clear owner_id on org-owned projects to restore XOR invariant
    op.execute("""
        UPDATE auth.projects
        SET owner_id = NULL
        WHERE org_id IS NOT NULL
    """)

    # Re-add the XOR constraint
    op.execute("""
        ALTER TABLE auth.projects
        ADD CONSTRAINT ck_projects_ownership_xor
        CHECK (
            (org_id IS NOT NULL AND owner_id IS NULL) OR
            (org_id IS NULL AND owner_id IS NOT NULL)
        )
    """)
