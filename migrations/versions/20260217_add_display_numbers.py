"""Add sequential display_number to boards and work_items.

Revision ID: 20260217_display_numbers
Revises: 20260122_device_sessions
Create Date: 2026-02-17

Adds project-scoped sequential display numbers for user-friendly IDs
(e.g., MYPROJ-1, MYPROJ-42) on boards and work items. UUIDs remain
as internal primary keys. A project_counters table provides atomic
counter increments via INSERT ... ON CONFLICT ... RETURNING.

Only new entities receive display numbers; existing rows stay NULL
and the frontend shows a truncated UUID fallback.

Following behavior_migrate_postgres_schema (Student).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260217_display_numbers"
down_revision = "20260122_device_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add display_number column to boards (nullable for existing rows)
    op.add_column(
        "boards",
        sa.Column("display_number", sa.Integer(), nullable=True),
        schema="board",
    )

    # 2. Add display_number column to work_items (nullable for existing rows)
    op.add_column(
        "work_items",
        sa.Column("display_number", sa.Integer(), nullable=True),
        schema="board",
    )

    # 3. Create project_counters table for atomic sequential ID generation
    op.create_table(
        "project_counters",
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("next_number", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("project_id", "entity_type"),
        schema="board",
    )

    # 4. Index for fast display_number lookups within a board
    op.create_index(
        "ix_work_items_board_display_number",
        "work_items",
        ["board_id", "display_number"],
        schema="board",
    )

    # 5. Index for fast display_number lookups on boards within a project
    op.create_index(
        "ix_boards_project_display_number",
        "boards",
        ["project_id", "display_number"],
        schema="board",
    )


def downgrade() -> None:
    op.drop_index("ix_boards_project_display_number", table_name="boards", schema="board")
    op.drop_index("ix_work_items_board_display_number", table_name="work_items", schema="board")
    op.drop_table("project_counters", schema="board")
    op.drop_column("work_items", "display_number", schema="board")
    op.drop_column("boards", "display_number", schema="board")
