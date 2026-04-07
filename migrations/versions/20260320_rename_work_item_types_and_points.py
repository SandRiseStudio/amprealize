"""Rename work item types (epic→goal, story→feature) and story_points→points.

Part of AMPREALIZE-491: Standardize work item terminology.

- Renames item_type values: 'epic' → 'goal', 'story' → 'feature' in work_items table
- Renames column: story_points → points in work_items table
- Recreates agent_workload view with updated column names (total_points)
- Maintains backward-compat aliases in the view for 1 release cycle

Revision ID: 20260320_rename_wi_types
Revises: 20260319_add_feature_flags
Create Date: 2026-03-20

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "20260320_rename_wi_types"
down_revision = "20260319_add_feature_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Rename item_type values in work_items
    op.execute("""
        UPDATE board.work_items
        SET item_type = 'goal'
        WHERE item_type = 'epic'
    """)
    op.execute("""
        UPDATE board.work_items
        SET item_type = 'feature'
        WHERE item_type = 'story'
    """)

    # 2. Rename story_points column → points (or add points if column never existed)
    #    The baseline schema (20251216) never included story_points, so on a fresh DB
    #    the column doesn't exist. Only legacy DBs upgraded from archived migrations have it.
    has_story_points = conn.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'board'
              AND table_name = 'work_items'
              AND column_name = 'story_points'
        )
    """)).scalar()

    if has_story_points:
        op.alter_column(
            "work_items",
            "story_points",
            new_column_name="points",
            schema="board",
        )
    else:
        # Fresh install — add the column directly
        has_points = conn.execute(sa.text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'board'
                  AND table_name = 'work_items'
                  AND column_name = 'points'
            )
        """)).scalar()
        if not has_points:
            op.add_column(
                "work_items",
                sa.Column("points", sa.Integer(), nullable=True),
                schema="board",
            )

    # 3. Recreate agent_workload view with new column names
    #    Keep total_story_points as alias for backward compat (1 release)
    op.execute("""
        DROP VIEW IF EXISTS board.agent_workload;
        CREATE OR REPLACE VIEW board.agent_workload AS
        SELECT
            assignee_id,
            assignee_type,
            org_id,
            COUNT(*) FILTER (WHERE status IN ('todo', 'in_progress', 'in_review')) AS active_items,
            COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
            COUNT(*) FILTER (WHERE status = 'done') AS completed_count,
            SUM(COALESCE(points, 0)) AS total_points,
            SUM(COALESCE(points, 0)) AS total_story_points  -- backward compat alias
        FROM board.work_items
        WHERE assignee_id IS NOT NULL AND assignee_type = 'agent'
        GROUP BY assignee_id, assignee_type, org_id
    """)

    op.execute("""
        COMMENT ON VIEW board.agent_workload IS
        'Aggregated workload per agent for capacity planning. total_story_points is a deprecated alias for total_points.'
    """)


def downgrade() -> None:
    conn = op.get_bind()

    # 1. Check if we need to rename points back to story_points (legacy DB)
    #    or just drop the points column (fresh install where it was added by upgrade).
    has_points = conn.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'board'
              AND table_name = 'work_items'
              AND column_name = 'points'
        )
    """)).scalar()

    if has_points:
        # Check which migration path created it: if the pre-baseline DB had story_points,
        # we renamed it, so rename it back. Otherwise we added it fresh, so just drop it.
        # Heuristic: check revision history for legacy markers.  For simplicity, always
        # rename back — the column name doesn't affect the previous migration either way.
        op.alter_column(
            "work_items",
            "points",
            new_column_name="story_points",
            schema="board",
        )

    # 2. Revert item_type values
    op.execute("""
        UPDATE board.work_items
        SET item_type = 'epic'
        WHERE item_type = 'goal'
    """)
    op.execute("""
        UPDATE board.work_items
        SET item_type = 'story'
        WHERE item_type = 'feature'
    """)

    # 3. Recreate original agent_workload view
    op.execute("""
        DROP VIEW IF EXISTS board.agent_workload;
        CREATE OR REPLACE VIEW board.agent_workload AS
        SELECT
            assignee_id,
            assignee_type,
            org_id,
            COUNT(*) FILTER (WHERE status IN ('todo', 'in_progress', 'in_review')) AS active_items,
            COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
            COUNT(*) FILTER (WHERE status = 'done') AS completed_count,
            SUM(COALESCE(story_points, 0)) AS total_story_points
        FROM board.work_items
        WHERE assignee_id IS NOT NULL AND assignee_type = 'agent'
        GROUP BY assignee_id, assignee_type, org_id
    """)

    op.execute("""
        COMMENT ON VIEW board.agent_workload IS 'Aggregated workload per agent for capacity planning'
    """)
