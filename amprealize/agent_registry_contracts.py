"""Agent Registry data contracts and request/response types.

Following BehaviorService patterns for versioning and lifecycle management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentVisibility(str, Enum):
    """Agent visibility level for sharing/publishing."""
    PRIVATE = "PRIVATE"           # Only visible to owner
    ORGANIZATION = "ORGANIZATION"  # Visible to org members
    PUBLIC = "PUBLIC"             # Marketplace - visible to all


class AgentStatus(str, Enum):
    """Agent lifecycle status."""
    DRAFT = "DRAFT"               # Being created/edited
    ACTIVE = "ACTIVE"             # Available for use
    DEPRECATED = "DEPRECATED"     # Superseded, kept for history


class RoleAlignment(str, Enum):
    """Agent role alignment types."""
    STRATEGIST = "STRATEGIST"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"
    MULTI_ROLE = "MULTI_ROLE"


# ---------------------------------------------------------------------------
# Core Data Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Agent:
    """Core agent definition."""
    agent_id: str                      # UUID (agt-<12-hex>)
    name: str                          # Display name (e.g., "Engineering Agent")
    slug: str                          # URL-friendly ID (e.g., "engineering")
    description: str                   # Brief summary
    tags: List[str]                    # Searchable tags
    created_at: str                    # ISO timestamp
    updated_at: str                    # ISO timestamp
    latest_version: str                # Current version (e.g., "1.0.0")
    status: str                        # DRAFT | ACTIVE | DEPRECATED
    visibility: str                    # PRIVATE | ORGANIZATION | PUBLIC
    owner_id: str                      # Creator user ID
    org_id: Optional[str] = None       # Organization for RLS
    published_at: Optional[str] = None  # When made public
    is_builtin: bool = False           # True for system agents from playbooks
    service_principal_id: Optional[str] = None  # FK to auth.service_principals for API access

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "latest_version": self.latest_version,
            "status": self.status,
            "visibility": self.visibility,
            "owner_id": self.owner_id,
            "org_id": self.org_id,
            "published_at": self.published_at,
            "is_builtin": self.is_builtin,
            "service_principal_id": self.service_principal_id,
        }


@dataclass(frozen=True)
class AgentVersion:
    """Versioned agent content and configuration."""
    agent_id: str                      # Parent agent ID
    version: str                       # Semantic version (e.g., "1.0.0")
    mission: str                       # Full mission statement
    role_alignment: str                # STRATEGIST | TEACHER | STUDENT | MULTI_ROLE
    capabilities: List[str]            # Capability tags (extracted from playbook)
    default_behaviors: List[str]       # behavior_* IDs referenced
    playbook_content: str              # Full markdown playbook content
    status: str                        # DRAFT | ACTIVE | DEPRECATED
    created_at: str                    # ISO timestamp
    created_by: str                    # User who created this version
    effective_from: str                # When version became active
    effective_to: Optional[str] = None  # When deprecated (None if active)
    created_from: Optional[str] = None  # Previous version this was forked from
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_playbook: bool = True) -> Dict[str, Any]:
        payload = {
            "version_id": f"{self.agent_id}:{self.version}",
            "agent_id": self.agent_id,
            "version": self.version,
            "mission": self.mission,
            "role_alignment": self.role_alignment,
            "capabilities": list(self.capabilities),
            "default_behaviors": list(self.default_behaviors),
            "status": self.status,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "created_from": self.created_from,
            "metadata": dict(self.metadata),
        }
        if include_playbook:
            payload["playbook_content"] = self.playbook_content
        return payload


@dataclass(frozen=True)
class AgentSearchResult:
    """Search result with agent and active version."""
    agent: Agent
    active_version: Optional[AgentVersion]
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent.to_dict(),
            "active_version": self.active_version.to_dict() if self.active_version else None,
            "score": self.score,
        }


# ---------------------------------------------------------------------------
# Request Types
# ---------------------------------------------------------------------------


@dataclass
class CreateAgentRequest:
    """Request to create a new agent."""
    name: str                          # Display name
    slug: str                          # URL-friendly ID (must be unique)
    description: str                   # Brief summary
    mission: str                       # Full mission statement
    role_alignment: str                # STRATEGIST | TEACHER | STUDENT | MULTI_ROLE
    capabilities: List[str] = field(default_factory=list)
    default_behaviors: List[str] = field(default_factory=list)
    playbook_content: str = ""         # Full markdown playbook (optional)
    tags: List[str] = field(default_factory=list)
    visibility: str = AgentVisibility.PRIVATE.value
    metadata: Dict[str, Any] = field(default_factory=dict)
    request_api_credentials: bool = False  # If True, create ServicePrincipal for API access


@dataclass
class CreateAgentResponse:
    """Response from creating an agent."""
    agent: Agent
    # API credentials (only present if request_api_credentials=True)
    client_id: Optional[str] = None
    client_secret: Optional[str] = None  # Plain text secret, only returned on creation


@dataclass
class UpdateAgentRequest:
    """Request to update an agent (creates new version)."""
    agent_id: str
    version: str                       # Target version to update
    name: Optional[str] = None
    description: Optional[str] = None
    mission: Optional[str] = None
    role_alignment: Optional[str] = None
    capabilities: Optional[List[str]] = None
    default_behaviors: Optional[List[str]] = None
    playbook_content: Optional[str] = None
    tags: Optional[List[str]] = None
    visibility: Optional[str] = None   # New visibility level
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class CreateNewVersionRequest:
    """Request to create a new version of an existing agent."""
    agent_id: str
    base_version: Optional[str] = None  # Version to fork from (default: latest)
    mission: Optional[str] = None
    role_alignment: Optional[str] = None
    capabilities: Optional[List[str]] = None
    default_behaviors: Optional[List[str]] = None
    playbook_content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class PublishAgentRequest:
    """Request to publish an agent version."""
    agent_id: str
    version: str = "1.0.0"
    visibility: str = AgentVisibility.PUBLIC.value
    effective_from: Optional[str] = None


@dataclass
class DeprecateAgentRequest:
    """Request to deprecate an agent version."""
    agent_id: str
    version: str
    effective_to: str                  # ISO timestamp
    successor_agent_id: Optional[str] = None


@dataclass
class SearchAgentsRequest:
    """Request to search/filter agents."""
    query: Optional[str] = None        # Text search in name/description/mission
    tags: Optional[List[str]] = None   # Filter by tags
    role_alignment: Optional[str] = None  # Filter by role
    visibility: Optional[str] = None   # Filter by visibility
    status: Optional[str] = None       # Filter by status
    owner_id: Optional[str] = None     # Filter by owner
    include_builtin: bool = True       # Include system agents
    limit: int = 25
    org_id: Optional[str] = None       # Multi-tenant filter


@dataclass
class ListAgentsRequest:
    """Request to list agents with optional filters."""
    status: Optional[str] = None
    visibility: Optional[str] = None
    role_alignment: Optional[str] = None
    owner_id: Optional[str] = None
    include_builtin: bool = True
    limit: int = 50
    org_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Response Types
# ---------------------------------------------------------------------------


@dataclass
class AgentWithVersions:
    """Agent with all its versions."""
    agent: Agent
    versions: List[AgentVersion]
    active_version: Optional[AgentVersion] = None

    def to_dict(self, include_playbook: bool = False) -> Dict[str, Any]:
        return {
            "agent": self.agent.to_dict(),
            "versions": [v.to_dict(include_playbook=include_playbook) for v in self.versions],
            "active_version": self.active_version.to_dict(include_playbook=include_playbook) if self.active_version else None,
        }
