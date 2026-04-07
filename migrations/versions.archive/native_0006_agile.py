"""Agent enhancements and agile board system

Revision ID: native_0006_agile
Revises: native_0005_multitenancy
Create Date: 2025-01-13

Behavior: behavior_migrate_postgres_schema

This migration creates the agent enhancements and agile board system using native
SQLAlchemy operations. It consolidates SQL files 028-032 from schema/migrations/:
- 028_add_agent_idle_status.sql
- 029_create_agent_registry.sql
- 030_create_agile_board.sql
- 031_unified_work_items.sql
- 031_agent_performance_metrics.sql
- 032_add_updated_at_to_board_columns.sql

IMPORTANT: This is meant to replace the hybrid SQL approach. For existing databases
with the schema already applied via SQL files, stamp this revision:
    alembic stamp native_0006_agile
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "native_0006_agile"
down_revision: Union[str, None] = "native_0005_multi_tenancy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create agent enhancements and agile board tables."""
    conn = op.get_bind()

    # =========================================================================
    # 028: Add 'idle' to agent_status ENUM
    # =========================================================================

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'agent_status'::regtype
                AND enumlabel = 'idle'
            ) THEN
                ALTER TYPE agent_status ADD VALUE 'idle' AFTER 'busy';
            END IF;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
            WHEN undefined_object THEN NULL;
        END $$
    """)

    # =========================================================================
    # 028: Agent Status Transitions (Audit Trail)
    # =========================================================================

    op.create_table(
        "agent_status_transitions",
        sa.Column("id", sa.String(36), nullable=False, server_default=sa.text("gen_random_uuid()::TEXT")),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("from_status", sa.String(50), nullable=False),  # Uses agent_status enum
        sa.Column("to_status", sa.String(50), nullable=False),  # Uses agent_status enum
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(36), nullable=True),
        sa.Column("trigger_type", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.agent_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )

    op.create_index("idx_agent_status_transitions_agent", "agent_status_transitions", ["agent_id"])
    op.create_index("idx_agent_status_transitions_org", "agent_status_transitions", ["org_id"])
    op.create_index("idx_agent_status_transitions_created", "agent_status_transitions", ["created_at"], postgresql_using="btree", postgresql_ops={"created_at": "DESC"})
    op.create_index("idx_agent_status_transitions_trigger_type", "agent_status_transitions", ["trigger_type"])

    # Enable RLS
    op.execute("ALTER TABLE agent_status_transitions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY agent_status_transitions_tenant_isolation ON agent_status_transitions
            FOR ALL
            USING (org_id = current_org_id())
    """)

    # Notify function for real-time status updates
    op.execute("""
        CREATE OR REPLACE FUNCTION notify_agent_status_change()
        RETURNS TRIGGER AS $$
        DECLARE
            payload JSONB;
        BEGIN
            IF OLD.status IS DISTINCT FROM NEW.status THEN
                payload := jsonb_build_object(
                    'event', 'agent_status_changed',
                    'agent_id', NEW.agent_id,
                    'org_id', NEW.org_id,
                    'from_status', OLD.status::TEXT,
                    'to_status', NEW.status::TEXT,
                    'timestamp', NOW()::TEXT
                );
                PERFORM pg_notify('agent_events', payload::TEXT);
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("DROP TRIGGER IF EXISTS trigger_agent_status_notify ON agents")
    op.execute("""
        CREATE TRIGGER trigger_agent_status_notify
            AFTER UPDATE OF status ON agents
            FOR EACH ROW
            EXECUTE FUNCTION notify_agent_status_change()
    """)

    # Validate status transition function
    op.execute("""
        CREATE OR REPLACE FUNCTION is_valid_agent_status_transition(
            current_status agent_status,
            new_status agent_status
        ) RETURNS BOOLEAN AS $$
        BEGIN
            IF current_status = new_status THEN
                RETURN TRUE;
            END IF;

            CASE current_status
                WHEN 'active' THEN
                    RETURN new_status IN ('busy', 'idle', 'paused', 'disabled', 'archived');
                WHEN 'busy' THEN
                    RETURN new_status IN ('active', 'idle', 'paused');
                WHEN 'idle' THEN
                    RETURN new_status IN ('active', 'busy', 'paused', 'disabled', 'archived');
                WHEN 'paused' THEN
                    RETURN new_status IN ('active', 'disabled', 'archived');
                WHEN 'disabled' THEN
                    RETURN new_status IN ('active', 'archived');
                WHEN 'archived' THEN
                    RETURN FALSE;
                ELSE
                    RETURN FALSE;
            END CASE;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE
    """)

    # Add last_status_change column to agents
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'agents' AND column_name = 'last_status_change'
            ) THEN
                ALTER TABLE agents ADD COLUMN last_status_change TIMESTAMPTZ DEFAULT NOW();
            END IF;
        END $$
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION update_agent_last_status_change()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.status IS DISTINCT FROM NEW.status THEN
                NEW.last_status_change = NOW();
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("DROP TRIGGER IF EXISTS trigger_agent_last_status_change ON agents")
    op.execute("""
        CREATE TRIGGER trigger_agent_last_status_change
            BEFORE UPDATE OF status ON agents
            FOR EACH ROW
            EXECUTE FUNCTION update_agent_last_status_change()
    """)

    # =========================================================================
    # 029: Agent Registry (agent_versions table)
    # =========================================================================

    op.create_table(
        "agent_versions",
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("mission", sa.Text(), nullable=False),
        sa.Column("role_alignment", sa.String(50), nullable=False),  # STRATEGIST, TEACHER, STUDENT, MULTI_ROLE
        sa.Column("capabilities", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("default_behaviors", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("playbook_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(50), nullable=False),  # DRAFT, ACTIVE, DEPRECATED
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("effective_to", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_from", sa.Text(), nullable=True),  # Previous version
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("agent_id", "version"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.agent_id"], ondelete="CASCADE"),
        sa.CheckConstraint("role_alignment IN ('STRATEGIST', 'TEACHER', 'STUDENT', 'MULTI_ROLE')", name="ck_agent_versions_role_alignment"),
        sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'DEPRECATED')", name="ck_agent_versions_status"),
    )

    op.create_index("idx_agent_versions_status", "agent_versions", ["status"])
    op.create_index("idx_agent_versions_role_alignment", "agent_versions", ["role_alignment"])
    op.create_index("idx_agent_versions_effective_from", "agent_versions", ["effective_from"])
    op.create_index("idx_agent_versions_capabilities", "agent_versions", ["capabilities"], postgresql_using="gin")
    op.create_index("idx_agent_versions_default_behaviors", "agent_versions", ["default_behaviors"], postgresql_using="gin")

    # Enable RLS
    op.execute("ALTER TABLE agent_versions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY agent_versions_access_policy ON agent_versions
            FOR SELECT
            USING (
                EXISTS (
                    SELECT 1 FROM agents a
                    WHERE a.agent_id = agent_versions.agent_id
                )
            )
    """)

    # =========================================================================
    # 030: Create Agile Board System
    # =========================================================================

    # ENUM types for agile board
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'assignee_type') THEN
                CREATE TYPE assignee_type AS ENUM ('user', 'agent');
            END IF;
        END$$
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'work_item_status') THEN
                CREATE TYPE work_item_status AS ENUM (
                    'backlog',
                    'todo',
                    'in_progress',
                    'in_review',
                    'done',
                    'cancelled'
                );
            END IF;
        END$$
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'epic_status') THEN
                CREATE TYPE epic_status AS ENUM (
                    'draft',
                    'active',
                    'completed',
                    'cancelled'
                );
            END IF;
        END$$
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'work_item_priority') THEN
                CREATE TYPE work_item_priority AS ENUM (
                    'critical',
                    'high',
                    'medium',
                    'low'
                );
            END IF;
        END$$
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_type') THEN
                CREATE TYPE task_type AS ENUM (
                    'feature',
                    'bug',
                    'chore',
                    'spike',
                    'documentation'
                );
            END IF;
        END$$
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'work_item_type') THEN
                CREATE TYPE work_item_type AS ENUM ('epic', 'story', 'task');
            END IF;
        END$$
    """)

    # Boards table
    op.create_table(
        "boards",
        sa.Column("board_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="FALSE"),
        sa.Column("org_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("board_id"),
    )

    op.create_index("idx_boards_project_id", "boards", ["project_id"])
    op.create_index("idx_boards_org_id", "boards", ["org_id"], postgresql_where=sa.text("org_id IS NOT NULL"))
    op.create_index("idx_boards_is_default", "boards", ["project_id", "is_default"], postgresql_where=sa.text("is_default = TRUE"))

    # Board columns table
    op.create_table(
        "board_columns",
        sa.Column("column_id", sa.Text(), nullable=False),
        sa.Column("board_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status_mapping", sa.String(50), nullable=False),  # work_item_status
        sa.Column("wip_limit", sa.Integer(), nullable=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("column_id"),
        sa.ForeignKeyConstraint(["board_id"], ["boards.board_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("board_id", "position", name="uq_board_columns_board_position"),
    )

    op.create_index("idx_board_columns_board_id", "board_columns", ["board_id"])

    # Epics table
    op.create_table(
        "epics",
        sa.Column("epic_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("board_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),  # epic_status
        sa.Column("priority", sa.String(50), nullable=False, server_default="medium"),  # work_item_priority
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("labels", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("epic_id"),
        sa.ForeignKeyConstraint(["board_id"], ["boards.board_id"], ondelete="SET NULL"),
    )

    op.create_index("idx_epics_project_id", "epics", ["project_id"])
    op.create_index("idx_epics_board_id", "epics", ["board_id"])
    op.create_index("idx_epics_status", "epics", ["status"])
    op.create_index("idx_epics_org_id", "epics", ["org_id"], postgresql_where=sa.text("org_id IS NOT NULL"))

    # Stories table
    op.create_table(
        "stories",
        sa.Column("story_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("board_id", sa.Text(), nullable=True),
        sa.Column("epic_id", sa.Text(), nullable=True),
        sa.Column("column_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="backlog"),  # work_item_status
        sa.Column("priority", sa.String(50), nullable=False, server_default="medium"),  # work_item_priority
        sa.Column("story_points", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assignee_id", sa.Text(), nullable=True),
        sa.Column("assignee_type", sa.String(50), nullable=True),  # assignee_type enum
        sa.Column("assigned_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("assigned_by", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("labels", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("acceptance_criteria", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("story_id"),
        sa.ForeignKeyConstraint(["board_id"], ["boards.board_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["epic_id"], ["epics.epic_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["column_id"], ["board_columns.column_id"], ondelete="SET NULL"),
    )

    op.create_index("idx_stories_project_id", "stories", ["project_id"])
    op.create_index("idx_stories_board_id", "stories", ["board_id"])
    op.create_index("idx_stories_epic_id", "stories", ["epic_id"])
    op.create_index("idx_stories_column_id", "stories", ["column_id"])
    op.create_index("idx_stories_status", "stories", ["status"])
    op.create_index("idx_stories_assignee", "stories", ["assignee_id", "assignee_type"], postgresql_where=sa.text("assignee_id IS NOT NULL"))
    op.create_index("idx_stories_org_id", "stories", ["org_id"], postgresql_where=sa.text("org_id IS NOT NULL"))

    # Tasks table
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("story_id", sa.Text(), nullable=True),
        sa.Column("board_id", sa.Text(), nullable=True),
        sa.Column("column_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="backlog"),  # work_item_status
        sa.Column("priority", sa.String(50), nullable=False, server_default="medium"),  # work_item_priority
        sa.Column("task_type", sa.String(50), nullable=False, server_default="feature"),  # task_type
        sa.Column("estimated_hours", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("actual_hours", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assignee_id", sa.Text(), nullable=True),
        sa.Column("assignee_type", sa.String(50), nullable=True),  # assignee_type enum
        sa.Column("assigned_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("assigned_by", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("behavior_id", sa.Text(), nullable=True),  # Link to behavior
        sa.Column("run_id", sa.Text(), nullable=True),  # Link to run
        sa.Column("checklist", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("labels", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("task_id"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.story_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["board_id"], ["boards.board_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["column_id"], ["board_columns.column_id"], ondelete="SET NULL"),
    )

    op.create_index("idx_tasks_project_id", "tasks", ["project_id"])
    op.create_index("idx_tasks_story_id", "tasks", ["story_id"])
    op.create_index("idx_tasks_board_id", "tasks", ["board_id"])
    op.create_index("idx_tasks_column_id", "tasks", ["column_id"])
    op.create_index("idx_tasks_status", "tasks", ["status"])
    op.create_index("idx_tasks_assignee", "tasks", ["assignee_id", "assignee_type"], postgresql_where=sa.text("assignee_id IS NOT NULL"))
    op.create_index("idx_tasks_behavior_id", "tasks", ["behavior_id"], postgresql_where=sa.text("behavior_id IS NOT NULL"))
    op.create_index("idx_tasks_run_id", "tasks", ["run_id"], postgresql_where=sa.text("run_id IS NOT NULL"))
    op.create_index("idx_tasks_org_id", "tasks", ["org_id"], postgresql_where=sa.text("org_id IS NOT NULL"))

    # =========================================================================
    # 031: Unified Work Items Table
    # =========================================================================

    op.create_table(
        "work_items",
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("item_type", sa.String(50), nullable=False),  # work_item_type enum
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("board_id", sa.Text(), nullable=True),
        sa.Column("column_id", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.Text(), nullable=True),  # Self-referencing for hierarchy
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="backlog"),  # work_item_status
        sa.Column("priority", sa.String(50), nullable=False, server_default="medium"),  # work_item_priority
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("story_points", sa.Integer(), nullable=True),
        sa.Column("estimated_hours", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("actual_hours", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("assignee_id", sa.Text(), nullable=True),
        sa.Column("assignee_type", sa.String(50), nullable=True),  # assignee_type enum
        sa.Column("assigned_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("assigned_by", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("labels", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("acceptance_criteria", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("checklist", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("attachments", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("behavior_id", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("item_id"),
        sa.ForeignKeyConstraint(["board_id"], ["boards.board_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["column_id"], ["board_columns.column_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_id"], ["work_items.item_id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "(assignee_id IS NULL AND assignee_type IS NULL) OR (assignee_id IS NOT NULL AND assignee_type IS NOT NULL)",
            name="ck_work_items_assignee"
        ),
        sa.CheckConstraint(
            "(item_type = 'epic' AND parent_id IS NULL) OR (item_type IN ('story', 'task'))",
            name="ck_work_items_hierarchy"
        ),
    )

    op.create_index("idx_work_items_item_type", "work_items", ["item_type"])
    op.create_index("idx_work_items_project_id", "work_items", ["project_id"])
    op.create_index("idx_work_items_board_id", "work_items", ["board_id"])
    op.create_index("idx_work_items_column_id", "work_items", ["column_id"])
    op.create_index("idx_work_items_parent_id", "work_items", ["parent_id"])
    op.create_index("idx_work_items_status", "work_items", ["status"])
    op.create_index("idx_work_items_priority", "work_items", ["priority"])
    op.create_index("idx_work_items_assignee", "work_items", ["assignee_id", "assignee_type"], postgresql_where=sa.text("assignee_id IS NOT NULL"))
    op.create_index("idx_work_items_behavior_id", "work_items", ["behavior_id"], postgresql_where=sa.text("behavior_id IS NOT NULL"))
    op.create_index("idx_work_items_run_id", "work_items", ["run_id"], postgresql_where=sa.text("run_id IS NOT NULL"))
    op.create_index("idx_work_items_org_id", "work_items", ["org_id"], postgresql_where=sa.text("org_id IS NOT NULL"))
    op.create_index("idx_work_items_position", "work_items", ["column_id", "position"])
    op.create_index("idx_work_items_created_at", "work_items", ["created_at"], postgresql_using="btree", postgresql_ops={"created_at": "DESC"})
    op.create_index("idx_work_items_hierarchy", "work_items", ["project_id", "item_type", "parent_id"])

    # Views for backward compatibility
    op.execute("""
        CREATE OR REPLACE VIEW epics_view AS
        SELECT
            item_id AS epic_id,
            project_id,
            board_id,
            title AS name,
            description,
            status,
            priority,
            color,
            start_date,
            target_date,
            completed_at,
            labels,
            metadata,
            created_at,
            updated_at,
            created_by,
            org_id,
            story_points
        FROM work_items
        WHERE item_type = 'epic'
    """)

    op.execute("""
        CREATE OR REPLACE VIEW stories_view AS
        SELECT
            item_id AS story_id,
            project_id,
            board_id,
            parent_id AS epic_id,
            column_id,
            title,
            description,
            status,
            priority,
            story_points,
            position,
            assignee_id,
            assignee_type,
            assigned_at,
            assigned_by,
            started_at,
            completed_at,
            due_date,
            labels,
            acceptance_criteria,
            metadata,
            created_at,
            updated_at,
            created_by,
            org_id
        FROM work_items
        WHERE item_type = 'story'
    """)

    op.execute("""
        CREATE OR REPLACE VIEW tasks_view AS
        SELECT
            item_id AS task_id,
            project_id,
            parent_id AS story_id,
            board_id,
            column_id,
            title,
            description,
            status,
            priority,
            estimated_hours,
            actual_hours,
            position,
            assignee_id,
            assignee_type,
            assigned_at,
            assigned_by,
            started_at,
            completed_at,
            due_date,
            behavior_id,
            run_id,
            checklist,
            labels,
            metadata,
            created_at,
            updated_at,
            created_by,
            org_id
        FROM work_items
        WHERE item_type = 'task'
    """)

    # =========================================================================
    # 031: Agent Performance Metrics (TimescaleDB)
    # =========================================================================

    # ENUM types for performance metrics
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'performance_alert_severity') THEN
                CREATE TYPE performance_alert_severity AS ENUM (
                    'info',
                    'warning',
                    'critical'
                );
            END IF;
        END$$
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'performance_metric_type') THEN
                CREATE TYPE performance_metric_type AS ENUM (
                    'success_rate',
                    'token_efficiency',
                    'behavior_reuse',
                    'compliance_coverage',
                    'avg_task_duration',
                    'utilization'
                );
            END IF;
        END$$
    """)

    # Agent performance snapshots (TimescaleDB hypertable)
    op.create_table(
        "agent_performance_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("snapshot_time", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("project_id", sa.Text(), nullable=True),
        sa.Column("task_completed", sa.Boolean(), nullable=False, server_default="FALSE"),
        sa.Column("task_success", sa.Boolean(), nullable=False, server_default="FALSE"),
        sa.Column("task_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("tokens_used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("baseline_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("token_savings_pct", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("behaviors_cited", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_behaviors", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("compliance_checks_passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compliance_checks_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status_from", sa.Text(), nullable=True),
        sa.Column("status_to", sa.Text(), nullable=True),
        sa.Column("time_in_status_ms", sa.BigInteger(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("snapshot_id", "snapshot_time"),
    )

    # Convert to TimescaleDB hypertable
    op.execute("""
        SELECT create_hypertable('agent_performance_snapshots', 'snapshot_time',
            if_not_exists => TRUE,
            migrate_data => TRUE
        )
    """)

    op.create_index("idx_perf_snap_agent_id", "agent_performance_snapshots", ["agent_id", "snapshot_time"], postgresql_using="btree", postgresql_ops={"snapshot_time": "DESC"})
    op.create_index("idx_perf_snap_org_id", "agent_performance_snapshots", ["org_id", "snapshot_time"], postgresql_where=sa.text("org_id IS NOT NULL"), postgresql_using="btree", postgresql_ops={"snapshot_time": "DESC"})
    op.create_index("idx_perf_snap_run_id", "agent_performance_snapshots", ["run_id"], postgresql_where=sa.text("run_id IS NOT NULL"))
    op.create_index("idx_perf_snap_project_id", "agent_performance_snapshots", ["project_id", "snapshot_time"], postgresql_where=sa.text("project_id IS NOT NULL"), postgresql_using="btree", postgresql_ops={"snapshot_time": "DESC"})

    # Agent performance daily rollups
    op.create_table(
        "agent_performance_daily",
        sa.Column("rollup_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("rollup_date", sa.Date(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=True),
        sa.Column("project_id", sa.Text(), nullable=True),
        sa.Column("tasks_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rate_pct", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("avg_task_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("min_task_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("max_task_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("total_execution_time_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_tokens_used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_baseline_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_token_savings_pct", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("total_behaviors_cited", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_behaviors_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("behavior_reuse_rate_pct", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("compliance_checks_passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compliance_checks_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compliance_coverage_pct", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("time_busy_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("time_idle_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("time_paused_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("utilization_pct", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("switch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assignments_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("rollup_id"),
        sa.UniqueConstraint("rollup_date", "agent_id", "org_id", "project_id", name="uq_agent_performance_daily_key"),
    )

    op.create_index("idx_perf_daily_agent_date", "agent_performance_daily", ["agent_id", "rollup_date"], postgresql_using="btree", postgresql_ops={"rollup_date": "DESC"})
    op.create_index("idx_perf_daily_org_date", "agent_performance_daily", ["org_id", "rollup_date"], postgresql_where=sa.text("org_id IS NOT NULL"), postgresql_using="btree", postgresql_ops={"rollup_date": "DESC"})
    op.create_index("idx_perf_daily_project_date", "agent_performance_daily", ["project_id", "rollup_date"], postgresql_where=sa.text("project_id IS NOT NULL"), postgresql_using="btree", postgresql_ops={"rollup_date": "DESC"})

    # Add updated_at trigger for boards
    op.execute("""
        CREATE OR REPLACE FUNCTION update_boards_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("DROP TRIGGER IF EXISTS boards_updated_at_trigger ON boards")
    op.execute("""
        CREATE TRIGGER boards_updated_at_trigger
            BEFORE UPDATE ON boards
            FOR EACH ROW
            EXECUTE FUNCTION update_boards_updated_at()
    """)

    # Add updated_at trigger for work_items
    op.execute("""
        CREATE OR REPLACE FUNCTION update_work_items_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("DROP TRIGGER IF EXISTS work_items_updated_at_trigger ON work_items")
    op.execute("""
        CREATE TRIGGER work_items_updated_at_trigger
            BEFORE UPDATE ON work_items
            FOR EACH ROW
            EXECUTE FUNCTION update_work_items_updated_at()
    """)


def downgrade() -> None:
    """Downgrade is marked irreversible per user decision.

    This migration creates extensive schema changes including:
    - Agent status enhancements and triggers
    - Agent registry versioning
    - Complete agile board system
    - Unified work items with hierarchy
    - TimescaleDB performance metrics

    To revert, restore from backup or manually drop objects.
    """
    raise NotImplementedError(
        "Downgrade is marked irreversible for native_0006_agile. "
        "This migration creates agent enhancements, agile board, and performance metrics. "
        "To revert, restore from backup or manually drop the following objects:\n"
        "- Tables: agent_status_transitions, agent_versions, boards, board_columns, "
        "epics, stories, tasks, work_items, agent_performance_snapshots, agent_performance_daily\n"
        "- Views: epics_view, stories_view, tasks_view\n"
        "- Functions: notify_agent_status_change, is_valid_agent_status_transition, "
        "update_agent_last_status_change, update_boards_updated_at, update_work_items_updated_at\n"
        "- Types: assignee_type, work_item_status, epic_status, work_item_priority, "
        "task_type, work_item_type, performance_alert_severity, performance_metric_type"
    )
