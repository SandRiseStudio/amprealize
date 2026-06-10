"""Partial index on active participants by actor for conversation list EXISTS.

Revision ID: 20260506_msg_p_actor_ix (kept <=32 chars for alembic_version.version_num)
Revises: 20260505_observability_analytics
Create Date: 2026-05-06

Supports `list_conversations` membership filter:
`EXISTS (SELECT 1 FROM messaging.participants p WHERE p.actor_id = %s AND p.left_at IS NULL ...)`.

Following behavior_migrate_postgres_schema (Student).
"""

from __future__ import annotations

from alembic import op


revision = "20260506_msg_p_actor_ix"
down_revision = "20260505_observability_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_participants_actor_active
        ON messaging.participants (actor_id)
        INCLUDE (conversation_id)
        WHERE left_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS messaging.idx_participants_actor_active")
