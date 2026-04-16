"""Add whiteboard_snapshots table for persisted brainstorm session exports.

Revision ID: 20260414_whiteboard_snapshots
Revises: 20260413_whiteboard_rooms
Create Date: 2026-04-14

Stores exported snapshots when a brainstorm whiteboard session closes.
Canvas elements are preserved as structured JSONB so individual shapes,
notes, and frames can be reused as building blocks in future features.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = "20260414_whiteboard_snapshots"
down_revision = "20260413_whiteboard_rooms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whiteboard_snapshots",
        sa.Column("id", UUID(as_uuid=False), nullable=False),
        sa.Column(
            "room_id",
            UUID(as_uuid=False),
            sa.ForeignKey("whiteboard_rooms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False, server_default="Untitled"),
        sa.Column(
            "format",
            sa.Text(),
            nullable=False,
            server_default="json",
        ),
        sa.Column(
            "data",
            JSONB(),
            nullable=True,
        ),
        sa.Column(
            "canvas_elements",
            JSONB(),
            nullable=True,
        ),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "exported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "metadata",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "shared_with",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_whiteboard_snapshots_room_id",
        "whiteboard_snapshots",
        ["room_id"],
    )
    op.create_index(
        "ix_whiteboard_snapshots_session_id",
        "whiteboard_snapshots",
        ["session_id"],
    )
    op.create_index(
        "ix_whiteboard_snapshots_created_by",
        "whiteboard_snapshots",
        ["created_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_whiteboard_snapshots_created_by", table_name="whiteboard_snapshots")
    op.drop_index("ix_whiteboard_snapshots_session_id", table_name="whiteboard_snapshots")
    op.drop_index("ix_whiteboard_snapshots_room_id", table_name="whiteboard_snapshots")
    op.drop_table("whiteboard_snapshots")
