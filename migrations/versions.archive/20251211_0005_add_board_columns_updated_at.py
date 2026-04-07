"""Add board_columns.updated_at for optimistic concurrency

Revision ID: 0005_board_columns_updated_at
Revises: 0004_board_entities
Create Date: 2025-12-11

Behavior: behavior_migrate_postgres_schema

Adds `updated_at` to `board_columns` to support optimistic concurrency for drag-and-drop
operations (Epic 13.5.5).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0005_board_columns_updated_at"
down_revision: Union[str, None] = "0004_board_entities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add as nullable first for safe backfill.
    op.execute("ALTER TABLE board_columns ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")

    # Backfill for existing rows.
    op.execute(
        "UPDATE board_columns SET updated_at = created_at WHERE updated_at IS NULL"
    )

    # Enforce not-null and default.
    op.execute("ALTER TABLE board_columns ALTER COLUMN updated_at SET NOT NULL")
    op.execute("ALTER TABLE board_columns ALTER COLUMN updated_at SET DEFAULT NOW()")


def downgrade() -> None:
    op.execute("ALTER TABLE board_columns DROP COLUMN IF EXISTS updated_at")
