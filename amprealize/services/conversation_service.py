"""ConversationService — CRUD operations for the messaging system (AMPREALIZE-570).

Follows the BoardService pattern: PostgresPool-backed, transactional, RLS-aware.
All SQL targets the ``messaging`` schema tables created by the
``20260331_create_messaging_schema`` migration.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from amprealize.conversation_contracts import (
    ActorType,
    Conversation,
    ConversationScope,
    ExternalBinding,
    ExternalProvider,
    Message,
    MessageType,
    NotificationPreference,
    Participant,
    ParticipantRole,
    Reaction,
)
from amprealize.storage.postgres_pool import PostgresPool
from amprealize.utils.dsn import resolve_postgres_dsn

logger = logging.getLogger(__name__)

_MSG_PG_DSN_ENV = "MESSAGING_POSTGRES_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize@localhost:5432/amprealize"  # pragma: allowlist secret

# Edit window: messages can only be edited within this many seconds of creation.
EDIT_WINDOW_SECONDS = 300  # 5 minutes

# Maximum page size for list queries
MAX_PAGE_SIZE = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _parse_jsonb(value: Any, default: Any = None) -> Any:
    """Safely parse a JSONB column which may arrive as str or already-parsed dict."""
    if value is None:
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value) if value else (default if default is not None else {})
    return value


def _set_messaging_search_path(conn: Any, org_id: Optional[str], user_id: Optional[str]) -> None:
    """Set search_path to include 'messaging' schema and RLS context vars."""
    with conn.cursor() as cur:
        cur.execute(
            "SET LOCAL search_path = messaging, board, auth, execution, workflow, research, public"
        )
        if org_id:
            cur.execute("SET LOCAL app.current_org_id = %s", (org_id,))
        else:
            cur.execute("RESET app.current_org_id")
        if user_id:
            cur.execute("SET LOCAL app.current_user_id = %s", (user_id,))
        else:
            cur.execute("RESET app.current_user_id")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConversationServiceError(Exception):
    """Base exception for the conversation service."""


class ConversationNotFoundError(ConversationServiceError):
    """Conversation not found or inaccessible."""


class MessageNotFoundError(ConversationServiceError):
    """Message not found or inaccessible."""


class AccessDeniedError(ConversationServiceError):
    """Caller does not have access to this resource."""


class EditWindowClosedError(ConversationServiceError):
    """Message edit window has expired."""


class DuplicateReactionError(ConversationServiceError):
    """Actor already reacted with this emoji."""


# ---------------------------------------------------------------------------
# Row → domain mappers
# ---------------------------------------------------------------------------


def _row_to_conversation(cols: List[str], row: tuple) -> Conversation:
    d = dict(zip(cols, row))
    return Conversation(
        id=str(d["id"]),
        project_id=d["project_id"],
        org_id=d.get("org_id"),
        scope=ConversationScope(d["scope"]),
        title=d.get("title"),
        created_by=d["created_by"],
        pinned_message_id=str(d["pinned_message_id"]) if d.get("pinned_message_id") else None,
        is_archived=d.get("is_archived", False),
        metadata=_parse_jsonb(d.get("metadata")),
        created_at=d.get("created_at"),
        updated_at=d.get("updated_at"),
    )


def _row_to_participant(cols: List[str], row: tuple) -> Participant:
    d = dict(zip(cols, row))
    return Participant(
        id=str(d["id"]),
        conversation_id=str(d["conversation_id"]),
        actor_id=d["actor_id"],
        actor_type=ActorType(d["actor_type"]),
        role=ParticipantRole(d.get("role", "member")),
        joined_at=d.get("joined_at"),
        left_at=d.get("left_at"),
        last_read_at=d.get("last_read_at"),
        is_muted=d.get("is_muted", False),
        notification_preference=NotificationPreference(d.get("notification_preference", "mentions")),
    )


def _row_to_message(cols: List[str], row: tuple) -> Message:
    d = dict(zip(cols, row))
    return Message(
        id=str(d["id"]),
        conversation_id=str(d["conversation_id"]),
        sender_id=d["sender_id"],
        sender_type=ActorType(d["sender_type"]),
        content=d.get("content"),
        message_type=MessageType(d.get("message_type", "text")),
        structured_payload=_parse_jsonb(d.get("structured_payload"), default=None),
        parent_id=str(d["parent_id"]) if d.get("parent_id") else None,
        run_id=d.get("run_id"),
        behavior_id=d.get("behavior_id"),
        work_item_id=d.get("work_item_id"),
        is_edited=d.get("is_edited", False),
        edited_at=d.get("edited_at"),
        is_deleted=d.get("is_deleted", False),
        deleted_at=d.get("deleted_at"),
        metadata=_parse_jsonb(d.get("metadata")),
        created_at=d.get("created_at"),
    )


def _row_to_reaction(cols: List[str], row: tuple) -> Reaction:
    d = dict(zip(cols, row))
    return Reaction(
        id=str(d["id"]),
        message_id=str(d["message_id"]),
        actor_id=d["actor_id"],
        actor_type=ActorType(d["actor_type"]),
        emoji=d["emoji"],
        created_at=d.get("created_at"),
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ConversationService:
    """CRUD operations for conversations, messages, participants, reactions.

    Follows the same transactional / RLS pattern as BoardService.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        pool: Optional[PostgresPool] = None,
        telemetry: Optional[Any] = None,
        event_hub: Optional[Any] = None,
    ) -> None:
        if pool is None:
            if dsn is None:
                dsn = resolve_postgres_dsn(
                    service="MESSAGING",
                    explicit_dsn=None,
                    env_var=_MSG_PG_DSN_ENV,
                    default_dsn=_DEFAULT_PG_DSN,
                )
            pool = PostgresPool(dsn, schema="messaging")
        self._pool = pool
        self._telemetry = telemetry
        self._event_hub = event_hub

    def _publish_event(self, event_type: str, conversation_id: str, payload: Dict[str, Any]) -> None:
        """Publish an event to the event hub if one is configured."""
        if self._event_hub is not None:
            try:
                self._event_hub.publish(event_type, conversation_id, payload)
            except Exception:
                logger.debug("Failed to publish event %s", event_type, exc_info=True)

    # =========================================================================
    # Conversations
    # =========================================================================

    def create_conversation(
        self,
        *,
        project_id: str,
        scope: ConversationScope = ConversationScope.AGENT_DM,
        title: Optional[str] = None,
        created_by: str,
        participant_ids: Optional[List[str]] = None,
        org_id: Optional[str] = None,
    ) -> Conversation:
        """Create a new conversation and add participants."""
        now = _now()
        conv_id = _new_id()
        participants = participant_ids or []

        # Always include the creator as a participant.
        if created_by not in participants:
            participants = [created_by] + list(participants)

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, created_by)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO messaging.conversations
                        (id, project_id, org_id, scope, title, created_by,
                         metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (conv_id, project_id, org_id, scope.value, title,
                     created_by, json.dumps({}), now, now),
                )
                # Insert participants
                for pid in participants:
                    role = ParticipantRole.OWNER if pid == created_by else ParticipantRole.MEMBER
                    cur.execute(
                        """
                        INSERT INTO messaging.participants
                            (id, conversation_id, actor_id, actor_type, role,
                             joined_at, notification_preference)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (_new_id(), conv_id, pid, ActorType.USER.value, role.value,
                         now, NotificationPreference.MENTIONS.value),
                    )

        self._pool.run_transaction(
            operation="conversation.create",
            service_prefix="messaging",
            metadata={"conversation_id": conv_id, "project_id": project_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        return self.get_conversation(conv_id, org_id=org_id, user_id=created_by)

    def get_or_create_direct_conversation(
        self,
        *,
        project_id: str,
        user_id: str,
        target_participant_id: str,
        target_actor_type: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Tuple[Conversation, bool]:
        """Get or create a 1:1 DM between user_id and target_participant_id.

        Uses SELECT ... FOR UPDATE to prevent duplicate conversations when
        two callers race to create the same DM.

        Returns:
            (conversation, created) — the Conversation and whether it was new.
        """
        actor_type = ActorType(target_actor_type) if target_actor_type else ActorType.USER
        now = _now()
        conv_id = _new_id()
        created_flag: List[bool] = [False]

        def _execute(conn: Any) -> Optional[str]:
            _set_messaging_search_path(conn, org_id, user_id)
            with conn.cursor() as cur:
                # Look for an existing AGENT_DM between these two participants
                # Lock matching rows to prevent racing inserts.
                cur.execute(
                    """
                    SELECT c.id
                    FROM messaging.conversations c
                    WHERE c.project_id = %s
                      AND c.scope = %s
                      AND c.is_archived = false
                      AND EXISTS (
                          SELECT 1 FROM messaging.participants p1
                          WHERE p1.conversation_id = c.id
                            AND p1.actor_id = %s AND p1.left_at IS NULL
                      )
                      AND EXISTS (
                          SELECT 1 FROM messaging.participants p2
                          WHERE p2.conversation_id = c.id
                            AND p2.actor_id = %s AND p2.left_at IS NULL
                      )
                      AND (SELECT count(*) FROM messaging.participants px
                           WHERE px.conversation_id = c.id AND px.left_at IS NULL) = 2
                    FOR UPDATE OF c
                    LIMIT 1
                    """,
                    (project_id, ConversationScope.AGENT_DM.value,
                     user_id, target_participant_id),
                )
                existing = cur.fetchone()
                if existing:
                    return str(existing[0])

                # Create new conversation
                cur.execute(
                    """
                    INSERT INTO messaging.conversations
                        (id, project_id, org_id, scope, title, created_by,
                         metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (conv_id, project_id, org_id,
                     ConversationScope.AGENT_DM.value, None,
                     user_id, json.dumps({}), now, now),
                )
                # Add creator as USER participant
                cur.execute(
                    """
                    INSERT INTO messaging.participants
                        (id, conversation_id, actor_id, actor_type, role,
                         joined_at, notification_preference)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (_new_id(), conv_id, user_id,
                     ActorType.USER.value, ParticipantRole.OWNER.value,
                     now, NotificationPreference.MENTIONS.value),
                )
                # Add target with correct actor_type
                cur.execute(
                    """
                    INSERT INTO messaging.participants
                        (id, conversation_id, actor_id, actor_type, role,
                         joined_at, notification_preference)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (_new_id(), conv_id, target_participant_id,
                     actor_type.value, ParticipantRole.MEMBER.value,
                     now, NotificationPreference.MENTIONS.value),
                )
                created_flag[0] = True
                return conv_id

        result_id = self._pool.run_transaction(
            operation="conversation.get_or_create_direct",
            service_prefix="messaging",
            metadata={
                "project_id": project_id,
                "target": target_participant_id,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        final_id = result_id if result_id else conv_id
        conv = self.get_conversation(final_id, org_id=org_id, user_id=user_id)
        return conv, created_flag[0]

    def get_conversation(
        self,
        conversation_id: str,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Conversation:
        """Get a single conversation by ID, including derived counts."""

        def _query(conn: Any) -> Optional[Conversation]:
            _set_messaging_search_path(conn, org_id, user_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.*,
                           (SELECT count(*) FROM messaging.participants p
                            WHERE p.conversation_id = c.id AND p.left_at IS NULL) AS participant_count
                    FROM messaging.conversations c
                    WHERE c.id = %s AND c.is_archived = false
                    """,
                    (conversation_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                conv = _row_to_conversation(cols, row)
                # Set participant_count from the subquery
                d = dict(zip(cols, row))
                conv.participant_count = d.get("participant_count", 0)
                return conv

        result = self._pool.run_query(
            operation="conversation.get",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )
        if result is None:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
        return result

    def list_conversations(
        self,
        *,
        project_id: str,
        user_id: str,
        org_id: Optional[str] = None,
        scope: Optional[ConversationScope] = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Conversation], int]:
        """List conversations the user participates in within a project."""
        limit = min(limit, MAX_PAGE_SIZE)

        def _query(conn: Any) -> Tuple[List[Conversation], int]:
            _set_messaging_search_path(conn, org_id, user_id)
            with conn.cursor() as cur:
                # Base conditions
                conditions = [
                    "c.project_id = %s",
                    """EXISTS (
                        SELECT 1 FROM messaging.participants p
                        WHERE p.conversation_id = c.id
                          AND p.actor_id = %s
                          AND p.left_at IS NULL
                    )""",
                ]
                params: List[Any] = [project_id, user_id]

                if not include_archived:
                    conditions.append("c.is_archived = false")

                if scope:
                    conditions.append("c.scope = %s")
                    params.append(scope.value)

                where = " AND ".join(conditions)

                # Count
                cur.execute(
                    f"SELECT count(*) FROM messaging.conversations c WHERE {where}",
                    params,
                )
                total = cur.fetchone()[0]

                # Fetch
                cur.execute(
                    f"""
                    SELECT c.*,
                           (SELECT count(*) FROM messaging.participants p
                            WHERE p.conversation_id = c.id AND p.left_at IS NULL) AS participant_count
                    FROM messaging.conversations c
                    WHERE {where}
                    ORDER BY c.updated_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                cols = [d[0] for d in cur.description]
                convs = []
                for row in cur.fetchall():
                    conv = _row_to_conversation(cols, row)
                    d = dict(zip(cols, row))
                    conv.participant_count = d.get("participant_count", 0)
                    convs.append(conv)

                return convs, total

        result = self._pool.run_query(
            operation="conversation.list",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )
        return result

    def archive_conversation(
        self,
        conversation_id: str,
        *,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> None:
        """Soft-archive a conversation (owner/admin only)."""
        self._require_participant_role(conversation_id, user_id, org_id=org_id,
                                       required_roles=[ParticipantRole.OWNER, ParticipantRole.ADMIN])

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, user_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE messaging.conversations
                    SET is_archived = true, updated_at = %s
                    WHERE id = %s
                    """,
                    (_now(), conversation_id),
                )

        self._pool.run_transaction(
            operation="conversation.archive",
            service_prefix="messaging",
            metadata={"conversation_id": conversation_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

    # =========================================================================
    # Participants
    # =========================================================================

    def add_participant(
        self,
        conversation_id: str,
        *,
        actor_id: str,
        actor_type: ActorType = ActorType.USER,
        role: ParticipantRole = ParticipantRole.MEMBER,
        added_by: str,
        org_id: Optional[str] = None,
    ) -> Participant:
        """Add a participant to a conversation."""
        now = _now()
        part_id = _new_id()

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, added_by)
            with conn.cursor() as cur:
                # Check conversation exists
                cur.execute(
                    "SELECT id FROM messaging.conversations WHERE id = %s",
                    (conversation_id,),
                )
                if not cur.fetchone():
                    raise ConversationNotFoundError(f"Conversation {conversation_id} not found")

                # Check not already participating (and not left)
                cur.execute(
                    """
                    SELECT id FROM messaging.participants
                    WHERE conversation_id = %s AND actor_id = %s AND left_at IS NULL
                    """,
                    (conversation_id, actor_id),
                )
                if cur.fetchone():
                    return  # Already a participant, no-op

                cur.execute(
                    """
                    INSERT INTO messaging.participants
                        (id, conversation_id, actor_id, actor_type, role,
                         joined_at, notification_preference)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (part_id, conversation_id, actor_id, actor_type.value, role.value,
                     now, NotificationPreference.MENTIONS.value),
                )

        self._pool.run_transaction(
            operation="participant.add",
            service_prefix="messaging",
            metadata={"conversation_id": conversation_id, "actor_id": actor_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        participant = self.get_participant(conversation_id, actor_id, org_id=org_id, user_id=added_by)
        self._publish_event("participant.joined", conversation_id, {
            "actor_id": actor_id, "role": role.value, "added_by": added_by,
        })
        return participant

    def remove_participant(
        self,
        conversation_id: str,
        *,
        actor_id: str,
        removed_by: str,
        org_id: Optional[str] = None,
    ) -> None:
        """Soft-remove a participant (set left_at)."""
        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, removed_by)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE messaging.participants
                    SET left_at = %s
                    WHERE conversation_id = %s AND actor_id = %s AND left_at IS NULL
                    """,
                    (_now(), conversation_id, actor_id),
                )

        self._pool.run_transaction(
            operation="participant.remove",
            service_prefix="messaging",
            metadata={"conversation_id": conversation_id, "actor_id": actor_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        self._publish_event("participant.left", conversation_id, {
            "actor_id": actor_id, "removed_by": removed_by,
        })

    def get_participant(
        self,
        conversation_id: str,
        actor_id: str,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Participant:
        """Get a single participant record."""
        def _query(conn: Any) -> Optional[Participant]:
            _set_messaging_search_path(conn, org_id, user_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM messaging.participants
                    WHERE conversation_id = %s AND actor_id = %s AND left_at IS NULL
                    """,
                    (conversation_id, actor_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                return _row_to_participant(cols, row)

        result = self._pool.run_query(
            operation="participant.get",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )
        if result is None:
            raise AccessDeniedError(f"Not a participant in conversation {conversation_id}")
        return result

    def list_participants(
        self,
        conversation_id: str,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Participant]:
        """List active participants in a conversation."""
        def _query(conn: Any) -> List[Participant]:
            _set_messaging_search_path(conn, org_id, user_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM messaging.participants
                    WHERE conversation_id = %s AND left_at IS NULL
                    ORDER BY joined_at ASC
                    """,
                    (conversation_id,),
                )
                cols = [d[0] for d in cur.description]
                return [_row_to_participant(cols, row) for row in cur.fetchall()]

        return self._pool.run_query(
            operation="participant.list",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )

    def update_participant(
        self,
        conversation_id: str,
        actor_id: str,
        *,
        is_muted: Optional[bool] = None,
        notification_preference: Optional[NotificationPreference] = None,
        last_read_at: Optional[datetime] = None,
        org_id: Optional[str] = None,
    ) -> Participant:
        """Update participant notification settings or read cursor."""
        sets: List[str] = []
        params: List[Any] = []

        if is_muted is not None:
            sets.append("is_muted = %s")
            params.append(is_muted)
        if notification_preference is not None:
            sets.append("notification_preference = %s")
            params.append(notification_preference.value)
        if last_read_at is not None:
            sets.append("last_read_at = %s")
            params.append(last_read_at)

        if not sets:
            return self.get_participant(conversation_id, actor_id, org_id=org_id, user_id=actor_id)

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, actor_id)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE messaging.participants
                    SET {', '.join(sets)}
                    WHERE conversation_id = %s AND actor_id = %s AND left_at IS NULL
                    """,
                    params + [conversation_id, actor_id],
                )

        self._pool.run_transaction(
            operation="participant.update",
            service_prefix="messaging",
            metadata={"conversation_id": conversation_id, "actor_id": actor_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        return self.get_participant(conversation_id, actor_id, org_id=org_id, user_id=actor_id)

    # =========================================================================
    # Messages
    # =========================================================================

    def send_message(
        self,
        conversation_id: str,
        *,
        sender_id: str,
        sender_type: ActorType = ActorType.USER,
        content: Optional[str] = None,
        message_type: MessageType = MessageType.TEXT,
        structured_payload: Optional[Dict[str, Any]] = None,
        parent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        behavior_id: Optional[str] = None,
        work_item_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        org_id: Optional[str] = None,
    ) -> Message:
        """Send a message to a conversation.

        The sender must be a participant. System messages bypass this check.
        """
        now = _now()
        msg_id = _new_id()

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, sender_id)
            with conn.cursor() as cur:
                # Verify sender is participant (system messages skip)
                if sender_type != ActorType.SYSTEM:
                    cur.execute(
                        """
                        SELECT id FROM messaging.participants
                        WHERE conversation_id = %s AND actor_id = %s AND left_at IS NULL
                        """,
                        (conversation_id, sender_id),
                    )
                    if not cur.fetchone():
                        raise AccessDeniedError(
                            f"Sender {sender_id} is not a participant in conversation {conversation_id}"
                        )

                # Verify parent_id exists if threading
                if parent_id:
                    cur.execute(
                        "SELECT id FROM messaging.messages WHERE id = %s AND conversation_id = %s",
                        (parent_id, conversation_id),
                    )
                    if not cur.fetchone():
                        raise MessageNotFoundError(f"Parent message {parent_id} not found")

                cur.execute(
                    """
                    INSERT INTO messaging.messages
                        (id, conversation_id, sender_id, sender_type, content,
                         message_type, structured_payload, parent_id,
                         run_id, behavior_id, work_item_id,
                         metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (msg_id, conversation_id, sender_id, sender_type.value,
                     content, message_type.value,
                     json.dumps(structured_payload) if structured_payload else None,
                     parent_id, run_id, behavior_id, work_item_id,
                     json.dumps(metadata or {}), now),
                )

                # Touch conversation updated_at
                cur.execute(
                    "UPDATE messaging.conversations SET updated_at = %s WHERE id = %s",
                    (now, conversation_id),
                )

        self._pool.run_transaction(
            operation="message.send",
            service_prefix="messaging",
            metadata={"conversation_id": conversation_id, "message_id": msg_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        msg = self.get_message(msg_id, org_id=org_id, user_id=sender_id)
        self._publish_event("message.new", conversation_id, {
            "conversation_id": conversation_id,
            "message": msg.to_dict(),
        })
        return msg

    def get_message(
        self,
        message_id: str,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Message:
        """Get a single message with its reactions."""
        def _query(conn: Any) -> Optional[Message]:
            _set_messaging_search_path(conn, org_id, user_id)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM messaging.messages WHERE id = %s",
                    (message_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                msg = _row_to_message(cols, row)

                # Load reactions
                cur.execute(
                    """
                    SELECT * FROM messaging.reactions
                    WHERE message_id = %s
                    ORDER BY created_at ASC
                    """,
                    (message_id,),
                )
                rcols = [d[0] for d in cur.description]
                msg.reactions = [_row_to_reaction(rcols, r) for r in cur.fetchall()]

                # Count replies if this is a root message
                cur.execute(
                    "SELECT count(*) FROM messaging.messages WHERE parent_id = %s AND is_deleted = false",
                    (message_id,),
                )
                msg.reply_count = cur.fetchone()[0]

                return msg

        result = self._pool.run_query(
            operation="message.get",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )
        if result is None:
            raise MessageNotFoundError(f"Message {message_id} not found")
        return result

    def list_messages(
        self,
        conversation_id: str,
        *,
        user_id: str,
        org_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        before: Optional[datetime] = None,
        after: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Message], int, bool]:
        """List messages in a conversation.

        Returns:
            (messages, total_count, has_more)
        """
        limit = min(limit, MAX_PAGE_SIZE)

        def _query(conn: Any) -> Tuple[List[Message], int, bool]:
            _set_messaging_search_path(conn, org_id, user_id)
            with conn.cursor() as cur:
                conditions = [
                    "m.conversation_id = %s",
                    "m.is_deleted = false",
                ]
                params: List[Any] = [conversation_id]

                if parent_id is not None:
                    conditions.append("m.parent_id = %s")
                    params.append(parent_id)
                else:
                    # Top-level messages only by default
                    conditions.append("m.parent_id IS NULL")

                if before:
                    conditions.append("m.created_at < %s")
                    params.append(before)

                if after:
                    conditions.append("m.created_at > %s")
                    params.append(after)

                where = " AND ".join(conditions)

                # Count
                cur.execute(
                    f"SELECT count(*) FROM messaging.messages m WHERE {where}",
                    params,
                )
                total = cur.fetchone()[0]

                # Fetch messages
                cur.execute(
                    f"""
                    SELECT m.* FROM messaging.messages m
                    WHERE {where}
                    ORDER BY m.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                cols = [d[0] for d in cur.description]
                messages = [_row_to_message(cols, row) for row in cur.fetchall()]

                # Load reactions for all fetched messages (batch)
                if messages:
                    msg_ids = [m.id for m in messages]
                    placeholders = ",".join(["%s"] * len(msg_ids))
                    cur.execute(
                        f"""
                        SELECT * FROM messaging.reactions
                        WHERE message_id IN ({placeholders})
                        ORDER BY created_at ASC
                        """,
                        msg_ids,
                    )
                    rcols = [d[0] for d in cur.description]
                    reactions_by_msg: Dict[str, List[Reaction]] = {}
                    for row in cur.fetchall():
                        r = _row_to_reaction(rcols, row)
                        reactions_by_msg.setdefault(r.message_id, []).append(r)
                    for m in messages:
                        m.reactions = reactions_by_msg.get(m.id, [])

                    # Load reply counts (batch)
                    cur.execute(
                        f"""
                        SELECT parent_id, count(*) FROM messaging.messages
                        WHERE parent_id IN ({placeholders}) AND is_deleted = false
                        GROUP BY parent_id
                        """,
                        msg_ids,
                    )
                    reply_counts: Dict[str, int] = {}
                    for row in cur.fetchall():
                        reply_counts[str(row[0])] = row[1]
                    for m in messages:
                        m.reply_count = reply_counts.get(m.id, 0)

                has_more = (offset + limit) < total
                return messages, total, has_more

        return self._pool.run_query(
            operation="message.list",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )

    def edit_message(
        self,
        message_id: str,
        *,
        new_content: str,
        editor_id: str,
        org_id: Optional[str] = None,
    ) -> Message:
        """Edit a message within the 5-minute edit window.

        Only the original sender can edit; admins cannot edit on behalf.
        """
        now = _now()

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, editor_id)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sender_id, created_at FROM messaging.messages WHERE id = %s",
                    (message_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise MessageNotFoundError(f"Message {message_id} not found")

                sender_id, created_at = row
                if sender_id != editor_id:
                    raise AccessDeniedError("Only the sender can edit their message")

                if created_at and (now - created_at).total_seconds() > EDIT_WINDOW_SECONDS:
                    raise EditWindowClosedError(
                        f"Edit window ({EDIT_WINDOW_SECONDS}s) has expired"
                    )

                cur.execute(
                    """
                    UPDATE messaging.messages
                    SET content = %s, is_edited = true, edited_at = %s
                    WHERE id = %s
                    """,
                    (new_content, now, message_id),
                )

        self._pool.run_transaction(
            operation="message.edit",
            service_prefix="messaging",
            metadata={"message_id": message_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        msg = self.get_message(message_id, org_id=org_id, user_id=editor_id)
        self._publish_event("message.updated", msg.conversation_id, {
            "conversation_id": msg.conversation_id,
            "message": msg.to_dict(),
        })
        return msg

    def delete_message(
        self,
        message_id: str,
        *,
        deleter_id: str,
        org_id: Optional[str] = None,
    ) -> None:
        """Soft-delete a message. Sender or conversation owner/admin can delete."""
        now = _now()
        _context: Dict[str, str] = {}

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, deleter_id)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sender_id, conversation_id FROM messaging.messages WHERE id = %s",
                    (message_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise MessageNotFoundError(f"Message {message_id} not found")

                sender_id, conv_id = row
                _context["conversation_id"] = conv_id
                if sender_id != deleter_id:
                    # Check if deleter is owner/admin of the conversation
                    cur.execute(
                        """
                        SELECT role FROM messaging.participants
                        WHERE conversation_id = %s AND actor_id = %s AND left_at IS NULL
                        """,
                        (conv_id, deleter_id),
                    )
                    prow = cur.fetchone()
                    if not prow or prow[0] not in ("owner", "admin"):
                        raise AccessDeniedError("Only the sender or conversation admin can delete messages")

                cur.execute(
                    """
                    UPDATE messaging.messages
                    SET is_deleted = true, deleted_at = %s
                    WHERE id = %s
                    """,
                    (now, message_id),
                )

        self._pool.run_transaction(
            operation="message.delete",
            service_prefix="messaging",
            metadata={"message_id": message_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        if _context.get("conversation_id"):
            self._publish_event("message.deleted", _context["conversation_id"], {
                "conversation_id": _context["conversation_id"],
                "message": {"id": message_id, "is_deleted": True, "content": "", "deleted_by": deleter_id},
            })

    def pin_message(
        self,
        conversation_id: str,
        message_id: str,
        *,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> None:
        """Pin a message in a conversation (owner/admin only)."""
        self._require_participant_role(conversation_id, user_id, org_id=org_id,
                                       required_roles=[ParticipantRole.OWNER, ParticipantRole.ADMIN])

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, user_id)
            with conn.cursor() as cur:
                # Verify msg exists in this conversation
                cur.execute(
                    "SELECT id FROM messaging.messages WHERE id = %s AND conversation_id = %s",
                    (message_id, conversation_id),
                )
                if not cur.fetchone():
                    raise MessageNotFoundError(f"Message {message_id} not found in conversation")
                cur.execute(
                    """
                    UPDATE messaging.conversations
                    SET pinned_message_id = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (message_id, _now(), conversation_id),
                )

        self._pool.run_transaction(
            operation="message.pin",
            service_prefix="messaging",
            metadata={"conversation_id": conversation_id, "message_id": message_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        self._publish_event("pin.updated", conversation_id, {
            "message_id": message_id, "pinned": True, "by": user_id,
        })

    def unpin_message(
        self,
        conversation_id: str,
        *,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> None:
        """Unpin the current pinned message in a conversation."""
        self._require_participant_role(conversation_id, user_id, org_id=org_id,
                                       required_roles=[ParticipantRole.OWNER, ParticipantRole.ADMIN])

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, user_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE messaging.conversations
                    SET pinned_message_id = NULL, updated_at = %s
                    WHERE id = %s
                    """,
                    (_now(), conversation_id),
                )

        self._pool.run_transaction(
            operation="message.unpin",
            service_prefix="messaging",
            metadata={"conversation_id": conversation_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        self._publish_event("pin.updated", conversation_id, {
            "pinned": False, "by": user_id,
        })

    # =========================================================================
    # Reactions
    # =========================================================================

    def add_reaction(
        self,
        message_id: str,
        *,
        actor_id: str,
        actor_type: ActorType = ActorType.USER,
        emoji: str,
        org_id: Optional[str] = None,
    ) -> Reaction:
        """Add an emoji reaction to a message."""
        now = _now()
        reaction_id = _new_id()
        _context: Dict[str, str] = {}

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, actor_id)
            with conn.cursor() as cur:
                # Check message exists
                cur.execute(
                    "SELECT conversation_id FROM messaging.messages WHERE id = %s AND is_deleted = false",
                    (message_id,),
                )
                mrow = cur.fetchone()
                if not mrow:
                    raise MessageNotFoundError(f"Message {message_id} not found")
                _context["conversation_id"] = str(mrow[0])

                # Check for duplicate
                cur.execute(
                    """
                    SELECT id FROM messaging.reactions
                    WHERE message_id = %s AND actor_id = %s AND emoji = %s
                    """,
                    (message_id, actor_id, emoji),
                )
                if cur.fetchone():
                    raise DuplicateReactionError(
                        f"Actor {actor_id} already reacted with {emoji}"
                    )

                cur.execute(
                    """
                    INSERT INTO messaging.reactions
                        (id, message_id, actor_id, actor_type, emoji, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (reaction_id, message_id, actor_id, actor_type.value, emoji, now),
                )

        self._pool.run_transaction(
            operation="reaction.add",
            service_prefix="messaging",
            metadata={"message_id": message_id, "emoji": emoji},
            executor=_execute,
            telemetry=self._telemetry,
        )
        reaction = Reaction(
            id=reaction_id,
            message_id=message_id,
            actor_id=actor_id,
            actor_type=actor_type,
            emoji=emoji,
            created_at=now,
        )
        if _context.get("conversation_id"):
            self._publish_event("reaction.added", _context["conversation_id"], {
                "conversation_id": _context["conversation_id"],
                "message_id": message_id,
                "reaction": reaction.to_dict(),
            })
        return reaction

    def remove_reaction(
        self,
        message_id: str,
        *,
        actor_id: str,
        emoji: str,
        org_id: Optional[str] = None,
    ) -> None:
        """Remove an emoji reaction from a message."""
        _context: Dict[str, str] = {}

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, actor_id)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT conversation_id FROM messaging.messages WHERE id = %s",
                    (message_id,),
                )
                mrow = cur.fetchone()
                if mrow:
                    _context["conversation_id"] = str(mrow[0])
                cur.execute(
                    """
                    DELETE FROM messaging.reactions
                    WHERE message_id = %s AND actor_id = %s AND emoji = %s
                    """,
                    (message_id, actor_id, emoji),
                )

        self._pool.run_transaction(
            operation="reaction.remove",
            service_prefix="messaging",
            metadata={"message_id": message_id, "emoji": emoji},
            executor=_execute,
            telemetry=self._telemetry,
        )
        if _context.get("conversation_id"):
            self._publish_event("reaction.removed", _context["conversation_id"], {
                "conversation_id": _context["conversation_id"],
                "message_id": message_id,
                "reaction": {"actor_id": actor_id, "emoji": emoji},
            })

    # =========================================================================
    # Search
    # =========================================================================

    def search_messages(
        self,
        conversation_id: str,
        *,
        query: str,
        user_id: str,
        org_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Tuple[Message, float, Optional[str]]], int]:
        """Full-text search within a conversation.

        Uses the search_vector GIN index for fast phrase-based search.

        Returns:
            (list of (message, rank, headline), total_count)
        """
        limit = min(limit, MAX_PAGE_SIZE)

        def _query(conn: Any) -> Tuple[List[Tuple[Message, float, Optional[str]]], int]:
            _set_messaging_search_path(conn, org_id, user_id)
            with conn.cursor() as cur:
                tsquery = "plainto_tsquery('english', %s)"

                # Count
                cur.execute(
                    f"""
                    SELECT count(*)
                    FROM messaging.messages m
                    WHERE m.conversation_id = %s
                      AND m.is_deleted = false
                      AND m.search_vector @@ {tsquery}
                    """,
                    (conversation_id, query),
                )
                total = cur.fetchone()[0]

                # Search with ranking
                cur.execute(
                    f"""
                    SELECT m.*,
                           ts_rank(m.search_vector, {tsquery}) AS rank,
                           ts_headline('english', m.content, {tsquery},
                                       'MaxWords=35, MinWords=15, MaxFragments=3') AS headline
                    FROM messaging.messages m
                    WHERE m.conversation_id = %s
                      AND m.is_deleted = false
                      AND m.search_vector @@ {tsquery}
                    ORDER BY rank DESC, m.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (query, query, conversation_id, query, limit, offset),
                )
                cols = [d[0] for d in cur.description]
                results = []
                for row in cur.fetchall():
                    d = dict(zip(cols, row))
                    msg = _row_to_message(cols, row)
                    rank = d.get("rank", 0.0)
                    headline = d.get("headline")
                    results.append((msg, rank, headline))

                return results, total

        return self._pool.run_query(
            operation="message.search",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )

    # =========================================================================
    # External Bindings (Slack / Teams / Discord bridge)
    # =========================================================================

    def create_external_binding(
        self,
        *,
        conversation_id: str,
        provider: ExternalProvider,
        external_channel_id: str,
        external_workspace_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        bound_by: str,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> ExternalBinding:
        """Bind a conversation to an external channel (e.g., Slack channel)."""
        binding_id = _new_id()
        now = _now()

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, user_id)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO messaging.external_bindings
                    (id, conversation_id, provider, external_channel_id,
                     external_workspace_id, config, is_active, bound_at, bound_by)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s)
                ON CONFLICT (conversation_id, provider, external_channel_id)
                DO UPDATE SET is_active = TRUE, config = EXCLUDED.config,
                              bound_at = EXCLUDED.bound_at, bound_by = EXCLUDED.bound_by
                """,
                (
                    binding_id,
                    conversation_id,
                    provider.value,
                    external_channel_id,
                    external_workspace_id,
                    json.dumps(config or {}),
                    now,
                    bound_by,
                ),
            )
            conn.commit()

        self._pool.run_transaction(
            operation="external_binding.create",
            service_prefix="messaging",
            executor=_execute,
            telemetry=self._telemetry,
        )

        return ExternalBinding(
            id=binding_id,
            conversation_id=conversation_id,
            provider=provider,
            external_channel_id=external_channel_id,
            external_workspace_id=external_workspace_id,
            config=config or {},
            is_active=True,
            bound_at=now,
            bound_by=bound_by,
        )

    def get_external_binding(
        self,
        *,
        provider: ExternalProvider,
        external_channel_id: str,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[ExternalBinding]:
        """Look up an active external binding by provider + channel ID."""

        def _query(conn: Any) -> Optional[ExternalBinding]:
            _set_messaging_search_path(conn, org_id, user_id)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, conversation_id, provider, external_channel_id,
                       external_workspace_id, config, is_active, bound_at, bound_by
                FROM messaging.external_bindings
                WHERE provider = %s AND external_channel_id = %s AND is_active = TRUE
                LIMIT 1
                """,
                (provider.value, external_channel_id),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return ExternalBinding(
                id=row[0],
                conversation_id=row[1],
                provider=ExternalProvider(row[2]),
                external_channel_id=row[3],
                external_workspace_id=row[4],
                config=_parse_jsonb(row[5], {}),
                is_active=row[6],
                bound_at=row[7],
                bound_by=row[8],
            )

        return self._pool.run_query(
            operation="external_binding.get",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )

    def list_external_bindings(
        self,
        conversation_id: str,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[ExternalBinding]:
        """List all active external bindings for a conversation."""

        def _query(conn: Any) -> List[ExternalBinding]:
            _set_messaging_search_path(conn, org_id, user_id)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, conversation_id, provider, external_channel_id,
                       external_workspace_id, config, is_active, bound_at, bound_by
                FROM messaging.external_bindings
                WHERE conversation_id = %s AND is_active = TRUE
                ORDER BY bound_at
                """,
                (conversation_id,),
            )
            results = []
            for row in cur.fetchall():
                results.append(ExternalBinding(
                    id=row[0],
                    conversation_id=row[1],
                    provider=ExternalProvider(row[2]),
                    external_channel_id=row[3],
                    external_workspace_id=row[4],
                    config=_parse_jsonb(row[5], {}),
                    is_active=row[6],
                    bound_at=row[7],
                    bound_by=row[8],
                ))
            return results

        return self._pool.run_query(
            operation="external_binding.list",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )

    def list_all_active_bindings(
        self,
        provider: ExternalProvider,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[ExternalBinding]:
        """List all active external bindings for a given provider (across all conversations).

        Used at startup to discover which conversations need outbound relay subscriptions.
        """

        def _query(conn: Any) -> List[ExternalBinding]:
            _set_messaging_search_path(conn, org_id, user_id)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, conversation_id, provider, external_channel_id,
                       external_workspace_id, config, is_active, bound_at, bound_by
                FROM messaging.external_bindings
                WHERE provider = %s AND is_active = TRUE
                ORDER BY bound_at
                """,
                (provider.value,),
            )
            results = []
            for row in cur.fetchall():
                results.append(ExternalBinding(
                    id=row[0],
                    conversation_id=row[1],
                    provider=ExternalProvider(row[2]),
                    external_channel_id=row[3],
                    external_workspace_id=row[4],
                    config=_parse_jsonb(row[5], {}),
                    is_active=row[6],
                    bound_at=row[7],
                    bound_by=row[8],
                ))
            return results

        return self._pool.run_query(
            operation="external_binding.list_all",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )

    def deactivate_external_binding(
        self,
        binding_id: str,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Deactivate an external binding (soft delete)."""

        def _execute(conn: Any) -> None:
            _set_messaging_search_path(conn, org_id, user_id)
            cur = conn.cursor()
            cur.execute(
                "UPDATE messaging.external_bindings SET is_active = FALSE WHERE id = %s",
                (binding_id,),
            )
            conn.commit()

        self._pool.run_transaction(
            operation="external_binding.deactivate",
            service_prefix="messaging",
            executor=_execute,
            telemetry=self._telemetry,
        )

    def get_binding_by_conversation(
        self,
        conversation_id: str,
        provider: ExternalProvider,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[ExternalBinding]:
        """Look up an active binding for a specific conversation + provider."""

        def _query(conn: Any) -> Optional[ExternalBinding]:
            _set_messaging_search_path(conn, org_id, user_id)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, conversation_id, provider, external_channel_id,
                       external_workspace_id, config, is_active, bound_at, bound_by
                FROM messaging.external_bindings
                WHERE conversation_id = %s AND provider = %s AND is_active = TRUE
                LIMIT 1
                """,
                (conversation_id, provider.value),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return ExternalBinding(
                id=row[0],
                conversation_id=row[1],
                provider=ExternalProvider(row[2]),
                external_channel_id=row[3],
                external_workspace_id=row[4],
                config=_parse_jsonb(row[5], {}),
                is_active=row[6],
                bound_at=row[7],
                bound_by=row[8],
            )

        return self._pool.run_query(
            operation="external_binding.get_by_conversation",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )

    # =========================================================================
    # Retention & archival (AMPREALIZE-609, Phase 8)
    # =========================================================================

    def archive_messages_older_than(
        self,
        archive_after_days: int,
        *,
        batch_size: int = 500,
        org_id: Optional[str] = None,
    ) -> int:
        """Mark messages older than *archive_after_days* as archived.

        Respects compliance hold on conversations (metadata->>compliance_hold = 'true').
        Returns the number of messages archived.
        """

        def _execute(conn: Any) -> int:
            _set_messaging_search_path(conn, org_id, None)
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE messaging.messages m
                SET archived_at = NOW()
                WHERE m.archived_at IS NULL
                  AND m.is_deleted = FALSE
                  AND m.created_at < NOW() - (%s || ' days')::INTERVAL
                  AND NOT EXISTS (
                      SELECT 1 FROM messaging.conversations c
                      WHERE c.id = m.conversation_id
                        AND (c.metadata->>'compliance_hold')::boolean IS TRUE
                  )
                RETURNING m.id
                """,
                (str(archive_after_days),),
            )
            rows = cur.fetchall()
            count = len(rows)
            conn.commit()
            return count

        return self._pool.run_transaction(
            operation="retention.archive_messages",
            service_prefix="messaging",
            executor=_execute,
            telemetry=self._telemetry,
        )

    def list_cold_eligible_conversations(
        self,
        cold_after_days: int,
        *,
        batch_size: int = 100,
        org_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List conversations where all messages are archived and older than *cold_after_days*.

        Returns lightweight conversation dicts (id, project_id, archived_at) suitable
        for cold export processing.
        """

        def _query(conn: Any) -> List[Dict[str, Any]]:
            _set_messaging_search_path(conn, org_id, None)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT c.id, c.project_id, c.title, c.scope,
                       MAX(m.archived_at) AS last_archived_at,
                       COUNT(m.id) AS message_count
                FROM messaging.conversations c
                JOIN messaging.messages m ON m.conversation_id = c.id
                WHERE m.archived_at IS NOT NULL
                  AND m.archived_at < NOW() - (%s || ' days')::INTERVAL
                  AND NOT EXISTS (
                      SELECT 1 FROM messaging.messages m2
                      WHERE m2.conversation_id = c.id
                        AND m2.archived_at IS NULL
                        AND m2.is_deleted = FALSE
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM messaging.conversations c2
                      WHERE c2.id = c.id
                        AND (c2.metadata->>'compliance_hold')::boolean IS TRUE
                  )
                GROUP BY c.id, c.project_id, c.title, c.scope
                ORDER BY last_archived_at ASC
                LIMIT %s
                """,
                (str(cold_after_days), batch_size),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

        return self._pool.run_query(
            operation="retention.list_cold_eligible",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )

    def get_conversation_messages_for_export(
        self,
        conversation_id: str,
        *,
        org_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch all messages for a conversation as plain dicts (for cold export JSONL)."""

        def _query(conn: Any) -> List[Dict[str, Any]]:
            _set_messaging_search_path(conn, org_id, None)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, conversation_id, sender_id, sender_type, content,
                       message_type, structured_payload, parent_id, run_id,
                       behavior_id, work_item_id, is_edited, edited_at,
                       is_deleted, deleted_at, metadata, created_at, archived_at
                FROM messaging.messages
                WHERE conversation_id = %s
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            )
            cols = [desc[0] for desc in cur.description]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                # Serialize datetimes to ISO strings for JSON export
                for k in ("edited_at", "deleted_at", "created_at", "archived_at"):
                    if d.get(k) is not None:
                        d[k] = d[k].isoformat()
                rows.append(d)
            return rows

        return self._pool.run_query(
            operation="retention.get_messages_for_export",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )

    def delete_conversation_for_cold_export(
        self,
        conversation_id: str,
        *,
        org_id: Optional[str] = None,
    ) -> int:
        """Hard-delete a conversation and all its messages after cold export.

        This is irreversible — only call after the S3 export is confirmed.
        Returns the number of messages deleted.
        """

        def _execute(conn: Any) -> int:
            _set_messaging_search_path(conn, org_id, None)
            cur = conn.cursor()
            # Delete messages first (FK cascade would handle this too, but be explicit)
            cur.execute(
                "DELETE FROM messaging.messages WHERE conversation_id = %s RETURNING id",
                (conversation_id,),
            )
            count = len(cur.fetchall())
            cur.execute(
                "DELETE FROM messaging.conversations WHERE id = %s",
                (conversation_id,),
            )
            conn.commit()
            return count

        return self._pool.run_transaction(
            operation="retention.delete_cold_conversation",
            service_prefix="messaging",
            executor=_execute,
            telemetry=self._telemetry,
        )

    def get_conversation_stats(
        self,
        *,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return aggregated conversation analytics (AMPREALIZE-612).

        Includes: total conversations, total messages, active conversations
        (messages in last 7 days), messages by type, messages by sender type,
        and archive rate.
        """

        def _query(conn: Any) -> Dict[str, Any]:
            _set_messaging_search_path(conn, org_id, None)
            cur = conn.cursor()

            project_filter = "AND c.project_id = %s" if project_id else ""
            params: tuple = (project_id,) if project_id else ()

            cur.execute(
                f"""
                SELECT
                    COUNT(DISTINCT c.id) AS total_conversations,
                    COUNT(DISTINCT CASE WHEN c.is_archived = FALSE THEN c.id END) AS active_conversations,
                    COUNT(DISTINCT CASE WHEN c.is_archived = TRUE THEN c.id END) AS archived_conversations,
                    COUNT(m.id) AS total_messages,
                    COUNT(CASE WHEN m.archived_at IS NOT NULL THEN 1 END) AS archived_messages,
                    COUNT(CASE WHEN m.created_at >= NOW() - INTERVAL '7 days' THEN 1 END) AS messages_last_7_days,
                    COUNT(CASE WHEN m.created_at >= NOW() - INTERVAL '24 hours' THEN 1 END) AS messages_last_24h,
                    COUNT(CASE WHEN m.sender_type = 'agent' THEN 1 END) AS agent_messages,
                    COUNT(CASE WHEN m.sender_type = 'user' THEN 1 END) AS user_messages,
                    COUNT(CASE WHEN m.sender_type = 'system' THEN 1 END) AS system_messages
                FROM messaging.conversations c
                LEFT JOIN messaging.messages m
                    ON m.conversation_id = c.id AND m.is_deleted = FALSE
                WHERE 1=1 {project_filter}
                """,
                params,
            )
            row = cur.fetchone()
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row)) if row else {}

        return self._pool.run_query(
            operation="analytics.conversation_stats",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )

    def get_project_retention_config(
        self,
        project_id: str,
        *,
        org_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch per-project retention override from projects.settings JSONB.

        Returns a dict with retention_days (int) or None if no project found.
        """

        def _query(conn: Any) -> Optional[Dict[str, Any]]:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, settings->>'retention_days' AS retention_days
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (project_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "project_id": row[0],
                "retention_days": int(row[1]) if row[1] else None,
            }

        return self._pool.run_query(
            operation="retention.get_project_config",
            service_prefix="messaging",
            executor=_query,
            telemetry=self._telemetry,
        )

    def set_project_retention_config(
        self,
        project_id: str,
        retention_days: int,
        *,
        org_id: Optional[str] = None,
    ) -> None:
        """Set per-project retention override in projects.settings JSONB."""

        def _execute(conn: Any) -> None:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE projects
                SET settings = COALESCE(settings, '{}'::jsonb) ||
                               jsonb_build_object('retention_days', %s::text)
                WHERE id = %s
                """,
                (str(retention_days), project_id),
            )
            conn.commit()

        self._pool.run_transaction(
            operation="retention.set_project_config",
            service_prefix="messaging",
            executor=_execute,
            telemetry=self._telemetry,
        )

    # =========================================================================
    # Access control helpers
    # =========================================================================

    def _require_participant_role(
        self,
        conversation_id: str,
        user_id: str,
        *,
        org_id: Optional[str] = None,
        required_roles: Optional[List[ParticipantRole]] = None,
    ) -> Participant:
        """Verify the user is a participant with one of the required roles."""
        participant = self.get_participant(
            conversation_id, user_id, org_id=org_id, user_id=user_id
        )
        if required_roles and participant.role not in required_roles:
            raise AccessDeniedError(
                f"User {user_id} has role '{participant.role.value}' but needs "
                f"one of {[r.value for r in required_roles]}"
            )
        return participant
