"""Create agent_presence table for runtime presence tracking.

Tracks per-agent runtime presence state (working, available, paused, etc.)
separate from the agent registry lifecycle (ACTIVE/DEPRECATED) and
project assignment status (active/inactive/removed).

Revision ID: 20260321_agent_presence
Revises: 20260320_rename_wi_types
Create Date: 2026-03-21

Behavior: behavior_migrate_postgres_schema
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260321_agent_presence"
down_revision: Union[str, None] = "20260320_rename_wi_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create execution.agent_presence table."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution.agent_presence (
            -- Composite PK: one presence row per agent per project
            agent_id TEXT NOT NULL,
            project_id VARCHAR(36) NOT NULL,

            -- Runtime presence state
            presence_status VARCHAR(30) NOT NULL DEFAULT 'offline'
                CHECK (presence_status IN (
                    'available', 'working', 'finished_recently',
                    'paused', 'offline', 'at_capacity'
                )),

            -- Activity timestamps
            last_activity_at TIMESTAMPTZ,
            last_completed_at TIMESTAMPTZ,

            -- Workload
            active_item_count INTEGER NOT NULL DEFAULT 0,
            capacity_max INTEGER NOT NULL DEFAULT 4,
            current_work_item_id TEXT,

            -- Audit
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- Constraints
            PRIMARY KEY (agent_id, project_id),

            CONSTRAINT fk_presence_agent
                FOREIGN KEY (agent_id)
                REFERENCES execution.agents(agent_id)
                ON DELETE CASCADE
        );
        """
    )

    # Index for the most common query: all agents' presence in a project
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_presence_project
            ON execution.agent_presence (project_id);
        """
    )

    # Index for looking up a single agent's presence across projects
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_presence_agent
            ON execution.agent_presence (agent_id);
        """
    )


def downgrade() -> None:
    """Drop execution.agent_presence table."""
    op.execute("DROP INDEX IF EXISTS execution.idx_agent_presence_agent;")
    op.execute("DROP INDEX IF EXISTS execution.idx_agent_presence_project;")
    op.execute("DROP TABLE IF EXISTS execution.agent_presence;")
