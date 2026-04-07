"""Create Board entity tables for Agile Board System

Revision ID: 0004_board_entities
Revises: 0003_task_cycle
Create Date: 2025-12-10

Behavior: behavior_migrate_postgres_schema

Creates tables for the Agile Board System (Feature 13.5.1):
1. boards - Kanban/Scrum boards for project management
2. board_columns - Columns with WIP limits and status mapping
3. epics - High-level milestones grouping stories
4. stories - User stories with polymorphic assignee (user/agent)
5. board_tasks - Subtasks with behavior/run linking
6. assignment_history - Audit trail for assignment changes
7. sprints - Time-boxed iterations
8. sprint_stories - Many-to-many sprint-story relationship

Includes RLS policies, triggers, and agent_workload view.
Refactored from schema/migrations/030_create_agile_board.sql into proper Alembic.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0004_board_entities"
down_revision: Union[str, None] = "0003_task_cycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create Agile Board System tables."""

    # ==========================================================================
    # ENUM Types
    # ==========================================================================

    op.execute("""
        -- Assignee type for polymorphic assignment (user OR agent)
        DO $$ BEGIN
            CREATE TYPE assignee_type AS ENUM ('user', 'agent');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;

        -- Work item status (generic for epic/story/task)
        DO $$ BEGIN
            CREATE TYPE work_item_status AS ENUM (
                'backlog',
                'todo',
                'in_progress',
                'in_review',
                'done',
                'cancelled'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;

        -- Epic status (higher-level milestones)
        DO $$ BEGIN
            CREATE TYPE epic_status AS ENUM (
                'draft',
                'active',
                'completed',
                'cancelled'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;

        -- Work item priority
        DO $$ BEGIN
            CREATE TYPE work_item_priority AS ENUM (
                'critical',
                'high',
                'medium',
                'low'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;

        -- Work item type for tasks
        DO $$ BEGIN
            CREATE TYPE task_type AS ENUM (
                'feature',
                'bug',
                'chore',
                'spike',
                'documentation'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ==========================================================================
    # Boards Table
    # ==========================================================================

    op.execute("""
        CREATE TABLE IF NOT EXISTS boards (
            board_id TEXT PRIMARY KEY,                -- brd-<12-hex> format
            project_id TEXT NOT NULL,                 -- Links to projects table
            name TEXT NOT NULL,
            description TEXT,
            settings JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,                 -- User ID who created
            is_default BOOLEAN NOT NULL DEFAULT FALSE,

            -- Multi-tenant context (inherited from project)
            org_id TEXT                               -- NULL for user-owned projects
        )
    """)

    op.execute("""
        COMMENT ON TABLE boards IS 'Kanban/Scrum boards for project management';
        COMMENT ON COLUMN boards.settings IS 'Board settings including visibility inheritance';
    """)

    # Indexes for boards
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_boards_project_id ON boards (project_id);
        CREATE INDEX IF NOT EXISTS idx_boards_org_id ON boards (org_id) WHERE org_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_boards_is_default ON boards (project_id, is_default) WHERE is_default = TRUE;
    """)

    # ==========================================================================
    # Board Columns Table
    # ==========================================================================

    op.execute("""
        CREATE TABLE IF NOT EXISTS board_columns (
            column_id TEXT PRIMARY KEY,               -- col-<12-hex> format
            board_id TEXT NOT NULL REFERENCES boards(board_id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,      -- Order within board
            status_mapping work_item_status NOT NULL, -- Maps to work item status
            wip_limit INTEGER,                        -- Work in progress limit (NULL = no limit)
            settings JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            UNIQUE (board_id, position)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_board_columns_board_id ON board_columns (board_id);
    """)

    # ==========================================================================
    # Epics Table
    # ==========================================================================

    op.execute("""
        CREATE TABLE IF NOT EXISTS epics (
            epic_id TEXT PRIMARY KEY,                 -- epic-<12-hex> format
            project_id TEXT NOT NULL,
            board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            description TEXT,
            status epic_status NOT NULL DEFAULT 'draft',
            priority work_item_priority NOT NULL DEFAULT 'medium',
            color TEXT,                               -- Hex color for UI
            start_date DATE,
            target_date DATE,
            completed_at TIMESTAMPTZ,
            labels JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,

            -- Multi-tenant context
            org_id TEXT
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_epics_project_id ON epics (project_id);
        CREATE INDEX IF NOT EXISTS idx_epics_board_id ON epics (board_id);
        CREATE INDEX IF NOT EXISTS idx_epics_status ON epics (status);
        CREATE INDEX IF NOT EXISTS idx_epics_org_id ON epics (org_id) WHERE org_id IS NOT NULL;
    """)

    # ==========================================================================
    # Stories Table
    # ==========================================================================

    op.execute("""
        CREATE TABLE IF NOT EXISTS stories (
            story_id TEXT PRIMARY KEY,                -- story-<12-hex> format
            project_id TEXT NOT NULL,
            board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
            epic_id TEXT REFERENCES epics(epic_id) ON DELETE SET NULL,
            column_id TEXT REFERENCES board_columns(column_id) ON DELETE SET NULL,

            title TEXT NOT NULL,
            description TEXT,
            status work_item_status NOT NULL DEFAULT 'backlog',
            priority work_item_priority NOT NULL DEFAULT 'medium',
            story_points INTEGER,                     -- Estimation
            position INTEGER NOT NULL DEFAULT 0,      -- Order within column

            -- Polymorphic single assignee (user OR agent)
            assignee_id TEXT,                         -- user_id or agent_id
            assignee_type assignee_type,              -- 'user' or 'agent'
            assigned_at TIMESTAMPTZ,
            assigned_by TEXT,

            -- Timestamps
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            due_date DATE,

            -- Metadata
            labels JSONB NOT NULL DEFAULT '[]'::jsonb,
            acceptance_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,

            -- Multi-tenant context
            org_id TEXT,

            -- Ensure assignee_id and assignee_type are both set or both null
            CONSTRAINT valid_assignee CHECK (
                (assignee_id IS NULL AND assignee_type IS NULL) OR
                (assignee_id IS NOT NULL AND assignee_type IS NOT NULL)
            )
        )
    """)

    op.execute("""
        COMMENT ON TABLE stories IS 'User stories with polymorphic assignee (user or agent)';
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_stories_project_id ON stories (project_id);
        CREATE INDEX IF NOT EXISTS idx_stories_board_id ON stories (board_id);
        CREATE INDEX IF NOT EXISTS idx_stories_epic_id ON stories (epic_id);
        CREATE INDEX IF NOT EXISTS idx_stories_column_id ON stories (column_id);
        CREATE INDEX IF NOT EXISTS idx_stories_status ON stories (status);
        CREATE INDEX IF NOT EXISTS idx_stories_assignee ON stories (assignee_id, assignee_type) WHERE assignee_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_stories_org_id ON stories (org_id) WHERE org_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_stories_position ON stories (column_id, position);
    """)

    # ==========================================================================
    # Board Tasks Table
    # ==========================================================================

    op.execute("""
        CREATE TABLE IF NOT EXISTS board_tasks (
            task_id TEXT PRIMARY KEY,                 -- task-<12-hex> format
            project_id TEXT NOT NULL,
            story_id TEXT REFERENCES stories(story_id) ON DELETE CASCADE,
            board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
            column_id TEXT REFERENCES board_columns(column_id) ON DELETE SET NULL,

            title TEXT NOT NULL,
            description TEXT,
            task_type task_type NOT NULL DEFAULT 'feature',
            status work_item_status NOT NULL DEFAULT 'todo',
            priority work_item_priority NOT NULL DEFAULT 'medium',
            estimated_hours DECIMAL(5,2),
            actual_hours DECIMAL(5,2),
            position INTEGER NOT NULL DEFAULT 0,

            -- Polymorphic single assignee (user OR agent)
            assignee_id TEXT,
            assignee_type assignee_type,
            assigned_at TIMESTAMPTZ,
            assigned_by TEXT,

            -- Timestamps
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            due_date DATE,

            -- Behavior/Run linking (for agent tasks)
            behavior_id TEXT,                         -- behavior_* reference
            run_id TEXT,                              -- Execution run reference

            -- Metadata
            labels JSONB NOT NULL DEFAULT '[]'::jsonb,
            checklist JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,

            -- Multi-tenant context
            org_id TEXT,

            CONSTRAINT valid_task_assignee CHECK (
                (assignee_id IS NULL AND assignee_type IS NULL) OR
                (assignee_id IS NOT NULL AND assignee_type IS NOT NULL)
            )
        )
    """)

    op.execute("""
        COMMENT ON TABLE board_tasks IS 'Tasks/subtasks of stories with polymorphic assignee';
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_board_tasks_project_id ON board_tasks (project_id);
        CREATE INDEX IF NOT EXISTS idx_board_tasks_story_id ON board_tasks (story_id);
        CREATE INDEX IF NOT EXISTS idx_board_tasks_board_id ON board_tasks (board_id);
        CREATE INDEX IF NOT EXISTS idx_board_tasks_column_id ON board_tasks (column_id);
        CREATE INDEX IF NOT EXISTS idx_board_tasks_status ON board_tasks (status);
        CREATE INDEX IF NOT EXISTS idx_board_tasks_assignee ON board_tasks (assignee_id, assignee_type) WHERE assignee_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_board_tasks_behavior_id ON board_tasks (behavior_id) WHERE behavior_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_board_tasks_run_id ON board_tasks (run_id) WHERE run_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_board_tasks_org_id ON board_tasks (org_id) WHERE org_id IS NOT NULL;
    """)

    # ==========================================================================
    # Assignment History Table
    # ==========================================================================

    op.execute("""
        CREATE TABLE IF NOT EXISTS assignment_history (
            history_id TEXT PRIMARY KEY,              -- ahist-<12-hex> format

            -- Polymorphic reference to assignable (story or task)
            assignable_id TEXT NOT NULL,              -- story_id or task_id
            assignable_type TEXT NOT NULL,            -- 'story' or 'task'

            -- Assignment details
            assignee_id TEXT,                         -- NULL for unassignment
            assignee_type assignee_type,

            -- Action metadata
            action TEXT NOT NULL,                     -- 'assigned', 'unassigned', 'reassigned'
            performed_by TEXT NOT NULL,               -- User who made the change
            performed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- Previous assignee (for reassignment tracking)
            previous_assignee_id TEXT,
            previous_assignee_type assignee_type,

            reason TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

            -- Multi-tenant context
            org_id TEXT,

            CONSTRAINT valid_assignable_type CHECK (assignable_type IN ('story', 'task'))
        )
    """)

    op.execute("""
        COMMENT ON TABLE assignment_history IS 'Audit trail for all assignment changes';
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_assignment_history_assignable ON assignment_history (assignable_id, assignable_type);
        CREATE INDEX IF NOT EXISTS idx_assignment_history_assignee ON assignment_history (assignee_id, assignee_type) WHERE assignee_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_assignment_history_performed_at ON assignment_history (performed_at DESC);
        CREATE INDEX IF NOT EXISTS idx_assignment_history_org_id ON assignment_history (org_id) WHERE org_id IS NOT NULL;
    """)

    # ==========================================================================
    # Sprints Table
    # ==========================================================================

    op.execute("""
        CREATE TABLE IF NOT EXISTS sprints (
            sprint_id TEXT PRIMARY KEY,               -- sprint-<12-hex> format
            project_id TEXT NOT NULL,
            board_id TEXT REFERENCES boards(board_id) ON DELETE CASCADE,

            name TEXT NOT NULL,
            goal TEXT,
            status TEXT NOT NULL DEFAULT 'planning' CHECK (status IN ('planning', 'active', 'completed', 'cancelled')),

            start_date DATE NOT NULL,
            end_date DATE NOT NULL,

            velocity_planned INTEGER,                 -- Planned story points
            velocity_completed INTEGER,               -- Actual completed points

            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,

            -- Multi-tenant context
            org_id TEXT,

            CONSTRAINT valid_sprint_dates CHECK (end_date > start_date)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sprints_board_id ON sprints (board_id);
        CREATE INDEX IF NOT EXISTS idx_sprints_project_id ON sprints (project_id);
        CREATE INDEX IF NOT EXISTS idx_sprints_status ON sprints (status);
        CREATE INDEX IF NOT EXISTS idx_sprints_org_id ON sprints (org_id) WHERE org_id IS NOT NULL;
    """)

    # ==========================================================================
    # Sprint-Story Relationship
    # ==========================================================================

    op.execute("""
        CREATE TABLE IF NOT EXISTS sprint_stories (
            sprint_id TEXT NOT NULL REFERENCES sprints(sprint_id) ON DELETE CASCADE,
            story_id TEXT NOT NULL REFERENCES stories(story_id) ON DELETE CASCADE,
            added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            added_by TEXT NOT NULL,

            PRIMARY KEY (sprint_id, story_id)
        )
    """)

    # ==========================================================================
    # Row-Level Security Policies
    # ==========================================================================

    op.execute("""
        ALTER TABLE boards ENABLE ROW LEVEL SECURITY;
        ALTER TABLE board_columns ENABLE ROW LEVEL SECURITY;
        ALTER TABLE epics ENABLE ROW LEVEL SECURITY;
        ALTER TABLE stories ENABLE ROW LEVEL SECURITY;
        ALTER TABLE board_tasks ENABLE ROW LEVEL SECURITY;
        ALTER TABLE assignment_history ENABLE ROW LEVEL SECURITY;
        ALTER TABLE sprints ENABLE ROW LEVEL SECURITY;
        ALTER TABLE sprint_stories ENABLE ROW LEVEL SECURITY;
    """)

    # RLS Policies
    op.execute("""
        -- Boards RLS: Access if in org or project owner
        DROP POLICY IF EXISTS boards_org_policy ON boards;
        CREATE POLICY boards_org_policy ON boards
            FOR ALL
            USING (
                org_id IS NULL OR
                org_id = current_setting('app.current_org_id', TRUE)
            );

        -- Similar policies for other tables
        DROP POLICY IF EXISTS epics_org_policy ON epics;
        CREATE POLICY epics_org_policy ON epics
            FOR ALL
            USING (
                org_id IS NULL OR
                org_id = current_setting('app.current_org_id', TRUE)
            );

        DROP POLICY IF EXISTS stories_org_policy ON stories;
        CREATE POLICY stories_org_policy ON stories
            FOR ALL
            USING (
                org_id IS NULL OR
                org_id = current_setting('app.current_org_id', TRUE)
            );

        DROP POLICY IF EXISTS board_tasks_org_policy ON board_tasks;
        CREATE POLICY board_tasks_org_policy ON board_tasks
            FOR ALL
            USING (
                org_id IS NULL OR
                org_id = current_setting('app.current_org_id', TRUE)
            );

        DROP POLICY IF EXISTS assignment_history_org_policy ON assignment_history;
        CREATE POLICY assignment_history_org_policy ON assignment_history
            FOR ALL
            USING (
                org_id IS NULL OR
                org_id = current_setting('app.current_org_id', TRUE)
            );

        DROP POLICY IF EXISTS sprints_org_policy ON sprints;
        CREATE POLICY sprints_org_policy ON sprints
            FOR ALL
            USING (
                org_id IS NULL OR
                org_id = current_setting('app.current_org_id', TRUE)
            );

        -- Board columns follow board access
        DROP POLICY IF EXISTS board_columns_access_policy ON board_columns;
        CREATE POLICY board_columns_access_policy ON board_columns
            FOR ALL
            USING (
                EXISTS (
                    SELECT 1 FROM boards b
                    WHERE b.board_id = board_columns.board_id
                )
            );

        -- Sprint stories follow sprint access
        DROP POLICY IF EXISTS sprint_stories_access_policy ON sprint_stories;
        CREATE POLICY sprint_stories_access_policy ON sprint_stories
            FOR ALL
            USING (
                EXISTS (
                    SELECT 1 FROM sprints s
                    WHERE s.sprint_id = sprint_stories.sprint_id
                )
            );
    """)

    # ==========================================================================
    # Trigger Functions
    # ==========================================================================

    op.execute("""
        -- Update timestamps on modification
        CREATE OR REPLACE FUNCTION update_board_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS boards_updated_at ON boards;
        CREATE TRIGGER boards_updated_at
            BEFORE UPDATE ON boards
            FOR EACH ROW
            EXECUTE FUNCTION update_board_updated_at();

        DROP TRIGGER IF EXISTS epics_updated_at ON epics;
        CREATE TRIGGER epics_updated_at
            BEFORE UPDATE ON epics
            FOR EACH ROW
            EXECUTE FUNCTION update_board_updated_at();

        DROP TRIGGER IF EXISTS stories_updated_at ON stories;
        CREATE TRIGGER stories_updated_at
            BEFORE UPDATE ON stories
            FOR EACH ROW
            EXECUTE FUNCTION update_board_updated_at();

        DROP TRIGGER IF EXISTS board_tasks_updated_at ON board_tasks;
        CREATE TRIGGER board_tasks_updated_at
            BEFORE UPDATE ON board_tasks
            FOR EACH ROW
            EXECUTE FUNCTION update_board_updated_at();

        DROP TRIGGER IF EXISTS sprints_updated_at ON sprints;
        CREATE TRIGGER sprints_updated_at
            BEFORE UPDATE ON sprints
            FOR EACH ROW
            EXECUTE FUNCTION update_board_updated_at();
    """)

    # ==========================================================================
    # Agent Workload View
    # ==========================================================================

    op.execute("""
        DROP VIEW IF EXISTS agent_workload;
        CREATE OR REPLACE VIEW agent_workload AS
        SELECT
            assignee_id,
            assignee_type,
            org_id,
            COUNT(*) FILTER (WHERE status IN ('todo', 'in_progress', 'in_review')) AS active_items,
            COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
            COUNT(*) FILTER (WHERE status = 'done') AS completed_count,
            SUM(CASE WHEN story_points IS NOT NULL THEN story_points ELSE 0 END) AS total_story_points
        FROM stories
        WHERE assignee_id IS NOT NULL AND assignee_type = 'agent'
        GROUP BY assignee_id, assignee_type, org_id

        UNION ALL

        SELECT
            assignee_id,
            assignee_type,
            org_id,
            COUNT(*) FILTER (WHERE status IN ('todo', 'in_progress', 'in_review')) AS active_items,
            COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
            COUNT(*) FILTER (WHERE status = 'done') AS completed_count,
            SUM(COALESCE(estimated_hours, 0)) AS total_story_points  -- Use hours for tasks
        FROM board_tasks
        WHERE assignee_id IS NOT NULL AND assignee_type = 'agent'
        GROUP BY assignee_id, assignee_type, org_id
    """)

    op.execute("""
        COMMENT ON VIEW agent_workload IS 'Aggregated workload per agent for capacity planning';
    """)


