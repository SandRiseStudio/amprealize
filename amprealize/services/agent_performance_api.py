"""FastAPI routes for Agent Performance Metrics API.

Following: behavior_design_api_contract, behavior_validate_cross_surface_parity

Provides REST API endpoints for agent performance tracking.
The service layer is synchronous; routes wrap it for async FastAPI.
"""

from __future__ import annotations

import logging
from typing import Optional, List, Any, Dict
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel, Field

from amprealize.agent_performance_contracts import (
    RecordTaskCompletionRequest as TaskCompletionContract,
    RecordStatusChangeRequest as StatusChangeContract,
    AgentPerformanceSnapshot,
    AgentPerformanceSummary,
    AgentPerformanceDaily,
    PerformanceAlert,
    AgentPerformanceThresholds,
)
from amprealize.services.agent_performance_service import AgentPerformanceService

logger = logging.getLogger(__name__)

# Thread pool for running sync service methods
_executor = ThreadPoolExecutor(max_workers=4)


# =============================================================================
# Pydantic Request/Response Models
# =============================================================================

class RecordTaskCompletionRequest(BaseModel):
    """Request to record a task completion."""
    agent_id: str = Field(..., description="Agent identifier")
    run_id: str = Field(..., description="Run identifier")
    task_id: Optional[str] = Field(None, description="Task identifier")
    project_id: Optional[str] = Field(None, description="Project ID")
    org_id: Optional[str] = Field(None, description="Organization ID")
    success: bool = Field(True, description="Whether task succeeded")
    duration_ms: Optional[int] = Field(None, ge=0, description="Duration in ms")
    tokens_used: int = Field(0, ge=0, description="Tokens used")
    baseline_tokens: int = Field(0, ge=0, description="Baseline tokens (for savings calc)")
    behaviors_cited: List[str] = Field(default_factory=list, description="Behaviors used")
    compliance_passed: int = Field(0, ge=0, description="Compliance checks passed")
    compliance_total: int = Field(0, ge=0, description="Total compliance checks")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class RecordStatusChangeRequest(BaseModel):
    """Request to record an agent status change."""
    agent_id: str = Field(..., description="Agent identifier")
    status_from: str = Field(..., description="Previous status")
    status_to: str = Field(..., description="New status")
    time_in_status_ms: int = Field(..., ge=0, description="Time in previous status")
    task_id: Optional[str] = Field(None, description="Related task ID")
    org_id: Optional[str] = Field(None, description="Organization ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class UpdateThresholdsRequest(BaseModel):
    """Request to update performance thresholds."""
    success_rate_warning: Optional[float] = Field(None, ge=0, le=100)
    success_rate_critical: Optional[float] = Field(None, ge=0, le=100)
    token_savings_warning: Optional[float] = Field(None, ge=0, le=100)
    token_savings_critical: Optional[float] = Field(None, ge=0, le=100)
    behavior_reuse_warning: Optional[float] = Field(None, ge=0, le=100)
    behavior_reuse_critical: Optional[float] = Field(None, ge=0, le=100)
    compliance_coverage_warning: Optional[float] = Field(None, ge=0, le=100)
    compliance_coverage_critical: Optional[float] = Field(None, ge=0, le=100)


class AcknowledgeAlertRequest(BaseModel):
    """Request to acknowledge an alert."""
    acknowledged_by: str = Field(..., description="User who acknowledged")


class ResolveAlertRequest(BaseModel):
    """Request to resolve an alert."""
    resolution_notes: str = Field(..., description="Resolution notes")


# =============================================================================
# Route Factory
# =============================================================================

def create_agent_performance_router(
    service: AgentPerformanceService,
) -> APIRouter:
    """Create FastAPI router for agent performance API.

    Args:
        service: AgentPerformanceService instance

    Returns:
        APIRouter with performance endpoints
    """
    router = APIRouter(prefix="/v1/agents/performance", tags=["agent-performance"])

    # -------------------------------------------------------------------------
    # Record Endpoints
    # -------------------------------------------------------------------------

    @router.post(
        "/tasks",
        status_code=201,
        summary="Record task completion",
        description="Record a task completion event with performance metrics.",
    )
    async def record_task_completion(
        request: RecordTaskCompletionRequest,
    ) -> Dict[str, Any]:
        """Record a task completion and return the performance snapshot."""
        try:
            contract = TaskCompletionContract(
                agent_id=request.agent_id,
                run_id=request.run_id,
                task_id=request.task_id,
                project_id=request.project_id,
                org_id=request.org_id,
                success=request.success,
                duration_ms=request.duration_ms,
                tokens_used=request.tokens_used,
                baseline_tokens=request.baseline_tokens,
                behaviors_cited=request.behaviors_cited,
                compliance_passed=request.compliance_passed,
                compliance_total=request.compliance_total,
                metadata=request.metadata,
            )
            snapshot = service.record_task_completion(contract)
            return snapshot.to_dict()
        except Exception as e:
            logger.exception("Failed to record task completion")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/status-changes",
        status_code=201,
        summary="Record status change",
        description="Record an agent status change for utilization tracking.",
    )
    async def record_status_change(
        request: RecordStatusChangeRequest,
    ) -> Dict[str, Any]:
        """Record an agent status change."""
        try:
            contract = StatusChangeContract(
                agent_id=request.agent_id,
                status_from=request.status_from,
                status_to=request.status_to,
                time_in_status_ms=request.time_in_status_ms,
                task_id=request.task_id,
                org_id=request.org_id,
                metadata=request.metadata,
            )
            snapshot = service.record_status_change(contract)
            return snapshot.to_dict()
        except Exception as e:
            logger.exception("Failed to record status change")
            raise HTTPException(status_code=500, detail=str(e))

    # -------------------------------------------------------------------------
    # Query Endpoints
    # -------------------------------------------------------------------------

    @router.get(
        "/{agent_id}/summary",
        summary="Get agent performance summary",
        description="Get aggregated performance metrics for an agent.",
    )
    async def get_agent_summary(
        agent_id: str = Path(..., description="Agent identifier"),
        period_days: int = Query(30, ge=1, le=365, description="Analysis period"),
        org_id: Optional[str] = Query(None, description="Filter by organization"),
    ) -> Dict[str, Any]:
        """Get performance summary for an agent."""
        try:
            summary = service.get_agent_summary(
                agent_id=agent_id,
                org_id=org_id,
                period_days=period_days,
            )
            return summary.to_dict()
        except Exception as e:
            logger.exception("Failed to get agent summary")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/top-performers",
        summary="Get top performing agents",
        description="Get agents ranked by a specific metric.",
    )
    async def get_top_performers(
        metric: str = Query("success_rate", description="Metric to sort by"),
        limit: int = Query(10, ge=1, le=100, description="Number of results"),
        period_days: int = Query(30, ge=1, le=365, description="Analysis period"),
        org_id: Optional[str] = Query(None, description="Filter by organization"),
        min_tasks: int = Query(5, ge=1, description="Minimum tasks to qualify"),
    ) -> List[Dict[str, Any]]:
        """Get top performing agents."""
        try:
            performers = service.get_top_performers(
                metric=metric,
                limit=limit,
                period_days=period_days,
                org_id=org_id,
                min_tasks=min_tasks,
            )
            return [p.to_dict() for p in performers]
        except Exception as e:
            logger.exception("Failed to get top performers")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/compare",
        summary="Compare agent performance",
        description="Compare performance metrics across multiple agents.",
    )
    async def compare_agents(
        agent_ids: List[str],
        period_days: int = Query(30, ge=1, le=365),
        org_id: Optional[str] = Query(None),
    ) -> Dict[str, Any]:
        """Compare multiple agents."""
        try:
            if len(agent_ids) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="At least 2 agents required for comparison"
                )
            if len(agent_ids) > 10:
                raise HTTPException(
                    status_code=400,
                    detail="Maximum 10 agents per comparison"
                )

            comparison = service.compare_agents(
                agent_ids=agent_ids,
                org_id=org_id,
                period_days=period_days,
            )
            return comparison
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Failed to compare agents")
            raise HTTPException(status_code=500, detail=str(e))

    # -------------------------------------------------------------------------
    # Daily Performance Endpoints
    # -------------------------------------------------------------------------

    @router.get(
        "/{agent_id}/daily",
        summary="Get daily performance trend",
        description="Get daily aggregated performance metrics.",
    )
    async def get_daily_trend(
        agent_id: str = Path(..., description="Agent identifier"),
        days: int = Query(30, ge=1, le=365, description="Number of days"),
        org_id: Optional[str] = Query(None, description="Filter by organization"),
    ) -> List[Dict[str, Any]]:
        """Get daily performance trend for an agent."""
        try:
            daily_data = service.get_daily_trend(
                agent_id=agent_id,
                days=days,
                org_id=org_id,
            )
            return [d.to_dict() for d in daily_data]
        except Exception as e:
            logger.exception("Failed to get daily trend")
            raise HTTPException(status_code=500, detail=str(e))

    # -------------------------------------------------------------------------
    # Alert Endpoints
    # -------------------------------------------------------------------------

    @router.get(
        "/alerts",
        summary="Get performance alerts",
        description="Get performance alerts filtered by various criteria.",
    )
    async def get_alerts(
        agent_id: Optional[str] = Query(None, description="Filter by agent"),
        severity: Optional[str] = Query(None, description="Filter by severity"),
        include_resolved: bool = Query(False, description="Include resolved alerts"),
        org_id: Optional[str] = Query(None, description="Filter by organization"),
        limit: int = Query(50, ge=1, le=500, description="Maximum results"),
    ) -> List[Dict[str, Any]]:
        """Get performance alerts."""
        try:
            alerts = service.get_alerts(
                agent_id=agent_id,
                org_id=org_id,
                severity=severity,
                include_resolved=include_resolved,
                limit=limit,
            )
            return [a.to_dict() for a in alerts]
        except Exception as e:
            logger.exception("Failed to get alerts")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/alerts/{alert_id}/acknowledge",
        summary="Acknowledge alert",
        description="Acknowledge a performance alert.",
    )
    async def acknowledge_alert(
        request: AcknowledgeAlertRequest,
        alert_id: str = Path(..., description="Alert identifier"),
    ) -> Dict[str, Any]:
        """Acknowledge an alert."""
        try:
            alert = service.acknowledge_alert(
                alert_id=alert_id,
                acknowledged_by=request.acknowledged_by,
            )
            return alert.to_dict()
        except Exception as e:
            logger.exception("Failed to acknowledge alert")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/alerts/{alert_id}/resolve",
        summary="Resolve alert",
        description="Resolve a performance alert.",
    )
    async def resolve_alert(
        request: ResolveAlertRequest,
        alert_id: str = Path(..., description="Alert identifier"),
    ) -> Dict[str, Any]:
        """Resolve an alert."""
        try:
            alert = service.resolve_alert(
                alert_id=alert_id,
                resolution_notes=request.resolution_notes,
            )
            return alert.to_dict()
        except Exception as e:
            logger.exception("Failed to resolve alert")
            raise HTTPException(status_code=500, detail=str(e))

    # -------------------------------------------------------------------------
    # Threshold Endpoints
    # -------------------------------------------------------------------------

    @router.get(
        "/thresholds",
        summary="Get performance thresholds",
        description="Get performance thresholds for an agent or organization.",
    )
    async def get_thresholds(
        agent_id: Optional[str] = Query(None, description="Agent ID"),
        org_id: Optional[str] = Query(None, description="Organization ID"),
    ) -> Dict[str, Any]:
        """Get performance thresholds."""
        try:
            thresholds = service.get_thresholds(
                agent_id=agent_id,
                org_id=org_id,
            )
            return thresholds.to_dict()
        except Exception as e:
            logger.exception("Failed to get thresholds")
            raise HTTPException(status_code=500, detail=str(e))

    @router.put(
        "/thresholds",
        summary="Update performance thresholds",
        description="Update performance thresholds for an agent or organization.",
    )
    async def update_thresholds(
        request: UpdateThresholdsRequest,
        agent_id: Optional[str] = Query(None, description="Agent ID"),
        org_id: Optional[str] = Query(None, description="Organization ID"),
    ) -> Dict[str, Any]:
        """Update performance thresholds."""
        try:
            # Build thresholds dict from non-None values
            thresholds_dict = {}
            if request.success_rate_warning is not None:
                thresholds_dict["success_rate_warning"] = request.success_rate_warning
            if request.success_rate_critical is not None:
                thresholds_dict["success_rate_critical"] = request.success_rate_critical
            if request.token_savings_warning is not None:
                thresholds_dict["token_savings_warning"] = request.token_savings_warning
            if request.token_savings_critical is not None:
                thresholds_dict["token_savings_critical"] = request.token_savings_critical
            if request.behavior_reuse_warning is not None:
                thresholds_dict["behavior_reuse_warning"] = request.behavior_reuse_warning
            if request.behavior_reuse_critical is not None:
                thresholds_dict["behavior_reuse_critical"] = request.behavior_reuse_critical
            if request.compliance_coverage_warning is not None:
                thresholds_dict["compliance_coverage_warning"] = request.compliance_coverage_warning
            if request.compliance_coverage_critical is not None:
                thresholds_dict["compliance_coverage_critical"] = request.compliance_coverage_critical

            result = service.update_thresholds(
                thresholds=thresholds_dict,
                agent_id=agent_id,
                org_id=org_id,
            )
            return result.to_dict()
        except Exception as e:
            logger.exception("Failed to update thresholds")
            raise HTTPException(status_code=500, detail=str(e))

    # -------------------------------------------------------------------------
    # Admin Endpoints
    # -------------------------------------------------------------------------

    @router.post(
        "/rollup/daily",
        summary="Compute daily rollup",
        description="Manually trigger daily rollup computation for an agent.",
    )
    async def compute_daily_rollup(
        agent_id: str = Query(..., description="Agent identifier"),
        date: str = Query(..., description="Date to compute (YYYY-MM-DD)"),
    ) -> Dict[str, Any]:
        """Compute daily rollup for an agent."""
        try:
            rollup = service.compute_daily_rollup(
                date=date,
                agent_id=agent_id,
            )
            return rollup.to_dict()
        except Exception as e:
            logger.exception("Failed to compute daily rollup")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/{agent_id}/check-thresholds",
        summary="Check thresholds",
        description="Check current performance against thresholds and generate alerts.",
    )
    async def check_thresholds(
        agent_id: str = Path(..., description="Agent identifier"),
        period_days: int = Query(7, ge=1, le=30, description="Evaluation period"),
        org_id: Optional[str] = Query(None, description="Organization ID"),
    ) -> List[Dict[str, Any]]:
        """Check thresholds and return any triggered alerts."""
        try:
            alerts = service.check_thresholds(
                agent_id=agent_id,
                org_id=org_id,
                period_days=period_days,
            )
            return [a.to_dict() for a in alerts]
        except Exception as e:
            logger.exception("Failed to check thresholds")
            raise HTTPException(status_code=500, detail=str(e))

    return router
