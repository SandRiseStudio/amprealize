"""Add workflow_id column to execution.runs table.

Revision ID: add_workflow_id_to_runs
Revises: drop_assignee_fk, add_llm_credentials
Create Date: 2026-01-13

This column is used by WorkItemExecutionService to filter runs by workflow type.
The 'work_item_execution' workflow_id identifies runs that are work item executions.

This migration merges the two divergent branches:
- drop_assignee_fk (agent assignment changes)
- add_llm_credentials (LLM credential storage)
"""

import sqlalchemy as sa
from alembic import op

revision = "add_workflow_id_to_runs"
down_revision = ("drop_assignee_fk", "add_llm_credentials")  # Merge point
branch_labels = None
depends_on = None


def upgrade():
    # Add workflow_id column to execution.runs
    op.add_column(
        "runs",
        sa.Column("workflow_id", sa.String(128), nullable=True),
        schema="execution",
    )
    # Add workflow_name column for descriptive name
    op.add_column(
        "runs",
        sa.Column("workflow_name", sa.String(256), nullable=True),
        schema="execution",
    )
    # Add index for workflow_id filtering
    op.create_index(
        "idx_execution_runs_workflow",
        "runs",
        ["workflow_id"],
        schema="execution",
    )


def downgrade():
    op.drop_index("idx_execution_runs_workflow", table_name="runs", schema="execution")
    op.drop_column("runs", "workflow_name", schema="execution")
    op.drop_column("runs", "workflow_id", schema="execution")
