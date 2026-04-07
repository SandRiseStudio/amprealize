"""Add local_project_path column to projects table

Revision ID: 0008_local_project_path
Revises: 0007_federated_auth
Create Date: 2025-12-12

Behavior: behavior_migrate_postgres_schema

This migration adds an explicit local_project_path column to the projects table
for direct querying, separate from the JSONB settings column.

The local_project_path stores the filesystem path to the project on the user's
local machine (e.g., /Users/nick/myproject). This enables:
- VS Code extension workspace auto-detection
- Quick lookup without parsing JSONB
- Better indexing for project discovery

The column is nullable since not all projects will have a local path configured
(e.g., cloud-only projects or projects viewed from different machines).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0008_local_project_path"
down_revision: Union[str, None] = "0007_federated_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add local_project_path column to projects table."""

    # Add local_project_path column for explicit querying
    # This is separate from the settings JSONB to enable:
    # 1. Direct SQL queries without JSON extraction
    # 2. Indexing for workspace discovery
    # 3. Cross-reference with VS Code workspace detection
    op.add_column(
        'projects',
        sa.Column('local_project_path', sa.Text(), nullable=True)
    )

    # Add index for fast lookups by local path
    # Useful for "find project by workspace path" queries
    op.create_index(
        'ix_projects_local_project_path',
        'projects',
        ['local_project_path'],
        unique=False
    )

    # Migrate existing data from settings JSONB if present
    # This ensures backwards compatibility with any projects that
    # already have local_project_path stored in settings
    op.execute("""
        UPDATE projects
        SET local_project_path = settings->>'local_project_path'
        WHERE settings->>'local_project_path' IS NOT NULL
          AND local_project_path IS NULL
    """)


def downgrade() -> None:
    """Remove local_project_path column from projects table."""

    # Drop the index first
    op.drop_index('ix_projects_local_project_path', table_name='projects')

    # Drop the column
    op.drop_column('projects', 'local_project_path')
