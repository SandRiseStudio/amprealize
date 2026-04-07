"""add_project_id_to_agents

Revision ID: add_project_id_to_agents
Revises: drop_internal_users
Create Date: 2026-01-11

Behavior: behavior_migrate_postgres_schema

Adds project_id to execution.agents for org/project agent assignments.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_project_id_to_agents"
down_revision: Union[str, None] = "drop_internal_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add project_id column to execution.agents for project-level assignments."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'execution' AND table_name = 'agents'
            ) THEN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'execution'
                      AND table_name = 'agents'
                      AND column_name = 'project_id'
                ) THEN
                    ALTER TABLE execution.agents ADD COLUMN project_id VARCHAR(36);
                END IF;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agents_project_id
        ON execution.agents (project_id)
        WHERE project_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    """Remove project_id column from execution.agents."""
    op.execute("DROP INDEX IF EXISTS execution.idx_agents_project_id")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'execution'
                  AND table_name = 'agents'
                  AND column_name = 'project_id'
            ) THEN
                ALTER TABLE execution.agents DROP COLUMN project_id;
            END IF;
        END $$;
        """
    )
