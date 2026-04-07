"""Pydantic contracts for multi-tenant entities.

These contracts define the data models for:
- Organizations and memberships
- Projects and project memberships
- Agents (AI agents within organizations)
- Subscriptions and usage records

All contracts align with the PostgreSQL schema defined in migration 023.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Set
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import uuid


# =============================================================================
# Pagination Support
# =============================================================================

class PageInfo(BaseModel):
    """Pagination metadata in responses."""
    total: int = Field(..., description="Total number of items")
    limit: int = Field(..., description="Items per page")
    offset: int = Field(..., description="Current offset")
    has_more: bool = Field(..., description="Whether more items exist")


# =============================================================================
# Enums (matching PostgreSQL ENUMs from migration 023)
# =============================================================================

class OrgPlan(str, Enum):
    """Organization subscription plan tiers."""
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class OrgStatus(str, Enum):
    """Organization lifecycle status."""
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class MemberRole(str, Enum):
    """Organization-level member roles."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ProjectRole(str, Enum):
    """Project-level member roles."""
    OWNER = "owner"
    MAINTAINER = "maintainer"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


class ProjectVisibility(str, Enum):
    """Project visibility settings."""
    PRIVATE = "private"      # Only project members
    INTERNAL = "internal"    # All org members
    PUBLIC = "public"        # Anyone (future)


class AgentType(str, Enum):
    """Types of AI agents."""
    ORCHESTRATOR = "orchestrator"
    SPECIALIST = "specialist"
    CUSTOM = "custom"


class AgentStatus(str, Enum):
    """Agent lifecycle status.

    Status transitions:
        ACTIVE -> BUSY, IDLE, PAUSED, DISABLED, ARCHIVED
        BUSY -> ACTIVE, IDLE, PAUSED (cannot go directly to disabled/archived)
        IDLE -> ACTIVE, BUSY, PAUSED, DISABLED, ARCHIVED
        PAUSED -> ACTIVE, DISABLED, ARCHIVED
        DISABLED -> ACTIVE, ARCHIVED
        ARCHIVED -> (none - must use restore_agent to go to ACTIVE)

    Automatic transitions:
        - ACTIVE/IDLE -> BUSY when task is assigned
        - BUSY -> IDLE when task is completed
    """
    ACTIVE = "active"      # Ready and available for work
    BUSY = "busy"          # Currently executing a task
    IDLE = "idle"          # Available but not actively working
    PAUSED = "paused"      # Manually paused by user
    DISABLED = "disabled"  # Administratively disabled
    ARCHIVED = "archived"  # Soft-deleted


class SubscriptionStatus(str, Enum):
    """Stripe subscription status."""
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    TRIALING = "trialing"


# =============================================================================
# Base Models
# =============================================================================

class TimestampMixin(BaseModel):
    """Mixin for created_at/updated_at timestamps."""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Organization Models
# =============================================================================

class Organization(TimestampMixin):
    """Organization entity representing a tenant."""

    id: str = Field(default_factory=lambda: f"org-{uuid.uuid4().hex[:12]}")
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    display_name: Optional[str] = None

    plan: OrgPlan = OrgPlan.FREE
    status: OrgStatus = OrgStatus.ACTIVE

    stripe_customer_id: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class CreateOrgRequest(BaseModel):
    """Request to create a new organization."""

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    display_name: Optional[str] = None
    plan: OrgPlan = OrgPlan.FREE
    settings: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        """Ensure slug is lowercase and URL-safe."""
        return v.lower().strip()


