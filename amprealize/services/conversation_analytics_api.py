"""FastAPI routes for conversation analytics and retention policy (AMPREALIZE-612, Phase 8).

Exposes:
    GET  /v1/conversations/stats               — aggregated conversation metrics
    GET  /v1/conversations/stats?project_id=X  — per-project metrics
    GET  /v1/projects/{project_id}/retention   — get per-project retention config
    PUT  /v1/projects/{project_id}/retention   — set per-project retention days
    POST /v1/admin/retention/archive           — trigger manual archive run
    POST /v1/admin/retention/cold-export       — trigger manual cold export run
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from amprealize.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ConversationStatsResponse(BaseModel):
    """Aggregated conversation analytics."""

    total_conversations: int = 0
    active_conversations: int = 0
    archived_conversations: int = 0
    total_messages: int = 0
    archived_messages: int = 0
    messages_last_7_days: int = 0
    messages_last_24h: int = 0
    agent_messages: int = 0
    user_messages: int = 0
    system_messages: int = 0
    archive_rate_percent: float = Field(
        default=0.0,
        description="Percentage of total messages that have been archived",
    )


class ProjectRetentionConfig(BaseModel):
    """Per-project retention policy configuration."""

    project_id: str
    retention_days: Optional[int] = Field(
        default=None,
        description="Message retention duration in days. NULL = use system default.",
        ge=1,
    )


class SetRetentionRequest(BaseModel):
    retention_days: int = Field(
        ...,
        description="Retention period in days (minimum: 1)",
        ge=1,
    )


class RetentionJobResult(BaseModel):
    """Result from a manual retention job trigger."""

    job: str
    count: int
    message: str


# ---------------------------------------------------------------------------
# Route factory
# ---------------------------------------------------------------------------


def create_conversation_analytics_routes(
    conversation_service: ConversationService,
    retention_worker: Optional[Any] = None,
    tags: Optional[List[str]] = None,
) -> APIRouter:
    """Create FastAPI router for conversation analytics and retention endpoints.

    Args:
        conversation_service: Initialized ConversationService.
        retention_worker: Optional RetentionWorker for manual job triggers.
        tags: Optional OpenAPI tags.

    Returns:
        APIRouter with analytics and retention routes.
    """
    router = APIRouter(tags=tags or ["conversations", "analytics"])

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    @router.get(
        "/v1/conversations/stats",
        response_model=ConversationStatsResponse,
        summary="Conversation analytics",
        description="Return aggregated message and conversation metrics.",
    )
    async def conversation_stats(
        project_id: Optional[str] = Query(
            default=None,
            description="Filter metrics to a specific project",
        ),
    ) -> ConversationStatsResponse:
        try:
            raw = conversation_service.get_conversation_stats(
                project_id=project_id
            )
        except Exception as exc:
            logger.exception("Failed to fetch conversation stats")
            raise HTTPException(status_code=500, detail=str(exc))

        total = int(raw.get("total_messages") or 0)
        archived = int(raw.get("archived_messages") or 0)
        archive_rate = round(archived / total * 100, 1) if total > 0 else 0.0

        return ConversationStatsResponse(
            total_conversations=int(raw.get("total_conversations") or 0),
            active_conversations=int(raw.get("active_conversations") or 0),
            archived_conversations=int(raw.get("archived_conversations") or 0),
            total_messages=total,
            archived_messages=archived,
            messages_last_7_days=int(raw.get("messages_last_7_days") or 0),
            messages_last_24h=int(raw.get("messages_last_24h") or 0),
            agent_messages=int(raw.get("agent_messages") or 0),
            user_messages=int(raw.get("user_messages") or 0),
            system_messages=int(raw.get("system_messages") or 0),
            archive_rate_percent=archive_rate,
        )

    # ------------------------------------------------------------------
    # Per-project retention config
    # ------------------------------------------------------------------

    @router.get(
        "/v1/projects/{project_id}/retention",
        response_model=ProjectRetentionConfig,
        summary="Get project retention policy",
        description="Fetch the per-project message retention configuration.",
    )
    async def get_project_retention(project_id: str) -> ProjectRetentionConfig:
        try:
            result = conversation_service.get_project_retention_config(project_id)
        except Exception as exc:
            logger.exception("Failed to fetch retention config for project %s", project_id)
            raise HTTPException(status_code=500, detail=str(exc))

        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"Project '{project_id}' not found",
            )

        return ProjectRetentionConfig(
            project_id=result["project_id"],
            retention_days=result.get("retention_days"),
        )

    @router.put(
        "/v1/projects/{project_id}/retention",
        response_model=ProjectRetentionConfig,
        summary="Set project retention policy",
        description="Configure per-project message retention duration.",
    )
    async def set_project_retention(
        project_id: str,
        body: SetRetentionRequest,
    ) -> ProjectRetentionConfig:
        try:
            conversation_service.set_project_retention_config(
                project_id, body.retention_days
            )
        except Exception as exc:
            logger.exception(
                "Failed to set retention config for project %s", project_id
            )
            raise HTTPException(status_code=500, detail=str(exc))

        return ProjectRetentionConfig(
            project_id=project_id,
            retention_days=body.retention_days,
        )

    # ------------------------------------------------------------------
    # Manual job triggers (admin)
    # ------------------------------------------------------------------

    @router.post(
        "/v1/admin/retention/archive",
        response_model=RetentionJobResult,
        summary="Trigger archive job",
        description="Manually trigger the Active → Archive retention job.",
    )
    async def trigger_archive_job() -> RetentionJobResult:
        if retention_worker is None:
            raise HTTPException(
                status_code=503,
                detail="Retention worker not configured",
            )
        try:
            count = await retention_worker.run_archive_job()
        except Exception as exc:
            logger.exception("Manual archive job failed")
            raise HTTPException(status_code=500, detail=str(exc))

        return RetentionJobResult(
            job="archive",
            count=count,
            message=f"Archived {count} messages",
        )

    @router.post(
        "/v1/admin/retention/cold-export",
        response_model=RetentionJobResult,
        summary="Trigger cold export job",
        description="Manually trigger the Archive → Cold storage export job (enterprise only).",
    )
    async def trigger_cold_export_job() -> RetentionJobResult:
        if retention_worker is None:
            raise HTTPException(
                status_code=503,
                detail="Retention worker not configured",
            )
        try:
            count = await retention_worker.run_cold_export_job()
        except Exception as exc:
            logger.exception("Manual cold export job failed")
            raise HTTPException(status_code=500, detail=str(exc))

        return RetentionJobResult(
            job="cold_export",
            count=count,
            message=f"Exported {count} conversations to cold storage",
        )

    return router
