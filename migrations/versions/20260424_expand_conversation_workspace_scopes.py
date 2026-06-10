"""Expand messaging conversations to target chat workspace scopes.

Revision ID: 20260424_conv_scopes
Revises: 20260415_board_item_perf_indexes
Create Date: 2026-04-24

Following behavior_migrate_postgres_schema (Student).
"""

from __future__ import annotations

from alembic import op


revision = "20260424_conv_scopes"
down_revision = "20260415_board_item_perf_indexes"
branch_labels = None
depends_on = None


TARGET_SCOPES = (
    "project_room",
    "agent_dm",
    "global_user_home",
    "project_space",
    "dm",
    "group_chat",
    "work_item_thread",
    "run_thread",
)


def _scope_list(scopes: tuple[str, ...]) -> str:
    return ", ".join(f"'{scope}'" for scope in scopes)


def upgrade() -> None:
    # Global user chat is not project-bound; project scopes remain project-bound.
    op.execute(
        """
        ALTER TABLE messaging.conversations
        ALTER COLUMN project_id DROP NOT NULL
        """
    )

    op.execute(
        """
        ALTER TABLE messaging.conversations
        DROP CONSTRAINT IF EXISTS conversations_scope_check
        """
    )
    op.execute(
        f"""
        ALTER TABLE messaging.conversations
        ADD CONSTRAINT conversations_scope_check
        CHECK (scope IN ({_scope_list(TARGET_SCOPES)}))
        """
    )

    op.execute(
        """
        ALTER TABLE messaging.conversations
        DROP CONSTRAINT IF EXISTS conversations_project_scope_binding_check
        """
    )
    op.execute(
        """
        ALTER TABLE messaging.conversations
        ADD CONSTRAINT conversations_project_scope_binding_check
        CHECK (
            (scope = 'global_user_home' AND project_id IS NULL)
            OR (scope <> 'global_user_home' AND project_id IS NOT NULL)
        )
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_global_user_home
            ON messaging.conversations (created_by)
            WHERE scope = 'global_user_home' AND is_archived = false
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversations_scope
            ON messaging.conversations (scope)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS messaging.idx_conversations_scope")
    op.execute("DROP INDEX IF EXISTS messaging.uq_global_user_home")

    op.execute(
        """
        ALTER TABLE messaging.conversations
        DROP CONSTRAINT IF EXISTS conversations_project_scope_binding_check
        """
    )
    op.execute(
        """
        ALTER TABLE messaging.conversations
        DROP CONSTRAINT IF EXISTS conversations_scope_check
        """
    )
    op.execute(
        """
        ALTER TABLE messaging.conversations
        ADD CONSTRAINT conversations_scope_check
        CHECK (scope IN ('project_room', 'agent_dm'))
        """
    )
    op.execute(
        """
        ALTER TABLE messaging.conversations
        ALTER COLUMN project_id SET NOT NULL
        """
    )
