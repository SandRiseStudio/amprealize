"""CollaborationService - shared workspaces and real-time co-editing service."""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import uuid
import json
from collections import defaultdict, deque

from .collaboration_contracts import (
    WorkspaceStatus, CollaborationRole, EditOperationType, Workspace, WorkspaceMember,
    Document, EditOperation, Comment, ActivityLog, CreateWorkspaceRequest, InviteUserRequest,
    CreateDocumentRequest, RealTimeEditRequest, CommentRequest, WorkspaceSettings,
    CollaborationMetrics, ConflictResolution, NotificationSettings
)
from .telemetry import TelemetryClient


class VersionConflictError(Exception):
    """Raised when a document edit conflicts with the current version."""

    def __init__(self, message: str, expected_version: int, got_version: int) -> None:
        super().__init__(message)
        self.expected_version = expected_version
        self.got_version = got_version


class CollaborationService:
    """Collaboration service for shared workspaces and real-time co-editing."""

    def __init__(self, telemetry: Optional[TelemetryClient] = None) -> None:
        """Initialize CollaborationService."""
        self._telemetry = telemetry or TelemetryClient.noop()
        self._workspaces: Dict[str, Workspace] = {}
        self._members: Dict[str, WorkspaceMember] = {}
        self._documents: Dict[str, Document] = {}
        self._edit_operations: Dict[str, List[EditOperation]] = defaultdict(list)
        self._comments: Dict[str, Comment] = {}
        self._activity_logs: List[ActivityLog] = []
        self._notification_settings: Dict[str, NotificationSettings] = {}
        self._active_sessions: Dict[str, Dict[str, Any]] = {}  # session_id -> session_info
        self._document_locks: Dict[str, str] = {}  # document_id -> user_id

        self._logger = logging.getLogger(__name__)

    def create_workspace(self, request: CreateWorkspaceRequest) -> Workspace:
        """Create a new collaborative workspace."""
        workspace_id = str(uuid.uuid4())

        workspace = Workspace(
            workspace_id=workspace_id,
            name=request.name,
            description=request.description,
            owner_id=request.owner_id,
            status=WorkspaceStatus.ACTIVE if not request.is_shared else WorkspaceStatus.SHARED,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            settings=request.settings or {},
            tags=request.tags or []
        )

        self._workspaces[workspace_id] = workspace

        # Add owner as member
        owner_member = WorkspaceMember(
            member_id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            user_id=request.owner_id,
            role=CollaborationRole.OWNER,
            joined_at=datetime.utcnow(),
            last_active=datetime.utcnow(),
            permissions=["read", "write", "admin", "invite"]
        )
        self._members[owner_member.member_id] = owner_member

        # Log activity
        self._log_activity(workspace_id, request.owner_id, "workspace_created",
                          f"Created workspace '{request.name}'")

        self._emit_telemetry("workspace_created", {
            "workspace_id": workspace_id,
            "name": request.name,
            "owner_id": request.owner_id,
            "is_shared": request.is_shared
        })

        return workspace

    def invite_user(self, request: InviteUserRequest) -> WorkspaceMember:
        """Invite user to workspace with specific role."""
        if request.workspace_id not in self._workspaces:
            raise ValueError(f"Workspace {request.workspace_id} not found")

        # Check if user is already a member
        for member in self._members.values():
            if (member.workspace_id == request.workspace_id and
                member.user_id == request.user_id):
                raise ValueError(f"User {request.user_id} is already a member")

        member_id = str(uuid.uuid4())
        member = WorkspaceMember(
            member_id=member_id,
            workspace_id=request.workspace_id,
            user_id=request.user_id,
            role=request.role,
            joined_at=datetime.utcnow(),
            last_active=None,
            permissions=request.permissions
        )

        self._members[member_id] = member

        # Update workspace member count
        workspace = self._workspaces[request.workspace_id]
        workspace.member_count += 1
        workspace.updated_at = datetime.utcnow()

        # Log activity
        self._log_activity(request.workspace_id, request.invited_by, "user_invited",
                          f"Invited {request.user_id} as {request.role}")

        self._emit_telemetry("user_invited", {
            "workspace_id": request.workspace_id,
            "user_id": request.user_id,
            "role": request.role.value,
            "invited_by": request.invited_by
        })

        return member

    def create_document(self, request: CreateDocumentRequest) -> Document:
        """Create a new document in workspace."""
        if request.workspace_id not in self._workspaces:
            raise ValueError(f"Workspace {request.workspace_id} not found")

        document_id = str(uuid.uuid4())
        document = Document(
            document_id=document_id,
            workspace_id=request.workspace_id,
            title=request.title,
            content=request.content,
            version=1,
            created_by=request.created_by,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            document_type=request.document_type,
            metadata=request.metadata or {}
        )

        self._documents[document_id] = document

        # Log activity
        self._log_activity(request.workspace_id, request.created_by, "document_created",
                          f"Created document '{request.title}'")

        self._emit_telemetry("document_created", {
            "document_id": document_id,
            "title": request.title,
            "workspace_id": request.workspace_id,
            "created_by": request.created_by
        })

        return document

    def apply_real_time_edit(self, request: RealTimeEditRequest) -> EditOperation:
        """Apply real-time edit operation to document."""
        if request.document_id not in self._documents:
            raise ValueError(f"Document {request.document_id} not found")

        document = self._documents[request.document_id]

        # Check if document is locked by another user
        if document.is_locked and document.lock_owner != request.user_id:
            raise ValueError(f"Document is locked by {document.lock_owner}")

        # Create edit operation
        operation_id = str(uuid.uuid4())
        operation = EditOperation(
            operation_id=operation_id,
            document_id=request.document_id,
            user_id=request.user_id,
            operation_type=request.operation_type,
            position=request.position,
            content=request.content,
            timestamp=datetime.utcnow(),
            version=document.version + 1,
            user_color=self._get_user_color(request.user_id),
            session_id=request.session_id
        )

        # Store operation
        self._edit_operations[request.document_id].append(operation)

        # Apply operation to document content
        self._apply_operation_to_document(document, operation)
        document.version += 1
        document.updated_at = datetime.utcnow()

        # Keep only recent operations for performance
        if len(self._edit_operations[request.document_id]) > 1000:
            self._edit_operations[request.document_id] = self._edit_operations[request.document_id][-500:]

        # Update member activity
        workspace_id = document.workspace_id
        self._update_member_activity(workspace_id, request.user_id)

        # Log activity
        self._log_activity(workspace_id, request.user_id, "document_edited",
                          f"Applied {request.operation_type.value} operation")

        self._emit_telemetry("real_time_edit_applied", {
            "document_id": request.document_id,
            "operation_id": operation_id,
            "operation_type": request.operation_type.value,
            "user_id": request.user_id
        })

        return operation

    def add_comment(self, request: CommentRequest) -> Comment:
        """Add comment to document."""
        if request.document_id not in self._documents:
            raise ValueError(f"Document {request.document_id} not found")

        document = self._documents[request.document_id]

        comment_id = str(uuid.uuid4())
        comment = Comment(
            comment_id=comment_id,
            document_id=request.document_id,
            user_id=request.user_id,
            content=request.content,
            position_start=request.position_start,
            position_end=request.position_end,
            created_at=datetime.utcnow(),
            parent_comment_id=request.parent_comment_id
        )

        self._comments[comment_id] = comment

        # Add to parent comment replies if specified
        if request.parent_comment_id and request.parent_comment_id in self._comments:
            parent_comment = self._comments[request.parent_comment_id]
            if parent_comment.replies is None:
                parent_comment.replies = []
            parent_comment.replies.append(comment_id)

        # Log activity
        self._log_activity(document.workspace_id, request.user_id, "comment_added",
                          "Added comment to document")

        self._emit_telemetry("comment_added", {
            "comment_id": comment_id,
            "document_id": request.document_id,
            "user_id": request.user_id
        })

        return comment

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        """Get workspace by ID."""
        return self._workspaces.get(workspace_id)

    def get_workspace_members(self, workspace_id: str) -> List[WorkspaceMember]:
        """Get all members of a workspace."""
        return [m for m in self._members.values() if m.workspace_id == workspace_id]

    def get_document(self, document_id: str) -> Optional[Document]:
        """Get document by ID."""
        return self._documents.get(document_id)

    def get_workspace_documents(self, workspace_id: str) -> List[Document]:
        """Get all documents in a workspace."""
        return [d for d in self._documents.values() if d.workspace_id == workspace_id]

    def get_document_operations(self, document_id: str, limit: int = 100) -> List[EditOperation]:
        """Get recent edit operations for a document."""
        operations = self._edit_operations.get(document_id, [])
        return operations[-limit:] if limit > 0 else operations

    def get_document_comments(self, document_id: str) -> List[Comment]:
        """Get all comments for a document."""
        return [c for c in self._comments.values() if c.document_id == document_id]

    def get_workspace_activity(self, workspace_id: str, limit: int = 50) -> List[ActivityLog]:
        """Get recent activity for a workspace."""
        activities = [a for a in self._activity_logs if a.workspace_id == workspace_id]
        return sorted(activities, key=lambda x: x.timestamp, reverse=True)[:limit]

    def get_collaboration_metrics(self, workspace_id: str) -> CollaborationMetrics:
        """Get collaboration metrics for workspace."""
        workspace = self._workspaces.get(workspace_id)
        if not workspace:
            raise ValueError(f"Workspace {workspace_id} not found")

        # Count active collaborators (active in last 24 hours)
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        active_members = [
            m for m in self._members.values()
            if m.workspace_id == workspace_id and
            m.last_active and m.last_active >= cutoff_time
        ]

        # Count edits today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        todays_operations = [
            op for ops in self._edit_operations.values()
            for op in ops
            if op.timestamp >= today_start
        ]

        # Count comments today
        todays_comments = [
            c for c in self._comments.values()
            if c.created_at >= today_start
        ]

        # Calculate collaboration score
        collaboration_score = min(1.0, (len(active_members) * 0.3 +
                                       len(todays_operations) * 0.01 +
                                       len(todays_comments) * 0.05))

        # Calculate engagement level
        engagement_level = min(1.0, (len(active_members) / max(1, workspace.member_count)) * 0.6 +
                              collaboration_score * 0.4)

        # Get last activity
        workspace_activities = [a for a in self._activity_logs if a.workspace_id == workspace_id]
        last_activity = max([a.timestamp for a in workspace_activities]) if workspace_activities else workspace.created_at

        return CollaborationMetrics(
            workspace_id=workspace_id,
            active_collaborators=len(active_members),
            total_edits_today=len(todays_operations),
            comments_added=len(todays_comments),
            average_response_time_seconds=30.0,  # Simulated
            collaboration_score=collaboration_score,
            engagement_level=engagement_level,
            last_activity=last_activity
        )

    def lock_document(self, document_id: str, user_id: str) -> bool:
        """Lock document for exclusive editing."""
        if document_id not in self._documents:
            return False

        document = self._documents[document_id]
        if document.is_locked and document.lock_owner != user_id:
            return False

        document.is_locked = True
        document.lock_owner = user_id
        self._document_locks[document_id] = user_id

        self._log_activity(document.workspace_id, user_id, "document_locked",
                          f"Locked document for editing")

        return True

    def unlock_document(self, document_id: str, user_id: str) -> bool:
        """Unlock document."""
        if document_id not in self._documents:
            return False

        document = self._documents[document_id]
        if document.lock_owner != user_id:
            return False

        document.is_locked = False
        document.lock_owner = None
        self._document_locks.pop(document_id, None)

        self._log_activity(document.workspace_id, user_id, "document_unlocked",
                          f"Unlocked document")

        return True

    def resolve_edit_conflict(self, document_id: str, operations: List[EditOperation],
                            strategy: str) -> ConflictResolution:
        """Resolve simultaneous edit conflicts."""
        conflict_id = str(uuid.uuid4())

        document = self._documents.get(document_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")

        # Apply conflict resolution strategy
        if strategy == "merge":
            final_content = self._merge_operations(document.content, operations)
        elif strategy == "priority":
            final_content = self._priority_resolution(document.content, operations)
        else:  # manual
            final_content = document.content  # Keep original, manual resolution needed

        # Update document
        document.content = final_content
        document.version += len(operations)
        document.updated_at = datetime.utcnow()

        resolution = ConflictResolution(
            conflict_id=conflict_id,
            document_id=document_id,
            operations=operations,
            resolution_strategy=strategy,
            resolved_at=datetime.utcnow(),
            resolved_by="system",
            final_content=final_content
        )

        self._log_activity(document.workspace_id, "system", "conflict_resolved",
                          f"Resolved edit conflict using {strategy} strategy")

        self._emit_telemetry("edit_conflict_resolved", {
            "conflict_id": conflict_id,
            "document_id": document_id,
            "strategy": strategy,
            "operation_count": len(operations)
        })

        return resolution

    def update_notification_settings(self, settings: NotificationSettings) -> None:
        """Update user notification preferences."""
        self._notification_settings[settings.user_id] = settings

    def get_notification_settings(self, user_id: str) -> Optional[NotificationSettings]:
        """Get user notification settings."""
        return self._notification_settings.get(user_id)

    def start_collaboration_session(self, document_id: str, user_id: str) -> str:
        """Start a real-time collaboration session."""
        session_id = str(uuid.uuid4())

        self._active_sessions[session_id] = {
            "session_id": session_id,
            "document_id": document_id,
            "user_id": user_id,
            "started_at": datetime.utcnow(),
            "last_activity": datetime.utcnow(),
            "cursor_position": 0,
            "selection_end": None,
            "status": "active",
            "is_active": True
        }

        return session_id

    def end_collaboration_session(self, session_id: str) -> bool:
        """End a collaboration session."""
        if session_id in self._active_sessions:
            self._active_sessions[session_id]["is_active"] = False
            self._active_sessions[session_id]["status"] = "disconnected"
            self._active_sessions[session_id]["last_activity"] = datetime.utcnow()
            return True
        return False

    def touch_collaboration_session(
        self,
        session_id: str,
        *,
        cursor_position: Optional[int] = None,
        selection_end: Optional[int] = None,
        status: Optional[str] = None,
    ) -> bool:
        """Update activity metadata for a live collaboration session."""
        session = self._active_sessions.get(session_id)
        if session is None:
            return False

        session["last_activity"] = datetime.utcnow()
        if cursor_position is not None:
            session["cursor_position"] = cursor_position
        if selection_end is not None:
            session["selection_end"] = selection_end
        if status is not None:
            session["status"] = status
        return True

    def get_active_collaborators(self, document_id: str) -> List[Dict[str, Any]]:
        """Get currently active collaborators on a document."""
        active_users = []
        for session in self._active_sessions.values():
            if (session["document_id"] == document_id and
                session["is_active"] and
                (datetime.utcnow() - session["last_activity"]).seconds < 300):  # 5 min timeout
                active_users.append({
                    "user_id": session["user_id"],
                    "cursor_position": session["cursor_position"],
                    "selection_end": session.get("selection_end"),
                    "status": session.get("status", "active"),
                    "session_id": session.get("session_id", ""),
                    "last_activity": session["last_activity"].isoformat()
                })
        return active_users

    def _apply_operation_to_document(self, document: Document, operation: EditOperation) -> None:
        """Apply edit operation to document content."""
        content = list(document.content)

        if operation.operation_type == EditOperationType.INSERT:
            content.insert(operation.position, operation.content)
        elif operation.operation_type == EditOperationType.DELETE:
            del content[operation.position:operation.position + len(operation.content)]
        elif operation.operation_type == EditOperationType.REPLACE:
            del content[operation.position:operation.position + len(operation.content)]
            content.insert(operation.position, operation.content)

        document.content = ''.join(content)

    def _merge_operations(self, original_content: str, operations: List[EditOperation]) -> str:
        """Merge conflicting operations intelligently."""
        # Simplified merge strategy - in production, use operational transform
        content = list(original_content)

        # Sort operations by position and timestamp
        sorted_ops = sorted(operations, key=lambda x: (x.position, x.timestamp))

        for operation in sorted_ops:
            if operation.operation_type == EditOperationType.INSERT:
                content.insert(operation.position, operation.content)
            elif operation.operation_type == EditOperationType.DELETE:
                if operation.position < len(content):
                    del content[operation.position:operation.position + len(operation.content)]

        return ''.join(content)

    def _priority_resolution(self, original_content: str, operations: List[EditOperation]) -> str:
        """Resolve conflicts by prioritizing later operations."""
        content = list(original_content)

        # Sort by timestamp (latest first)
        sorted_ops = sorted(operations, key=lambda x: x.timestamp, reverse=True)

        for operation in sorted_ops:
            if operation.operation_type == EditOperationType.INSERT:
                content.insert(operation.position, operation.content)
            elif operation.operation_type == EditOperationType.DELETE:
                if operation.position < len(content):
                    del content[operation.position:operation.position + len(operation.content)]

        return ''.join(content)

    def _get_user_color(self, user_id: str) -> str:
        """Get consistent color for user in collaboration UI."""
        colors = [
            "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
            "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9"
        ]
        hash_val = hash(user_id) % len(colors)
        return colors[hash_val]

    def _log_activity(self, workspace_id: str, user_id: str, activity_type: str, description: str) -> None:
        """Log workspace activity."""
        activity = ActivityLog(
            activity_id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            user_id=user_id,
            activity_type=activity_type,
            description=description,
            metadata={},
            timestamp=datetime.utcnow()
        )
        self._activity_logs.append(activity)

        # Keep only recent activities
        if len(self._activity_logs) > 10000:
            self._activity_logs = self._activity_logs[-5000:]

    def _update_member_activity(self, workspace_id: str, user_id: str) -> None:
        """Update member's last active timestamp."""
        for member in self._members.values():
            if member.workspace_id == workspace_id and member.user_id == user_id:
                member.last_active = datetime.utcnow()
                break

    def _emit_telemetry(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit telemetry event."""
        try:
            self._telemetry.emit_event(
                event_type=event_type,
                payload=data
            )
        except Exception as e:
            self._logger.warning(f"Failed to emit telemetry: {e}")

    def get_user_workspaces(self, user_id: str) -> List[Workspace]:
        """Get all workspaces where user is a member."""
        user_workspace_ids = [
            m.workspace_id for m in self._members.values()
            if m.user_id == user_id and m.is_active
        ]
        return [w for w in self._workspaces.values() if w.workspace_id in user_workspace_ids]

    def remove_user_from_workspace(self, workspace_id: str, user_id: str) -> bool:
        """Remove user from workspace."""
        # Find member
        member_to_remove = None
        for member in self._members.values():
            if member.workspace_id == workspace_id and member.user_id == user_id:
                member_to_remove = member
                break

        if not member_to_remove:
            return False

        # Remove member
        del self._members[member_to_remove.member_id]

        # Update workspace
        workspace = self._workspaces[workspace_id]
        workspace.member_count = max(0, workspace.member_count - 1)
        workspace.updated_at = datetime.utcnow()

        # Log activity
        self._log_activity(workspace_id, "system", "user_removed",
                          f"Removed {user_id} from workspace")

        return True

    def search_workspaces(self, query: str, user_id: str) -> List[Workspace]:
        """Search workspaces accessible to user."""
        user_workspaces = self.get_user_workspaces(user_id)
        query_lower = query.lower()

        matching_workspaces = []
        for workspace in user_workspaces:
            if (query_lower in workspace.name.lower() or
                query_lower in workspace.description.lower() or
                any(query_lower in tag.lower() for tag in workspace.tags)):
                matching_workspaces.append(workspace)

        return matching_workspaces
