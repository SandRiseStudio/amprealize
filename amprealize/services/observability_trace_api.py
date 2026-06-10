"""REST routes for governed trace-shaped reads (warehouse SQL views)."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from amprealize.observability_trace_query import GovernedTraceReadService, TraceSummaryFilters


class TraceSummaryRequest(BaseModel):
    """Shared list filters for run and conversation trace summaries."""

    project_id: str = Field(..., min_length=1, description="Project scope for observability rows")
    run_id: Optional[str] = Field(default=None, description="Filter run summaries to a single run")
    conversation_id: Optional[str] = Field(
        default=None,
        description="Filter conversation summaries to a single conversation",
    )
    since: Optional[str] = Field(
        default=None,
        description="ISO timestamp or relative window (e.g. 7d) — lower bound on activity",
    )
    until: Optional[str] = Field(
        default=None,
        description="ISO timestamp or relative window — upper bound on span start",
    )
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=100_000)


class TraceSpanTreeRequest(BaseModel):
    """Request span-tree rows for a trace within a project."""

    project_id: str = Field(..., min_length=1)
    trace_id: str = Field(..., min_length=1)
    limit: int = Field(default=500, ge=1, le=2000)


class TraceReadResponse(BaseModel):
    """Payload shared by list endpoints."""

    access_tier: str
    records: list[dict[str, Any]]
    count: int
    truncated: bool
    query: Dict[str, Any]


class TraceSpanTreeResponse(BaseModel):
    """Span tree rows for one trace."""

    access_tier: str
    trace_id: str
    records: list[dict[str, Any]]
    count: int
    truncated: bool
    query: Dict[str, Any]


def _default_current_user() -> Dict[str, Any]:
    return {"user_id": "", "role": "viewer"}


def create_observability_trace_routes(
    *,
    trace_read_service: GovernedTraceReadService,
    get_current_user: Callable[..., Dict[str, Any]] = _default_current_user,
) -> APIRouter:
    """Mount trace query endpoints under the shared ``/api`` prefix.

    **Project RBAC:** Each handler requires an authenticated user and
    :attr:`ProjectPermission.VIEW_RUNS` on the request body ``project_id`` when
    ``app.state.async_permission_service`` is set. If the service is missing and
    ``AMPREALIZE_AUTH_STRICT`` is not enabled, the check is skipped (local
    development). If strict, a missing service yields HTTP 500.
    """

    router = APIRouter(tags=["observability", "traces"])

    @router.post(
        "/v1/observability/traces/runs",
        response_model=TraceReadResponse,
        summary="List run-level observability summaries",
    )
    async def list_trace_run_summaries(
        request: Request,
        payload: TraceSummaryRequest,
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> TraceReadResponse:
        actor = _actor_from_user(current_user)
        filters = TraceSummaryFilters(
            project_id=payload.project_id.strip(),
            run_id=payload.run_id,
            since=payload.since,
            until=payload.until,
            limit=payload.limit,
            offset=payload.offset,
        )
        if not filters.project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        await _ensure_project_view_runs(request, current_user, filters.project_id)
        result = trace_read_service.list_run_summaries(actor, filters)
        return TraceReadResponse(
            **result,
            query=_summary_query_meta(payload),
        )

    @router.post(
        "/v1/observability/traces/conversations",
        response_model=TraceReadResponse,
        summary="List conversation-level observability summaries",
    )
    async def list_trace_conversation_summaries(
        request: Request,
        payload: TraceSummaryRequest,
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> TraceReadResponse:
        actor = _actor_from_user(current_user)
        filters = TraceSummaryFilters(
            project_id=payload.project_id.strip(),
            conversation_id=payload.conversation_id,
            since=payload.since,
            until=payload.until,
            limit=payload.limit,
            offset=payload.offset,
        )
        if not filters.project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        await _ensure_project_view_runs(request, current_user, filters.project_id)
        result = trace_read_service.list_conversation_summaries(actor, filters)
        return TraceReadResponse(
            **result,
            query=_summary_query_meta(payload),
        )

    @router.post(
        "/v1/observability/traces/spans",
        response_model=TraceSpanTreeResponse,
        summary="Return ordered span rows for a trace",
    )
    async def list_trace_span_tree(
        request: Request,
        payload: TraceSpanTreeRequest,
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> TraceSpanTreeResponse:
        actor = _actor_from_user(current_user)
        project_id = payload.project_id.strip()
        trace_id = payload.trace_id.strip()
        if not project_id or not trace_id:
            raise HTTPException(status_code=400, detail="project_id and trace_id are required")
        await _ensure_project_view_runs(request, current_user, project_id)
        result = trace_read_service.get_span_tree(
            actor,
            project_id=project_id,
            trace_id=trace_id,
            limit=payload.limit,
        )
        return TraceSpanTreeResponse(
            **result,
            query={
                "project_id": project_id,
                "trace_id": trace_id,
                "limit": payload.limit,
            },
        )

    return router


def _actor_from_user(current_user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": current_user.get("user_id") or current_user.get("id") or "",
        "role": current_user.get("role") or "viewer",
        "observability_access_tier": current_user.get("observability_access_tier"),
        "analytics_access_tier": current_user.get("analytics_access_tier"),
    }


async def _ensure_project_view_runs(
    request: Request,
    current_user: Dict[str, Any],
    project_id: str,
) -> None:
    """Require authentication and :attr:`ProjectPermission.VIEW_RUNS` when permissions are configured.

    Mirrors ``require_project_permission_dep`` for body-scoped ``project_id``: if
    ``app.state.async_permission_service`` is missing and ``AMPREALIZE_AUTH_STRICT`` is not set,
    the check is skipped (local development). If strict, missing service returns 500.
    """

    from amprealize.tenant.permissions import NotAMember, PermissionDenied, ProjectPermission

    user_id = getattr(request.state, "user_id", None) or current_user.get("user_id") or current_user.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    perm_service = getattr(request.app.state, "async_permission_service", None)
    if perm_service is None:
        if os.getenv("AMPREALIZE_AUTH_STRICT", "").lower() in ("true", "1", "yes"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Permission service not configured",
            )
        return

    try:
        await perm_service.require_project_permission(
            str(user_id),
            project_id,
            ProjectPermission.VIEW_RUNS,
        )
    except NotAMember:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    except PermissionDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )


def _summary_query_meta(payload: TraceSummaryRequest) -> Dict[str, Any]:
    return {
        "project_id": payload.project_id,
        "run_id": payload.run_id,
        "conversation_id": payload.conversation_id,
        "since": payload.since,
        "until": payload.until,
        "limit": payload.limit,
        "offset": payload.offset,
    }


__all__ = [
    "TraceReadResponse",
    "TraceSpanTreeRequest",
    "TraceSpanTreeResponse",
    "TraceSummaryRequest",
    "create_observability_trace_routes",
]
