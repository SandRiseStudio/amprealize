"""REST API routes for governed observability analytics."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from amprealize.observability_analytics import (
    GovernedObservabilityQueryService,
    ObservabilityQuery,
)


class ObservabilityQueryRequest(BaseModel):
    """Shared request contract for governed observability queries."""

    event_types: List[str] = Field(
        default_factory=list,
        description="Optional telemetry event types to include",
    )
    run_id: Optional[str] = Field(default=None, description="Optional run ID filter")
    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum records to return for event-list queries",
    )
    max_series: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum series values to include in dashboard summaries",
    )


class ObservabilityEventsResponse(BaseModel):
    """Role-filtered event-list response."""

    access_tier: str
    records: List[Dict[str, Any]]
    count: int
    truncated: bool
    query: Dict[str, Any]


class ObservabilityDashboardResponse(BaseModel):
    """Role-filtered dashboard summary response."""

    access_tier: str
    event_count: int
    unique_run_count: int
    event_types: Dict[str, int]
    surfaces: Dict[str, int]
    truncated_series: Dict[str, int]
    sample_events: List[Dict[str, Any]]
    query: Dict[str, Any]


def _default_current_user() -> Dict[str, Any]:
    return {"user_id": "", "role": "viewer"}


def create_observability_analytics_routes(
    *,
    observability_query_service: GovernedObservabilityQueryService,
    get_current_user: Callable[..., Dict[str, Any]] = _default_current_user,
) -> APIRouter:
    """Create REST routes for governed telemetry and trace analytics."""

    router = APIRouter(tags=["observability", "analytics"])

    @router.post(
        "/v1/observability/events",
        response_model=ObservabilityEventsResponse,
        summary="List governed observability events",
    )
    async def list_observability_events(
        payload: ObservabilityQueryRequest,
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> ObservabilityEventsResponse:
        query = _build_query(payload, current_user)
        result = observability_query_service.list_events(query)
        return ObservabilityEventsResponse(
            **result,
            query=_query_metadata(payload),
        )

    @router.post(
        "/v1/observability/dashboard",
        response_model=ObservabilityDashboardResponse,
        summary="Summarize governed observability events",
    )
    async def summarize_observability_dashboard(
        payload: ObservabilityQueryRequest,
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> ObservabilityDashboardResponse:
        query = _build_query(payload, current_user)
        result = observability_query_service.dashboard_summary(query)
        return ObservabilityDashboardResponse(
            **result,
            query=_query_metadata(payload),
        )

    return router


def _build_query(
    payload: ObservabilityQueryRequest,
    current_user: Dict[str, Any],
) -> ObservabilityQuery:
    actor = {
        "id": current_user.get("user_id") or current_user.get("id") or "",
        "role": current_user.get("role") or "viewer",
        "observability_access_tier": current_user.get("observability_access_tier"),
        "analytics_access_tier": current_user.get("analytics_access_tier"),
    }
    return ObservabilityQuery(
        actor=actor,
        event_types=tuple(payload.event_types),
        run_id=payload.run_id,
        limit=payload.limit,
        max_series=payload.max_series,
    )


def _query_metadata(payload: ObservabilityQueryRequest) -> Dict[str, Any]:
    return {
        "event_types": list(payload.event_types),
        "run_id": payload.run_id,
        "limit": payload.limit,
        "max_series": payload.max_series,
    }


__all__ = [
    "ObservabilityDashboardResponse",
    "ObservabilityEventsResponse",
    "ObservabilityQueryRequest",
    "create_observability_analytics_routes",
]
