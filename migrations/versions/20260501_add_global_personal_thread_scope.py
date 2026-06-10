"""Add global_personal_thread scope for multiple global chat threads.

Revision ID: 20260501_global_personal_thread
Revises: 20260428_lifecycle_numeric_guard
Create Date: 2026-05-01

Following behavior_migrate_postgres_schema (Student): extends workspace scopes so users
can create additional project-less chats beyond the single global_user_home row.
Downgrade removes the scope from the CHECK constraint; downgrade will fail if any
global_personal_thread rows exist—delete or archive those rows first.
"""

from __future__ import annotations

from alembic import op


revision = "20260501_global_personal_thread"
down_revision = "20260428_lifecycle_numeric_guard"
branch_labels = None
depends_on = None


TARGET_SCOPES = (
    "project_room",
    "agent_dm",
    "global_user_home",
    "global_personal_thread",
    "project_space",
    "dm",
    "group_chat",
    "work_item_thread",
    "run_thread",
)


def _scope_list(scopes: tuple[str, ...]) -> str:
    return ", ".join(f"'{scope}'" for scope in scopes)


def upgrade() -> None:
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
            (scope IN ('global_user_home', 'global_personal_thread') AND project_id IS NULL)
            OR (scope NOT IN ('global_user_home', 'global_personal_thread') AND project_id IS NOT NULL)
        )
        """
    )


def downgrade() -> None:
    prior_scopes = tuple(s for s in TARGET_SCOPES if s != "global_personal_thread")
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
        ALTER TABLE messaging.conversations
        DROP CONSTRAINT IF EXISTS conversations_scope_check
        """
    )
    op.execute(
        f"""
        ALTER TABLE messaging.conversations
        ADD CONSTRAINT conversations_scope_check
        CHECK (scope IN ({_scope_list(prior_scopes)}))
        """
    )
