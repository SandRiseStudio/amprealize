# Multi-Tenant Platform Architecture

> **Status:** Epic 13 - Multi-Tenant Platform
> **Author:** Amprealize Platform Team
> **Created:** 2025-12-02
> **Last Updated:** 2025-12-02

## Table of Contents

- [Overview](#overview)
- [Core Concepts](#core-concepts)
- [Database Strategy](#database-strategy)
- [Organization Model](#organization-model)
- [Project Model](#project-model)
- [User & Membership Model](#user--membership-model)
- [Agent Identity Model](#agent-identity-model)
- [Billing & Subscriptions](#billing--subscriptions)
- [Agile Board System](#agile-board-system)
- [API Design](#api-design)
- [MCP Tools](#mcp-tools)
- [Security Considerations](#security-considerations)
- [Migration Strategy](#migration-strategy)

---

## Overview

The Multi-Tenant Platform transforms Amprealize from a single-user tool into an enterprise-ready platform supporting multiple organizations, projects, teams, and billing tiers. This document defines the architectural foundation for:

- **Organizations** - Top-level tenant isolation with PostgreSQL schema-per-tenant
- **Projects** - Workspaces within organizations for logical separation
- **Users & Teams** - Role-based membership with RBAC permissions
- **Agents as First-Class Members** - Agents have their own identity and can be assigned to tasks
- **Billing & Subscriptions** - Stripe-integrated subscription management with usage metering
- **Agile Boards** - Full project management with epics, stories, tasks, and sprints

### Design Principles

1. **Schema-per-Tenant Isolation** - Each organization gets its own PostgreSQL schema for strongest data isolation
2. **Agents as Board Members** - Agents are first-class participants, assignable to stories and tasks
3. **Real-Time Collaboration** - WebSocket for board interactions, SSE for run progress
4. **Cross-Surface Parity** - All features available via API, MCP, CLI, and Web UI
5. **Usage-Based Billing** - Metered billing tied to token consumption and agent runs

---

## Core Concepts

### Entity Hierarchy

```
Organization (Tenant)
├── Billing / Subscription
├── Members (Users + Agents)
│   ├── User Members
│   └── Agent Members (first-class)
├── Projects
│   ├── Project Members (subset of org members)
│   ├── Boards
│   │   ├── Columns
│   │   ├── Epics
│   │   │   └── Stories
│   │   │       └── Tasks
│   │   └── Sprints
│   ├── Runs (linked to tasks)
│   └── Behaviors (project-scoped)
└── Settings / Integrations
```

### Key Relationships

| Entity | Belongs To | Contains |
|--------|-----------|----------|
| Organization | - | Projects, Members, Subscription |
| Project | Organization | Boards, Runs, Behaviors |
| Board | Project | Columns, Epics, Stories, Tasks, Sprints |
| Epic | Board | Stories |
| Story | Epic, Sprint | Tasks |
| Task | Story | Subtasks, Comments |
| Sprint | Board | Stories |
| Agent | Organization | Task Assignments, Run Executions |

---

## Database Strategy

### PostgreSQL Schema-Per-Tenant

Each organization receives its own PostgreSQL schema, providing:

- **Strong Isolation** - No cross-tenant data leakage risk
- **Performance** - Per-tenant query optimization and indexing
- **Compliance** - Easy data export/deletion for GDPR
- **Migration Flexibility** - Per-tenant schema versions possible

```sql
-- Schema naming convention
CREATE SCHEMA org_<org_id>;  -- e.g., org_abc123

-- Example: organization-specific tables
CREATE TABLE org_abc123.projects (
    project_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Shared/global tables remain in 'public' schema
CREATE TABLE public.organizations (
    org_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    schema_name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Schema Lifecycle

```python
class TenantSchemaManager:
    """Manages PostgreSQL schema lifecycle for tenants."""

    async def create_tenant_schema(self, org_id: str) -> str:
        """Create isolated schema for new organization."""
        schema_name = f"org_{org_id.replace('-', '_')}"

        async with self.pool.acquire() as conn:
            # Create schema
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")

            # Apply tenant migrations
            await self._apply_tenant_migrations(conn, schema_name)

            # Set up RLS policies as additional safety layer
            await self._setup_rls_policies(conn, schema_name, org_id)

        return schema_name

    async def drop_tenant_schema(self, schema_name: str):
        """Drop tenant schema (data deletion for compliance)."""
        async with self.pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
```

### Connection Management

```python
class TenantConnectionPool:
    """Connection pool with automatic schema switching."""

    def __init__(self, base_dsn: str):
        self.base_dsn = base_dsn
        self._pools: Dict[str, asyncpg.Pool] = {}

    async def get_tenant_connection(self, org_id: str) -> asyncpg.Connection:
        """Get connection with search_path set to tenant schema."""
        schema_name = f"org_{org_id.replace('-', '_')}"

        pool = await self._get_or_create_pool(org_id)
        conn = await pool.acquire()

        # Set schema context
        await conn.execute(f"SET search_path TO {schema_name}, public")

        return conn
```

---

## Organization Model

### Organization Entity

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from enum import Enum

class OrganizationPlan(str, Enum):
    FREE = "free"
    STARTER = "starter"
    TEAM = "team"
    ENTERPRISE = "enterprise"

class Organization(BaseModel):
    """Top-level tenant entity."""
    org_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    slug: str  # URL-friendly identifier
    schema_name: str  # PostgreSQL schema
    plan: OrganizationPlan = OrganizationPlan.FREE

    # Settings
    settings: dict = Field(default_factory=dict)

    # Billing
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Limits (based on plan)
    max_projects: int = 3
    max_members: int = 5
    max_agents: int = 1
    monthly_token_budget: int = 100_000
```

### Organization Service

```python
class OrganizationService:
    """Manages organization lifecycle and membership."""

    async def create_organization(
        self,
        name: str,
        slug: str,
        owner_user_id: str,
        plan: OrganizationPlan = OrganizationPlan.FREE
    ) -> Organization:
        """Create new organization with isolated schema."""
        org = Organization(name=name, slug=slug, plan=plan)
        org.schema_name = await self.schema_manager.create_tenant_schema(org.org_id)

        # Store in public.organizations
        await self._persist_organization(org)

        # Add owner as admin member
        await self.add_member(org.org_id, owner_user_id, role=MemberRole.ADMIN)

        # Initialize billing
        if plan != OrganizationPlan.FREE:
            await self.billing_service.create_customer(org)

        return org

    async def delete_organization(self, org_id: str):
        """Delete organization and all associated data."""
        org = await self.get_organization(org_id)

        # Cancel subscription
        if org.stripe_subscription_id:
            await self.billing_service.cancel_subscription(org.stripe_subscription_id)

        # Drop schema (cascades all data)
        await self.schema_manager.drop_tenant_schema(org.schema_name)

        # Remove from public.organizations
        await self._delete_organization_record(org_id)
```

---

## Project Model

### Project Entity

```python
class ProjectVisibility(str, Enum):
    PRIVATE = "private"  # Only project members
    INTERNAL = "internal"  # All org members
    PUBLIC = "public"  # Anyone (read-only for non-members)

class Project(BaseModel):
    """Workspace within an organization."""
    project_id: str = Field(default_factory=lambda: str(uuid4()))
    org_id: str
    name: str
    slug: str
    description: Optional[str] = None
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE

    # Project settings
    default_branch: str = "main"
    settings: dict = Field(default_factory=dict)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    archived_at: Optional[datetime] = None
```

### Project Service

```python
class ProjectService:
    """Manages projects within organizations."""

    async def create_project(
        self,
        org_id: str,
        name: str,
        slug: str,
        creator_user_id: str,
        visibility: ProjectVisibility = ProjectVisibility.PRIVATE
    ) -> Project:
        """Create new project in organization schema."""
        # Validate org limits
        org = await self.org_service.get_organization(org_id)
        current_count = await self._count_projects(org_id)
        if current_count >= org.max_projects:
            raise QuotaExceededError(f"Organization limit: {org.max_projects} projects")

        project = Project(
            org_id=org_id,
            name=name,
            slug=slug,
            visibility=visibility
        )

        # Store in tenant schema
        async with self.pool.get_tenant_connection(org_id) as conn:
            await conn.execute("""
                INSERT INTO projects (project_id, name, slug, description, visibility)
                VALUES ($1, $2, $3, $4, $5)
            """, project.project_id, name, slug, project.description, visibility.value)

        # Add creator as project admin
        await self.add_project_member(project.project_id, creator_user_id, role=ProjectRole.ADMIN)

        # Create default board
        await self.board_service.create_board(project.project_id, name="Main Board")

        return project
```

---

## User & Membership Model

### Membership Hierarchy

```
Organization Membership
├── Role: admin | member | viewer | billing
└── Grants access to all org resources

Project Membership (optional, for PRIVATE projects)
├── Role: admin | maintainer | developer | viewer
└── Grants access to specific project
```

### Membership Entities

```python
class MemberRole(str, Enum):
    ADMIN = "admin"  # Full control
    MEMBER = "member"  # Create/edit
    VIEWER = "viewer"  # Read-only
    BILLING = "billing"  # Billing only

class ProjectRole(str, Enum):
    ADMIN = "admin"  # Project settings
    MAINTAINER = "maintainer"  # Merge, release
    DEVELOPER = "developer"  # Edit, comment
    VIEWER = "viewer"  # Read-only

class OrgMembership(BaseModel):
    """User membership in an organization."""
    membership_id: str = Field(default_factory=lambda: str(uuid4()))
    org_id: str
    user_id: str
    role: MemberRole
    invited_by: Optional[str] = None
    invited_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ProjectMembership(BaseModel):
    """User membership in a project (for PRIVATE projects)."""
    membership_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    user_id: str
    role: ProjectRole
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

---

## Agent Identity Model

### Agents as First-Class Board Members

Agents in Amprealize are first-class participants with their own identity, capable of:

- Being assigned to stories and tasks
- Executing runs linked to board items
- Having their own activity history and metrics
- Participating in sprint planning (AI suggestions)

```python
class AgentType(str, Enum):
    CODER = "coder"  # Code generation, refactoring
    REVIEWER = "reviewer"  # Code review, compliance
    PLANNER = "planner"  # Task breakdown, estimation
    TESTER = "tester"  # Test generation, execution
    DOCUMENTER = "documenter"  # Documentation generation
    CUSTOM = "custom"  # User-defined capabilities

class AgentStatus(str, Enum):
    ACTIVE = "active"
    BUSY = "busy"  # Currently executing
    PAUSED = "paused"
    DISABLED = "disabled"

class Agent(BaseModel):
    """First-class agent identity within an organization."""
    agent_id: str = Field(default_factory=lambda: str(uuid4()))
    org_id: str
    name: str  # e.g., "CodeBot", "ReviewerAgent"
    agent_type: AgentType
    status: AgentStatus = AgentStatus.ACTIVE

    # Capabilities
    capabilities: List[str] = Field(default_factory=list)  # behavior IDs
    max_concurrent_tasks: int = 3

    # Configuration
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    temperature: float = 0.7
    token_budget_per_task: int = 50_000

    # Metrics
    total_tasks_completed: int = 0
    total_tokens_used: int = 0
    average_task_duration_seconds: float = 0.0

    # Metadata
    created_by: str  # user_id
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

### Agent Assignment

```python
class AssigneeType(str, Enum):
    USER = "user"
    AGENT = "agent"

class TaskAssignment(BaseModel):
    """Assignment of user or agent to a task/story."""
    assignment_id: str = Field(default_factory=lambda: str(uuid4()))
    assignable_id: str  # task_id or story_id
    assignable_type: str  # "task" or "story"
    assignee_id: str  # user_id or agent_id
    assignee_type: AssigneeType
    assigned_by: str  # user_id
    assigned_at: datetime = Field(default_factory=datetime.utcnow)

    # For agents - link to execution
    run_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

---

## Billing & Subscriptions

### Subscription Plans

| Plan | Price | Projects | Members | Agents | Tokens/Month |
|------|-------|----------|---------|--------|--------------|
| Free | $0 | 3 | 5 | 1 | 100K |
| Starter | $29/mo | 10 | 15 | 3 | 500K |
| Team | $99/mo | Unlimited | 50 | 10 | 2M |
| Enterprise | Custom | Unlimited | Unlimited | Unlimited | Custom |

### Subscription Entity

```python
class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    TRIALING = "trialing"

class Subscription(BaseModel):
    """Organization subscription managed via Stripe."""
    subscription_id: str = Field(default_factory=lambda: str(uuid4()))
    org_id: str
    stripe_subscription_id: str
    stripe_customer_id: str
    plan: OrganizationPlan
    status: SubscriptionStatus

    # Billing cycle
    current_period_start: datetime
    current_period_end: datetime

    # Usage tracking
    tokens_used_this_period: int = 0
    runs_this_period: int = 0

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

### Billing Service

```python
class BillingService:
    """Stripe-integrated billing management."""

    def __init__(self):
        self.stripe = stripe
        self.stripe.api_key = settings.stripe_secret_key

    async def create_subscription(
        self,
        org: Organization,
        plan: OrganizationPlan,
        payment_method_id: str
    ) -> Subscription:
        """Create new Stripe subscription."""
        # Get or create Stripe customer
        if not org.stripe_customer_id:
            customer = self.stripe.Customer.create(
                metadata={"org_id": org.org_id}
            )
            org.stripe_customer_id = customer.id

        # Attach payment method
        self.stripe.PaymentMethod.attach(
            payment_method_id,
            customer=org.stripe_customer_id
        )

        # Create subscription
        stripe_sub = self.stripe.Subscription.create(
            customer=org.stripe_customer_id,
            items=[{"price": self._get_price_id(plan)}],
            expand=["latest_invoice.payment_intent"]
        )

        return Subscription(
            org_id=org.org_id,
            stripe_subscription_id=stripe_sub.id,
            stripe_customer_id=org.stripe_customer_id,
            plan=plan,
            status=SubscriptionStatus(stripe_sub.status),
            current_period_start=datetime.fromtimestamp(stripe_sub.current_period_start),
            current_period_end=datetime.fromtimestamp(stripe_sub.current_period_end)
        )

    async def record_usage(self, org_id: str, tokens_used: int):
        """Record metered usage for billing."""
        subscription = await self.get_subscription(org_id)

        # Update local tracking
        subscription.tokens_used_this_period += tokens_used
        await self._persist_subscription(subscription)

        # Report to Stripe for metered billing (Enterprise)
        if subscription.plan == OrganizationPlan.ENTERPRISE:
            self.stripe.SubscriptionItem.create_usage_record(
                subscription.stripe_subscription_id,
                quantity=tokens_used,
                timestamp=int(datetime.utcnow().timestamp())
            )
```

### Stripe Webhook Handler

```python
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    event = stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )

    match event.type:
        case "customer.subscription.created":
            await billing_service.handle_subscription_created(event.data.object)
        case "customer.subscription.updated":
            await billing_service.handle_subscription_updated(event.data.object)
        case "customer.subscription.deleted":
            await billing_service.handle_subscription_deleted(event.data.object)
        case "invoice.payment_failed":
            await billing_service.handle_payment_failed(event.data.object)
        case "invoice.paid":
            await billing_service.handle_invoice_paid(event.data.object)

    return {"status": "ok"}
```

---

## Agile Board System

### Board Entities

```python
class Board(BaseModel):
    """Agile board within a project."""
    board_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    name: str
    description: Optional[str] = None
    is_default: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

class BoardColumn(BaseModel):
    """Column in a board (e.g., To Do, In Progress, Done)."""
    column_id: str = Field(default_factory=lambda: str(uuid4()))
    board_id: str
    name: str
    position: int  # 0-indexed ordering
    wip_limit: Optional[int] = None  # Work-in-progress limit
    color: str = "#6366f1"  # Indigo default

class Epic(BaseModel):
    """Large feature or initiative containing stories."""
    epic_id: str = Field(default_factory=lambda: str(uuid4()))
    board_id: str
    title: str
    description: Optional[str] = None
    color: str = "#8b5cf6"  # Purple default
    status: str = "open"  # open, in_progress, done
    start_date: Optional[date] = None
    target_date: Optional[date] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Story(BaseModel):
    """User story that can be assigned to users or agents."""
    story_id: str = Field(default_factory=lambda: str(uuid4()))
    board_id: str
    epic_id: Optional[str] = None
    sprint_id: Optional[str] = None
    column_id: str  # Current board column

    title: str
    description: Optional[str] = None
    acceptance_criteria: List[str] = Field(default_factory=list)

    # Assignment (polymorphic - user or agent)
    assignee_id: Optional[str] = None
    assignee_type: Optional[AssigneeType] = None

    # Estimation
    story_points: Optional[int] = None
    priority: int = 3  # 1=highest, 5=lowest

    # Labels/tags
    labels: List[str] = Field(default_factory=list)

    # Metadata
    reporter_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Task(BaseModel):
    """Subtask within a story."""
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    story_id: str

    title: str
    description: Optional[str] = None

    # Assignment (polymorphic - user or agent)
    assignee_id: Optional[str] = None
    assignee_type: Optional[AssigneeType] = None

    # Status
    status: str = "todo"  # todo, in_progress, done

    # Link to agent execution
    run_id: Optional[str] = None

    # Time tracking
    estimated_hours: Optional[float] = None
    logged_hours: float = 0.0

    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

class Sprint(BaseModel):
    """Time-boxed iteration for stories."""
    sprint_id: str = Field(default_factory=lambda: str(uuid4()))
    board_id: str
    name: str  # e.g., "Sprint 23"
    goal: Optional[str] = None

    start_date: date
    end_date: date

    status: str = "planned"  # planned, active, completed

    # Velocity tracking
    committed_points: int = 0
    completed_points: int = 0

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Board Service

```python
class BoardService:
    """Manages agile boards, stories, and tasks."""

    async def create_board(
        self,
        project_id: str,
        name: str,
        columns: Optional[List[str]] = None
    ) -> Board:
        """Create board with default columns."""
        columns = columns or ["Backlog", "To Do", "In Progress", "Review", "Done"]

        board = Board(project_id=project_id, name=name)
        await self._persist_board(board)

        # Create columns
        for i, col_name in enumerate(columns):
            column = BoardColumn(
                board_id=board.board_id,
                name=col_name,
                position=i
            )
            await self._persist_column(column)

        return board

    async def move_story(
        self,
        story_id: str,
        target_column_id: str,
        position: Optional[int] = None
    ) -> Story:
        """Move story to different column (drag-and-drop)."""
        story = await self.get_story(story_id)
        old_column_id = story.column_id

        # Check WIP limit
        target_column = await self.get_column(target_column_id)
        if target_column.wip_limit:
            current_count = await self._count_stories_in_column(target_column_id)
            if current_count >= target_column.wip_limit:
                raise WipLimitExceededError(f"Column WIP limit: {target_column.wip_limit}")

        # Update story
        story.column_id = target_column_id
        story.updated_at = datetime.utcnow()
        await self._persist_story(story)

        # Emit WebSocket event
        await self.websocket_hub.broadcast(
            f"board:{story.board_id}",
            {
                "type": "story_moved",
                "story_id": story_id,
                "from_column": old_column_id,
                "to_column": target_column_id
            }
        )

        return story

    async def assign_to_agent(
        self,
        assignable_id: str,
        assignable_type: str,  # "story" or "task"
        agent_id: str,
        assigner_id: str
    ) -> TaskAssignment:
        """Assign story or task to an agent."""
        agent = await self.agent_service.get_agent(agent_id)

        # Check agent availability
        if agent.status == AgentStatus.DISABLED:
            raise AgentUnavailableError(f"Agent {agent.name} is disabled")

        current_assignments = await self._count_agent_active_assignments(agent_id)
        if current_assignments >= agent.max_concurrent_tasks:
            raise AgentBusyError(f"Agent {agent.name} at capacity ({agent.max_concurrent_tasks} tasks)")

        assignment = TaskAssignment(
            assignable_id=assignable_id,
            assignable_type=assignable_type,
            assignee_id=agent_id,
            assignee_type=AssigneeType.AGENT,
            assigned_by=assigner_id
        )

        # Update the story/task
        if assignable_type == "story":
            story = await self.get_story(assignable_id)
            story.assignee_id = agent_id
            story.assignee_type = AssigneeType.AGENT
            await self._persist_story(story)
        else:
            task = await self.get_task(assignable_id)
            task.assignee_id = agent_id
            task.assignee_type = AssigneeType.AGENT
            await self._persist_task(task)

        await self._persist_assignment(assignment)

        # Emit event for agent to pick up
        await self.event_bus.publish(
            "agent.task.assigned",
            {
                "assignment_id": assignment.assignment_id,
                "agent_id": agent_id,
                "assignable_id": assignable_id,
                "assignable_type": assignable_type
            }
        )

        return assignment
```

---

## API Design

### REST Endpoints

```yaml
# Organizations
POST   /v1/orgs                       # Create organization
GET    /v1/orgs                       # List user's organizations
GET    /v1/orgs/{org_id}              # Get organization details
PATCH  /v1/orgs/{org_id}              # Update organization
DELETE /v1/orgs/{org_id}              # Delete organization

# Organization Members
GET    /v1/orgs/{org_id}/members      # List members
POST   /v1/orgs/{org_id}/members      # Invite member
PATCH  /v1/orgs/{org_id}/members/{id} # Update member role
DELETE /v1/orgs/{org_id}/members/{id} # Remove member

# Projects
POST   /v1/orgs/{org_id}/projects           # Create project
GET    /v1/orgs/{org_id}/projects           # List projects
GET    /v1/projects/{project_id}            # Get project
PATCH  /v1/projects/{project_id}            # Update project
DELETE /v1/projects/{project_id}            # Delete project

# Boards
POST   /v1/projects/{project_id}/boards     # Create board
GET    /v1/projects/{project_id}/boards     # List boards
GET    /v1/boards/{board_id}                # Get board with columns
PATCH  /v1/boards/{board_id}                # Update board

# Epics
POST   /v1/boards/{board_id}/epics          # Create epic
GET    /v1/boards/{board_id}/epics          # List epics
PATCH  /v1/epics/{epic_id}                  # Update epic

# Stories
POST   /v1/boards/{board_id}/stories        # Create story
GET    /v1/boards/{board_id}/stories        # List stories (with filters)
PATCH  /v1/stories/{story_id}               # Update story
POST   /v1/stories/{story_id}/move          # Move story to column
POST   /v1/stories/{story_id}/assign        # Assign to user/agent

# Tasks
POST   /v1/stories/{story_id}/tasks         # Create task
GET    /v1/stories/{story_id}/tasks         # List tasks
PATCH  /v1/tasks/{task_id}                  # Update task
POST   /v1/tasks/{task_id}/assign           # Assign to user/agent

# Sprints
POST   /v1/boards/{board_id}/sprints        # Create sprint
GET    /v1/boards/{board_id}/sprints        # List sprints
PATCH  /v1/sprints/{sprint_id}              # Update sprint
POST   /v1/sprints/{sprint_id}/start        # Start sprint
POST   /v1/sprints/{sprint_id}/complete     # Complete sprint

# Agents
POST   /v1/orgs/{org_id}/agents             # Create agent
GET    /v1/orgs/{org_id}/agents             # List agents
PATCH  /v1/agents/{agent_id}                # Update agent
GET    /v1/agents/{agent_id}/assignments    # Get agent's assignments

# Billing
GET    /v1/orgs/{org_id}/subscription       # Get subscription
POST   /v1/orgs/{org_id}/subscription       # Create/update subscription
GET    /v1/orgs/{org_id}/usage              # Get usage metrics
GET    /v1/orgs/{org_id}/invoices           # List invoices
```

### WebSocket Events (Board Real-Time)

```typescript
// Client connects to board channel
ws.connect(`/ws/boards/{board_id}`)

// Server → Client events
interface BoardEvent {
  type:
    | "story_created"
    | "story_updated"
    | "story_moved"
    | "story_deleted"
    | "task_created"
    | "task_updated"
    | "task_completed"
    | "sprint_started"
    | "sprint_completed"
    | "agent_assigned"
    | "agent_progress"  // Agent execution progress
    | "member_joined"
    | "member_left";
  payload: Record<string, any>;
  timestamp: string;
  actor: {
    id: string;
    type: "user" | "agent";
    name: string;
  };
}

// Client → Server events
interface ClientEvent {
  type:
    | "move_story"
    | "update_task"
    | "cursor_position"  // For collaborative presence
    | "typing";
  payload: Record<string, any>;
}
```

---

## MCP Tools

### Organization Tools

```json
// mcp/tools/orgs.create.json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "name": "orgs.create",
  "description": "Create a new organization",
  "inputSchema": {
    "type": "object",
    "properties": {
      "name": {"type": "string"},
      "slug": {"type": "string", "pattern": "^[a-z0-9-]+$"},
      "plan": {"enum": ["free", "starter", "team", "enterprise"]}
    },
    "required": ["name", "slug"]
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "org_id": {"type": "string"},
      "name": {"type": "string"},
      "slug": {"type": "string"},
      "schema_name": {"type": "string"}
    }
  }
}
```

### Board Tools

```json
// mcp/tools/boards.moveStory.json
{
  "name": "boards.moveStory",
  "description": "Move a story to a different column",
  "inputSchema": {
    "type": "object",
    "properties": {
      "story_id": {"type": "string"},
      "target_column_id": {"type": "string"},
      "position": {"type": "integer", "minimum": 0}
    },
    "required": ["story_id", "target_column_id"]
  }
}

// mcp/tools/boards.assignAgent.json
{
  "name": "boards.assignAgent",
  "description": "Assign an agent to a story or task",
  "inputSchema": {
    "type": "object",
    "properties": {
      "assignable_type": {"enum": ["story", "task"]},
      "assignable_id": {"type": "string"},
      "agent_id": {"type": "string"}
    },
    "required": ["assignable_type", "assignable_id", "agent_id"]
  }
}
```

---

## Security Considerations

### Tenant Isolation

1. **Schema Isolation** - Each tenant's data in separate PostgreSQL schema
2. **Connection Scoping** - `search_path` set per request
3. **RLS Backup** - Row-Level Security as defense-in-depth
4. **Audit Logging** - All cross-tenant operations logged

### Authorization Model

```python
class Permission(str, Enum):
    # Organization
    ORG_READ = "org:read"
    ORG_WRITE = "org:write"
    ORG_ADMIN = "org:admin"
    ORG_BILLING = "org:billing"

    # Project
    PROJECT_READ = "project:read"
    PROJECT_WRITE = "project:write"
    PROJECT_ADMIN = "project:admin"

    # Board
    BOARD_READ = "board:read"
    BOARD_WRITE = "board:write"
    BOARD_ADMIN = "board:admin"

    # Agent
    AGENT_CREATE = "agent:create"
    AGENT_ASSIGN = "agent:assign"
    AGENT_ADMIN = "agent:admin"

ROLE_PERMISSIONS = {
    MemberRole.ADMIN: {Permission.ORG_ADMIN, Permission.PROJECT_ADMIN, Permission.BOARD_ADMIN, Permission.AGENT_ADMIN},
    MemberRole.MEMBER: {Permission.ORG_READ, Permission.PROJECT_WRITE, Permission.BOARD_WRITE, Permission.AGENT_ASSIGN},
    MemberRole.VIEWER: {Permission.ORG_READ, Permission.PROJECT_READ, Permission.BOARD_READ},
    MemberRole.BILLING: {Permission.ORG_READ, Permission.ORG_BILLING},
}
```

---

## Migration Strategy

### Phase 1: Schema Infrastructure (Week 1-2)

1. Create `public.organizations` table
2. Implement `TenantSchemaManager`
3. Migrate existing data to default org schema
4. Add `org_id` context to all service calls

### Phase 2: Organization & Project Services (Week 3-4)

1. Implement `OrganizationService`
2. Implement `ProjectService`
3. Add membership management
4. Update all existing services with tenant context

### Phase 3: Billing Integration (Week 5-6)

1. Set up Stripe integration
2. Implement `BillingService`
3. Add webhook handlers
4. Create billing dashboard UI

### Phase 4: Agent Identity (Week 7-8)

1. Implement `Agent` entity and service
2. Update `TaskAssignment` for polymorphic assignment
3. Integrate with `RunService` for agent executions
4. Add agent metrics and dashboards

### Phase 5: Agile Boards (Week 9-12)

1. Implement `BoardService`
2. Create board UI components
3. Add WebSocket real-time updates
4. Implement sprint management

---

## Related Documents

- [`WEB_UI_DESIGN.md`](./WEB_UI_DESIGN.md) - Modern web frontend architecture
- [`WORK_STRUCTURE.md`](../WORK_STRUCTURE.md) - Epic 13 tracking
- [`MCP_SERVER_DESIGN.md`](contracts/MCP_SERVER_DESIGN.md) - MCP tool patterns
- [`BEHAVIOR_SERVICE_CONTRACT.md`](contracts/BEHAVIOR_SERVICE_CONTRACT.md) - Service contract patterns

---

*Document created: 2025-12-02*
*Behaviors referenced: `behavior_design_api_contract`, `behavior_migrate_postgres_schema`, `behavior_extract_standalone_package`*
