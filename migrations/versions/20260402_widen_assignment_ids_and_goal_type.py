"""Widen assignment ID columns and allow goal in assignment_history.

Fixes 500 on POST /v1/work-items/:id:assign when:
- assignable_type is goal (CHECK only allowed epic/story/task/bug/feature)
- assignee_id or performed_by exceeds VARCHAR(36) (OAuth subs, external IDs)

Revision ID: 20260402_widen_assignment
"""

from alembic import op

revision = "20260402_widen_assignment"
down_revision = "20260402_msg_archived_at"
branch_labels = None
depends_on = None


_AGENT_WORKLOAD_VIEW = """
CREATE OR REPLACE VIEW board.agent_workload AS
SELECT
    assignee_id,
    assignee_type,
    org_id,
    COUNT(*) FILTER (WHERE status IN ('todo', 'in_progress', 'in_review')) AS active_items,
    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
    COUNT(*) FILTER (WHERE status = 'done') AS completed_count,
    SUM(COALESCE(points, 0)) AS total_points,
    SUM(COALESCE(points, 0)) AS total_story_points
FROM board.work_items
WHERE assignee_id IS NOT NULL AND assignee_type = 'agent'
GROUP BY assignee_id, assignee_type, org_id
"""

_AGENT_WORKLOAD_COMMENT = """
COMMENT ON VIEW board.agent_workload IS
'Aggregated workload per agent for capacity planning. total_story_points is a deprecated alias for total_points.'
"""


def upgrade() -> None:
    # View references assignee_id; Postgres forbids ALTER TYPE until dependent view is dropped.
    op.execute("DROP VIEW IF EXISTS board.agent_workload")

    # work_items: store long external user/agent IDs
    op.execute(
        """
        ALTER TABLE board.work_items
          ALTER COLUMN assignee_id TYPE VARCHAR(255),
          ALTER COLUMN assigned_by TYPE VARCHAR(255)
        """
    )

    # assignment_history: same + actor id on performed_by
    op.execute(
        """
        ALTER TABLE board.assignment_history
          ALTER COLUMN assignee_id TYPE VARCHAR(255),
          ALTER COLUMN previous_assignee_id TYPE VARCHAR(255),
          ALTER COLUMN performed_by TYPE VARCHAR(255)
        """
    )

    # Allow unified work-item types (goal was missing → CHECK failure on assign)
    op.execute(
        """
        ALTER TABLE board.assignment_history
          DROP CONSTRAINT IF EXISTS valid_assignable_type
        """
    )
    op.execute(
        """
        ALTER TABLE board.assignment_history
          ADD CONSTRAINT valid_assignable_type
          CHECK (assignable_type IN (
            'goal', 'feature', 'task', 'bug',
            'epic', 'story'
          ))
        """
    )

    op.execute(_AGENT_WORKLOAD_VIEW)
    op.execute(_AGENT_WORKLOAD_COMMENT)


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE board.assignment_history
          DROP CONSTRAINT IF EXISTS valid_assignable_type
        """
    )
    op.execute(
        """
        ALTER TABLE board.assignment_history
          ADD CONSTRAINT valid_assignable_type
          CHECK (assignable_type IN ('story', 'task', 'epic', 'bug', 'feature'))
        """
    )

    op.execute("DROP VIEW IF EXISTS board.agent_workload")

    op.execute(
        """
        ALTER TABLE board.work_items
          ALTER COLUMN assignee_id TYPE VARCHAR(36),
          ALTER COLUMN assigned_by TYPE VARCHAR(36)
        """
    )
    op.execute(
        """
        ALTER TABLE board.assignment_history
          ALTER COLUMN assignee_id TYPE VARCHAR(36),
          ALTER COLUMN previous_assignee_id TYPE VARCHAR(36),
          ALTER COLUMN performed_by TYPE VARCHAR(36)
        """
    )

    op.execute(_AGENT_WORKLOAD_VIEW)
    op.execute(_AGENT_WORKLOAD_COMMENT)
