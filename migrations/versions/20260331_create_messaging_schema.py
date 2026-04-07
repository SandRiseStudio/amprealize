"""Create messaging schema with five tables.

Adds the `messaging` schema and five tables for the agent conversation system:
- messaging.conversations: project rooms and agent DMs
- messaging.participants: conversation membership and read state
- messaging.messages: all message content with full-text search
- messaging.reactions: emoji reactions on messages
- messaging.external_bindings: Slack/Teams bridge configuration

Includes indexes, partial unique constraints, and RLS policies.

Revision ID: 20260331_create_messaging
Revises: 20260329_research_enhanced
Create Date: 2026-03-31

Behavior: behavior_migrate_postgres_schema
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260331_create_messaging"
down_revision: Union[str, None] = "20260329_research_enhanced"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create messaging schema with all tables, indexes, and constraints."""

    # -- Schema ----------------------------------------------------------
    op.execute("CREATE SCHEMA IF NOT EXISTS messaging")

    # -- messaging.conversations -----------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS messaging.conversations (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id      TEXT NOT NULL,
            org_id          TEXT,
            scope           TEXT NOT NULL CHECK (scope IN ('project_room', 'agent_dm')),
            title           TEXT,
            created_by      TEXT NOT NULL,
            pinned_message_id UUID,
            is_archived     BOOLEAN NOT NULL DEFAULT FALSE,
            metadata        JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    # Partial unique index: one project_room per project
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_project_room
            ON messaging.conversations (project_id)
            WHERE scope = 'project_room';
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversations_project
            ON messaging.conversations (project_id);
        """
    )

    # -- messaging.participants ------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS messaging.participants (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES messaging.conversations(id) ON DELETE CASCADE,
            actor_id        TEXT NOT NULL,
            actor_type      TEXT NOT NULL CHECK (actor_type IN ('user', 'agent', 'system')),
            role            TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
            joined_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            left_at         TIMESTAMPTZ,
            last_read_at    TIMESTAMPTZ,
            is_muted        BOOLEAN NOT NULL DEFAULT FALSE,
            notification_preference TEXT NOT NULL DEFAULT 'mentions'
                CHECK (notification_preference IN ('all', 'mentions', 'none')),

            CONSTRAINT uq_conversation_actor UNIQUE (conversation_id, actor_id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_participants_actor
            ON messaging.participants (actor_id, actor_type);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_participants_conversation
            ON messaging.participants (conversation_id);
        """
    )

    # -- messaging.messages ----------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS messaging.messages (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES messaging.conversations(id) ON DELETE CASCADE,
            sender_id       TEXT NOT NULL,
            sender_type     TEXT NOT NULL CHECK (sender_type IN ('user', 'agent', 'system')),
            content         TEXT,
            message_type    TEXT NOT NULL DEFAULT 'text'
                CHECK (message_type IN (
                    'text', 'status_card', 'blocker_card', 'progress_card',
                    'code_block', 'run_summary', 'system'
                )),
            structured_payload JSONB,
            parent_id       UUID REFERENCES messaging.messages(id) ON DELETE SET NULL,
            run_id          TEXT,
            behavior_id     TEXT,
            work_item_id    TEXT,
            is_edited       BOOLEAN NOT NULL DEFAULT FALSE,
            edited_at       TIMESTAMPTZ,
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at      TIMESTAMPTZ,
            metadata        JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

            search_vector   TSVECTOR GENERATED ALWAYS AS (
                to_tsvector('english', COALESCE(content, ''))
            ) STORED
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
            ON messaging.messages (conversation_id, created_at DESC);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_parent
            ON messaging.messages (parent_id) WHERE parent_id IS NOT NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_sender
            ON messaging.messages (sender_id, sender_type);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_run
            ON messaging.messages (run_id) WHERE run_id IS NOT NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_search
            ON messaging.messages USING GIN (search_vector);
        """
    )

    # -- messaging.reactions ---------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS messaging.reactions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            message_id      UUID NOT NULL REFERENCES messaging.messages(id) ON DELETE CASCADE,
            actor_id        TEXT NOT NULL,
            actor_type      TEXT NOT NULL CHECK (actor_type IN ('user', 'agent')),
            emoji           TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT uq_reaction UNIQUE (message_id, actor_id, emoji)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reactions_message
            ON messaging.reactions (message_id);
        """
    )

    # -- messaging.external_bindings -------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS messaging.external_bindings (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES messaging.conversations(id) ON DELETE CASCADE,
            provider        TEXT NOT NULL CHECK (provider IN ('slack', 'teams', 'discord')),
            external_channel_id TEXT NOT NULL,
            external_workspace_id TEXT,
            config          JSONB NOT NULL DEFAULT '{}',
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            bound_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            bound_by        TEXT NOT NULL,

            CONSTRAINT uq_external_binding UNIQUE (conversation_id, provider, external_channel_id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_external_bindings_conversation
            ON messaging.external_bindings (conversation_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_external_bindings_external
            ON messaging.external_bindings (provider, external_channel_id);
        """
    )

    # -- Pinned message FK (deferred: column exists, add FK after messages table) --
    op.execute(
        """
        ALTER TABLE messaging.conversations
            ADD CONSTRAINT fk_pinned_message
            FOREIGN KEY (pinned_message_id)
            REFERENCES messaging.messages(id)
            ON DELETE SET NULL;
        """
    )

    # -- RLS policies (enable on all messaging tables) -------------------
    for table in ['conversations', 'participants', 'messages', 'reactions', 'external_bindings']:
        op.execute(f"ALTER TABLE messaging.{table} ENABLE ROW LEVEL SECURITY")

    # Conversations: visible to participants
    op.execute(
        """
        CREATE POLICY conversations_access ON messaging.conversations
            FOR ALL
            USING (
                EXISTS (
                    SELECT 1 FROM messaging.participants p
                    WHERE p.conversation_id = id
                      AND p.actor_id = current_setting('app.current_user_id', true)
                      AND p.left_at IS NULL
                )
            );
        """
    )

    # Participants: visible to fellow participants in the same conversation
    op.execute(
        """
        CREATE POLICY participants_access ON messaging.participants
            FOR ALL
            USING (
                conversation_id IN (
                    SELECT p2.conversation_id FROM messaging.participants p2
                    WHERE p2.actor_id = current_setting('app.current_user_id', true)
                      AND p2.left_at IS NULL
                )
            );
        """
    )

    # Messages: visible to conversation participants
    op.execute(
        """
        CREATE POLICY messages_access ON messaging.messages
            FOR ALL
            USING (
                conversation_id IN (
                    SELECT p.conversation_id FROM messaging.participants p
                    WHERE p.actor_id = current_setting('app.current_user_id', true)
                      AND p.left_at IS NULL
                )
            );
        """
    )

    # Reactions: visible to conversation participants
    op.execute(
        """
        CREATE POLICY reactions_access ON messaging.reactions
            FOR ALL
            USING (
                message_id IN (
                    SELECT m.id FROM messaging.messages m
                    JOIN messaging.participants p ON p.conversation_id = m.conversation_id
                    WHERE p.actor_id = current_setting('app.current_user_id', true)
                      AND p.left_at IS NULL
                )
            );
        """
    )

    # External bindings: visible to conversation participants
    op.execute(
        """
        CREATE POLICY external_bindings_access ON messaging.external_bindings
            FOR ALL
            USING (
                conversation_id IN (
                    SELECT p.conversation_id FROM messaging.participants p
                    WHERE p.actor_id = current_setting('app.current_user_id', true)
                      AND p.left_at IS NULL
                )
            );
        """
    )


def downgrade() -> None:
    """Drop messaging schema and all tables."""

    # Drop RLS policies first
    for table in ['conversations', 'participants', 'messages', 'reactions', 'external_bindings']:
        op.execute(f"DROP POLICY IF EXISTS {table}_access ON messaging.{table}")

    # Drop FK constraint on conversations before dropping messages
    op.execute(
        "ALTER TABLE messaging.conversations "
        "DROP CONSTRAINT IF EXISTS fk_pinned_message"
    )

    # Drop tables in reverse dependency order
    op.execute("DROP TABLE IF EXISTS messaging.external_bindings CASCADE")
    op.execute("DROP TABLE IF EXISTS messaging.reactions CASCADE")
    op.execute("DROP TABLE IF EXISTS messaging.messages CASCADE")
    op.execute("DROP TABLE IF EXISTS messaging.participants CASCADE")
    op.execute("DROP TABLE IF EXISTS messaging.conversations CASCADE")

    # Drop schema
    op.execute("DROP SCHEMA IF EXISTS messaging CASCADE")
