"""add_execution_mode_to_projects

Revision ID: add_execution_mode
Revises: add_workflow_id_to_runs
Create Date: 2026-01-14

Behavior: behavior_migrate_postgres_schema

Adds execution_mode to project settings JSONB column with safe default (github_pr).
This enables execution surface enforcement - blocking local-mode execution from web UI.

The execution_mode field determines where file changes are written:
- 'local': Direct filesystem writes (requires IDE/CLI)
- 'github_pr': Create branch and PR (works from any surface)
- 'local_and_pr': Both local writes and PR (requires IDE/CLI)

Default is 'github_pr' as it works universally from all surfaces.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_execution_mode"
down_revision: Union[str, None] = "add_workflow_id_to_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add execution_mode to project settings with github_pr default.

    Updates existing projects to have execution_mode='github_pr' in their
    JSONB settings column. This is the safe default that works from all
    execution surfaces (web, API, CLI, IDE).
    """
    # Update all existing projects to have execution_mode in their settings
    # Uses JSONB || operator to merge new key while preserving existing settings
    # COALESCE handles NULL settings columns gracefully
    op.execute("""
        UPDATE auth.projects
        SET settings = COALESCE(settings, '{}'::jsonb) || '{"execution_mode": "github_pr"}'::jsonb
        WHERE settings IS NULL
           OR settings->>'execution_mode' IS NULL
    """)


def downgrade() -> None:
    """Remove execution_mode from project settings.

    Removes the execution_mode key from all project settings JSONB columns.
    """
    op.execute("""
        UPDATE auth.projects
        SET settings = settings - 'execution_mode'
        WHERE settings->>'execution_mode' IS NOT NULL
    """)
