"""add_comments_and_status_mapping

Revision ID: add_comments_and_status_mapping
Revises: add_assignment_schema
Create Date: 2026-01-12

Behavior: behavior_migrate_postgres_schema

Adds:
1. work_item_comments table for tracking comments on work items
2. status_mapping column to columns table for column→status mapping

This enables:
- workItems.postComment MCP tool
- workItems.moveToColumn MCP tool with semantic status resolution
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "add_comments_and_status_mapping"
down_revision: Union[str, None] = "add_assignment_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add work_item_comments table and status_mapping column."""

    # =========================================================================
    # Add status_mapping column to columns table
    # =========================================================================
    op.add_column(
        "columns",
        sa.Column("status_mapping", sa.String(64), nullable=True),
        schema="board",
    )

    # Set default status_mapping based on column name heuristics
    # This is a data migration to populate existing columns
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE board.columns
        SET status_mapping = CASE
            WHEN LOWER(name) LIKE '%done%' OR LOWER(name) LIKE '%complete%' THEN 'done'
            WHEN LOWER(name) LIKE '%review%' THEN 'in_review'
            WHEN LOWER(name) LIKE '%progress%' OR LOWER(name) LIKE '%working%' THEN 'in_progress'
            WHEN LOWER(name) LIKE '%todo%' OR LOWER(name) LIKE '%to do%' THEN 'todo'
            WHEN LOWER(name) LIKE '%backlog%' THEN 'backlog'
            ELSE 'todo'
        END
        WHERE status_mapping IS NULL
    """))

    # =========================================================================
    # Create work_item_comments table
    # =========================================================================
    op.create_table(
        "work_item_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", sa.String(36), nullable=False),
        sa.Column("author_type", sa.String(32), nullable=False),  # 'user' or 'agent'
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),  # Link to execution run
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["work_item_id"],
            ["board.work_items.id"],
            ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["execution.runs.id"],
            ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "author_type IN ('user', 'agent')",
            name="valid_comment_author_type"
        ),
        schema="board",
    )

    # Indexes for efficient queries
    op.create_index(
        "idx_board_work_item_comments_work_item",
        "work_item_comments",
        ["work_item_id"],
        schema="board",
    )
    op.create_index(
        "idx_board_work_item_comments_author",
        "work_item_comments",
        ["author_id"],
        schema="board",
    )
    op.create_index(
        "idx_board_work_item_comments_run",
        "work_item_comments",
        ["run_id"],
        schema="board",
    )
    op.create_index(
        "idx_board_work_item_comments_created",
        "work_item_comments",
        ["created_at"],
        schema="board",
    )
    op.create_index(
        "idx_board_work_item_comments_org",
        "work_item_comments",
        ["org_id"],
        schema="board",
    )


def downgrade() -> None:
    """Remove work_item_comments table and status_mapping column."""

    # Drop indexes first
    op.drop_index("idx_board_work_item_comments_org", table_name="work_item_comments", schema="board")
    op.drop_index("idx_board_work_item_comments_created", table_name="work_item_comments", schema="board")
    op.drop_index("idx_board_work_item_comments_run", table_name="work_item_comments", schema="board")
    op.drop_index("idx_board_work_item_comments_author", table_name="work_item_comments", schema="board")
    op.drop_index("idx_board_work_item_comments_work_item", table_name="work_item_comments", schema="board")

    # Drop table
    op.drop_table("work_item_comments", schema="board")

    # Drop status_mapping column
    op.drop_column("columns", "status_mapping", schema="board")
