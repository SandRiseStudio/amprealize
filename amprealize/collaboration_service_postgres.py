"""PostgreSQL-backed Collaboration Service for persistent workspace storage.

This service extends the in-memory CollaborationService with PostgreSQL persistence
for workspaces, documents, members, and real-time collaboration state.

Behaviors referenced:
- behavior_migrate_postgres_schema: PostgreSQL migration pattern
- behavior_use_raze_for_logging: Structured logging via Raze
- behavior_align_storage_layers: Consistent storage interface

Usage:
    from amprealize.collaboration_service_postgres import PostgresCollaborationService

    service = PostgresCollaborationService(
        dsn="postgresql://user:pass@host:5432/amprealize_collaboration"
    )

    # Create workspace
    workspace = service.create_workspace(CreateWorkspaceRequest(
        name="Team Workspace",
        owner_id="user-123"
    ))

    # Create document
    doc = service.create_document(CreateDocumentRequest(
        workspace_id=workspace.workspace_id,
        title="README.md",
        content="# Hello",
        created_by="user-123"
    ))

    # Update cursor position (for presence)
    service.update_cursor(doc.document_id, "user-123", line=10, column=5)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from psycopg2 import extras

from .collaboration_contracts import (
    WorkspaceStatus,
    CollaborationRole,
    EditOperationType,
    Workspace,
    WorkspaceMember,
    Document,
    EditOperation,
    Comment,
    ActivityLog,
    CreateWorkspaceRequest,
    InviteUserRequest,
    CreateDocumentRequest,
    RealTimeEditRequest,
    CommentRequest,
    CollaborationMetrics,
    ConflictResolution,
)
from .collaboration_service import CollaborationService
from .storage.postgres_pool import PostgresPool
from .storage.redis_cache import get_cache
from .telemetry import TelemetryClient


logger = logging.getLogger(__name__)


# ============================================================================
# Additional Data Models for PostgreSQL
# ============================================================================

class CursorPosition:
    """Real-time cursor position for presence awareness."""

    def __init__(
        self,
        cursor_id: str,
        document_id: str,
        user_id: str,
        position_line: int,
        position_column: int,
        selection_start_line: Optional[int] = None,
        selection_start_column: Optional[int] = None,
        selection_end_line: Optional[int] = None,
        selection_end_column: Optional[int] = None,
        color: Optional[str] = None,
        last_updated: Optional[datetime] = None,
    ):
        self.cursor_id = cursor_id
        self.document_id = document_id
        self.user_id = user_id
        self.position_line = position_line
        self.position_column = position_column
        self.selection_start_line = selection_start_line
        self.selection_start_column = selection_start_column
        self.selection_end_line = selection_end_line
        self.selection_end_column = selection_end_column
        self.color = color
        self.last_updated = last_updated or datetime.now(timezone.utc)


class DocumentVersion:
    """Version history entry for a document."""

    def __init__(
        self,
        version_id: str,
        document_id: str,
        version_number: int,
        content: str,
        edited_by: str,
        edit_summary: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ):
        self.version_id = version_id
        self.document_id = document_id
        self.version_number = version_number
        self.content = content
        self.edited_by = edited_by
        self.edit_summary = edit_summary
        self.created_at = created_at or datetime.now(timezone.utc)


class PendingEdit:
    """Queued edit for conflict resolution."""

    def __init__(
        self,
        edit_id: str,
        document_id: str,
        user_id: str,
        operation: str,
        position_start: int,
        position_end: Optional[int],
        content: Optional[str],
        base_version: int,
        status: str = "pending",
        conflict_resolution: Optional[str] = None,
        created_at: Optional[datetime] = None,
        applied_at: Optional[datetime] = None,
    ):
        self.edit_id = edit_id
        self.document_id = document_id
        self.user_id = user_id
        self.operation = operation
        self.position_start = position_start
        self.position_end = position_end
        self.content = content
        self.base_version = base_version
        self.status = status
        self.conflict_resolution = conflict_resolution
        self.created_at = created_at or datetime.now(timezone.utc)
        self.applied_at = applied_at


# ============================================================================
# PostgreSQL Collaboration Service
# ============================================================================

class PostgresCollaborationService(CollaborationService):
    """PostgreSQL-backed CollaborationService with persistent storage.

    Extends the base CollaborationService to persist:
    - Workspaces and workspace settings
    - Members with permissions
    - Documents with version history
    - Real-time cursor positions for presence
    - Pending edits for conflict resolution
    - Collaboration events for activity stream
    """

    CACHE_SERVICE = "collaboration"
    CACHE_TTL = 60  # 1 minute (shorter for real-time data)
    CURSOR_STALE_MINUTES = 5  # Cleanup cursors older than this

    # Color palette for user cursors
    CURSOR_COLORS = [
        "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
        "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9",
    ]

    def __init__(
        self,
        dsn: str,
        *,
        telemetry: Optional[TelemetryClient] = None,
    ) -> None:
        """Initialize PostgreSQL-backed CollaborationService.

        Args:
            dsn: PostgreSQL connection string
            telemetry: Optional TelemetryClient
        """
        super().__init__(telemetry=telemetry)
        self._pool = PostgresPool(dsn=dsn)
        self._logger = logging.getLogger("amprealize.collaboration_service_postgres")
        self._ensure_schema()
        self._logger.info("PostgresCollaborationService initialized")

    def _ensure_schema(self) -> None:
        """Ensure database schema exists."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'collaboration_workspaces'
                    )
                """)
                if not cur.fetchone()[0]:
                    self._logger.warning(
                        "Collaboration tables not found. Run migration 021_create_collaboration_service.sql"
                    )

    # ========================================================================
    # Workspace Operations (Override parent with persistence)
    # ========================================================================

    def create_workspace(self, request: CreateWorkspaceRequest) -> Workspace:
        """Create a new collaborative workspace with PostgreSQL persistence."""
        workspace_id = f"ws_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        workspace_type = "shared" if getattr(request, "is_shared", False) else "private"

        def _execute(conn):
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Create workspace
                cur.execute("""
                    INSERT INTO collaboration_workspaces (
                        workspace_id, name, description, owner_id, workspace_type,
                        settings, is_active, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (
                    workspace_id,
                    request.name,
                    request.description,
                    request.owner_id,
                    workspace_type,
                    json.dumps(request.settings or {}),
                    True,
                    now,
                    now,
                ))
                ws_row = cur.fetchone()

                # Add owner as member
                member_id = f"mem_{uuid4().hex[:12]}"
                cur.execute("""
                    INSERT INTO workspace_members (
                        member_id, workspace_id, user_id, role, permissions,
                        joined_at, last_active_at, is_active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    member_id,
                    workspace_id,
                    request.owner_id,
                    "owner",
                    json.dumps(["read", "write", "admin", "invite"]),
                    now,
                    now,
                    True,
                ))

                # Log event
                event_id = f"evt_{uuid4().hex[:12]}"
                cur.execute("""
                    INSERT INTO collaboration_events (
                        event_id, workspace_id, user_id, event_type, event_data, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    event_id,
                    workspace_id,
                    request.owner_id,
                    "workspace_created",
                    json.dumps({"name": request.name}),
                    now,
                ))

                return ws_row

        row = self._pool.run_transaction("create_workspace", executor=_execute)
        get_cache().invalidate_service(self.CACHE_SERVICE)

        workspace = self._row_to_workspace(row)

        self._emit_telemetry("workspace_created", {
            "workspace_id": workspace_id,
            "name": request.name,
            "owner_id": request.owner_id,
        })

        return workspace

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        """Get workspace by ID with caching."""
        cache = get_cache()
        cache_key = f"workspace:{workspace_id}"

        cached = cache.get(cache_key)
        if cached:
            return Workspace(**cached)

        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM collaboration_workspaces WHERE workspace_id = %s",
                    (workspace_id,)
                )
                row = cur.fetchone()

        if not row:
            return None

        workspace = self._row_to_workspace(row)
        # Cache the workspace data
        cache.set(cache_key, {
            "workspace_id": workspace.workspace_id,
            "name": workspace.name,
            "description": workspace.description,
            "owner_id": workspace.owner_id,
            "status": workspace.status.value if hasattr(workspace.status, "value") else workspace.status,
            "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
            "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
            "settings": workspace.settings,
            "tags": workspace.tags,
            "member_count": workspace.member_count,
        }, ttl=self.CACHE_TTL)
        return workspace

    def get_workspace_members(self, workspace_id: str) -> List[WorkspaceMember]:
        """Get all members of a workspace."""
        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM workspace_members
                    WHERE workspace_id = %s AND is_active = true
                    ORDER BY joined_at
                """, (workspace_id,))
                rows = cur.fetchall()

        return [self._row_to_member(row) for row in rows]

    def invite_user(self, request: InviteUserRequest) -> WorkspaceMember:
        """Invite user to workspace with PostgreSQL persistence."""
        member_id = f"mem_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        def _execute(conn):
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Check workspace exists
                cur.execute(
                    "SELECT workspace_id FROM collaboration_workspaces WHERE workspace_id = %s",
                    (request.workspace_id,)
                )
                if not cur.fetchone():
                    raise ValueError(f"Workspace {request.workspace_id} not found")

                # Check if already a member
                cur.execute("""
                    SELECT member_id FROM workspace_members
                    WHERE workspace_id = %s AND user_id = %s AND is_active = true
                """, (request.workspace_id, request.user_id))
                if cur.fetchone():
                    raise ValueError(f"User {request.user_id} is already a member")

                # Add member
                cur.execute("""
                    INSERT INTO workspace_members (
                        member_id, workspace_id, user_id, role, permissions,
                        joined_at, is_active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (
                    member_id,
                    request.workspace_id,
                    request.user_id,
                    request.role.value if hasattr(request.role, "value") else request.role,
                    json.dumps(request.permissions or []),
                    now,
                    True,
                ))
                member_row = cur.fetchone()

                # Log event
                event_id = f"evt_{uuid4().hex[:12]}"
                cur.execute("""
                    INSERT INTO collaboration_events (
                        event_id, workspace_id, user_id, event_type, event_data, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    event_id,
                    request.workspace_id,
                    request.invited_by,
                    "user_invited",
                    json.dumps({
                        "invited_user": request.user_id,
                        "role": request.role.value if hasattr(request.role, "value") else request.role,
                    }),
                    now,
                ))

                return member_row

        row = self._pool.run_transaction("invite_user", executor=_execute)
        get_cache().invalidate_service(self.CACHE_SERVICE)

        return self._row_to_member(row)

    # ========================================================================
    # Document Operations
    # ========================================================================

    def create_document(self, request: CreateDocumentRequest) -> Document:
        """Create a new document with PostgreSQL persistence."""
        document_id = f"doc_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        def _execute(conn):
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Check workspace exists
                cur.execute(
                    "SELECT workspace_id FROM collaboration_workspaces WHERE workspace_id = %s",
                    (request.workspace_id,)
                )
                if not cur.fetchone():
                    raise ValueError(f"Workspace {request.workspace_id} not found")

                # Create document
                cur.execute("""
                    INSERT INTO collaboration_documents (
                        document_id, workspace_id, title, content, document_type,
                        version, created_by, metadata, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (
                    document_id,
                    request.workspace_id,
                    request.title,
                    request.content or "",
                    request.document_type or "text",
                    1,
                    request.created_by,
                    json.dumps(request.metadata or {}),
                    now,
                    now,
                ))
                doc_row = cur.fetchone()

                # Create initial version
                version_id = f"ver_{uuid4().hex[:12]}"
                cur.execute("""
                    INSERT INTO document_versions (
                        version_id, document_id, version_number, content,
                        edited_by, edit_summary, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    version_id,
                    document_id,
                    1,
                    request.content or "",
                    request.created_by,
                    "Initial version",
                    now,
                ))

                # Log event
                event_id = f"evt_{uuid4().hex[:12]}"
                cur.execute("""
                    INSERT INTO collaboration_events (
                        event_id, workspace_id, document_id, user_id,
                        event_type, event_data, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    event_id,
                    request.workspace_id,
                    document_id,
                    request.created_by,
                    "document_created",
                    json.dumps({"title": request.title}),
                    now,
                ))

                return doc_row

        row = self._pool.run_transaction("create_document", executor=_execute)
        get_cache().invalidate_service(self.CACHE_SERVICE)

        document = self._row_to_document(row)

        self._emit_telemetry("document_created", {
            "document_id": document_id,
            "workspace_id": request.workspace_id,
            "title": request.title,
        })

        return document

    def get_document(self, document_id: str) -> Optional[Document]:
        """Get document by ID with caching."""
        cache = get_cache()
        cache_key = f"document:{document_id}"

        cached = cache.get(cache_key)
        if cached:
            return Document(**cached)

        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM collaboration_documents WHERE document_id = %s",
                    (document_id,)
                )
                row = cur.fetchone()

        if not row:
            return None

        document = self._row_to_document(row)
        return document

    def get_workspace_documents(self, workspace_id: str) -> List[Document]:
        """Get all documents in a workspace."""
        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM collaboration_documents
                    WHERE workspace_id = %s
                    ORDER BY updated_at DESC
                """, (workspace_id,))
                rows = cur.fetchall()

        return [self._row_to_document(row) for row in rows]

    def update_document_content(
        self,
        document_id: str,
        content: str,
        edited_by: str,
        edit_summary: Optional[str] = None,
    ) -> Document:
        """Update document content and create new version."""
        now = datetime.now(timezone.utc)

        def _execute(conn):
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Get current version
                cur.execute(
                    "SELECT version, workspace_id FROM collaboration_documents WHERE document_id = %s",
                    (document_id,)
                )
                current = cur.fetchone()
                if not current:
                    raise ValueError(f"Document {document_id} not found")

                new_version = current["version"] + 1

                # Update document
                cur.execute("""
                    UPDATE collaboration_documents
                    SET content = %s, version = %s, last_edited_by = %s, updated_at = %s
                    WHERE document_id = %s
                    RETURNING *
                """, (content, new_version, edited_by, now, document_id))
                doc_row = cur.fetchone()

                # Create version record
                version_id = f"ver_{uuid4().hex[:12]}"
                cur.execute("""
                    INSERT INTO document_versions (
                        version_id, document_id, version_number, content,
                        edited_by, edit_summary, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    version_id,
                    document_id,
                    new_version,
                    content,
                    edited_by,
                    edit_summary,
                    now,
                ))

                return doc_row

        row = self._pool.run_transaction("update_document", executor=_execute)
        get_cache().delete(f"document:{document_id}")

        return self._row_to_document(row)

    def get_document_versions(
        self,
        document_id: str,
        limit: int = 20,
    ) -> List[DocumentVersion]:
        """Get version history for a document."""
        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM document_versions
                    WHERE document_id = %s
                    ORDER BY version_number DESC
                    LIMIT %s
                """, (document_id, limit))
                rows = cur.fetchall()

        return [
            DocumentVersion(
                version_id=row["version_id"],
                document_id=row["document_id"],
                version_number=row["version_number"],
                content=row["content"],
                edited_by=row["edited_by"],
                edit_summary=row.get("edit_summary"),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # ========================================================================
    # Real-time Cursor/Presence
    # ========================================================================

    def update_cursor(
        self,
        document_id: str,
        user_id: str,
        line: int,
        column: int,
        *,
        selection_start_line: Optional[int] = None,
        selection_start_column: Optional[int] = None,
        selection_end_line: Optional[int] = None,
        selection_end_column: Optional[int] = None,
    ) -> CursorPosition:
        """Update cursor position for presence awareness."""
        cursor_id = f"cur_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        color = self._get_user_color(user_id)

        def _execute(conn):
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Upsert cursor position
                cur.execute("""
                    INSERT INTO active_cursors (
                        cursor_id, document_id, user_id, position_line, position_column,
                        selection_start_line, selection_start_column,
                        selection_end_line, selection_end_column,
                        color, last_updated
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (document_id, user_id)
                    DO UPDATE SET
                        position_line = EXCLUDED.position_line,
                        position_column = EXCLUDED.position_column,
                        selection_start_line = EXCLUDED.selection_start_line,
                        selection_start_column = EXCLUDED.selection_start_column,
                        selection_end_line = EXCLUDED.selection_end_line,
                        selection_end_column = EXCLUDED.selection_end_column,
                        last_updated = EXCLUDED.last_updated
                    RETURNING *
                """, (
                    cursor_id, document_id, user_id, line, column,
                    selection_start_line, selection_start_column,
                    selection_end_line, selection_end_column,
                    color, now
                ))
                return cur.fetchone()

        row = self._pool.run_transaction("update_cursor", executor=_execute)

        return CursorPosition(
            cursor_id=row["cursor_id"],
            document_id=row["document_id"],
            user_id=row["user_id"],
            position_line=row["position_line"],
            position_column=row["position_column"],
            selection_start_line=row.get("selection_start_line"),
            selection_start_column=row.get("selection_start_column"),
            selection_end_line=row.get("selection_end_line"),
            selection_end_column=row.get("selection_end_column"),
            color=row.get("color"),
            last_updated=row["last_updated"],
        )

    def get_active_cursors(self, document_id: str) -> List[CursorPosition]:
        """Get active cursor positions for a document."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.CURSOR_STALE_MINUTES)

        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM active_cursors
                    WHERE document_id = %s AND last_updated > %s
                    ORDER BY user_id
                """, (document_id, cutoff))
                rows = cur.fetchall()

        return [
            CursorPosition(
                cursor_id=row["cursor_id"],
                document_id=row["document_id"],
                user_id=row["user_id"],
                position_line=row["position_line"],
                position_column=row["position_column"],
                selection_start_line=row.get("selection_start_line"),
                selection_start_column=row.get("selection_start_column"),
                selection_end_line=row.get("selection_end_line"),
                selection_end_column=row.get("selection_end_column"),
                color=row.get("color"),
                last_updated=row["last_updated"],
            )
            for row in rows
        ]

    def remove_cursor(self, document_id: str, user_id: str) -> bool:
        """Remove cursor when user leaves document."""
        def _execute(conn):
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM active_cursors
                    WHERE document_id = %s AND user_id = %s
                """, (document_id, user_id))
                return cur.rowcount > 0

        return self._pool.run_transaction("remove_cursor", executor=_execute)

    def cleanup_stale_cursors(self) -> int:
        """Clean up stale cursor positions."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.CURSOR_STALE_MINUTES)

        def _execute(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM active_cursors WHERE last_updated < %s",
                    (cutoff,)
                )
                return cur.rowcount

        count = self._pool.run_transaction("cleanup_cursors", executor=_execute)
        if count > 0:
            self._logger.info(f"Cleaned up {count} stale cursors")
        return count

    # ========================================================================
    # Document Locking
    # ========================================================================

    def lock_document(self, document_id: str, user_id: str, duration_minutes: int = 30) -> bool:
        """Lock document for exclusive editing with PostgreSQL."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=duration_minutes)

        def _execute(conn):
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Check if already locked
                cur.execute("""
                    SELECT locked_by, lock_expires_at
                    FROM collaboration_documents
                    WHERE document_id = %s
                """, (document_id,))
                row = cur.fetchone()

                if not row:
                    return False

                # If locked by someone else and not expired, fail
                if row["locked_by"] and row["locked_by"] != user_id:
                    if row["lock_expires_at"] and row["lock_expires_at"] > now:
                        return False

                # Acquire lock
                cur.execute("""
                    UPDATE collaboration_documents
                    SET locked_by = %s, locked_at = %s, lock_expires_at = %s
                    WHERE document_id = %s
                """, (user_id, now, expires, document_id))

                return True

        result = self._pool.run_transaction("lock_document", executor=_execute)

        if result:
            get_cache().delete(f"document:{document_id}")
            self._logger.info(f"Document {document_id} locked by {user_id}")

        return result

    def unlock_document(self, document_id: str, user_id: str) -> bool:
        """Unlock document with PostgreSQL."""
        def _execute(conn):
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE collaboration_documents
                    SET locked_by = NULL, locked_at = NULL, lock_expires_at = NULL
                    WHERE document_id = %s AND locked_by = %s
                """, (document_id, user_id))
                return cur.rowcount > 0

        result = self._pool.run_transaction("unlock_document", executor=_execute)

        if result:
            get_cache().delete(f"document:{document_id}")
            self._logger.info(f"Document {document_id} unlocked by {user_id}")

        return result

    # ========================================================================
    # Activity Stream
    # ========================================================================

    def get_workspace_activity(self, workspace_id: str, limit: int = 50) -> List[ActivityLog]:
        """Get recent activity for a workspace from PostgreSQL."""
        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM collaboration_events
                    WHERE workspace_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (workspace_id, limit))
                rows = cur.fetchall()

        return [
            ActivityLog(
                activity_id=row["event_id"],
                workspace_id=row["workspace_id"],
                user_id=row["user_id"],
                action_type=row["event_type"],
                description=json.dumps(row.get("event_data") or {}),
                timestamp=row["created_at"],
                target_document_id=row.get("document_id"),
            )
            for row in rows
        ]

    def log_event(
        self,
        workspace_id: str,
        user_id: str,
        event_type: str,
        event_data: Optional[Dict[str, Any]] = None,
        document_id: Optional[str] = None,
    ) -> None:
        """Log a collaboration event."""
        event_id = f"evt_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        def _execute(conn):
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO collaboration_events (
                        event_id, workspace_id, document_id, user_id,
                        event_type, event_data, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    event_id, workspace_id, document_id, user_id,
                    event_type, json.dumps(event_data or {}), now
                ))

        self._pool.run_transaction("log_event", executor=_execute)

    # ========================================================================
    # Metrics
    # ========================================================================

    def get_collaboration_metrics(self, workspace_id: str) -> CollaborationMetrics:
        """Get collaboration metrics from PostgreSQL."""
        now = datetime.now(timezone.utc)
        cutoff_24h = now - timedelta(hours=24)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Get workspace
                cur.execute(
                    "SELECT * FROM collaboration_workspaces WHERE workspace_id = %s",
                    (workspace_id,)
                )
                ws_row = cur.fetchone()
                if not ws_row:
                    raise ValueError(f"Workspace {workspace_id} not found")

                # Active collaborators (last 24h)
                cur.execute("""
                    SELECT COUNT(DISTINCT user_id) FROM workspace_members
                    WHERE workspace_id = %s AND is_active = true
                    AND last_active_at > %s
                """, (workspace_id, cutoff_24h))
                active_count = cur.fetchone()["count"]

                # Total members
                cur.execute("""
                    SELECT COUNT(*) FROM workspace_members
                    WHERE workspace_id = %s AND is_active = true
                """, (workspace_id,))
                total_members = cur.fetchone()["count"]

                # Edits today
                cur.execute("""
                    SELECT COUNT(*) FROM collaboration_events
                    WHERE workspace_id = %s
                    AND event_type IN ('edit', 'document_edited')
                    AND created_at > %s
                """, (workspace_id, today_start))
                edits_today = cur.fetchone()["count"]

                # Comments today
                cur.execute("""
                    SELECT COUNT(*) FROM collaboration_events
                    WHERE workspace_id = %s
                    AND event_type IN ('comment', 'comment_added')
                    AND created_at > %s
                """, (workspace_id, today_start))
                comments_today = cur.fetchone()["count"]

                # Last activity
                cur.execute("""
                    SELECT MAX(created_at) as last_activity
                    FROM collaboration_events
                    WHERE workspace_id = %s
                """, (workspace_id,))
                last_row = cur.fetchone()
                last_activity = last_row["last_activity"] if last_row else ws_row["created_at"]

        # Calculate scores
        collaboration_score = min(1.0, (
            active_count * 0.3 + edits_today * 0.01 + comments_today * 0.05
        ))
        engagement_level = min(1.0, (
            (active_count / max(1, total_members)) * 0.6 + collaboration_score * 0.4
        ))

        return CollaborationMetrics(
            workspace_id=workspace_id,
            active_collaborators=active_count,
            total_edits_today=edits_today,
            comments_added=comments_today,
            average_response_time_seconds=30.0,  # Would need more data to calculate
            collaboration_score=collaboration_score,
            engagement_level=engagement_level,
            last_activity=last_activity or now,
        )

    # ========================================================================
    # Row Converters
    # ========================================================================

    def _row_to_workspace(self, row: Dict[str, Any]) -> Workspace:
        """Convert database row to Workspace."""
        settings = row.get("settings")
        if isinstance(settings, str):
            settings = json.loads(settings)

        return Workspace(
            workspace_id=row["workspace_id"],
            name=row["name"],
            description=row.get("description"),
            owner_id=row["owner_id"],
            status=WorkspaceStatus.ACTIVE if row.get("is_active", True) else WorkspaceStatus.ARCHIVED,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            settings=settings or {},
            tags=[],
            member_count=0,  # Would need join to get accurate count
        )

    def _row_to_member(self, row: Dict[str, Any]) -> WorkspaceMember:
        """Convert database row to WorkspaceMember."""
        role_str = row.get("role", "viewer")
        try:
            role = CollaborationRole(role_str)
        except ValueError:
            role = CollaborationRole.VIEWER

        permissions = row.get("permissions")
        if isinstance(permissions, str):
            permissions = json.loads(permissions)

        return WorkspaceMember(
            member_id=row["member_id"],
            workspace_id=row["workspace_id"],
            user_id=row["user_id"],
            role=role,
            joined_at=row["joined_at"],
            last_active=row.get("last_active_at"),
            permissions=permissions or [],
        )

    def _row_to_document(self, row: Dict[str, Any]) -> Document:
        """Convert database row to Document."""
        metadata = row.get("metadata")
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        return Document(
            document_id=row["document_id"],
            workspace_id=row["workspace_id"],
            title=row["title"],
            content=row.get("content", ""),
            version=row.get("version", 1),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            document_type=row.get("document_type", "text"),
            metadata=metadata or {},
            is_locked=row.get("locked_by") is not None,
            lock_owner=row.get("locked_by"),
        )

    def _get_user_color(self, user_id: str) -> str:
        """Get consistent color for user cursor."""
        # Use hash of user_id to pick color deterministically
        index = hash(user_id) % len(self.CURSOR_COLORS)
        return self.CURSOR_COLORS[index]


__all__ = [
    "PostgresCollaborationService",
    "CursorPosition",
    "DocumentVersion",
    "PendingEdit",
]