def downgrade() -> None:
    """Drop Agile Board System tables."""

    # Drop view first
    op.execute("DROP VIEW IF EXISTS agent_workload")

    # Drop triggers
    op.execute("""
        DROP TRIGGER IF EXISTS boards_updated_at ON boards;
        DROP TRIGGER IF EXISTS epics_updated_at ON epics;
        DROP TRIGGER IF EXISTS stories_updated_at ON stories;
        DROP TRIGGER IF EXISTS board_tasks_updated_at ON board_tasks;
        DROP TRIGGER IF EXISTS sprints_updated_at ON sprints;
    """)

    # Drop function
    op.execute("DROP FUNCTION IF EXISTS update_board_updated_at")

    # Drop tables in reverse dependency order
    op.execute("DROP TABLE IF EXISTS sprint_stories CASCADE")
    op.execute("DROP TABLE IF EXISTS sprints CASCADE")
    op.execute("DROP TABLE IF EXISTS assignment_history CASCADE")
    op.execute("DROP TABLE IF EXISTS board_tasks CASCADE")
    op.execute("DROP TABLE IF EXISTS stories CASCADE")
    op.execute("DROP TABLE IF EXISTS epics CASCADE")
    op.execute("DROP TABLE IF EXISTS board_columns CASCADE")
    op.execute("DROP TABLE IF EXISTS boards CASCADE")

    # Drop ENUMs
    op.execute("DROP TYPE IF EXISTS task_type CASCADE")
    op.execute("DROP TYPE IF EXISTS work_item_priority CASCADE")
    op.execute("DROP TYPE IF EXISTS epic_status CASCADE")
    op.execute("DROP TYPE IF EXISTS work_item_status CASCADE")
    op.execute("DROP TYPE IF EXISTS assignee_type CASCADE")
