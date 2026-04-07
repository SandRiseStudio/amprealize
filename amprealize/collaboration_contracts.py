"""Data contracts for Collaboration Features - shared workspaces and real-time co-editing."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class WorkspaceStatus(str, Enum):
    """Workspace status states."""
    ACTIVE = "active"
    ARCHIVED = "archived"
    SHARED = "shared"
    PRIVATE = "private"


class CollaborationRole(str, Enum):
    """Collaboration roles within workspaces."""
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
    COMMENTER = "commenter"
    ADMIN = "admin"


# Alias for backward compatibility with tests and other code
MemberRole = CollaborationRole


class DocumentType(str, Enum):
    """Types of collaborative documents."""
    TEXT = "text"
    MARKDOWN = "markdown"
    CODE = "code"
    NOTEBOOK = "notebook"
    DIAGRAM = "diagram"


class EditOperationType(str, Enum):
    """Types of edit operations for real-time collaboration."""
    INSERT = "insert"
    DELETE = "delete"
    REPLACE = "replace"
    FORMAT = "format"
    COMMENT = "comment"


@dataclass
class Workspace:
    """Collaborative workspace for shared work."""
    workspace_id: str
    name: str
    description: str
    owner_id: str
    status: WorkspaceStatus
    created_at: datetime
    updated_at: datetime
    settings: Dict[str, Any]
    tags: List[str]
    member_count: int = 0
    activity_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "name": self.name,
            "description": self.description,
            "owner_id": self.owner_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "settings": self.settings,
            "tags": self.tags,
            "member_count": self.member_count,
            "activity_score": self.activity_score,
        }


@dataclass
class WorkspaceMember:
    """Member of a collaborative workspace."""
    member_id: str
    workspace_id: str
    user_id: str
    role: CollaborationRole
    joined_at: datetime
    last_active: Optional[datetime]
    permissions: List[str]
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "member_id": self.member_id,
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "role": self.role.value,
            "joined_at": self.joined_at.isoformat(),
            "last_active": self.last_active.isoformat() if self.last_active else None,
            "permissions": self.permissions,
            "is_active": self.is_active,
        }


@dataclass
class Document:
    """Document within a collaborative workspace."""
    document_id: str
    workspace_id: str
    title: str
    content: str
    version: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    document_type: str
    metadata: Dict[str, Any]
    is_locked: bool = False
    lock_owner: Optional[str] = None

    def __post_init__(self):
        if not hasattr(self, 'document_type') or not self.document_type:
            self.document_type = "markdown"
        if not hasattr(self, 'metadata') or not self.metadata:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "content": self.content,
            "version": self.version,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "document_type": self.document_type,
            "metadata": self.metadata,
            "is_locked": self.is_locked,
            "lock_owner": self.lock_owner,
        }


@dataclass
class EditOperation:
    """Real-time edit operation for collaborative editing."""
    operation_id: str
    document_id: str
    user_id: str
    operation_type: EditOperationType
    position: int
    content: str
    timestamp: datetime
    version: int
    user_color: str  # For tracking in UI
    session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "document_id": self.document_id,
            "user_id": self.user_id,
            "operation_type": self.operation_type.value,
            "position": self.position,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "version": self.version,
            "user_color": self.user_color,
            "session_id": self.session_id,
        }


@dataclass
class Comment:
    """Comment on a document or specific text selection."""
    comment_id: str
    document_id: str
    user_id: str
    content: str
    position_start: int
    position_end: int
    created_at: datetime
    resolved: bool = False
    parent_comment_id: Optional[str] = None
    replies: Optional[List[str]] = None

    def __post_init__(self):
        if self.replies is None:
            self.replies = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "comment_id": self.comment_id,
            "document_id": self.document_id,
            "user_id": self.user_id,
            "content": self.content,
            "position_start": self.position_start,
            "position_end": self.position_end,
            "created_at": self.created_at.isoformat(),
            "resolved": self.resolved,
            "parent_comment_id": self.parent_comment_id,
            "replies": self.replies or [],
        }


@dataclass
class ActivityLog:
    """Activity log for workspace collaboration."""
    activity_id: str
    workspace_id: str
    user_id: str
    activity_type: str
    description: str
    metadata: Dict[str, Any]
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "activity_type": self.activity_type,
            "description": self.description,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class CreateWorkspaceRequest:
    """Request to create a new workspace."""
    name: str
    description: str
    owner_id: str
    settings: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    is_shared: bool = False


@dataclass
class InviteUserRequest:
    """Request to invite user to workspace."""
    workspace_id: str
    user_id: str
    role: CollaborationRole
    permissions: List[str]
    invited_by: str


@dataclass
class CreateDocumentRequest:
    """Request to create a new document."""
    workspace_id: str
    title: str
    content: str
    document_type: str
    created_by: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class RealTimeEditRequest:
    """Request for real-time collaborative editing."""
    document_id: str
    user_id: str
    operation_type: EditOperationType
    position: int
    content: str
    version: int
    session_id: Optional[str] = None


@dataclass
class CommentRequest:
    """Request to add a comment."""
    document_id: str
    user_id: str
    content: str
    position_start: int
    position_end: int
    parent_comment_id: Optional[str] = None


@dataclass
class WorkspaceSettings:
    """Configuration settings for workspace collaboration."""
    allow_comments: bool = True
    allow_suggestions: bool = True
    require_approval_for_edits: bool = False
    max_collaborators: int = 50
    auto_save_interval_seconds: int = 30
    version_history_limit: int = 100
    share_permissions: Optional[Dict[str, str]] = None  # role -> permission level

    def __post_init__(self):
        if self.share_permissions is None:
            self.share_permissions = {
                "owner": "full_access",
                "editor": "edit_access",
                "commenter": "comment_access",
                "viewer": "read_access"
            }


@dataclass
class CollaborationMetrics:
    """Metrics for collaboration performance and usage."""
    workspace_id: str
    active_collaborators: int
    total_edits_today: int
    comments_added: int
    average_response_time_seconds: float
    collaboration_score: float
    engagement_level: float
    last_activity: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "active_collaborators": self.active_collaborators,
            "total_edits_today": self.total_edits_today,
            "comments_added": self.comments_added,
            "average_response_time_seconds": self.average_response_time_seconds,
            "collaboration_score": self.collaboration_score,
            "engagement_level": self.engagement_level,
            "last_activity": self.last_activity.isoformat(),
        }


@dataclass
class ConflictResolution:
    """Conflict resolution for simultaneous edits."""
    conflict_id: str
    document_id: str
    operations: List[EditOperation]
    resolution_strategy: str  # "merge", "priority", "manual"
    resolved_at: Optional[datetime]
    resolved_by: Optional[str]
    final_content: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "document_id": self.document_id,
            "operations": [op.to_dict() for op in self.operations],
            "resolution_strategy": self.resolution_strategy,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "final_content": self.final_content,
        }


@dataclass
class NotificationSettings:
    """User notification preferences for collaboration."""
    user_id: str
    email_notifications: bool = True
    in_app_notifications: bool = True
    mention_notifications: bool = True
    comment_notifications: bool = True
    edit_notifications: bool = False
    quiet_hours_start: Optional[datetime] = None
    quiet_hours_end: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email_notifications": self.email_notifications,
            "in_app_notifications": self.in_app_notifications,
            "mention_notifications": self.mention_notifications,
            "comment_notifications": self.comment_notifications,
            "edit_notifications": self.edit_notifications,
            "quiet_hours_start": self.quiet_hours_start.isoformat() if self.quiet_hours_start else None,
            "quiet_hours_end": self.quiet_hours_end.isoformat() if self.quiet_hours_end else None,
        }
