"""Project management for Amprealize.

Provides:
- Contract models for projects, agents, memberships, and related entities
- OSSProjectService: Lightweight project CRUD for personal projects
- ExecutionMode: Work-item execution mode selection
"""

from .contracts import (
    Agent,
    AgentPresence,
    AgentPresenceResponse,
    AgentStatus,
    AgentType,
    AssignAgentToProjectRequest,
    CreateProjectMembershipRequest,
    CreateProjectRequest,
    MemberRole,
    PageInfo,
    PresenceStatus,
    Project,
    ProjectAgentAssignment,
    ProjectAgentAssignmentResponse,
    ProjectAgentPresenceListResponse,
    ProjectAgentRole,
    ProjectAgentStatus,
    ProjectMembership,
    ProjectRole,
    ProjectVisibility,
    ProjectWithMembers,
    UpdateAgentPresenceRequest,
    UpdateAgentRequest,
    UpdateProjectAgentAssignmentRequest,
    UpdateProjectRequest,
)
from .service import OSSProjectService
from .settings import ExecutionMode, LOCAL_CAPABLE_SURFACES, REMOTE_ONLY_SURFACES

__all__ = [
    "Agent",
    "AgentPresence",
    "AgentPresenceResponse",
    "AgentStatus",
    "AgentType",
    "AssignAgentToProjectRequest",
    "CreateProjectMembershipRequest",
    "CreateProjectRequest",
    "ExecutionMode",
    "LOCAL_CAPABLE_SURFACES",
    "MemberRole",
    "OSSProjectService",
    "PageInfo",
    "PresenceStatus",
    "Project",
    "ProjectAgentAssignment",
    "ProjectAgentAssignmentResponse",
    "ProjectAgentPresenceListResponse",
    "ProjectAgentRole",
    "ProjectAgentStatus",
    "ProjectMembership",
    "ProjectRole",
    "ProjectVisibility",
    "ProjectWithMembers",
    "REMOTE_ONLY_SURFACES",
    "UpdateAgentPresenceRequest",
    "UpdateAgentRequest",
    "UpdateProjectAgentAssignmentRequest",
    "UpdateProjectRequest",
]
