"""MCP tool handlers for AgentPerformanceService.

Provides handlers for agent performance metrics tracking and analysis.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from dataclasses import asdict

from ...services.agent_performance_service import AgentPerformanceService
from ...agent_performance_contracts import (
    AgentPerformanceDaily,
    AgentPerformanceSnapshot,
    AgentPerformanceSummary,
    AgentPerformanceThresholds,
    PerformanceAlertSeverity,
    PerformanceAlert,
    RecordStatusChangeRequest,
    RecordTaskCompletionRequest,
)


def _parse_date(value: Optional[str]) -> Optional[date]:
    """Parse ISO date string to date object."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return None


def _parse_alert_severity(value: Optional[str]) -> Optional[PerformanceAlertSeverity]:
    """Parse alert severity string to enum."""
    if not value:
        return None
    normalized = value.strip().upper()
    try:
        return PerformanceAlertSeverity(normalized)
    except ValueError:
        return None


def _serialize_value(value: Any) -> Any:
    """Recursively serialize values for JSON output."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, 'value'):  # Enum
        return value.value
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return str(value)


def _snapshot_to_dict(snapshot: AgentPerformanceSnapshot) -> Dict[str, Any]:
    """Convert snapshot dataclass to dict with serialized timestamps."""
    result = asdict(snapshot)
    return {k: _serialize_value(v) for k, v in result.items()}


def _summary_to_dict(summary: AgentPerformanceSummary) -> Dict[str, Any]:
    """Convert summary dataclass to dict with serialized timestamps."""
    result = asdict(summary)
    return {k: _serialize_value(v) for k, v in result.items()}


def _alert_to_dict(alert: PerformanceAlert) -> Dict[str, Any]:
    """Convert alert dataclass to dict with serialized timestamps."""
    result = asdict(alert)
    return {k: _serialize_value(v) for k, v in result.items()}


def _daily_to_dict(daily: AgentPerformanceDaily) -> Dict[str, Any]:
    """Convert daily rollup dataclass to dict with serialized dates."""
    result = asdict(daily)
    return {k: _serialize_value(v) for k, v in result.items()}


def _thresholds_to_dict(thresholds: AgentPerformanceThresholds) -> Dict[str, Any]:
    """Convert thresholds dataclass to dict."""
    result = asdict(thresholds)
    return {k: _serialize_value(v) for k, v in result.items()}


# ==============================================================================
# Handler Functions
# ==============================================================================


def handle_record_task(
    service: AgentPerformanceService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Record a task completion event for an agent.

    MCP Tool: agentPerformance.recordTask
    """
    # Build request from arguments - match RecordTaskCompletionRequest fields
    request = RecordTaskCompletionRequest(
        agent_id=arguments["agent_id"],
        run_id=arguments["run_id"],
        task_id=arguments.get("task_id"),
        project_id=arguments.get("project_id"),
        org_id=arguments.get("org_id"),
        success=arguments.get("success", True),
        duration_ms=arguments.get("duration_ms"),
        tokens_used=arguments.get("tokens_used", 0),
        baseline_tokens=arguments.get("baseline_tokens", 0),
        behaviors_cited=arguments.get("behaviors_cited", []),
        compliance_passed=arguments.get("compliance_passed", 0),
        compliance_total=arguments.get("compliance_total", 0),
        metadata=arguments.get("metadata", {}),
    )

    snapshot = service.record_task_completion(request)

    return {
        "success": True,
        "snapshot": _snapshot_to_dict(snapshot),
        "message": f"Recorded task completion for agent {request.agent_id}",
    }


