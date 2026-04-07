"""Drop assignee_id foreign key constraint to allow agent assignment.

Revision ID: drop_assignee_fk
Revises: add_assignment_schema
Create Date: 2026-01-12

The work_items.assignee_id column can reference either:
- auth.users (when assignee_type = 'user')
- execution.agents (when assignee_type = 'agent')

PostgreSQL doesn't support conditional/polymorphic foreign keys, so we drop
the FK constraint and rely on application-level validation via assignee_type.

This aligns with AGENT_AUTH_ARCHITECTURE.md where users and agents are in
separate tables (auth.users vs execution.agents).
"""

import sqlalchemy as sa
from alembic import op

revision = "drop_assignee_fk"
down_revision = "add_assignment_schema"
branch_labels = None
depends_on = None


def upgrade():
    # Drop the FK constraint that requires assignee_id to be in auth.users
    # This allows assignee_id to hold either user IDs or agent IDs
    op.drop_constraint(
        "work_items_assignee_id_fkey",
        "work_items",
        schema="board",
        type_="foreignkey",
    )


def downgrade():
    # Re-add the FK constraint (will fail if any agent assignments exist)
    op.create_foreign_key(
        "work_items_assignee_id_fkey",
        "work_items",
        "users",
        ["assignee_id"],
        ["id"],
        source_schema="board",
        referent_schema="auth",
        ondelete="SET NULL",
    )
