"""add_assignment_schema

Revision ID: add_assignment_schema
Revises: create_project_agent_assignments
Create Date: 2026-01-12

Behavior: behavior_migrate_postgres_schema

Adds missing columns for work item assignments:
- assignee_type: user or agent
- assigned_at: timestamp of assignment
- assigned_by: user who made the assignment
- project_id: link to project

Also creates the assignment_history table for audit trail.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "add_assignment_schema"
down_revision: Union[str, None] = "create_project_agent_assignments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add assignment columns to work_items and create assignment_history table."""

    # Add missing columns to work_items
    op.add_column(
        "work_items",
        sa.Column("assignee_type", sa.String(32), nullable=True),
        schema="board",
    )
    op.add_column(
        "work_items",
        sa.Column("assigned_at", sa.TIMESTAMP(timezone=True), nullable=True),
        schema="board",
    )
    op.add_column(
        "work_items",
        sa.Column("assigned_by", sa.String(36), nullable=True),
        schema="board",
    )
    op.add_column(
        "work_items",
        sa.Column("project_id", sa.String(36), nullable=True),
        schema="board",
    )
    op.add_column(
        "work_items",
        sa.Column("org_id", sa.String(36), nullable=True),
        schema="board",
    )

    # Add index for project_id lookups
    op.create_index(
        "idx_board_work_items_project",
        "work_items",
        ["project_id"],
        schema="board",
    )

    # Add index for org_id lookups
    op.create_index(
        "idx_board_work_items_org",
        "work_items",
        ["org_id"],
        schema="board",
    )

    # Create assignment_history table in board schema
    op.create_table(
        "assignment_history",
        sa.Column("history_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("assignable_id", sa.String(64), nullable=False),
        sa.Column("assignable_type", sa.String(32), nullable=False),
        sa.Column("assignee_id", sa.String(36), nullable=True),
        sa.Column("assignee_type", sa.String(32), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("performed_by", sa.String(36), nullable=False),
        sa.Column("performed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("previous_assignee_id", sa.String(36), nullable=True),
        sa.Column("previous_assignee_type", sa.String(32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.CheckConstraint(
            "assignable_type IN ('story', 'task', 'epic', 'bug', 'feature')",
            name="valid_assignable_type"
        ),
        schema="board",
    )

    # Create indexes for assignment_history
    op.create_index(
        "idx_assignment_history_assignable",
        "assignment_history",
        ["assignable_id", "assignable_type"],
        schema="board",
    )
    op.create_index(
        "idx_assignment_history_assignee",
        "assignment_history",
        ["assignee_id", "assignee_type"],
        schema="board",
    )
    op.create_index(
        "idx_assignment_history_performed_at",
        "assignment_history",
        ["performed_at"],
        schema="board",
    )
    op.create_index(
        "idx_assignment_history_org_id",
        "assignment_history",
        ["org_id"],
        schema="board",
    )
    op.create_index(
        "idx_assignment_history_project_id",
        "assignment_history",
        ["project_id"],
        schema="board",
    )


def downgrade() -> None:
    """Remove assignment columns and assignment_history table."""

    # Drop assignment_history table
    op.drop_index("idx_assignment_history_project_id", table_name="assignment_history", schema="board")
    op.drop_index("idx_assignment_history_org_id", table_name="assignment_history", schema="board")
    op.drop_index("idx_assignment_history_performed_at", table_name="assignment_history", schema="board")
    op.drop_index("idx_assignment_history_assignee", table_name="assignment_history", schema="board")
    op.drop_index("idx_assignment_history_assignable", table_name="assignment_history", schema="board")
    op.drop_table("assignment_history", schema="board")

    # Drop work_items columns
    op.drop_index("idx_board_work_items_org", table_name="work_items", schema="board")
    op.drop_index("idx_board_work_items_project", table_name="work_items", schema="board")
    op.drop_column("work_items", "org_id", schema="board")
    op.drop_column("work_items", "project_id", schema="board")
    op.drop_column("work_items", "assigned_by", schema="board")
    op.drop_column("work_items", "assigned_at", schema="board")
    op.drop_column("work_items", "assignee_type", schema="board")
