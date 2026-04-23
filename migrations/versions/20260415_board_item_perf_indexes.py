"""Add board.work_items performance indexes for Neon/cloud pagination workloads.

Revision ID: 20260415_board_item_perf_indexes
Revises: 20260414_whiteboard_snapshots
Create Date: 2026-04-15

Following behavior_migrate_postgres_schema (Student).
"""

from alembic import op


revision = "20260415_board_item_perf_indexes"
down_revision = "20260414_whiteboard_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Speeds default board ordering query path (board_id filter + ORDER BY position, created_at)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_board_work_items_board_position_created_at
        ON board.work_items (board_id, position, created_at)
        """
    )

    # Ensure hierarchy support exists in fresh databases before indexing it.
    op.execute(
        """
        ALTER TABLE board.work_items
        ADD COLUMN IF NOT EXISTS parent_id UUID
        REFERENCES board.work_items(id) ON DELETE SET NULL
        """
    )

    # Speeds parent-child hierarchy lookups and aggregation queries.
    # Older runtime code created this index as idx_work_items_parent_id, so
    # reuse/rename that index instead of creating a duplicate with a new name.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('board.idx_board_work_items_parent_id') IS NULL THEN
                IF to_regclass('board.idx_work_items_parent_id') IS NOT NULL THEN
                    ALTER INDEX board.idx_work_items_parent_id
                    RENAME TO idx_board_work_items_parent_id;
                ELSE
                    CREATE INDEX idx_board_work_items_parent_id
                    ON board.work_items (parent_id)
                    WHERE parent_id IS NOT NULL;
                END IF;
            END IF;
        END
        $$;
        """
    )

    # Speeds labels overlap filter (w.labels && %s::varchar[])
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_board_work_items_labels_gin
        ON board.work_items USING GIN (labels)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS board.idx_board_work_items_labels_gin")
    op.execute("DROP INDEX IF EXISTS board.idx_board_work_items_parent_id")
    op.execute("DROP INDEX IF EXISTS board.idx_work_items_parent_id")
    op.execute("ALTER TABLE board.work_items DROP COLUMN IF EXISTS parent_id")
    op.execute("DROP INDEX IF EXISTS board.idx_board_work_items_board_position_created_at")