class UpdateOrgRequest(BaseModel):
    """Request to update an organization."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    display_name: Optional[str] = None
    plan: Optional[OrgPlan] = None
    status: Optional[OrgStatus] = None
    settings: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


# =============================================================================
# Membership Models
# =============================================================================

class OrgMembership(TimestampMixin):
    """Membership linking users to organizations."""

    id: str = Field(default_factory=lambda: f"mem-{uuid.uuid4().hex[:12]}")
    org_id: str
    user_id: str
    role: MemberRole = MemberRole.MEMBER
    invited_by: Optional[str] = None
    invited_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CreateMembershipRequest(BaseModel):
    """Request to add a member to an organization."""

    user_id: str
    role: MemberRole = MemberRole.MEMBER


class UpdateMembershipRequest(BaseModel):
    """Request to update a membership."""

    role: MemberRole


# =============================================================================
# Project Models
# =============================================================================

class Project(TimestampMixin):
    """Project always owned by a user, optionally in an organization.

    Every project has an owner_id (required). Projects may also belong to
    an organization via org_id (optional).
    """

    id: str = Field(default_factory=lambda: f"proj-{uuid.uuid4().hex[:12]}")
    org_id: Optional[str] = None  # Optional org association
    owner_id: str  # Always required — the user who owns/created the project
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = None
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE
    settings: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class CreateProjectRequest(BaseModel):
    """Request to create a new project.

    owner_id is required — every project has an owner.
    org_id is optional — set when project belongs to an organization.
    """

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = None
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE
    settings: Dict[str, Any] = Field(default_factory=dict)
    owner_id: str  # Always required


class UpdateProjectRequest(BaseModel):
    """Request to update a project."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    visibility: Optional[ProjectVisibility] = None
    settings: Optional[Dict[str, Any]] = None


# =============================================================================
# Project Membership Models
# =============================================================================

class ProjectMembership(TimestampMixin):
    """Membership linking users to projects."""

    id: str = Field(default_factory=lambda: f"pmem-{uuid.uuid4().hex[:12]}")
    project_id: str
    user_id: str
    role: ProjectRole = ProjectRole.CONTRIBUTOR

    class Config:
        from_attributes = True


class CreateProjectMembershipRequest(BaseModel):
    """Request to add a member to a project."""

    user_id: str
    role: ProjectRole = ProjectRole.CONTRIBUTOR


# =============================================================================
# Agent Models
# =============================================================================

class Agent(TimestampMixin):
    """AI agent created by a user, optionally belonging to an organization.

    Every agent has an owner (the user who created it). Agents may also
    belong to an organization (org_id set). Agents can be public
    (discoverable by all) or private (assignable to specific projects).
    """

    id: str = Field(default_factory=lambda: f"agent-{uuid.uuid4().hex[:12]}")
    org_id: Optional[str] = None
    owner_id: str  # The user who created the agent (required)
    project_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=255)
    agent_type: AgentType = AgentType.SPECIALIST
    status: AgentStatus = AgentStatus.ACTIVE
    config: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class UpdateAgentRequest(BaseModel):
    """Request to update an agent."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[AgentStatus] = None
    config: Optional[Dict[str, Any]] = None
    capabilities: Optional[List[str]] = None


# =============================================================================
# Project-Agent Assignment Models (Junction Table)
# =============================================================================


class ProjectAgentRole(str, Enum):
    """Role of an agent within a project context."""

    PRIMARY = "primary"  # Main agent for the project
    CONTRIBUTOR = "contributor"  # Contributing agent
    SUPPORTING = "supporting"  # Helper/secondary agent
    SPECIALIST = "specialist"  # Domain-specific specialist
    REVIEWER = "reviewer"  # Code review, compliance, etc.


class ProjectAgentStatus(str, Enum):
    """Status of an agent assignment to a project.

    Must match CHECK constraint in execution.project_agent_assignments:
    status IN ('active', 'inactive', 'removed')
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    REMOVED = "removed"


