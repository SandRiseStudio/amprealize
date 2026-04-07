"""Data contracts for MetricsService - real-time metrics aggregation and caching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MetricsSummary:
    """Real-time aggregated metrics summary.

    Attributes:
        snapshot_time: ISO timestamp when metrics were captured
        behavior_reuse_pct: Percentage of runs citing behaviors (PRD target: 70%)
        average_token_savings_pct: Average token reduction via BCI (PRD target: 30%)
        task_completion_rate_pct: Percentage of runs completed successfully (PRD target: 80%)
        average_compliance_coverage_pct: Average checklist coverage (PRD target: 95%)
        total_runs: Total number of runs in the period
        runs_with_behaviors: Runs that cited ≥1 behavior
        total_baseline_tokens: Sum of baseline token counts
        total_output_tokens: Sum of actual output tokens
        completed_runs: Number of successfully completed runs
        failed_runs: Number of failed runs
        total_compliance_events: Total compliance checklist events
        cache_hit: Whether this summary was served from cache
        cache_age_seconds: Age of cached data in seconds (0 if fresh)
    """

    snapshot_time: str
    behavior_reuse_pct: float
    average_token_savings_pct: float
    task_completion_rate_pct: float
    average_compliance_coverage_pct: float
    total_runs: int
    runs_with_behaviors: int
    total_baseline_tokens: int
    total_output_tokens: int
    completed_runs: int
    failed_runs: int
    total_compliance_events: int
    cache_hit: bool = False
    cache_age_seconds: float = 0.0


@dataclass
class MetricsExportRequest:
    """Request to export metrics data.

    Attributes:
        format: Export format ('json', 'csv', 'parquet')
        start_date: Start date for export (ISO format, optional)
        end_date: End date for export (ISO format, optional)
        metrics: List of metric names to export (empty = all)
        include_raw_events: Whether to include raw telemetry events
    """

    format: str = "json"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    metrics: List[str] = field(default_factory=list)
    include_raw_events: bool = False


@dataclass
class MetricsExportResult:
    """Result of metrics export operation.

    Attributes:
        export_id: Unique identifier for this export
        format: Export format used
        row_count: Number of rows exported
        file_path: Path to exported file (if file-based)
        data: Inline data (if format=json and small enough)
        created_at: ISO timestamp when export was created
        size_bytes: Size of export in bytes
    """

    export_id: str
    format: str
    row_count: int
    created_at: str
    size_bytes: int
    file_path: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None


@dataclass
class MetricsSubscription:
    """Subscription to real-time metrics updates via SSE.

    Attributes:
        subscription_id: Unique identifier for this subscription
        metrics: List of metric names to stream (empty = all KPIs)
        refresh_interval_seconds: How often to push updates
        created_at: ISO timestamp when subscription started
        event_count: Number of events sent so far
    """

    subscription_id: str
    metrics: List[str] = field(default_factory=list)
    refresh_interval_seconds: int = 30
    created_at: str = ""
    event_count: int = 0
