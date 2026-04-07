"""
Unit and integration tests for ConversationService (messaging system).

Tests verify:
- Conversation CRUD operations
- Participant management
- Message send, edit, delete lifecycle
- Threading (parent/child messages)
- Reactions (add, duplicate, remove)
- Full-text search
- Access control (participant-only, edit window)

Infrastructure requirements:
- PostgreSQL with messaging schema
- Uses AMPREALIZE_MESSAGING_PG_DSN or AMPREALIZE_PG_DSN from environment

Run with: ./scripts/run_tests.sh --breakeramp --env test tests/test_conversation_service.py
"""
import os
import time
import uuid

import pytest

# Mark all tests as requiring postgres
pytestmark = [
    pytest.mark.requires_services("postgres"),
    pytest.mark.integration,
]

from amprealize.conversation_contracts import (
    ConversationScope,
    MessageType,
    ParticipantRole,
)
from amprealize.services.conversation_service import (
    AccessDeniedError,
    ConversationNotFoundError,
    ConversationService,
    DuplicateReactionError,
    EditWindowClosedError,
    MessageNotFoundError,
)


# =============================================================================
# Fixtures
# =============================================================================

def _truncate_messaging_tables(dsn: str) -> None:
    """Truncate all messaging tables for test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, [
        "external_bindings", "reactions", "messages",
        "participants", "conversations",
    ], schema="messaging")


def _ensure_messaging_references(dsn: str) -> None:
    """Ensure auth reference rows exist for FK constraints."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 required for FK seed data")

    org_id = "org-test-001"
    project_id = "proj-test-001"
    user_id = "test-user-001"
    user2_id = "test-user-002"

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth.organizations (id, name, slug)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (org_id, "Test Organization", "test-org-001"),
            )
            for uid, email, name in [
                (user_id, "user1@example.com", "Test User 1"),
                (user2_id, "user2@example.com", "Test User 2"),
            ]:
                cur.execute(
                    """
                    INSERT INTO auth.users (id, email, display_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (uid, email, name),
                )
            cur.execute(
                """
                INSERT INTO auth.projects (project_id, org_id, name, created_by, owner_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (project_id) DO NOTHING
                """,
                (project_id, org_id, "Test Project", user_id, user_id),
            )
        conn.commit()


@pytest.fixture
def dsn() -> str:
    """Get PostgreSQL DSN from environment."""
    dsn = (
        os.environ.get("AMPREALIZE_MESSAGING_PG_DSN")
        or os.environ.get("AMPREALIZE_PG_DSN")
    )
    if not dsn:
        pytest.skip("AMPREALIZE_MESSAGING_PG_DSN or AMPREALIZE_PG_DSN not set")
    return dsn


@pytest.fixture
def service(dsn):
    """ConversationService fixture with table truncation."""
    svc = ConversationService(dsn=dsn)
    _ensure_messaging_references(dsn)
    _truncate_messaging_tables(dsn)
    yield svc
    _truncate_messaging_tables(dsn)


@pytest.fixture
def org_id() -> str:
    return "org-test-001"


@pytest.fixture
def project_id() -> str:
    return "proj-test-001"


@pytest.fixture
def user_id() -> str:
    return "test-user-001"


@pytest.fixture
def user2_id() -> str:
    return "test-user-002"


# =============================================================================
# Conversation CRUD
# =============================================================================

class TestConversationCRUD:
    """Test conversation lifecycle operations."""

    def test_create_project_room(self, service, project_id, user_id, org_id):
        """Create a project room conversation."""
        conv = service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.PROJECT_ROOM,
            created_by=user_id,
            org_id=org_id,
        )
        assert conv.id is not None
        uuid.UUID(conv.id)
        assert conv.project_id == project_id
        assert conv.scope == ConversationScope.PROJECT_ROOM
        assert conv.is_archived is False

    def test_create_agent_dm(self, service, project_id, user_id, user2_id, org_id):
        """Create an agent DM conversation with title."""
        conv = service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.AGENT_DM,
            title="Sprint Planning Discussion",
            created_by=user_id,
            participant_ids=[user2_id],
            org_id=org_id,
        )
        assert conv.title == "Sprint Planning Discussion"
        assert conv.scope == ConversationScope.AGENT_DM

    def test_create_agent_dm_with_participants(self, service, project_id, user_id, user2_id, org_id):
        """Create an agent DM conversation with participants."""
        conv = service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.AGENT_DM,
            created_by=user_id,
            participant_ids=[user2_id],
            org_id=org_id,
        )
        assert conv.scope == ConversationScope.AGENT_DM

    def test_get_conversation(self, service, project_id, user_id, org_id):
        """Retrieve a conversation by ID."""
        conv = service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.PROJECT_ROOM,
            created_by=user_id,
            org_id=org_id,
        )
        fetched = service.get_conversation(conv.id, org_id=org_id, user_id=user_id)
        assert fetched.id == conv.id
        assert fetched.project_id == project_id

    def test_get_conversation_not_found(self, service, org_id, user_id):
        """Get non-existent conversation raises error."""
        with pytest.raises(ConversationNotFoundError):
            service.get_conversation(str(uuid.uuid4()), org_id=org_id, user_id=user_id)

    def test_list_conversations(self, service, project_id, user_id, org_id):
        """List conversations for a project."""
        for i in range(3):
            service.create_conversation(
                project_id=project_id,
                scope=ConversationScope.AGENT_DM,
                title=f"DM {uuid.uuid4().hex[:6]}",
                created_by=user_id,
                org_id=org_id,
            )
        convs, total = service.list_conversations(
            project_id=project_id,
            user_id=user_id,
            org_id=org_id,
        )
        assert total >= 3
        assert len(convs) >= 3

    def test_list_conversations_filter_scope(self, service, project_id, user_id, user2_id, org_id):
        """List conversations filtered by scope."""
        service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.PROJECT_ROOM,
            created_by=user_id,
            org_id=org_id,
        )
        service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.AGENT_DM,
            title="A DM",
            created_by=user_id,
            participant_ids=[user2_id],
            org_id=org_id,
        )
        convs, total = service.list_conversations(
            project_id=project_id,
            user_id=user_id,
            org_id=org_id,
            scope=ConversationScope.AGENT_DM,
        )
        for c in convs:
            assert c.scope == ConversationScope.AGENT_DM

    def test_archive_conversation(self, service, project_id, user_id, org_id):
        """Archive a conversation."""
        conv = service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.PROJECT_ROOM,
            title="To Archive",
            created_by=user_id,
            org_id=org_id,
        )
        service.archive_conversation(conv.id, user_id=user_id, org_id=org_id)
        # get_conversation excludes archived, so use list with include_archived
        convs, total = service.list_conversations(
            project_id=project_id,
            user_id=user_id,
            org_id=org_id,
            include_archived=True,
        )
        archived = [c for c in convs if c.id == conv.id]
        assert len(archived) == 1
        assert archived[0].is_archived is True

    def test_list_excludes_archived(self, service, project_id, user_id, org_id):
        """Archived conversations excluded by default."""
        conv = service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.PROJECT_ROOM,
            title="Archived",
            created_by=user_id,
            org_id=org_id,
        )
        service.archive_conversation(conv.id, user_id=user_id, org_id=org_id)

        convs, total = service.list_conversations(
            project_id=project_id,
            user_id=user_id,
            org_id=org_id,
            include_archived=False,
        )
        ids = [c.id for c in convs]
        assert conv.id not in ids


# =============================================================================
# Message Lifecycle
# =============================================================================

class TestMessageLifecycle:
    """Test message send, edit, delete, threading."""

    @pytest.fixture
    def conversation(self, service, project_id, user_id, org_id):
        """Create a conversation and return it."""
        return service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.PROJECT_ROOM,
            created_by=user_id,
            org_id=org_id,
        )

    def test_send_message(self, service, conversation, user_id, org_id):
        """Send a text message."""
        msg = service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Hello, world!",
            org_id=org_id,
        )
        assert msg.id is not None
        assert msg.content == "Hello, world!"
        assert msg.sender_id == user_id
        assert msg.message_type == MessageType.TEXT
        assert msg.is_deleted is False

    def test_send_status_card_message(self, service, conversation, user_id, org_id):
        """Send a status card message with structured payload."""
        msg = service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Agent analysis complete",
            message_type=MessageType.STATUS_CARD,
            structured_payload={"model": "gpt-4", "tokens": 150},
            org_id=org_id,
        )
        assert msg.message_type == MessageType.STATUS_CARD
        assert msg.structured_payload["model"] == "gpt-4"

    def test_send_threaded_reply(self, service, conversation, user_id, org_id):
        """Send a threaded reply to an existing message."""
        parent = service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Original message",
            org_id=org_id,
        )
        reply = service.send_message(
            conversation.id,
            sender_id=user_id,
            content="This is a reply",
            parent_id=parent.id,
            org_id=org_id,
        )
        assert reply.parent_id == parent.id

    def test_list_messages(self, service, conversation, user_id, org_id):
        """List messages in a conversation."""
        for i in range(5):
            service.send_message(
                conversation.id,
                sender_id=user_id,
                content=f"Message {i}",
                org_id=org_id,
            )
        msgs, total, has_more = service.list_messages(
            conversation.id,
            user_id=user_id,
            org_id=org_id,
        )
        assert total == 5
        assert len(msgs) == 5
        assert has_more is False

    def test_list_messages_pagination(self, service, conversation, user_id, org_id):
        """Paginated message listing."""
        for i in range(10):
            service.send_message(
                conversation.id,
                sender_id=user_id,
                content=f"Msg {i}",
                org_id=org_id,
            )
        msgs, total, has_more = service.list_messages(
            conversation.id,
            user_id=user_id,
            org_id=org_id,
            limit=3,
            offset=0,
        )
        assert total == 10
        assert len(msgs) == 3
        assert has_more is True

    def test_get_message(self, service, conversation, user_id, org_id):
        """Get a specific message by ID."""
        sent = service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Specific message",
            org_id=org_id,
        )
        fetched = service.get_message(sent.id, org_id=org_id, user_id=user_id)
        assert fetched.id == sent.id
        assert fetched.content == "Specific message"

    def test_edit_message(self, service, conversation, user_id, org_id):
        """Edit a message within the edit window."""
        msg = service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Original content",
            org_id=org_id,
        )
        edited = service.edit_message(
            msg.id,
            new_content="Edited content",
            editor_id=user_id,
            org_id=org_id,
        )
        assert edited.content == "Edited content"
        assert edited.is_edited is True
        assert edited.edited_at is not None

    def test_edit_message_wrong_user(self, service, conversation, user_id, user2_id, org_id):
        """Only the sender can edit their message."""
        # Add user2 as participant first
        service.add_participant(
            conversation.id,
            actor_id=user2_id,
            role=ParticipantRole.MEMBER,
            added_by=user_id,
            org_id=org_id,
        )
        msg = service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Only I can edit this",
            org_id=org_id,
        )
        with pytest.raises(AccessDeniedError):
            service.edit_message(
                msg.id,
                new_content="Attempted edit",
                editor_id=user2_id,
                org_id=org_id,
            )

    def test_delete_message(self, service, conversation, user_id, org_id):
        """Soft-delete a message."""
        msg = service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Delete me",
            org_id=org_id,
        )
        service.delete_message(msg.id, deleter_id=user_id, org_id=org_id)
        deleted = service.get_message(msg.id, org_id=org_id, user_id=user_id)
        assert deleted.is_deleted is True

    def test_list_thread_replies(self, service, conversation, user_id, org_id):
        """List only thread replies for a parent message."""
        parent = service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Thread parent",
            org_id=org_id,
        )
        for i in range(3):
            service.send_message(
                conversation.id,
                sender_id=user_id,
                content=f"Reply {i}",
                parent_id=parent.id,
                org_id=org_id,
            )
        # Also send a non-threaded message
        service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Not in thread",
            org_id=org_id,
        )

        replies, total, _ = service.list_messages(
            conversation.id,
            user_id=user_id,
            org_id=org_id,
            parent_id=parent.id,
        )
        assert total == 3
        for r in replies:
            assert r.parent_id == parent.id


# =============================================================================
# Reactions
# =============================================================================

class TestReactions:
    """Test reaction add/remove/duplicate."""

    @pytest.fixture
    def conversation(self, service, project_id, user_id, org_id):
        return service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.PROJECT_ROOM,
            created_by=user_id,
            org_id=org_id,
        )

    @pytest.fixture
    def message(self, service, conversation, user_id, org_id):
        return service.send_message(
            conversation.id,
            sender_id=user_id,
            content="React to this",
            org_id=org_id,
        )

    def test_add_reaction(self, service, message, user_id, org_id):
        """Add an emoji reaction to a message."""
        reaction = service.add_reaction(
            message.id, actor_id=user_id, emoji="👍", org_id=org_id
        )
        assert reaction.emoji == "👍"
        assert reaction.actor_id == user_id

    def test_duplicate_reaction(self, service, message, user_id, org_id):
        """Adding the same emoji twice raises DuplicateReactionError."""
        service.add_reaction(message.id, actor_id=user_id, emoji="👍", org_id=org_id)
        with pytest.raises(DuplicateReactionError):
            service.add_reaction(message.id, actor_id=user_id, emoji="👍", org_id=org_id)

    def test_multiple_different_reactions(self, service, message, user_id, org_id):
        """Same user can add different emojis."""
        service.add_reaction(message.id, actor_id=user_id, emoji="👍", org_id=org_id)
        service.add_reaction(message.id, actor_id=user_id, emoji="❤️", org_id=org_id)
        # No error raised

    def test_remove_reaction(self, service, message, user_id, org_id):
        """Remove a reaction."""
        service.add_reaction(message.id, actor_id=user_id, emoji="👍", org_id=org_id)
        service.remove_reaction(message.id, actor_id=user_id, emoji="👍", org_id=org_id)
        # Can add same reaction again after removal
        service.add_reaction(message.id, actor_id=user_id, emoji="👍", org_id=org_id)


# =============================================================================
# Search
# =============================================================================

class TestSearch:
    """Test full-text search."""

    @pytest.fixture
    def conversation(self, service, project_id, user_id, org_id):
        return service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.PROJECT_ROOM,
            created_by=user_id,
            org_id=org_id,
        )

    def test_search_messages(self, service, conversation, user_id, org_id):
        """Search messages by content."""
        service.send_message(
            conversation.id,
            sender_id=user_id,
            content="The deployment pipeline is broken",
            org_id=org_id,
        )
        service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Let's fix the tests",
            org_id=org_id,
        )
        service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Pipeline configuration updated",
            org_id=org_id,
        )

        results, total = service.search_messages(
            conversation.id,
            query="pipeline",
            user_id=user_id,
            org_id=org_id,
        )
        assert total >= 2
        for msg, rank, headline in results:
            assert "pipeline" in msg.content.lower() or "pipeline" in headline.lower()

    def test_search_no_results(self, service, conversation, user_id, org_id):
        """Search with no matching results."""
        service.send_message(
            conversation.id,
            sender_id=user_id,
            content="Hello world",
            org_id=org_id,
        )
        results, total = service.search_messages(
            conversation.id,
            query="xyznonexistent",
            user_id=user_id,
            org_id=org_id,
        )
        assert total == 0
        assert len(results) == 0


# =============================================================================
# Participant Management
# =============================================================================

class TestParticipants:
    """Test participant add/remove/update."""

    @pytest.fixture
    def conversation(self, service, project_id, user_id, org_id):
        return service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.PROJECT_ROOM,
            created_by=user_id,
            org_id=org_id,
        )

    def test_add_participant(self, service, conversation, user_id, user2_id, org_id):
        """Add a participant to a conversation."""
        participant = service.add_participant(
            conversation.id,
            actor_id=user2_id,
            role=ParticipantRole.MEMBER,
            added_by=user_id,
            org_id=org_id,
        )
        assert participant.actor_id == user2_id
        assert participant.role == ParticipantRole.MEMBER

    def test_list_participants(self, service, conversation, user_id, user2_id, org_id):
        """List participants of a conversation."""
        service.add_participant(
            conversation.id,
            actor_id=user2_id,
            role=ParticipantRole.MEMBER,
            added_by=user_id,
            org_id=org_id,
        )
        participants = service.list_participants(conversation.id, org_id=org_id)
        actor_ids = [p.actor_id for p in participants]
        assert user_id in actor_ids  # creator auto-added
        assert user2_id in actor_ids

    def test_remove_participant(self, service, conversation, user_id, user2_id, org_id):
        """Remove a participant from a conversation."""
        service.add_participant(
            conversation.id,
            actor_id=user2_id,
            role=ParticipantRole.MEMBER,
            added_by=user_id,
            org_id=org_id,
        )
        service.remove_participant(conversation.id, actor_id=user2_id, removed_by=user_id, org_id=org_id)
        participants = service.list_participants(conversation.id, org_id=org_id)
        actor_ids = [p.actor_id for p in participants]
        assert user2_id not in actor_ids

    def test_update_participant_mute(self, service, conversation, user_id, user2_id, org_id):
        """Update a participant's mute setting."""
        service.add_participant(
            conversation.id,
            actor_id=user2_id,
            role=ParticipantRole.MEMBER,
            added_by=user_id,
            org_id=org_id,
        )
        updated = service.update_participant(
            conversation.id,
            user2_id,
            is_muted=True,
            org_id=org_id,
        )
        assert updated.is_muted is True


# =============================================================================
# MCP Handler Tests
# =============================================================================

class TestMCPHandlers:
    """Test MCP handler functions directly (no network)."""

    @pytest.fixture
    def conversation(self, service, project_id, user_id, org_id):
        return service.create_conversation(
            project_id=project_id,
            scope=ConversationScope.PROJECT_ROOM,
            created_by=user_id,
            org_id=org_id,
        )

    def test_mcp_create_conversation(self, service, project_id, org_id):
        """MCP handler: conversations.create"""
        from mcp.handlers.conversation_handlers import handle_create_conversation

        result = handle_create_conversation(service, {
            "project_id": project_id,
            "scope": "project_room",
            "title": "MCP Test Room",
            "user_id": "test-user-001",
            "org_id": org_id,
        })
        assert result["success"] is True
        assert result["conversation"]["scope"] == "project_room"

    def test_mcp_list_conversations(self, service, conversation, project_id, org_id):
        """MCP handler: conversations.list"""
        from mcp.handlers.conversation_handlers import handle_list_conversations

        result = handle_list_conversations(service, {
            "project_id": project_id,
            "user_id": "test-user-001",
            "org_id": org_id,
        })
        assert result["success"] is True
        assert result["total"] >= 1

    def test_mcp_send_message(self, service, conversation, org_id):
        """MCP handler: messages.send"""
        from mcp.handlers.conversation_handlers import handle_send_message

        result = handle_send_message(service, {
            "conversation_id": conversation.id,
            "content": "MCP test message",
            "user_id": "test-user-001",
            "org_id": org_id,
        })
        assert result["success"] is True
        assert result["message"]["content"] == "MCP test message"

    def test_mcp_search_messages(self, service, conversation, org_id):
        """MCP handler: messages.search"""
        from mcp.handlers.conversation_handlers import handle_send_message, handle_search_messages

        handle_send_message(service, {
            "conversation_id": conversation.id,
            "content": "Searching for deployment issues",
            "user_id": "test-user-001",
            "org_id": org_id,
        })

        result = handle_search_messages(service, {
            "conversation_id": conversation.id,
            "query": "deployment",
            "user_id": "test-user-001",
            "org_id": org_id,
        })
        assert result["success"] is True
        assert result["total"] >= 1

    def test_mcp_missing_required_param(self, service):
        """MCP handler returns error for missing required params."""
        from mcp.handlers.conversation_handlers import handle_create_conversation

        result = handle_create_conversation(service, {})
        assert result["success"] is False
        assert "project_id" in result["error"]

    def test_mcp_add_reaction(self, service, conversation, org_id):
        """MCP handler: messages.addReaction"""
        from mcp.handlers.conversation_handlers import handle_send_message, handle_add_reaction

        msg_result = handle_send_message(service, {
            "conversation_id": conversation.id,
            "content": "React to me via MCP",
            "user_id": "test-user-001",
            "org_id": org_id,
        })
        message_id = msg_result["message"]["id"]

        result = handle_add_reaction(service, {
            "message_id": message_id,
            "emoji": "🎉",
            "user_id": "test-user-001",
            "org_id": org_id,
        })
        assert result["success"] is True
        assert result["reaction"]["emoji"] == "🎉"
