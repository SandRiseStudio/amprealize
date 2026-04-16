"""Add whiteboard_rooms table for brainstorm whiteboard feature.

Revision ID: 20260413_whiteboard_rooms
Revises: 20260406_metrics_trace
Create Date: 2026-04-13

Part of GUIDEAI-931 — Add whiteboard data model and Alembic migration.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = "20260413_whiteboard_rooms"
down_revision = "20260406_metrics_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whiteboard_rooms",
        sa.Column("id", UUID(as_uuid=False), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False, server_default="Untitled"),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "participant_ids",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "canvas_state",
            JSONB(),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "closed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_whiteboard_rooms_session_id", "whiteboard_rooms", ["session_id"])
    op.create_index("ix_whiteboard_rooms_status", "whiteboard_rooms", ["status"])
    op.create_index("ix_whiteboard_rooms_created_by", "whiteboard_rooms", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_whiteboard_rooms_created_by", table_name="whiteboard_rooms")
    op.drop_index("ix_whiteboard_rooms_status", table_name="whiteboard_rooms")
    op.drop_index("ix_whiteboard_rooms_session_id", table_name="whiteboard_rooms")
    op.drop_table("whiteboard_rooms")
