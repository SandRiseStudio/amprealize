"""Console (web) dashboard — batched read models for first paint after login.

Following:
- behavior_lock_down_security_surface (Student): same auth as /v1/projects
- behavior_design_api_contract (Student): response models match list endpoints
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from amprealize.boards.contracts import Board
from amprealize.perf_log import perf_span
from amprealize.projects_api import ProjectDTO, _project_to_dto

if TYPE_CHECKING:
    from amprealize.multi_tenant.organization_service import OrganizationService
    from amprealize.services.board_service import BoardService

logger = logging.getLogger(__name__)


class DashboardBootstrapResponse(BaseModel):
    """Projects for the current scope plus all boards for those projects (one round-trip)."""

    projects: List[ProjectDTO]
    boards_by_project: Dict[str, List[Board]] = Field(
        default_factory=dict,
        description="Map of project_id to boards (same shape as /v1/boards per project).",
    )


def create_console_dashboard_routes(
    *,
    org_service: "OrganizationService",
    board_service: "BoardService",
    get_user_id: Callable[[Request], str],
    tags: Optional[List[str]] = None,
) -> APIRouter:
    """REST routes for web console read models."""
    router = APIRouter(prefix="/v1/console", tags=tags or ["console"])

    @router.get(
        "/dashboard-bootstrap",
        response_model=DashboardBootstrapResponse,
        summary="Dashboard bootstrap",
        description=(
            "Return the current user's projects and all boards for those projects in a single round-trip, "
            "for the home dashboard after login."
        ),
    )
    async def dashboard_bootstrap(
        request: Request,
        org_id: Optional[str] = Query(default=None, description="Scope (same as GET /v1/projects)"),
    ) -> DashboardBootstrapResponse:
        user_id = get_user_id(request)
        try:
            with perf_span("console.dashboard_bootstrap") as span:
                projects = await run_in_threadpool(
                    org_service.list_projects,
                    owner_id=user_id,
                    org_id=org_id,
                )
                project_ids = [p.id for p in projects]
                boards_map = await run_in_threadpool(
                    board_service.list_boards_for_projects,
                    project_ids,
                    org_id=org_id,
                )
                boards_by_project = {pid: boards_map.get(pid, []) for pid in project_ids}
                span["project_count"] = len(projects)
                span["board_total"] = sum(len(v) for v in boards_by_project.values())
                return DashboardBootstrapResponse(
                    projects=[_project_to_dto(p) for p in projects],
                    boards_by_project=boards_by_project,
                )
        except Exception as exc:
            logger.exception("dashboard-bootstrap failed", extra={"org_id": org_id})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Dashboard bootstrap unavailable.",
            ) from exc

    return router