class ProjectAgentAssignment(TimestampMixin):
    """Represents assignment of a registry agent to a project.

    This is a junction table model that links execution.agents (the registry)
    to projects. It allows:
    - Many-to-many: One agent can serve multiple projects
    - Per-project config overrides: Customize agent behavior per project
    - Role assignment: Define agent's role in the project context
    - Status management: Enable/disable agents per project
    """

    id: str = Field(default_factory=lambda: f"paa-{uuid.uuid4().hex[:12]}")
    project_id: str
    agent_id: str  # References execution.agents.agent_id
    assigned_by: str  # User who made the assignment (required in DB)
    config_overrides: Dict[str, Any] = Field(default_factory=dict)
    role: ProjectAgentRole = ProjectAgentRole.PRIMARY
    status: ProjectAgentStatus = ProjectAgentStatus.ACTIVE

    class Config:
        from_attributes = True


class AssignAgentToProjectRequest(BaseModel):
    """Request to assign a registry agent to a project."""

    agent_id: str = Field(..., description="ID of the agent from the registry (execution.agents)")
    config_overrides: Dict[str, Any] = Field(
        default_factory=dict,
        description="Project-specific configuration overrides"
    )
    role: ProjectAgentRole = Field(
        default=ProjectAgentRole.PRIMARY,
        description="Agent's role within this project"
    )


class UpdateProjectAgentAssignmentRequest(BaseModel):
    """Request to update an existing agent assignment."""

    config_overrides: Optional[Dict[str, Any]] = None
    role: Optional[ProjectAgentRole] = None
    status: Optional[ProjectAgentStatus] = None


class ProjectAgentAssignmentResponse(BaseModel):
    """Response model for project-agent assignments with agent details.

    Designed to be compatible with the frontend Agent interface which expects
    fields like `config.registry_agent_id` and `project_id`.
    """

    id: str
    project_id: str
    agent_id: str
    name: str = ""  # Frontend expects 'name' at top level
    agent_name: Optional[str] = None  # Also keep for explicitness
    agent_slug: Optional[str] = None
    agent_description: Optional[str] = None
    assigned_by: Optional[str] = None
    assigned_at: datetime
    config: Dict[str, Any] = Field(default_factory=dict)  # Frontend expects 'config'
    role: ProjectAgentRole
    status: ProjectAgentStatus

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Agent Presence Models (Runtime state)
# =============================================================================


class PresenceStatus(str, Enum):
    """Runtime presence state for an agent within a project.

    Distinct from AgentStatus (lifecycle) and ProjectAgentStatus (assignment).
    """

    AVAILABLE = "available"
    WORKING = "working"
    FINISHED_RECENTLY = "finished_recently"
    PAUSED = "paused"
    OFFLINE = "offline"
    AT_CAPACITY = "at_capacity"


class AgentPresence(BaseModel):
    """Runtime presence record for an agent in a project context."""

    agent_id: str
    project_id: str
    presence_status: PresenceStatus = PresenceStatus.OFFLINE
    last_activity_at: Optional[datetime] = None
    last_completed_at: Optional[datetime] = None
    active_item_count: int = 0
    capacity_max: int = 4
    current_work_item_id: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AgentPresenceResponse(BaseModel):
    """Response model enriched with agent name/slug for frontend display."""

    agent_id: str
    project_id: str
    name: str = ""
    agent_slug: Optional[str] = None
    presence_status: PresenceStatus = PresenceStatus.OFFLINE
    last_activity_at: Optional[datetime] = None
    last_completed_at: Optional[datetime] = None
    active_item_count: int = 0
    capacity_max: int = 4
    current_work_item_id: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ProjectAgentPresenceListResponse(BaseModel):
    """Response for GET /projects/{id}/agents/presence."""

    agents: List[AgentPresenceResponse]
    total: int


class UpdateAgentPresenceRequest(BaseModel):
    """Request to update an agent's presence in a project."""

    presence_status: Optional[PresenceStatus] = None
    active_item_count: Optional[int] = Field(None, ge=0)
    capacity_max: Optional[int] = Field(None, ge=1)
    current_work_item_id: Optional[str] = None


