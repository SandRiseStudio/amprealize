"""create_project_agent_assignments

Revision ID: create_project_agent_assignments
Revises: add_project_id_to_agents
Create Date: 2026-01-12

Behavior: behavior_migrate_postgres_schema

Creates a proper junction table for project-to-agent assignments, replacing
the incorrect personal agent model that expected a non-existent table structure.

Design:
- Projects can have multiple agents assigned
- Agents (from registry) can be assigned to multiple projects
- Each assignment records when it was made, by whom, and with what config overrides
- Supports both org-owned projects and personal (user-owned) projects
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "create_project_agent_assignments"
down_revision: Union[str, None] = "add_project_id_to_agents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create project_agent_assignments junction table in execution schema."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution.project_agent_assignments (
            -- Primary key
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            -- Foreign keys
            project_id VARCHAR(36) NOT NULL,
            agent_id TEXT NOT NULL,

            -- Assignment metadata
            assigned_by VARCHAR(36) NOT NULL,  -- User who made the assignment
            assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            unassigned_at TIMESTAMPTZ,  -- NULL means currently assigned

            -- Configuration overrides for this project context
            config_overrides JSONB NOT NULL DEFAULT '{}',

            -- Role/permissions within this project
            role VARCHAR(50) NOT NULL DEFAULT 'contributor',

            -- Soft delete / status
            status VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'inactive', 'removed')),

            -- Audit timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- Unique constraint: one active assignment per project-agent pair
            CONSTRAINT uq_project_agent_active
                UNIQUE (project_id, agent_id, status),

            -- Foreign key to execution.agents
            CONSTRAINT fk_assignment_agent
                FOREIGN KEY (agent_id)
                REFERENCES execution.agents(agent_id)
                ON DELETE CASCADE
        );
        """
    )

    # Create indexes for common query patterns
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_paa_project_id
        ON execution.project_agent_assignments (project_id)
        WHERE status = 'active';
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_paa_agent_id
        ON execution.project_agent_assignments (agent_id)
        WHERE status = 'active';
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_paa_assigned_by
        ON execution.project_agent_assignments (assigned_by);
        """
    )

    # Add updated_at trigger
    op.execute(
        """
        CREATE OR REPLACE FUNCTION execution.update_paa_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_paa_updated_at
        ON execution.project_agent_assignments;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_paa_updated_at
        BEFORE UPDATE ON execution.project_agent_assignments
        FOR EACH ROW
        EXECUTE FUNCTION execution.update_paa_updated_at();
        """
    )


def downgrade() -> None:
    """Drop project_agent_assignments table."""
    op.execute("DROP TRIGGER IF EXISTS trg_paa_updated_at ON execution.project_agent_assignments")
    op.execute("DROP FUNCTION IF EXISTS execution.update_paa_updated_at()")
    op.execute("DROP TABLE IF EXISTS execution.project_agent_assignments CASCADE")
