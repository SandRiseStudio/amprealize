"""Add archived_at column to messaging.messages and conversations (AMPREALIZE-609, Phase 8).

Adds:
- messaging.messages.archived_at TIMESTAMPTZ — set when a message is moved to archive phase
- messaging.conversations.retention_days INT — per-conversation override (NULL = use project default)
- Index on messaging.messages(created_at) for time-range archival queries
- Index on messaging.messages(archived_at) for identifying archive-eligible messages
"""

from alembic import op
import sqlalchemy as sa

revision = "20260402_msg_archived_at"
down_revision = "20260331_create_messaging"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add archived_at to messages
    op.execute("""
        ALTER TABLE messaging.messages
        ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ DEFAULT NULL
    """)

    # Add retention_days override to conversations (NULL = use project default)
    op.execute("""
        ALTER TABLE messaging.conversations
        ADD COLUMN IF NOT EXISTS retention_days INTEGER DEFAULT NULL
    """)

    # Index for time-range archival queries (find all messages older than N days)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_created_at
        ON messaging.messages (created_at)
    """)

    # Partial index for archive-eligible messages (not yet archived, not deleted)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_archive_eligible
        ON messaging.messages (created_at)
        WHERE archived_at IS NULL AND is_deleted = FALSE
    """)

    # Index for cold-export queries (find all archived messages older than N days)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_archived_at
        ON messaging.messages (archived_at)
        WHERE archived_at IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS messaging.idx_messages_archived_at")
    op.execute("DROP INDEX IF EXISTS messaging.idx_messages_archive_eligible")
    op.execute("DROP INDEX IF EXISTS messaging.idx_messages_created_at")
    op.execute("ALTER TABLE messaging.conversations DROP COLUMN IF EXISTS retention_days")
    op.execute("ALTER TABLE messaging.messages DROP COLUMN IF EXISTS archived_at")