# =============================================================================
# Subscription Models
# =============================================================================

class Subscription(TimestampMixin):
    """Stripe subscription for an organization or user.

    Subscriptions can be either:
    - Org-level: org_id is set, user_id is None
    - User-level: user_id is set, org_id is None

    Billing priority: When a user works in an org context, the org subscription
    takes precedence. User subscriptions are used for user-owned projects.
    """

    id: str = Field(default_factory=lambda: f"sub-{uuid.uuid4().hex[:12]}")
    org_id: Optional[str] = None  # Set for org-level subscription
    user_id: Optional[str] = None  # Set for user-level subscription
    stripe_subscription_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    plan: OrgPlan = OrgPlan.FREE
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_subscription_owner(self) -> "Subscription":
        """Ensure exactly one of org_id or user_id is set."""
        if self.org_id and self.user_id:
            raise ValueError("Cannot set both org_id and user_id - subscription must be org-level OR user-level")
        if not self.org_id and not self.user_id:
            raise ValueError("Must set either org_id or user_id for subscription")
        return self

    class Config:
        from_attributes = True


# =============================================================================
# Usage Models
# =============================================================================

class UsageRecord(BaseModel):
    """Usage tracking for metered billing.

    Usage can be attributed to either:
    - Org-level: org_id is set (usage within org context)
    - User-level: user_id is set, org_id is None (user-owned project usage)

    When user works in org context, usage goes to org subscription.
    """

    id: str = Field(default_factory=lambda: f"usage-{uuid.uuid4().hex[:12]}")
    org_id: Optional[str] = None  # Set for org-level usage
    user_id: Optional[str] = None  # Set for user-owned project usage
    metric_name: str
    quantity: int = 0
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_usage_owner(self) -> "UsageRecord":
        """Ensure at least one of org_id or user_id is set."""
        # Note: For usage, we allow both to be set (user working in org context)
        # but at least one must be present
        if not self.org_id and not self.user_id:
            raise ValueError("Must set either org_id or user_id for usage record")
        return self

    class Config:
        from_attributes = True


class RecordUsageRequest(BaseModel):
    """Request to record usage."""

    metric_name: str
    quantity: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Response Models
# =============================================================================

class OrgWithMembers(Organization):
    """Organization with membership info."""

    members: List[OrgMembership] = Field(default_factory=list)
    member_count: int = 0


class OrgWithRole(Organization):
    """Organization with user's role (for list_user_organizations)."""

    role: MemberRole
    member_count: int = 0


class ProjectWithMembers(Project):
    """Project with membership info."""

    members: List[ProjectMembership] = Field(default_factory=list)
    member_count: int = 0


class UserOrganizations(BaseModel):
    """List of organizations a user belongs to."""

    user_id: str
    organizations: List[OrgWithMembers] = Field(default_factory=list)


class OrgContext(BaseModel):
    """Current organization context for a request."""

    org_id: str
    user_id: str
    role: MemberRole
    plan: OrgPlan
    settings: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Project Collaborator Models (for sharing user-owned projects without orgs)
# =============================================================================

class ProjectCollaborator(TimestampMixin):
    """Collaborator on a user-owned project.

    This enables users to share projects without creating an org.
    The project owner invites collaborators directly.
    """

    id: str = Field(default_factory=lambda: f"collab-{uuid.uuid4().hex[:12]}")
    project_id: str  # Must be a user-owned project (owner_id set)
    user_id: str  # The collaborator being invited
    role: ProjectRole = ProjectRole.CONTRIBUTOR
    invited_by: str  # user_id who sent the invite
    invited_at: datetime = Field(default_factory=datetime.utcnow)
    accepted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AddCollaboratorRequest(BaseModel):
    """Request to add a collaborator to a user-owned project."""

    user_id: str  # Collaborator to invite
    role: ProjectRole = ProjectRole.CONTRIBUTOR


