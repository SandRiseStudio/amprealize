"""REST API routes for natural-language resource analysis.

Following `behavior_validate_cross_surface_parity` (Student): this exposes the
same read-only analyst capability used by chat, work-item agents, and MCP.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from amprealize.resource_analysis import ResourceAnalysisService


class ResourceAnalyzeRequest(BaseModel):
    """Request body for `POST /v1/resources:analyze`."""

    query: str = Field(..., min_length=1, description="Natural-language resource question to answer")
    project_id: Optional[str] = Field(default=None, description="Optional project scope")
    org_id: Optional[str] = Field(default=None, description="Optional organization scope")
    conversation_scope: Optional[str] = Field(default=None, description="Optional conversation scope hint")


class ResourceAnalyzeResponse(BaseModel):
    """Cross-surface resource-analysis response."""

    success: bool
    content: str
    answer_type: str
    query_plan: Dict[str, Any]
    structured_payload: Dict[str, Any]
    rows: List[Dict[str, Any]]
    trace_steps: List[Dict[str, Any]]
    metadata: Dict[str, Any]


def _default_current_user() -> Dict[str, Any]:
    return {"user_id": ""}


def create_resource_analysis_routes(
    *,
    resource_analysis_service: ResourceAnalysisService,
    get_current_user: Callable[..., Dict[str, Any]] = _default_current_user,
) -> APIRouter:
    """Create REST routes for read-only natural-language analysis."""

    router = APIRouter(tags=["resources", "analysis"])

    @router.post(
        "/v1/resources:analyze",
        response_model=ResourceAnalyzeResponse,
        summary="Analyze accessible Amprealize resources",
    )
    async def analyze_resources(
        payload: ResourceAnalyzeRequest,
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> ResourceAnalyzeResponse:
        answer = await resource_analysis_service.answer(
            query=payload.query,
            user_id=str(current_user.get("user_id") or ""),
            org_id=payload.org_id or current_user.get("org_id"),
            project_id=payload.project_id or current_user.get("project_id"),
            conversation_scope=payload.conversation_scope,
        )
        if answer is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No supported resource analysis query was detected.",
            )
        return ResourceAnalyzeResponse(
            success=True,
            content=answer.content,
            answer_type=answer.answer_type,
            query_plan=answer.query_plan.to_dict(),
            structured_payload=answer.structured_payload,
            rows=answer.source_rows,
            trace_steps=answer.trace_steps,
            metadata=answer.metadata,
        )

    return router


__all__ = [
    "ResourceAnalyzeRequest",
    "ResourceAnalyzeResponse",
    "create_resource_analysis_routes",
]