def handle_get_summary(
    service: AgentPerformanceService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get performance summary for an agent.

    MCP Tool: agentPerformance.getSummary
    """
    agent_id = arguments["agent_id"]
    org_id = arguments.get("org_id")
    period_days = arguments.get("period_days", 30)

    summary = service.get_agent_summary(
        agent_id=agent_id,
        org_id=org_id,
        period_days=period_days,
    )

    if summary is None:
        return {
            "success": False,
            "error": f"No performance data found for agent {agent_id}",
            "summary": None,
        }

    return {
        "success": True,
        "summary": _summary_to_dict(summary),
    }


def handle_top_performers(
    service: AgentPerformanceService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get top performing agents ranked by a metric.

    MCP Tool: agentPerformance.topPerformers
    """
    metric = arguments.get("metric", "success_rate")
    limit = arguments.get("limit", 10)
    period_days = arguments.get("period_days", 30)
    org_id = arguments.get("org_id")
    min_tasks = arguments.get("min_tasks", 5)

    performers = service.get_top_performers(
        metric=metric,
        limit=limit,
        period_days=period_days,
        org_id=org_id,
        min_tasks=min_tasks,
    )

    return {
        "success": True,
        "metric": metric,
        "period_days": period_days,
        "performers": [_summary_to_dict(p) for p in performers],
        "count": len(performers),
    }


def handle_compare_agents(
    service: AgentPerformanceService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compare performance metrics across multiple agents.

    MCP Tool: agentPerformance.compare
    """
    agent_ids = arguments["agent_ids"]
    period_days = arguments.get("period_days", 30)
    org_id = arguments.get("org_id")

    comparisons = service.compare_agents(
        agent_ids=agent_ids,
        period_days=period_days,
        org_id=org_id,
    )

    return {
        "success": True,
        "period_days": period_days,
        "comparisons": [_summary_to_dict(c) for c in comparisons],
        "agent_count": len(comparisons),
    }


def handle_daily_trend(
    service: AgentPerformanceService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get daily performance trend for an agent.

    MCP Tool: agentPerformance.dailyTrend
    """
    agent_id = arguments["agent_id"]
    days = arguments.get("days", 30)
    org_id = arguments.get("org_id")

    trend = service.get_daily_trend(
        agent_id=agent_id,
        days=days,
        org_id=org_id,
    )

    return {
        "success": True,
        "agent_id": agent_id,
        "days": days,
        "trend": [_daily_to_dict(d) for d in trend],
        "data_points": len(trend),
    }


def handle_get_alerts(
    service: AgentPerformanceService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get performance alerts for an agent or organization.

    MCP Tool: agentPerformance.getAlerts
    """
    agent_id = arguments.get("agent_id")
    org_id = arguments.get("org_id")
    severity = _parse_alert_severity(arguments.get("severity"))
    include_resolved = arguments.get("include_resolved", False)
    limit = arguments.get("limit", 50)

    alerts = service.get_alerts(
        agent_id=agent_id,
        org_id=org_id,
        severity=severity,
        include_resolved=include_resolved,
        limit=limit,
    )

    return {
        "success": True,
        "alerts": [_alert_to_dict(a) for a in alerts],
        "count": len(alerts),
        "filters": {
            "agent_id": agent_id,
            "org_id": org_id,
            "severity": severity.value if severity else None,
            "include_resolved": include_resolved,
        },
    }


def handle_acknowledge_alert(
    service: AgentPerformanceService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Acknowledge a performance alert.

    MCP Tool: agentPerformance.acknowledgeAlert
    """
    alert_id = arguments["alert_id"]
    acknowledged_by = arguments.get("acknowledged_by")

    alert = service.acknowledge_alert(
        alert_id=alert_id,
        acknowledged_by=acknowledged_by,
    )

    if alert is None:
        return {
            "success": False,
            "error": f"Alert {alert_id} not found",
        }

    return {
        "success": True,
        "alert": _alert_to_dict(alert),
        "message": f"Alert {alert_id} acknowledged",
    }


def handle_resolve_alert(
    service: AgentPerformanceService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Resolve a performance alert with optional notes.

    MCP Tool: agentPerformance.resolveAlert
    """
    alert_id = arguments["alert_id"]
    resolution_notes = arguments.get("resolution_notes")

    alert = service.resolve_alert(
        alert_id=alert_id,
        resolution_notes=resolution_notes,
    )

    if alert is None:
        return {
            "success": False,
            "error": f"Alert {alert_id} not found",
        }

    return {
        "success": True,
        "alert": _alert_to_dict(alert),
        "message": f"Alert {alert_id} resolved",
    }


def handle_get_thresholds(
    service: AgentPerformanceService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get performance alert thresholds.

    MCP Tool: agentPerformance.getThresholds
    """
    agent_id = arguments.get("agent_id")
    org_id = arguments.get("org_id")

    thresholds = service.get_thresholds(
        agent_id=agent_id,
        org_id=org_id,
    )

    # Determine scope
    if agent_id and thresholds.success_rate_warning != 70.0:  # Not default
        scope = "agent"
    elif org_id:
        scope = "org"
    else:
        scope = "default"

    return {
        "success": True,
        "scope": scope,
        "agent_id": agent_id,
        "org_id": org_id,
        "thresholds": _thresholds_to_dict(thresholds),
    }


def handle_update_thresholds(
    service: AgentPerformanceService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update performance alert thresholds.

    MCP Tool: agentPerformance.updateThresholds
    """
    agent_id = arguments.get("agent_id")
    org_id = arguments.get("org_id")

    # Build thresholds object from provided values
    thresholds = AgentPerformanceThresholds(
        success_rate_warning=arguments.get("success_rate_warning", 70.0),
        success_rate_critical=arguments.get("success_rate_critical", 50.0),
        token_savings_warning=arguments.get("token_savings_warning", 20.0),
        token_savings_critical=arguments.get("token_savings_critical", 10.0),
        behavior_reuse_warning=arguments.get("behavior_reuse_warning", 50.0),
        behavior_reuse_critical=arguments.get("behavior_reuse_critical", 30.0),
        compliance_coverage_warning=arguments.get("compliance_coverage_warning", 70.0),
        compliance_coverage_critical=arguments.get("compliance_coverage_critical", 50.0),
    )

    updated = service.update_thresholds(
        thresholds=thresholds,
        org_id=org_id,
        agent_id=agent_id,
    )

    scope = "agent" if agent_id else ("org" if org_id else "default")

    return {
        "success": True,
        "scope": scope,
        "thresholds": _thresholds_to_dict(updated),
        "message": f"Thresholds updated for {scope} scope",
    }


# ==============================================================================
# Handler Registry
# ==============================================================================

AGENT_PERFORMANCE_HANDLERS = {
    "agentPerformance.recordTask": handle_record_task,
    "agentPerformance.getSummary": handle_get_summary,
    "agentPerformance.topPerformers": handle_top_performers,
    "agentPerformance.compare": handle_compare_agents,
    "agentPerformance.dailyTrend": handle_daily_trend,
    "agentPerformance.getAlerts": handle_get_alerts,
    "agentPerformance.acknowledgeAlert": handle_acknowledge_alert,
    "agentPerformance.resolveAlert": handle_resolve_alert,
    "agentPerformance.getThresholds": handle_get_thresholds,
    "agentPerformance.updateThresholds": handle_update_thresholds,
}


def get_handler(tool_name: str):
    """Get handler function for a tool name."""
    return AGENT_PERFORMANCE_HANDLERS.get(tool_name)


def list_tools() -> List[str]:
    """List all available agent performance MCP tools."""
    return list(AGENT_PERFORMANCE_HANDLERS.keys())
