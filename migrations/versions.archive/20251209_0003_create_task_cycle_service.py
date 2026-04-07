"""Create TaskCycleService tables for GEP

Revision ID: 0003_task_cycle
Revises: 0002_tenant_limits
Create Date: 2025-12-09

Behavior: behavior_migrate_postgres_schema, behavior_follow_gep_cycle

Creates 5 tables for the Amprealize Execution Protocol (GEP):
1. task_cycles - Main cycle state and metadata
2. phase_transitions - Audit trail of phase changes
3. clarification_threads - Q&A threads between Agent A and Entity B
4. clarification_messages - Individual messages in threads
5. architecture_docs - Architecture/design documents with versioning

See TASK_CYCLE_SERVICE_CONTRACT.md for full specification.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0003_task_cycle"
down_revision: Union[str, None] = "0002_tenant_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create TaskCycleService tables for GEP."""

    # Create task_cycles table
    op.execute("""
        CREATE TABLE IF NOT EXISTS task_cycles (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            org_id TEXT REFERENCES organizations(id),

            -- Current state
            current_phase TEXT NOT NULL DEFAULT 'PLANNING',
            status TEXT NOT NULL DEFAULT 'active',

            -- Acceptance criteria (JSONB array of strings)
            acceptance_criteria JSONB NOT NULL DEFAULT '[]',

            -- Timeout configuration
            timeout_config JSONB NOT NULL DEFAULT '{
                "clarification_timeout_hours": 24,
                "architecture_timeout_hours": 48,
                "verification_timeout_hours": 48,
                "policy": "pause_with_notification"
            }',

            -- Test iteration tracking
            test_iteration INTEGER NOT NULL DEFAULT 0,
            max_test_iterations INTEGER NOT NULL DEFAULT 5,

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,

            -- Metadata (extensible)
            metadata JSONB NOT NULL DEFAULT '{}',

            -- Constraints
            CONSTRAINT valid_phase CHECK (current_phase IN (
                'PLANNING', 'CLARIFYING', 'ARCHITECTING', 'EXECUTING',
                'TESTING', 'FIXING', 'VERIFYING', 'COMPLETING',
                'COMPLETED', 'CANCELLED', 'FAILED'
            )),
            CONSTRAINT valid_status CHECK (status IN ('active', 'completed', 'cancelled', 'failed'))
        )
    """)

    # Add comments
    op.execute("""
        COMMENT ON TABLE task_cycles IS
            'GEP task cycles tracking 8-phase execution with Entity B oversight';
        COMMENT ON COLUMN task_cycles.current_phase IS
            'Current phase in GEP: PLANNING → CLARIFYING → ARCHITECTING → EXECUTING → TESTING → FIXING → VERIFYING → COMPLETING';
        COMMENT ON COLUMN task_cycles.timeout_config IS
            'Timeout configuration including policy: pause_with_notification, auto_escalate, proceed_with_assumptions';
    """)

    # Create indexes for task_cycles
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_task_cycles_task_id ON task_cycles(task_id);
        CREATE INDEX IF NOT EXISTS idx_task_cycles_org_id ON task_cycles(org_id);
        CREATE INDEX IF NOT EXISTS idx_task_cycles_phase ON task_cycles(current_phase);
        CREATE INDEX IF NOT EXISTS idx_task_cycles_status ON task_cycles(status);
        CREATE INDEX IF NOT EXISTS idx_task_cycles_created_at ON task_cycles(created_at DESC);
    """)

    # Enable RLS on task_cycles
    op.execute("""
        ALTER TABLE task_cycles ENABLE ROW LEVEL SECURITY;

        CREATE POLICY task_cycles_org_isolation ON task_cycles
            USING (
                org_id IS NULL
                OR org_id = current_setting('app.current_org_id', true)
            );
    """)

    # Create phase_transitions table (audit trail)
    op.execute("""
        CREATE TABLE IF NOT EXISTS phase_transitions (
            id TEXT PRIMARY KEY,
            cycle_id TEXT NOT NULL REFERENCES task_cycles(id) ON DELETE CASCADE,

            -- Transition details
            from_phase TEXT NOT NULL,
            to_phase TEXT NOT NULL,

            -- Gate enforcement
            gate_type TEXT NOT NULL,
            gate_satisfied BOOLEAN NOT NULL DEFAULT false,

            -- Actor and context
            actor_id TEXT,
            reason TEXT,

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            -- Metadata
            metadata JSONB NOT NULL DEFAULT '{}',

            -- Constraints
            CONSTRAINT valid_gate_type CHECK (gate_type IN ('NONE', 'SOFT', 'STRICT'))
        )
    """)

    op.execute("""
        COMMENT ON TABLE phase_transitions IS
            'Audit trail of GEP phase transitions with gate enforcement records';

        CREATE INDEX IF NOT EXISTS idx_phase_transitions_cycle_id
            ON phase_transitions(cycle_id);
        CREATE INDEX IF NOT EXISTS idx_phase_transitions_created_at
            ON phase_transitions(created_at DESC);
    """)

    # Create clarification_threads table
    op.execute("""
        CREATE TABLE IF NOT EXISTS clarification_threads (
            id TEXT PRIMARY KEY,
            cycle_id TEXT NOT NULL REFERENCES task_cycles(id) ON DELETE CASCADE,

            -- Thread metadata
            status TEXT NOT NULL DEFAULT 'open',
            priority TEXT NOT NULL DEFAULT 'medium',

            -- Initial question
            question TEXT NOT NULL,
            context TEXT,

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ,

            -- Constraints
            CONSTRAINT valid_thread_status CHECK (status IN ('open', 'answered', 'resolved', 'closed')),
            CONSTRAINT valid_priority CHECK (priority IN ('low', 'medium', 'high', 'critical'))
        )
    """)

    op.execute("""
        COMMENT ON TABLE clarification_threads IS
            'Q&A threads between Agent A and Entity B during CLARIFYING phase';

        CREATE INDEX IF NOT EXISTS idx_clarification_threads_cycle_id
            ON clarification_threads(cycle_id);
        CREATE INDEX IF NOT EXISTS idx_clarification_threads_status
            ON clarification_threads(status);
    """)

    # Create clarification_messages table
    op.execute("""
        CREATE TABLE IF NOT EXISTS clarification_messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES clarification_threads(id) ON DELETE CASCADE,

            -- Message content
            role TEXT NOT NULL,
            content TEXT NOT NULL,

            -- Actor tracking
            actor_id TEXT,

            -- Timestamp
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            -- Constraints
            CONSTRAINT valid_message_role CHECK (role IN ('agent', 'entity_b'))
        )
    """)

    op.execute("""
        COMMENT ON TABLE clarification_messages IS
            'Individual messages in clarification threads';

        CREATE INDEX IF NOT EXISTS idx_clarification_messages_thread_id
            ON clarification_messages(thread_id);
        CREATE INDEX IF NOT EXISTS idx_clarification_messages_created_at
            ON clarification_messages(created_at);
    """)

    # Create architecture_docs table
    op.execute("""
        CREATE TABLE IF NOT EXISTS architecture_docs (
            id TEXT PRIMARY KEY,
            cycle_id TEXT NOT NULL REFERENCES task_cycles(id) ON DELETE CASCADE,

            -- Document content
            title TEXT NOT NULL,
            overview TEXT NOT NULL,
            sections JSONB NOT NULL DEFAULT '[]',
            plan_steps JSONB NOT NULL DEFAULT '[]',

            -- Versioning
            version INTEGER NOT NULL DEFAULT 1,

            -- Review status
            review_status TEXT NOT NULL DEFAULT 'draft',
            reviewed_by TEXT,
            review_feedback TEXT,

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            approved_at TIMESTAMPTZ,

            -- Constraints
            CONSTRAINT valid_review_status CHECK (
                review_status IN ('draft', 'pending_review', 'changes_requested', 'approved', 'rejected')
            )
        )
    """)

    op.execute("""
        COMMENT ON TABLE architecture_docs IS
            'Architecture/design documents with versioning and Entity B approval workflow';
        COMMENT ON COLUMN architecture_docs.sections IS
            'JSONB array of {name, content} objects defining document sections';
        COMMENT ON COLUMN architecture_docs.plan_steps IS
            'JSONB array of {order, description, estimated_duration, status} objects';

        CREATE INDEX IF NOT EXISTS idx_architecture_docs_cycle_id
            ON architecture_docs(cycle_id);
        CREATE INDEX IF NOT EXISTS idx_architecture_docs_review_status
            ON architecture_docs(review_status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_architecture_docs_cycle_version
            ON architecture_docs(cycle_id, version);
    """)

    # Create trigger to update updated_at on task_cycles
    op.execute("""
        CREATE OR REPLACE FUNCTION update_task_cycle_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS task_cycles_updated_at ON task_cycles;
        CREATE TRIGGER task_cycles_updated_at
            BEFORE UPDATE ON task_cycles
            FOR EACH ROW
            EXECUTE FUNCTION update_task_cycle_timestamp();
    """)

    # Create trigger to update updated_at on architecture_docs
    op.execute("""
        DROP TRIGGER IF EXISTS architecture_docs_updated_at ON architecture_docs;
        CREATE TRIGGER architecture_docs_updated_at
            BEFORE UPDATE ON architecture_docs
            FOR EACH ROW
            EXECUTE FUNCTION update_task_cycle_timestamp();
    """)


def downgrade() -> None:
    """Remove TaskCycleService tables."""

    # Drop triggers first
    op.execute("""
        DROP TRIGGER IF EXISTS task_cycles_updated_at ON task_cycles;
        DROP TRIGGER IF EXISTS architecture_docs_updated_at ON architecture_docs;
        DROP FUNCTION IF EXISTS update_task_cycle_timestamp();
    """)

    # Drop RLS policy
    op.execute("""
        DROP POLICY IF EXISTS task_cycles_org_isolation ON task_cycles;
    """)

    # Drop tables in reverse dependency order
    op.execute("DROP TABLE IF EXISTS clarification_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS clarification_threads CASCADE")
    op.execute("DROP TABLE IF EXISTS architecture_docs CASCADE")
    op.execute("DROP TABLE IF EXISTS phase_transitions CASCADE")
    op.execute("DROP TABLE IF EXISTS task_cycles CASCADE")
