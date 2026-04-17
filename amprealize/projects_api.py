"""Project REST API routes.

Projects are a single resource type with a required owner (`owner_id`) and an
optional organization (`org_id`).

This module provides `/v1/projects` list/create and `/v1/projects/agents` for
project-level agent assignments.

Following:
- behavior_lock_down_security_surface (Student): require auth; avoid leaking cross-user data.
- behavior_align_storage_layers (Student): persist to PostgreSQL for board FK integrity.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
import re

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

if TYPE_CHECKING:
    from amprealize.multi_tenant.organization_service import OrganizationService

from amprealize.perf_log import perf_span
from amprealize.projects.contracts import (
    Agent,
    AgentType,
    AgentPresenceResponse,
    PresenceStatus,
    ProjectAgentAssignmentResponse,
    ProjectAgentPresenceListResponse,
    ProjectAgentRole,
    UpdateAgentPresenceRequest,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(value: str) -> str:
    slug = value.strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = _SLUG_RE.sub("", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or f"proj-{uuid.uuid4().hex[:8]}"


class ProjectDTO(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    visibility: str = "private"
    settings: Dict[str, object] = Field(default_factory=dict)
    org_id: Optional[str] = None
    owner_id: Optional[str] = None
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    items: List[ProjectDTO]


class CreateProjectBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    visibility: str = "private"
    org_id: Optional[str] = None


class ProjectAgentListResponse(BaseModel):
    """Response for listing project-agent assignments.

    Note: Uses ProjectAgentAssignmentResponse for proper junction table pattern.
    The 'agents' field name is kept for backward compatibility with frontend.
    """
    agents: List[ProjectAgentAssignmentResponse]
    total: int


class ProjectParticipantDTO(BaseModel):
    id: str
    kind: str
    role: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None

    user_id: Optional[str] = None
    membership_source: Optional[str] = None

    agent_id: Optional[str] = None
    agent_slug: Optional[str] = None
    description: Optional[str] = None
    assignment_status: Optional[str] = None
    presence: Optional[str] = None


class ProjectParticipantTotals(BaseModel):
    total: int
    humans: int
    agents: int


class ProjectParticipantListResponse(BaseModel):
    items: List[ProjectParticipantDTO]
    totals: ProjectParticipantTotals


class CreateProjectAgentBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    project_id: str = Field(..., min_length=1)
    agent_type: AgentType = AgentType.SPECIALIST
    config: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)


def _project_to_dto(project) -> ProjectDTO:
    """Convert a contracts.Project to the REST DTO."""
    return ProjectDTO(
        id=project.id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        visibility=project.visibility.value if hasattr(project.visibility, "value") else str(project.visibility),
        settings=project.settings or {},
        org_id=project.org_id,
        owner_id=project.owner_id,
        created_at=project.created_at.isoformat() if project.created_at else "",
        updated_at=project.updated_at.isoformat() if project.updated_at else "",
    )


def create_project_routes(
    *,
    org_service: "OrganizationService",
    get_user_id: Callable[[Request], str],
    tags: Optional[List[str]] = None,
) -> APIRouter:
    """Create REST routes for unified project management.

    All project operations go through OrganizationService — the single
    authoritative store for projects.
    """
    router = APIRouter(prefix="/v1/projects", tags=tags or ["projects"])

    @router.get("", response_model=ProjectListResponse)
    async def list_projects(request: Request, org_id: Optional[str] = Query(default=None)) -> ProjectListResponse:
        user_id = get_user_id(request)
        with perf_span("projects.list") as span:
            projects = await run_in_threadpool(
                org_service.list_projects, owner_id=user_id, org_id=org_id
            )
            span["item_count"] = len(projects)
            return ProjectListResponse(items=[_project_to_dto(p) for p in projects])

    @router.post("", response_model=ProjectDTO, status_code=status.HTTP_201_CREATED)
    async def create_project(request: Request, body: CreateProjectBody) -> ProjectDTO:
        user_id = get_user_id(request)

        if body.org_id is not None and not body.org_id.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="org_id cannot be empty")

        with perf_span("projects.create"):
            try:
                project = await run_in_threadpool(
                    org_service.create_project,
                    name=body.name,
                    owner_id=user_id,
                    org_id=body.org_id,
                    slug=body.slug,
                    description=body.description,
                    visibility=body.visibility or "private",
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

            return _project_to_dto(project)

    # -------------------------------------------------------------------------
    # /agents routes MUST be defined BEFORE /{project_id} to avoid route conflict
    # (FastAPI matches routes in order; /{project_id} would match "agents" as a project_id)
    # -------------------------------------------------------------------------

    async def _require_project_access(user_id: str, project_id: str):
        """Verify the user owns or has membership to the project."""
        project = await run_in_threadpool(org_service.get_project, project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        if project.owner_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        return project

    @router.get("/agents", response_model=ProjectAgentListResponse)
    async def list_project_agents(
        request: Request,
        project_id: Optional[str] = Query(default=None),
    ) -> ProjectAgentListResponse:
        """List agent assignments for projects owned by the requesting user."""
        user_id = get_user_id(request)
        with perf_span("projects.list_agents") as span:
            if project_id:
                await _require_project_access(user_id, project_id)
            assignments = await run_in_threadpool(
                org_service.list_user_project_agent_assignments,
                owner_id=user_id,
                project_id=project_id,
            )
            span["item_count"] = len(assignments)
            return ProjectAgentListResponse(agents=assignments, total=len(assignments))

    @router.post("/agents", response_model=ProjectAgentAssignmentResponse, status_code=status.HTTP_201_CREATED)
    async def create_project_agent(request: Request, body: CreateProjectAgentBody) -> ProjectAgentAssignmentResponse:
        """Assign a registry agent to a project."""
        user_id = get_user_id(request)
        await _require_project_access(user_id, body.project_id)

        registry_agent_id = body.config.get("registry_agent_id")
        if not registry_agent_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="config.registry_agent_id is required",
            )

        with perf_span("projects.create_agent"):
            try:
                assignment = await run_in_threadpool(
                    org_service.assign_registry_agent_to_project,
                    project_id=body.project_id,
                    agent_id=registry_agent_id,
                    assigned_by=user_id,
                    config_overrides=body.config,
                    role=ProjectAgentRole.PRIMARY,
                )

                assignments = await run_in_threadpool(
                    org_service.list_project_agent_assignments, body.project_id
                )
                return next((a for a in assignments if a.id == assignment.id), assignment)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc

    @router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_project_agent(request: Request, agent_id: str) -> None:
        """Remove an agent assignment."""
        user_id = get_user_id(request)
        with perf_span("projects.delete_agent"):
            removed = await run_in_threadpool(
                org_service.remove_project_agent_assignment,
                assignment_id=agent_id,
                removed_by=user_id,
            )
            if not removed:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent assignment {agent_id} not found",
                )

    @router.get("/{project_id}/participants", response_model=ProjectParticipantListResponse)
    async def list_project_participants(
        request: Request,
        project_id: str,
    ) -> ProjectParticipantListResponse:
        """List project-scoped participants across humans and agents."""
        user_id = get_user_id(request)
        project = await _require_project_access(user_id, project_id)

        with perf_span("projects.list_participants") as span:
            if hasattr(org_service, "list_project_participants"):
                raw_items = await run_in_threadpool(
                    org_service.list_project_participants, project_id
                )
            else:
                raw_items = [{
                    "id": project.owner_id,
                    "kind": "human",
                    "user_id": project.owner_id,
                    "display_name": None,
                    "email": None,
                    "role": "owner",
                    "membership_source": "owner",
                }]
                legacy_assignments = await run_in_threadpool(
                    org_service.list_project_agent_assignments, project_id
                )
                for assignment in legacy_assignments:
                    if getattr(assignment, "status", None) == ProjectAgentStatus.REMOVED:
                        continue
                    raw_items.append({
                        "id": assignment.agent_id,
                        "kind": "agent",
                        "agent_id": assignment.agent_id,
                        "display_name": assignment.name or assignment.agent_name,
                        "role": assignment.role.value if assignment.role else "primary",
                        "agent_slug": assignment.agent_slug,
                        "description": assignment.agent_description,
                        "assignment_status": assignment.status.value if assignment.status else "active",
                        "presence": "available",
                    })

            items = [
                ProjectParticipantDTO(**participant)
                for participant in raw_items
            ]
            human_count = sum(1 for item in items if item.kind == "human")
            agent_count = sum(1 for item in items if item.kind == "agent")
            span["item_count"] = len(items)
            span["human_count"] = human_count
            span["agent_count"] = agent_count
            return ProjectParticipantListResponse(
                items=items,
                totals=ProjectParticipantTotals(
                    total=len(items),
                    humans=human_count,
                    agents=agent_count,
                ),
            )

    # -------------------------------------------------------------------------
    # /agents/presence routes (before /{project_id} catch-all)
    # -------------------------------------------------------------------------

    @router.get("/agents/presence", response_model=ProjectAgentPresenceListResponse)
    async def list_agent_presence(
        request: Request,
        project_id: Optional[str] = Query(
            default=None,
            description="Single project ID (legacy). Use `project_ids` for batched lookup.",
        ),
        project_ids: Optional[str] = Query(
            default=None,
            description="Comma-separated list of project IDs for batched lookup.",
        ),
    ) -> ProjectAgentPresenceListResponse:
        """List runtime presence state for assigned agents.

        Accepts either a single `project_id` (legacy, one HTTP round-trip per
        project) or a batched comma-separated `project_ids` (one round-trip
        total). When `project_ids` is used, each returned `AgentPresenceResponse`
        carries its own `project_id` so the client can group client-side.
        """
        user_id = get_user_id(request)

        with perf_span("projects.list_presence") as span:
            if project_ids:
                ids = [pid.strip() for pid in project_ids.split(",") if pid.strip()]
                span["mode"] = "batch"
                span["project_count"] = len(ids)
                if not ids:
                    return ProjectAgentPresenceListResponse(agents=[], total=0)
                for pid in ids:
                    await _require_project_access(user_id, pid)
                if hasattr(org_service, "list_agent_presence_batch"):
                    grouped = await run_in_threadpool(
                        org_service.list_agent_presence_batch, ids
                    )
                    flat = [p for ps in grouped.values() for p in ps]
                else:
                    flat = []
                    for pid in ids:
                        flat.extend(
                            await run_in_threadpool(
                                org_service.list_agent_presence, pid
                            )
                        )
                span["item_count"] = len(flat)
                return ProjectAgentPresenceListResponse(agents=flat, total=len(flat))

            span["mode"] = "single"
            if not project_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Either `project_id` or `project_ids` must be provided",
                )
            await _require_project_access(user_id, project_id)
            agents = await run_in_threadpool(
                org_service.list_agent_presence, project_id
            )
            span["item_count"] = len(agents)
            return ProjectAgentPresenceListResponse(agents=agents, total=len(agents))

    @router.patch(
        "/agents/{agent_id}/presence",
        response_model=AgentPresenceResponse,
    )
    async def update_agent_presence(
        request: Request,
        agent_id: str,
        body: UpdateAgentPresenceRequest,
        project_id: str = Query(..., description="Project context for presence update"),
    ) -> AgentPresenceResponse:
        """Update an agent's runtime presence in a project."""
        user_id = get_user_id(request)
        await _require_project_access(user_id, project_id)
        with perf_span("projects.update_presence"):
            return await run_in_threadpool(
                org_service.update_agent_presence,
                agent_id=agent_id,
                project_id=project_id,
                presence_status=body.presence_status,
                active_item_count=body.active_item_count,
                capacity_max=body.capacity_max,
                current_work_item_id=body.current_work_item_id,
            )

    # -------------------------------------------------------------------------
    # /{project_id} routes MUST come AFTER /agents routes
    # -------------------------------------------------------------------------
    @router.get("/{project_id}", response_model=ProjectDTO)
    async def get_project(request: Request, project_id: str) -> ProjectDTO:
        user_id = get_user_id(request)
        with perf_span("projects.get"):
            project = await run_in_threadpool(org_service.get_project, project_id)
            if project is None or project.owner_id != user_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project {project_id} not found")
            return _project_to_dto(project)

    return router
