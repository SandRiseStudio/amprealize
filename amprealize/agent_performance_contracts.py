"""Agent Performance Metrics data contracts.

Following MetricsService patterns for KPI tracking and alerts.
Feature 13.4.6 - Agent performance metrics for task completion, token efficiency, behavior reuse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# =============================================================================
# Enums
# =============================================================================


class PerformanceAlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class PerformanceMetricType(str, Enum):
    """Performance metric types for alerting."""
    SUCCESS_RATE = "success_rate"
    TOKEN_EFFICIENCY = "token_efficiency"
    BEHAVIOR_REUSE = "behavior_reuse"
    COMPLIANCE_COVERAGE = "compliance_coverage"
    AVG_TASK_DURATION = "avg_task_duration"
    UTILIZATION = "utilization"


class ThresholdDirection(str, Enum):
    """Threshold comparison direction."""
    BELOW = "below"  # Alert when value falls below threshold
    ABOVE = "above"  # Alert when value exceeds threshold


# =============================================================================
# PRD-Aligned Threshold Constants
# =============================================================================


class PerformanceThresholds:
    """Default threshold values aligned with PRD targets."""

    # Success rate (PRD target: 80%)
    SUCCESS_RATE_TARGET = 80.0
    SUCCESS_RATE_WARNING = 70.0
    SUCCESS_RATE_CRITICAL = 60.0

    # Token savings (PRD target: 30%)
    TOKEN_SAVINGS_TARGET = 30.0
    TOKEN_SAVINGS_WARNING = 20.0
    TOKEN_SAVINGS_CRITICAL = 10.0

    # Behavior reuse (PRD target: 70%)
    BEHAVIOR_REUSE_TARGET = 70.0
    BEHAVIOR_REUSE_WARNING = 60.0
    BEHAVIOR_REUSE_CRITICAL = 40.0

    # Compliance coverage (PRD target: 95%)
    COMPLIANCE_COVERAGE_TARGET = 95.0
    COMPLIANCE_COVERAGE_WARNING = 90.0
    COMPLIANCE_COVERAGE_CRITICAL = 80.0

    # Task duration (ms) - warning/critical thresholds
    AVG_DURATION_WARNING_MS = 300_000      # 5 minutes
    AVG_DURATION_CRITICAL_MS = 600_000     # 10 minutes

    # Utilization - both low and high can be concerning
    UTILIZATION_LOW_WARNING = 20.0   # Agent underutilized
    UTILIZATION_HIGH_WARNING = 90.0  # Agent overloaded

    # Evaluation settings
    DEFAULT_EVALUATION_WINDOW_HOURS = 24
    DEFAULT_MIN_SAMPLE_SIZE = 5

    # Retention periods
    DETAILED_RETENTION_DAYS = 90
    AGGREGATED_RETENTION_DAYS = 365


# =============================================================================
# Core Data Models
# =============================================================================


@dataclass
class AgentPerformanceSnapshot:
    """Individual performance event snapshot.

    Recorded on task completion, status change, or other performance events.
    Stored in TimescaleDB hypertable with 90-day retention.
    """
    snapshot_id: str
    snapshot_time: str              # ISO timestamp
    agent_id: str
    org_id: Optional[str] = None

    # Task context
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    project_id: Optional[str] = None

    # Task metrics
    task_completed: bool = False
    task_success: bool = False
    task_duration_ms: Optional[int] = None

    # Token metrics
    tokens_used: int = 0
    baseline_tokens: int = 0
    token_savings_pct: Optional[float] = None

    # Behavior metrics
    behaviors_cited: int = 0
    unique_behaviors: List[str] = field(default_factory=list)

    # Compliance metrics
    compliance_checks_passed: int = 0
    compliance_checks_total: int = 0

    # Status tracking
    status_from: Optional[str] = None
    status_to: Optional[str] = None
    time_in_status_ms: Optional[int] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_time": self.snapshot_time,
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "task_completed": self.task_completed,
            "task_success": self.task_success,
            "task_duration_ms": self.task_duration_ms,
            "tokens_used": self.tokens_used,
            "baseline_tokens": self.baseline_tokens,
            "token_savings_pct": self.token_savings_pct,
            "behaviors_cited": self.behaviors_cited,
            "unique_behaviors": list(self.unique_behaviors),
            "compliance_checks_passed": self.compliance_checks_passed,
            "compliance_checks_total": self.compliance_checks_total,
            "status_from": self.status_from,
            "status_to": self.status_to,
            "time_in_status_ms": self.time_in_status_ms,
            "metadata": dict(self.metadata),
        }


@dataclass
class AgentPerformanceSummary:
    """Aggregated performance summary for an agent.

    Returned by get_agent_summary() and used in dashboard displays.
    """
    agent_id: str
    agent_name: str
    period_start: str               # ISO timestamp
    period_end: str                 # ISO timestamp

    # Task metrics
    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_total: int = 0
    success_rate_pct: Optional[float] = None

    # Time metrics
    avg_task_duration_ms: Optional[int] = None
    min_task_duration_ms: Optional[int] = None
    max_task_duration_ms: Optional[int] = None
    total_execution_time_ms: int = 0

    # Token metrics
    total_tokens_used: int = 0
    total_baseline_tokens: int = 0
    avg_token_savings_pct: Optional[float] = None

    # Behavior metrics
    total_behaviors_cited: int = 0
    unique_behaviors_count: int = 0
    behavior_reuse_rate_pct: Optional[float] = None
    top_behaviors: List[str] = field(default_factory=list)

    # Compliance metrics
    compliance_checks_passed: int = 0
    compliance_checks_total: int = 0
    compliance_coverage_pct: Optional[float] = None

    # Utilization metrics
    time_busy_ms: int = 0
    time_idle_ms: int = 0
    time_paused_ms: int = 0
    utilization_pct: Optional[float] = None

    # Assignment metrics
    switch_count: int = 0
    assignments_count: int = 0

    # Alert status
    active_alerts: int = 0
    alert_severities: Dict[str, int] = field(default_factory=dict)

    # Org/project context
    org_id: Optional[str] = None
    project_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "tasks_total": self.tasks_total,
            "success_rate_pct": self.success_rate_pct,
            "avg_task_duration_ms": self.avg_task_duration_ms,
            "min_task_duration_ms": self.min_task_duration_ms,
            "max_task_duration_ms": self.max_task_duration_ms,
            "total_execution_time_ms": self.total_execution_time_ms,
            "total_tokens_used": self.total_tokens_used,
            "total_baseline_tokens": self.total_baseline_tokens,
            "avg_token_savings_pct": self.avg_token_savings_pct,
            "total_behaviors_cited": self.total_behaviors_cited,
            "unique_behaviors_count": self.unique_behaviors_count,
            "behavior_reuse_rate_pct": self.behavior_reuse_rate_pct,
            "top_behaviors": list(self.top_behaviors),
            "compliance_checks_passed": self.compliance_checks_passed,
            "compliance_checks_total": self.compliance_checks_total,
            "compliance_coverage_pct": self.compliance_coverage_pct,
            "time_busy_ms": self.time_busy_ms,
            "time_idle_ms": self.time_idle_ms,
            "time_paused_ms": self.time_paused_ms,
            "utilization_pct": self.utilization_pct,
            "switch_count": self.switch_count,
            "assignments_count": self.assignments_count,
            "active_alerts": self.active_alerts,
            "alert_severities": dict(self.alert_severities),
            "org_id": self.org_id,
            "project_id": self.project_id,
        }


@dataclass
class AgentPerformanceDaily:
    """Daily rollup for dashboard queries.

    Pre-computed aggregates stored with 1-year retention.
    """
    rollup_id: str
    rollup_date: str                # YYYY-MM-DD
    agent_id: str
    org_id: Optional[str] = None
    project_id: Optional[str] = None

    # Aggregated metrics (same structure as summary)
    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_total: int = 0
    success_rate_pct: Optional[float] = None
    avg_task_duration_ms: Optional[int] = None
    min_task_duration_ms: Optional[int] = None
    max_task_duration_ms: Optional[int] = None
    total_execution_time_ms: int = 0
    total_tokens_used: int = 0
    total_baseline_tokens: int = 0
    avg_token_savings_pct: Optional[float] = None
    total_behaviors_cited: int = 0
    unique_behaviors_count: int = 0
    behavior_reuse_rate_pct: Optional[float] = None
    compliance_checks_passed: int = 0
    compliance_checks_total: int = 0
    compliance_coverage_pct: Optional[float] = None
    time_busy_ms: int = 0
    time_idle_ms: int = 0
    time_paused_ms: int = 0
    utilization_pct: Optional[float] = None
    switch_count: int = 0
    assignments_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rollup_id": self.rollup_id,
            "rollup_date": self.rollup_date,
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "project_id": self.project_id,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "tasks_total": self.tasks_total,
            "success_rate_pct": self.success_rate_pct,
            "avg_task_duration_ms": self.avg_task_duration_ms,
            "min_task_duration_ms": self.min_task_duration_ms,
            "max_task_duration_ms": self.max_task_duration_ms,
            "total_execution_time_ms": self.total_execution_time_ms,
            "total_tokens_used": self.total_tokens_used,
            "total_baseline_tokens": self.total_baseline_tokens,
            "avg_token_savings_pct": self.avg_token_savings_pct,
            "total_behaviors_cited": self.total_behaviors_cited,
            "unique_behaviors_count": self.unique_behaviors_count,
            "behavior_reuse_rate_pct": self.behavior_reuse_rate_pct,
            "compliance_checks_passed": self.compliance_checks_passed,
            "compliance_checks_total": self.compliance_checks_total,
            "compliance_coverage_pct": self.compliance_coverage_pct,
            "time_busy_ms": self.time_busy_ms,
            "time_idle_ms": self.time_idle_ms,
            "time_paused_ms": self.time_paused_ms,
            "utilization_pct": self.utilization_pct,
            "switch_count": self.switch_count,
            "assignments_count": self.assignments_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class PerformanceAlert:
    """Performance threshold alert.

    Generated when an agent's metrics cross configured thresholds.
    """
    alert_id: str
    created_at: str                 # ISO timestamp
    agent_id: str

    # Alert details
    metric_type: str                # PerformanceMetricType value
    severity: str                   # PerformanceAlertSeverity value
    current_value: float
    threshold_value: float
    threshold_direction: str        # ThresholdDirection value

    # Context
    period_start: str
    period_end: str

    # Optional fields (must come after required)
    org_id: Optional[str] = None
    sample_count: int = 0

    # Resolution
    acknowledged_at: Optional[str] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[str] = None
    resolution_notes: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "created_at": self.created_at,
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "metric_type": self.metric_type,
            "severity": self.severity,
            "current_value": self.current_value,
            "threshold_value": self.threshold_value,
            "threshold_direction": self.threshold_direction,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "sample_count": self.sample_count,
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
            "resolved_at": self.resolved_at,
            "resolution_notes": self.resolution_notes,
            "metadata": dict(self.metadata),
        }

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    @property
    def is_acknowledged(self) -> bool:
        return self.acknowledged_at is not None


@dataclass
class AgentPerformanceThresholds:
    """Configurable performance thresholds.

    Can be set at global, org, or agent level with cascade precedence.
    """
    threshold_id: str
    org_id: Optional[str] = None    # NULL = global default
    agent_id: Optional[str] = None  # NULL = org-wide default

    # Success rate thresholds
    success_rate_warning: float = PerformanceThresholds.SUCCESS_RATE_WARNING
    success_rate_critical: float = PerformanceThresholds.SUCCESS_RATE_CRITICAL

    # Token savings thresholds
    token_savings_warning: float = PerformanceThresholds.TOKEN_SAVINGS_WARNING
    token_savings_critical: float = PerformanceThresholds.TOKEN_SAVINGS_CRITICAL

    # Behavior reuse thresholds
    behavior_reuse_warning: float = PerformanceThresholds.BEHAVIOR_REUSE_WARNING
    behavior_reuse_critical: float = PerformanceThresholds.BEHAVIOR_REUSE_CRITICAL

    # Compliance coverage thresholds
    compliance_coverage_warning: float = PerformanceThresholds.COMPLIANCE_COVERAGE_WARNING
    compliance_coverage_critical: float = PerformanceThresholds.COMPLIANCE_COVERAGE_CRITICAL

    # Duration thresholds (ms)
    avg_duration_warning_ms: int = PerformanceThresholds.AVG_DURATION_WARNING_MS
    avg_duration_critical_ms: int = PerformanceThresholds.AVG_DURATION_CRITICAL_MS

    # Utilization thresholds
    utilization_low_warning: float = PerformanceThresholds.UTILIZATION_LOW_WARNING
    utilization_high_warning: float = PerformanceThresholds.UTILIZATION_HIGH_WARNING

    # Evaluation settings
    evaluation_window_hours: int = PerformanceThresholds.DEFAULT_EVALUATION_WINDOW_HOURS
    min_sample_size: int = PerformanceThresholds.DEFAULT_MIN_SAMPLE_SIZE

    # Metadata
    created_at: str = ""
    updated_at: str = ""
    created_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "threshold_id": self.threshold_id,
            "org_id": self.org_id,
            "agent_id": self.agent_id,
            "success_rate_warning": self.success_rate_warning,
            "success_rate_critical": self.success_rate_critical,
            "token_savings_warning": self.token_savings_warning,
            "token_savings_critical": self.token_savings_critical,
            "behavior_reuse_warning": self.behavior_reuse_warning,
            "behavior_reuse_critical": self.behavior_reuse_critical,
            "compliance_coverage_warning": self.compliance_coverage_warning,
            "compliance_coverage_critical": self.compliance_coverage_critical,
            "avg_duration_warning_ms": self.avg_duration_warning_ms,
            "avg_duration_critical_ms": self.avg_duration_critical_ms,
            "utilization_low_warning": self.utilization_low_warning,
            "utilization_high_warning": self.utilization_high_warning,
            "evaluation_window_hours": self.evaluation_window_hours,
            "min_sample_size": self.min_sample_size,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
        }


# =============================================================================
# Request/Response Types
# =============================================================================


@dataclass
class RecordTaskCompletionRequest:
    """Request to record a task completion event."""
    agent_id: str
    run_id: str
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    org_id: Optional[str] = None
    success: bool = True
    duration_ms: Optional[int] = None
    tokens_used: int = 0
    baseline_tokens: int = 0
    behaviors_cited: List[str] = field(default_factory=list)
    compliance_passed: int = 0
    compliance_total: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecordStatusChangeRequest:
    """Request to record an agent status change."""
    agent_id: str
    status_from: str
    status_to: str
    time_in_status_ms: int
    org_id: Optional[str] = None
    task_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GetAgentPerformanceRequest:
    """Request to get agent performance summary."""
    agent_id: str
    period_days: int = 30
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    include_alerts: bool = True


@dataclass
class GetTopPerformersRequest:
    """Request to get top performing agents."""
    metric: str = "success_rate"    # Sort by this metric
    limit: int = 10
    period_days: int = 30
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    min_tasks: int = 5              # Minimum tasks to qualify


@dataclass
class CompareAgentsRequest:
    """Request to compare multiple agents."""
    agent_ids: List[str]
    period_days: int = 30
    org_id: Optional[str] = None
    project_id: Optional[str] = None


@dataclass
class GetPerformanceAlertsRequest:
    """Request to get performance alerts."""
    agent_id: Optional[str] = None
    org_id: Optional[str] = None
    severity: Optional[str] = None
    include_resolved: bool = False
    limit: int = 50


@dataclass
class AcknowledgeAlertRequest:
    """Request to acknowledge an alert."""
    alert_id: str
    acknowledged_by: str
    notes: Optional[str] = None


@dataclass
class ResolveAlertRequest:
    """Request to resolve an alert."""
    alert_id: str
    resolution_notes: str


@dataclass
class UpdateThresholdsRequest:
    """Request to update performance thresholds."""
    org_id: Optional[str] = None
    agent_id: Optional[str] = None
    success_rate_warning: Optional[float] = None
    success_rate_critical: Optional[float] = None
    token_savings_warning: Optional[float] = None
    token_savings_critical: Optional[float] = None
    behavior_reuse_warning: Optional[float] = None
    behavior_reuse_critical: Optional[float] = None
    compliance_coverage_warning: Optional[float] = None
    compliance_coverage_critical: Optional[float] = None
    avg_duration_warning_ms: Optional[int] = None
    avg_duration_critical_ms: Optional[int] = None
    utilization_low_warning: Optional[float] = None
    utilization_high_warning: Optional[float] = None
    evaluation_window_hours: Optional[int] = None
    min_sample_size: Optional[int] = None
    updated_by: Optional[str] = None


# =============================================================================
# Response Types
# =============================================================================


@dataclass
class AgentPerformanceResponse:
    """Response containing agent performance summary."""
    summary: AgentPerformanceSummary
    alerts: List[PerformanceAlert] = field(default_factory=list)
    thresholds: Optional[AgentPerformanceThresholds] = None
    daily_trend: List[AgentPerformanceDaily] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary.to_dict(),
            "alerts": [a.to_dict() for a in self.alerts],
            "thresholds": self.thresholds.to_dict() if self.thresholds else None,
            "daily_trend": [d.to_dict() for d in self.daily_trend],
        }


@dataclass
class TopPerformersResponse:
    """Response containing top performing agents."""
    metric: str
    period_days: int
    agents: List[AgentPerformanceSummary]
    total_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "period_days": self.period_days,
            "agents": [a.to_dict() for a in self.agents],
            "total_count": self.total_count,
        }


@dataclass
class CompareAgentsResponse:
    """Response containing agent comparison."""
    period_days: int
    agents: List[AgentPerformanceSummary]
    comparison_metrics: Dict[str, Dict[str, float]]  # metric -> agent_id -> value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period_days": self.period_days,
            "agents": [a.to_dict() for a in self.agents],
            "comparison_metrics": dict(self.comparison_metrics),
        }