class UpdateCollaboratorRequest(BaseModel):
    """Request to update a collaborator's role."""

    role: ProjectRole


# =============================================================================
# Billing Context Models
# =============================================================================

class BillingContext(BaseModel):
    """Resolved billing context for a user/project.

    Determines which subscription to bill based on:
    1. If working in org context (org_id set) → use org subscription
    2. If working on user-owned project → use user subscription

    Org subscription takes precedence when working in org context.
    """

    subscription_id: str
    subscription_type: str  # 'org' or 'user'
    org_id: Optional[str] = None
    user_id: str
    plan: OrgPlan
    status: SubscriptionStatus
    token_budget: int = 100000
    tokens_used: int = 0
    is_within_budget: bool = True


class ResolveBillingRequest(BaseModel):
    """Request to resolve billing context for a user."""

    user_id: str
    org_id: Optional[str] = None  # If set, org subscription takes precedence
    project_id: Optional[str] = None  # Used to determine ownership if org_id not set


# =============================================================================
# User Subscription Request Models
# =============================================================================

class CreateUserSubscriptionRequest(BaseModel):
    """Request to create a user-level subscription."""

    plan: OrgPlan = OrgPlan.FREE
    stripe_payment_method_id: Optional[str] = None


class UserWithSubscription(BaseModel):
    """User with their personal subscription info."""

    user_id: str
    subscription: Optional[Subscription] = None
    has_active_subscription: bool = False
    plan: OrgPlan = OrgPlan.FREE


# =============================================================================
# Invitation Models
# =============================================================================

class InvitationStatus(str, Enum):
    """Invitation lifecycle status."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class InvitationChannel(str, Enum):
    """Channel through which invitation was sent."""
    EMAIL = "email"
    SLACK = "slack"
    SMS = "sms"
    LINK = "link"  # Copy-link for manual sharing


class Invitation(TimestampMixin):
    """Organization invitation entity."""

    id: str = Field(default_factory=lambda: f"inv-{uuid.uuid4().hex[:12]}")
    org_id: str
    email: str = Field(..., description="Email address of invitee")
    role: MemberRole = MemberRole.MEMBER
    status: InvitationStatus = InvitationStatus.PENDING
    token: str = Field(default_factory=lambda: uuid.uuid4().hex)
    channel: InvitationChannel = InvitationChannel.EMAIL

    invited_by: str  # User ID who sent invitation
    expires_at: datetime
    accepted_at: Optional[datetime] = None
    accepted_by: Optional[str] = None  # User ID who accepted

    message: Optional[str] = None  # Optional personal message
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class CreateInvitationRequest(BaseModel):
    """Request to create an invitation."""

    email: str = Field(..., description="Email address of invitee")
    role: MemberRole = MemberRole.MEMBER
    channel: InvitationChannel = InvitationChannel.EMAIL
    message: Optional[str] = Field(None, max_length=500, description="Personal message to include")
    expires_in_days: int = Field(default=7, ge=1, le=30, description="Days until expiration")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class InvitationEvent(BaseModel):
    """Event tracking invitation lifecycle changes."""

    id: str = Field(default_factory=lambda: f"iev-{uuid.uuid4().hex[:12]}")
    invitation_id: str
    event_type: str  # 'created', 'sent', 'viewed', 'accepted', 'expired', 'revoked'
    actor_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class InvitationWithOrg(BaseModel):
    """Invitation with organization details for display."""

    invitation: Invitation
    org_name: str
    org_slug: str
    inviter_name: Optional[str] = None


class AcceptInvitationRequest(BaseModel):
    """Request to accept an invitation."""

    token: str = Field(..., description="Invitation token from link")
    user_id: str = Field(..., description="User ID accepting the invitation")


class InvitationListResponse(BaseModel):
    """Response for listing invitations."""

    invitations: List[Invitation]
    total: int
    pending_count: int
    page_info: Optional[PageInfo] = None
