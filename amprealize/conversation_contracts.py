"""Data contracts for the Conversation / Messaging system (AMPREALIZE-361).

Defines enums, dataclasses and Pydantic models shared across:
- ConversationService (service layer)
- REST API (FastAPI router)
- MCP tool handlers
- WebSocket / SSE event transport (phase 2)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


# ============================================================================
# Enums
# ============================================================================


class ConversationScope(str, Enum):
    GLOBAL_USER_HOME = "global_user_home"
    # Additional project-less chats; unlimited per user (unlike uq_global_user_home).
    GLOBAL_PERSONAL_THREAD = "global_personal_thread"
    PROJECT_SPACE = "project_space"
    PROJECT_ROOM = "project_room"
    DM = "dm"
    AGENT_DM = "agent_dm"
    GROUP_CHAT = "group_chat"
    WORK_ITEM_THREAD = "work_item_thread"
    RUN_THREAD = "run_thread"

    @property
    def is_global(self) -> bool:
        return self in GLOBAL_WORKSPACE_SCOPES

    @property
    def is_project_scoped(self) -> bool:
        return self in PROJECT_SCOPED_CONVERSATION_SCOPES


GLOBAL_WORKSPACE_SCOPES = frozenset(
    {
        ConversationScope.GLOBAL_USER_HOME,
        ConversationScope.GLOBAL_PERSONAL_THREAD,
    }
)


def is_global_workspace_scope(scope: ConversationScope | str) -> bool:
    """True for global_user_home and global_personal_thread (project-less user chats)."""
    if isinstance(scope, ConversationScope):
        return scope in GLOBAL_WORKSPACE_SCOPES
    try:
        return ConversationScope(scope) in GLOBAL_WORKSPACE_SCOPES
    except ValueError:
        return False


PROJECT_SCOPED_CONVERSATION_SCOPES = frozenset(
    {
        ConversationScope.PROJECT_SPACE,
        ConversationScope.PROJECT_ROOM,
        ConversationScope.DM,
        ConversationScope.AGENT_DM,
        ConversationScope.GROUP_CHAT,
        ConversationScope.WORK_ITEM_THREAD,
        ConversationScope.RUN_THREAD,
    }
)

LEGACY_CONVERSATION_SCOPE_ALIASES = {
    ConversationScope.PROJECT_ROOM: ConversationScope.PROJECT_ROOM,
    ConversationScope.AGENT_DM: ConversationScope.DM,
}

ALL_CONVERSATION_SCOPE_VALUES = tuple(scope.value for scope in ConversationScope)


class ParticipantRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class ActorType(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class MessageType(str, Enum):
    TEXT = "text"
    STATUS_CARD = "status_card"
    BLOCKER_CARD = "blocker_card"
    PROGRESS_CARD = "progress_card"
    CODE_BLOCK = "code_block"
    RUN_SUMMARY = "run_summary"
    SYSTEM = "system"


class NotificationPreference(str, Enum):
    ALL = "all"
    MENTIONS = "mentions"
    NONE = "none"


class ExternalProvider(str, Enum):
    SLACK = "slack"
    TEAMS = "teams"
    DISCORD = "discord"


class ConversationResourceType(str, Enum):
    ORG = "org"
    PROJECT = "project"
    BOARD = "board"
    WORK_ITEM = "work_item"
    RUN = "run"
    PLAN = "plan"
    FILE = "file"
    UPLOAD = "upload"
    IMAGE = "image"
    AGENT = "agent"
    MCP_TOOL = "mcp_tool"
    PLATFORM_ACTION = "platform_action"


class ConversationWorkspaceKind(str, Enum):
    GLOBAL = "global"
    PROJECT = "project"


class ChatPermissionAction(str, Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    INVITE_SHARE = "invite_share"
    EXECUTE = "execute"
    PUBLISH = "publish"
    ADMINISTER = "administer"


class ChatPermissionScope(str, Enum):
    USER = "user"
    ORG = "org"
    PROJECT = "project"
    CONVERSATION = "conversation"
    AGENT = "agent"


class ChatPermissionSurface(str, Enum):
    GLOBAL_CHAT = "global_chat"
    PROJECT_SPACE = "project_space"
    GROUP_CHAT = "group_chat"
    WORK_ITEM_THREAD = "work_item_thread"
    RUN_THREAD = "run_thread"
    AGENT_LIFECYCLE = "agent_lifecycle"
    MCP_TOOL = "mcp_tool"
    ATTACHMENT = "attachment"
    PLATFORM_ACTION = "platform_action"


class ChatPermissionEffect(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


# ============================================================================
# Domain Dataclasses
# ============================================================================


@dataclass
class Conversation:
    id: str
    project_id: Optional[str]
    org_id: Optional[str]
    scope: ConversationScope
    title: Optional[str]
    created_by: str
    pinned_message_id: Optional[str] = None
    is_archived: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Derived
    participant_count: int = 0
    unread_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "org_id": self.org_id,
            "scope": self.scope.value if isinstance(self.scope, Enum) else self.scope,
            "title": self.title,
            "created_by": self.created_by,
            "pinned_message_id": self.pinned_message_id,
            "is_archived": self.is_archived,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "participant_count": self.participant_count,
            "unread_count": self.unread_count,
        }

    @property
    def workspace_kind(self) -> ConversationWorkspaceKind:
        return (
            ConversationWorkspaceKind.GLOBAL
            if self.scope in GLOBAL_WORKSPACE_SCOPES
            else ConversationWorkspaceKind.PROJECT
        )


@dataclass
class Participant:
    id: str
    conversation_id: str
    actor_id: str
    actor_type: ActorType
    role: ParticipantRole = ParticipantRole.MEMBER
    joined_at: Optional[datetime] = None
    left_at: Optional[datetime] = None
    last_read_at: Optional[datetime] = None
    is_muted: bool = False
    notification_preference: NotificationPreference = NotificationPreference.MENTIONS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "actor_id": self.actor_id,
            "actor_type": (
                self.actor_type.value
                if isinstance(self.actor_type, Enum)
                else self.actor_type
            ),
            "role": self.role.value if isinstance(self.role, Enum) else self.role,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
            "left_at": self.left_at.isoformat() if self.left_at else None,
            "last_read_at": (
                self.last_read_at.isoformat() if self.last_read_at else None
            ),
            "is_muted": self.is_muted,
            "notification_preference": (
                self.notification_preference.value
                if isinstance(self.notification_preference, Enum)
                else self.notification_preference
            ),
        }


@dataclass
class Message:
    id: str
    conversation_id: str
    sender_id: str
    sender_type: ActorType
    content: Optional[str] = None
    message_type: MessageType = MessageType.TEXT
    structured_payload: Optional[Dict[str, Any]] = None
    parent_id: Optional[str] = None
    run_id: Optional[str] = None
    behavior_id: Optional[str] = None
    work_item_id: Optional[str] = None
    resource_links: List[Dict[str, Any]] = field(default_factory=list)
    is_edited: bool = False
    edited_at: Optional[datetime] = None
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    # Derived
    reactions: List["Reaction"] = field(default_factory=list)
    reply_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "sender_id": self.sender_id,
            "sender_type": (
                self.sender_type.value
                if isinstance(self.sender_type, Enum)
                else self.sender_type
            ),
            "content": self.content,
            "message_type": (
                self.message_type.value
                if isinstance(self.message_type, Enum)
                else self.message_type
            ),
            "structured_payload": self.structured_payload,
            "parent_id": self.parent_id,
            "run_id": self.run_id,
            "behavior_id": self.behavior_id,
            "work_item_id": self.work_item_id,
            "resource_links": self.resource_links,
            "is_edited": self.is_edited,
            "edited_at": self.edited_at.isoformat() if self.edited_at else None,
            "is_deleted": self.is_deleted,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reactions": [r.to_dict() for r in self.reactions],
            "reply_count": self.reply_count,
        }


@dataclass
class Reaction:
    id: str
    message_id: str
    actor_id: str
    actor_type: ActorType
    emoji: str
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "message_id": self.message_id,
            "actor_id": self.actor_id,
            "actor_type": (
                self.actor_type.value
                if isinstance(self.actor_type, Enum)
                else self.actor_type
            ),
            "emoji": self.emoji,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class ExternalBinding:
    id: str
    conversation_id: str
    provider: ExternalProvider
    external_channel_id: str
    external_workspace_id: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    bound_at: Optional[datetime] = None
    bound_by: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "provider": (
                self.provider.value
                if isinstance(self.provider, Enum)
                else self.provider
            ),
            "external_channel_id": self.external_channel_id,
            "external_workspace_id": self.external_workspace_id,
            "config": self.config,
            "is_active": self.is_active,
            "bound_at": self.bound_at.isoformat() if self.bound_at else None,
            "bound_by": self.bound_by,
        }


@dataclass(frozen=True)
class ConversationScopeResolution:
    """Resolved workspace boundary for a conversation request."""

    scope: ConversationScope
    workspace_kind: ConversationWorkspaceKind
    user_id: str
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    resource_id: Optional[str] = None

    def validate(self) -> None:
        if self.scope.is_global:
            if self.project_id is not None:
                raise ValueError("global user chat must not be bound to a project_id")
            return
        if self.project_id is None:
            raise ValueError(f"{self.scope.value} requires a project_id")


@dataclass(frozen=True)
class ChatPermissionRequirement:
    """Contract row for chat governance; not a runtime policy evaluator."""

    surface: ChatPermissionSurface
    action: ChatPermissionAction
    scopes: Tuple[ChatPermissionScope, ...]
    effect: ChatPermissionEffect = ChatPermissionEffect.ALLOW
    notes: str = ""

    @property
    def is_denied(self) -> bool:
        return self.effect == ChatPermissionEffect.DENY


class ConversationResourceLink(BaseModel):
    """Typed link from a chat message to an Amprealize resource."""

    resource_type: ConversationResourceType
    resource_id: str
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    label: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


CHAT_PERMISSION_DENY_BY_DEFAULT = (
    "Chat governance denies any action/surface pair that is missing from the "
    "matrix, carries no recognized user/org/project/conversation/agent scope, "
    "or resolves to conflicting scopes that cannot be reconciled by the "
    "most-restrictive-wins rule."
)


def _permission(
    surface: ChatPermissionSurface,
    action: ChatPermissionAction,
    scopes: Tuple[ChatPermissionScope, ...],
    *,
    effect: ChatPermissionEffect = ChatPermissionEffect.ALLOW,
    notes: str = "",
) -> ChatPermissionRequirement:
    return ChatPermissionRequirement(
        surface=surface,
        action=action,
        scopes=scopes,
        effect=effect,
        notes=notes,
    )


CHAT_PERMISSION_MATRIX: Dict[
    Tuple[ChatPermissionSurface, ChatPermissionAction],
    ChatPermissionRequirement,
] = {
    (
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.READ,
    ): _permission(
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.READ,
        (ChatPermissionScope.USER,),
        notes="Global chat reads are limited to resources the user can already access.",
    ),
    (
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.CREATE,
    ): _permission(
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.CREATE,
        (ChatPermissionScope.USER,),
        notes="Users can create their own global home conversations.",
    ),
    (
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.UPDATE,
    ): _permission(
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.UPDATE,
        (ChatPermissionScope.USER, ChatPermissionScope.CONVERSATION),
        notes="Users can update their own global-chat messages and preferences.",
    ),
    (
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.DELETE,
    ): _permission(
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.DELETE,
        (ChatPermissionScope.USER, ChatPermissionScope.CONVERSATION),
        notes="Deletes are soft deletes and remain audit-visible.",
    ),
    (
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.INVITE_SHARE,
    ): _permission(
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.INVITE_SHARE,
        (),
        effect=ChatPermissionEffect.DENY,
        notes="A global user home is personal; sharing happens through linked resources.",
    ),
    (
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.EXECUTE,
    ): _permission(
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.EXECUTE,
        (
            ChatPermissionScope.USER,
            ChatPermissionScope.ORG,
            ChatPermissionScope.PROJECT,
            ChatPermissionScope.AGENT,
        ),
        effect=ChatPermissionEffect.REQUIRE_APPROVAL,
        notes="Execution from global chat must also satisfy each linked resource scope.",
    ),
    (
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.PUBLISH,
    ): _permission(
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.PUBLISH,
        (),
        effect=ChatPermissionEffect.DENY,
        notes="Global chat content is not publishable by default.",
    ),
    (
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.ADMINISTER,
    ): _permission(
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.ADMINISTER,
        (ChatPermissionScope.USER,),
        notes="Administration is limited to the user's own global-chat settings.",
    ),
    (
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.READ,
    ): _permission(
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.READ,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.CREATE,
    ): _permission(
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.CREATE,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.UPDATE,
    ): _permission(
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.UPDATE,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.DELETE,
    ): _permission(
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.DELETE,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.INVITE_SHARE,
    ): _permission(
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.INVITE_SHARE,
        (ChatPermissionScope.PROJECT, ChatPermissionScope.ORG),
    ),
    (
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.EXECUTE,
    ): _permission(
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.EXECUTE,
        (ChatPermissionScope.PROJECT, ChatPermissionScope.AGENT),
        effect=ChatPermissionEffect.REQUIRE_APPROVAL,
    ),
    (
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.PUBLISH,
    ): _permission(
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.PUBLISH,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.ADMINISTER,
    ): _permission(
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionAction.ADMINISTER,
        (ChatPermissionScope.PROJECT, ChatPermissionScope.ORG),
    ),
    (
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.READ,
    ): _permission(
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.READ,
        (ChatPermissionScope.CONVERSATION, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.CREATE,
    ): _permission(
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.CREATE,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.UPDATE,
    ): _permission(
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.UPDATE,
        (ChatPermissionScope.CONVERSATION, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.DELETE,
    ): _permission(
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.DELETE,
        (ChatPermissionScope.CONVERSATION, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.INVITE_SHARE,
    ): _permission(
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.INVITE_SHARE,
        (ChatPermissionScope.CONVERSATION, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.EXECUTE,
    ): _permission(
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.EXECUTE,
        (
            ChatPermissionScope.CONVERSATION,
            ChatPermissionScope.PROJECT,
            ChatPermissionScope.AGENT,
        ),
        effect=ChatPermissionEffect.REQUIRE_APPROVAL,
    ),
    (
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.PUBLISH,
    ): _permission(
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.PUBLISH,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.ADMINISTER,
    ): _permission(
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionAction.ADMINISTER,
        (ChatPermissionScope.CONVERSATION, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.READ,
    ): _permission(
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.READ,
        (ChatPermissionScope.CONVERSATION, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.CREATE,
    ): _permission(
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.CREATE,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.UPDATE,
    ): _permission(
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.UPDATE,
        (ChatPermissionScope.CONVERSATION, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.DELETE,
    ): _permission(
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.DELETE,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.INVITE_SHARE,
    ): _permission(
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.INVITE_SHARE,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.EXECUTE,
    ): _permission(
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.EXECUTE,
        (ChatPermissionScope.PROJECT, ChatPermissionScope.AGENT),
        effect=ChatPermissionEffect.REQUIRE_APPROVAL,
        notes="Work-item execution still flows through ExecutionGateway and GEP gates.",
    ),
    (
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.PUBLISH,
    ): _permission(
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.PUBLISH,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.ADMINISTER,
    ): _permission(
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionAction.ADMINISTER,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.READ,
    ): _permission(
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.READ,
        (ChatPermissionScope.CONVERSATION, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.CREATE,
    ): _permission(
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.CREATE,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.UPDATE,
    ): _permission(
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.UPDATE,
        (ChatPermissionScope.CONVERSATION, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.DELETE,
    ): _permission(
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.DELETE,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.INVITE_SHARE,
    ): _permission(
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.INVITE_SHARE,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.EXECUTE,
    ): _permission(
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.EXECUTE,
        (ChatPermissionScope.PROJECT, ChatPermissionScope.AGENT),
        effect=ChatPermissionEffect.REQUIRE_APPROVAL,
        notes="Run-thread actions cover cancel, retry, resume, and clarification flows.",
    ),
    (
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.PUBLISH,
    ): _permission(
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.PUBLISH,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.ADMINISTER,
    ): _permission(
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionAction.ADMINISTER,
        (ChatPermissionScope.PROJECT,),
    ),
    (
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.READ,
    ): _permission(
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.READ,
        (
            ChatPermissionScope.ORG,
            ChatPermissionScope.PROJECT,
            ChatPermissionScope.AGENT,
        ),
    ),
    (
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.CREATE,
    ): _permission(
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.CREATE,
        (ChatPermissionScope.ORG, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.UPDATE,
    ): _permission(
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.UPDATE,
        (
            ChatPermissionScope.ORG,
            ChatPermissionScope.PROJECT,
            ChatPermissionScope.AGENT,
        ),
    ),
    (
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.DELETE,
    ): _permission(
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.DELETE,
        (ChatPermissionScope.ORG,),
    ),
    (
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.INVITE_SHARE,
    ): _permission(
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.INVITE_SHARE,
        (ChatPermissionScope.ORG, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.EXECUTE,
    ): _permission(
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.EXECUTE,
        (ChatPermissionScope.PROJECT, ChatPermissionScope.AGENT),
        effect=ChatPermissionEffect.REQUIRE_APPROVAL,
    ),
    (
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.PUBLISH,
    ): _permission(
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.PUBLISH,
        (ChatPermissionScope.ORG,),
    ),
    (
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.ADMINISTER,
    ): _permission(
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionAction.ADMINISTER,
        (ChatPermissionScope.ORG,),
    ),
    (
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.READ,
    ): _permission(
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.READ,
        (
            ChatPermissionScope.USER,
            ChatPermissionScope.ORG,
            ChatPermissionScope.PROJECT,
        ),
    ),
    (
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.CREATE,
    ): _permission(
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.CREATE,
        (ChatPermissionScope.ORG,),
    ),
    (
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.UPDATE,
    ): _permission(
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.UPDATE,
        (ChatPermissionScope.ORG,),
    ),
    (
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.DELETE,
    ): _permission(
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.DELETE,
        (ChatPermissionScope.ORG,),
    ),
    (
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.INVITE_SHARE,
    ): _permission(
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.INVITE_SHARE,
        (ChatPermissionScope.ORG, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.EXECUTE,
    ): _permission(
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.EXECUTE,
        (
            ChatPermissionScope.USER,
            ChatPermissionScope.ORG,
            ChatPermissionScope.PROJECT,
            ChatPermissionScope.AGENT,
        ),
        effect=ChatPermissionEffect.REQUIRE_APPROVAL,
        notes="MCP tool execution requires an active grant and tool-specific scope.",
    ),
    (
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.PUBLISH,
    ): _permission(
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.PUBLISH,
        (ChatPermissionScope.ORG,),
    ),
    (
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.ADMINISTER,
    ): _permission(
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionAction.ADMINISTER,
        (ChatPermissionScope.ORG,),
    ),
    (
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.READ,
    ): _permission(
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.READ,
        (
            ChatPermissionScope.USER,
            ChatPermissionScope.CONVERSATION,
            ChatPermissionScope.PROJECT,
        ),
    ),
    (
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.CREATE,
    ): _permission(
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.CREATE,
        (
            ChatPermissionScope.USER,
            ChatPermissionScope.CONVERSATION,
            ChatPermissionScope.PROJECT,
        ),
    ),
    (
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.UPDATE,
    ): _permission(
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.UPDATE,
        (ChatPermissionScope.USER, ChatPermissionScope.CONVERSATION),
    ),
    (
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.DELETE,
    ): _permission(
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.DELETE,
        (
            ChatPermissionScope.USER,
            ChatPermissionScope.CONVERSATION,
            ChatPermissionScope.PROJECT,
        ),
    ),
    (
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.INVITE_SHARE,
    ): _permission(
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.INVITE_SHARE,
        (ChatPermissionScope.CONVERSATION, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.EXECUTE,
    ): _permission(
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.EXECUTE,
        (
            ChatPermissionScope.USER,
            ChatPermissionScope.CONVERSATION,
            ChatPermissionScope.AGENT,
        ),
        effect=ChatPermissionEffect.REQUIRE_APPROVAL,
        notes="Attachment analysis or transformation must be explicitly requested.",
    ),
    (
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.PUBLISH,
    ): _permission(
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.PUBLISH,
        (ChatPermissionScope.PROJECT, ChatPermissionScope.ORG),
    ),
    (
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.ADMINISTER,
    ): _permission(
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionAction.ADMINISTER,
        (ChatPermissionScope.PROJECT, ChatPermissionScope.ORG),
    ),
    (
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.READ,
    ): _permission(
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.READ,
        (
            ChatPermissionScope.USER,
            ChatPermissionScope.ORG,
            ChatPermissionScope.PROJECT,
        ),
    ),
    (
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.CREATE,
    ): _permission(
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.CREATE,
        (ChatPermissionScope.ORG, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.UPDATE,
    ): _permission(
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.UPDATE,
        (ChatPermissionScope.ORG, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.DELETE,
    ): _permission(
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.DELETE,
        (ChatPermissionScope.ORG,),
    ),
    (
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.INVITE_SHARE,
    ): _permission(
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.INVITE_SHARE,
        (ChatPermissionScope.ORG, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.EXECUTE,
    ): _permission(
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.EXECUTE,
        (
            ChatPermissionScope.USER,
            ChatPermissionScope.ORG,
            ChatPermissionScope.PROJECT,
            ChatPermissionScope.AGENT,
        ),
        effect=ChatPermissionEffect.REQUIRE_APPROVAL,
        notes="Platform mutations require an explicit actor and target scope.",
    ),
    (
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.PUBLISH,
    ): _permission(
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.PUBLISH,
        (ChatPermissionScope.ORG, ChatPermissionScope.PROJECT),
    ),
    (
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.ADMINISTER,
    ): _permission(
        ChatPermissionSurface.PLATFORM_ACTION,
        ChatPermissionAction.ADMINISTER,
        (ChatPermissionScope.ORG,),
    ),
}


def get_chat_permission_requirement(
    surface: ChatPermissionSurface,
    action: ChatPermissionAction,
) -> ChatPermissionRequirement:
    return CHAT_PERMISSION_MATRIX.get(
        (surface, action),
        ChatPermissionRequirement(
            surface=surface,
            action=action,
            scopes=(),
            effect=ChatPermissionEffect.DENY,
            notes=CHAT_PERMISSION_DENY_BY_DEFAULT,
        ),
    )


def normalize_conversation_scope(scope: ConversationScope) -> ConversationScope:
    """Map legacy conversation scopes to their target workspace equivalent."""
    return LEGACY_CONVERSATION_SCOPE_ALIASES.get(scope, scope)


def conversation_scope_storage_values(scope: ConversationScope) -> tuple[str, ...]:
    """Return storage values that should match a target or legacy scope filter."""
    normalized = normalize_conversation_scope(scope)
    values = {normalized.value}
    if normalized == ConversationScope.DM:
        values.add(ConversationScope.AGENT_DM.value)
    return tuple(sorted(values))


# ============================================================================
# Pydantic Request / Response Models (REST API)
# ============================================================================


class CreateConversationRequest(BaseModel):
    """Create a new conversation."""

    scope: ConversationScope = Field(
        default=ConversationScope.DM,
        description=(
            "Conversation scope. For POST /v1/conversations without project_id, send "
            "global_personal_thread or global_user_home — omitting scope defaults to dm, "
            "which requires project_id and yields 400 on global create."
        ),
    )
    project_id: Optional[str] = Field(
        default=None,
        description=(
            "Required for project-scoped conversations; omitted for global_user_home "
            "and global_personal_thread."
        ),
    )
    title: Optional[str] = None
    participant_ids: List[str] = Field(default_factory=list)


class UpdateConversationRequest(BaseModel):
    """Patch fields on a conversation (owner/admin)."""

    title: Optional[str] = Field(
        default=None,
        description="New title; send null to clear.",
        max_length=500,
    )


class SendMessageRequest(BaseModel):
    """Send a message to a conversation."""

    content: Optional[str] = None
    message_type: MessageType = MessageType.TEXT
    structured_payload: Optional[Dict[str, Any]] = None
    parent_id: Optional[str] = None
    run_id: Optional[str] = None
    behavior_id: Optional[str] = None
    work_item_id: Optional[str] = None
    resource_links: List[ConversationResourceLink] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EditMessageRequest(BaseModel):
    """Edit an existing message."""

    content: str


class UpdateParticipantRequest(BaseModel):
    """Update participant settings."""

    last_read_message_id: Optional[str] = None
    is_muted: Optional[bool] = None
    notification_preference: Optional[NotificationPreference] = None


class PinMessageRequest(BaseModel):
    """Pin a message in a conversation."""

    message_id: str


class SearchMessagesRequest(BaseModel):
    """Search messages in a conversation."""

    q: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ConversationResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    org_id: Optional[str] = None
    scope: str
    title: Optional[str] = None
    created_by: str
    pinned_message_id: Optional[str] = None
    is_archived: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    participant_count: int = 0
    unread_count: int = 0


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    sender_type: str
    content: Optional[str] = None
    message_type: str = "text"
    structured_payload: Optional[Dict[str, Any]] = None
    parent_id: Optional[str] = None
    run_id: Optional[str] = None
    behavior_id: Optional[str] = None
    work_item_id: Optional[str] = None
    resource_links: List[Dict[str, Any]] = Field(default_factory=list)
    is_edited: bool = False
    edited_at: Optional[str] = None
    is_deleted: bool = False
    deleted_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    reactions: List[Dict[str, Any]] = Field(default_factory=list)
    reply_count: int = 0


class ConversationListResponse(BaseModel):
    items: List[ConversationResponse]
    total: int = Field(
        ...,
        description=(
            "Total rows matching the filter when the server ran a COUNT; "
            "`-1` when the request used `include_total=false` (unknown total)."
        ),
    )


class MessageListResponse(BaseModel):
    items: List[MessageResponse]
    total: int = Field(
        ...,
        description=(
            "Total messages matching the filter when counted; "
            "`-1` when `include_total=false` (use `has_more` and page size)."
        ),
    )
    has_more: bool = False


class DirectConversationRequest(BaseModel):
    """Get-or-create a 1:1 DM with a specific participant."""

    target_participant_id: str = Field(..., description="User or agent ID to DM")
    actor_type: Optional[str] = Field(
        default=None,
        description="Actor type of target: 'user' or 'agent'. Inferred if omitted.",
    )


class DirectConversationResponse(BaseModel):
    """Response for direct conversation get-or-create."""

    conversation: ConversationResponse
    created: bool = Field(
        default=False, description="True if a new conversation was created"
    )


class GlobalChatBootstrapResponse(BaseModel):
    """One-shot load for opening global_user_home chat from the web console dock."""

    conversation: ConversationResponse
    messages: MessageListResponse = Field(
        ...,
        description="First page of messages (same shape as GET .../messages).",
    )


class SearchResult(BaseModel):
    message: MessageResponse
    rank: float = 0.0
    headline: Optional[str] = None


class SearchResultsResponse(BaseModel):
    items: List[SearchResult]
    total: int
    query: str
