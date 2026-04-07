"""AgentPerformanceService - Agent performance metrics tracking.

Feature 13.4.6 - Event-driven performance tracking with daily rollups and alerts.
Behavior: behavior_instrument_metrics_pipeline
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from amprealize.agent_performance_contracts import (
    AgentPerformanceDaily,
    AgentPerformanceSnapshot,
    AgentPerformanceSummary,
    AgentPerformanceThresholds,
    PerformanceAlert,
    PerformanceAlertSeverity,
    PerformanceMetricType,
    PerformanceThresholds,
    ThresholdDirection,
    RecordTaskCompletionRequest,
    RecordStatusChangeRequest,
)
from amprealize.storage.postgres_pool import PostgresPool
from amprealize.telemetry import TelemetryClient


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _uuid_str() -> str:
    """Generate a UUID string for database columns."""
    return str(uuid.uuid4())


class AgentPerformanceServiceError(Exception):
    """Base error for AgentPerformanceService."""


class AgentNotFoundError(AgentPerformanceServiceError):
    """Agent not found."""


class AlertNotFoundError(AgentPerformanceServiceError):
    """Alert not found."""


class AgentPerformanceService:
    """Service for tracking agent performance metrics.

    Features:
    - Event-driven snapshots on task completion/status change
    - Daily rollups for dashboard queries
    - Configurable thresholds with alerts
    - 90-day detailed retention, 1-year aggregated
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        telemetry: Optional[TelemetryClient] = None,
    ) -> None:
        self._pool = PostgresPool(dsn)
        self._telemetry = telemetry or TelemetryClient.noop()

    # ------------------------------------------------------------------
    # Recording Methods
    # ------------------------------------------------------------------

    def record_task_completion(
        self,
        request: RecordTaskCompletionRequest,
    ) -> AgentPerformanceSnapshot:
        """Record a task completion event for an agent."""
        snapshot_id = _uuid_str()
        snapshot_time = _utc_now_iso()

        # Calculate token savings
        token_savings_pct = None
        if request.baseline_tokens > 0:
            token_savings_pct = round(
                ((request.baseline_tokens - request.tokens_used) / request.baseline_tokens) * 100, 2
            )

        snapshot = AgentPerformanceSnapshot(
            snapshot_id=snapshot_id,
            snapshot_time=snapshot_time,
            agent_id=request.agent_id,
            org_id=request.org_id,
            run_id=request.run_id,
            task_id=request.task_id,
            project_id=request.project_id,
            task_completed=True,
            task_success=request.success,
            task_duration_ms=request.duration_ms,
            tokens_used=request.tokens_used,
            baseline_tokens=request.baseline_tokens,
            token_savings_pct=token_savings_pct,
            behaviors_cited=len(request.behaviors_cited),
            unique_behaviors=list(request.behaviors_cited),
            compliance_checks_passed=request.compliance_passed,
            compliance_checks_total=request.compliance_total,
            metadata=request.metadata,
        )

        self._insert_snapshot(snapshot)
        self._emit_telemetry("agent_performance.task_completed", snapshot.to_dict())
        return snapshot

    def record_status_change(
        self,
        request: RecordStatusChangeRequest,
    ) -> AgentPerformanceSnapshot:
        """Record an agent status change event."""
        snapshot_id = _uuid_str()
        snapshot_time = _utc_now_iso()

        snapshot = AgentPerformanceSnapshot(
            snapshot_id=snapshot_id,
            snapshot_time=snapshot_time,
            agent_id=request.agent_id,
            org_id=request.org_id,
            task_id=request.task_id,
            status_from=request.status_from,
            status_to=request.status_to,
            time_in_status_ms=request.time_in_status_ms,
            metadata=request.metadata,
        )

        self._insert_snapshot(snapshot)
        self._emit_telemetry("agent_performance.status_changed", snapshot.to_dict())
        return snapshot

    def _insert_snapshot(self, snapshot: AgentPerformanceSnapshot) -> None:
        """Insert snapshot into database."""
        with self._pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO agent_performance_snapshots (
                    snapshot_id, snapshot_time, agent_id, org_id,
                    run_id, task_id, project_id,
                    task_completed, task_success, task_duration_ms,
                    tokens_used, baseline_tokens, token_savings_pct,
                    behaviors_cited, unique_behaviors,
                    compliance_checks_passed, compliance_checks_total,
                    status_from, status_to, time_in_status_ms,
                    metadata
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.snapshot_time,
                    snapshot.agent_id,
                    snapshot.org_id,
                    snapshot.run_id,
                    snapshot.task_id,
                    snapshot.project_id,
                    snapshot.task_completed,
                    snapshot.task_success,
                    snapshot.task_duration_ms,
                    snapshot.tokens_used,
                    snapshot.baseline_tokens,
                    snapshot.token_savings_pct,
                    snapshot.behaviors_cited,
                    snapshot.unique_behaviors,
                    snapshot.compliance_checks_passed,
                    snapshot.compliance_checks_total,
                    snapshot.status_from,
                    snapshot.status_to,
                    snapshot.time_in_status_ms,
                    Json(snapshot.metadata) if snapshot.metadata else Json({}),
                ),
            )
            conn.commit()
            cur.close()

    def _emit_telemetry(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Emit telemetry event."""
        self._telemetry.emit_event(event_type=event_type, payload=payload)

    # ------------------------------------------------------------------
    # Query Methods
    # ------------------------------------------------------------------

    def get_agent_summary(
        self,
        agent_id: str,
        org_id: Optional[str] = None,
        period_days: int = 30,
    ) -> AgentPerformanceSummary:
        """Get performance summary for a single agent."""
        start_date = (_utc_now() - timedelta(days=period_days)).isoformat()
        end_date = _utc_now_iso()

        with self._pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE task_completed) as tasks_completed,
                    COUNT(*) FILTER (WHERE task_completed AND NOT task_success) as tasks_failed,
                    COUNT(*) FILTER (WHERE task_completed) as tasks_total,
                    ROUND(AVG(task_duration_ms)::numeric, 2) as avg_duration,
                    MIN(task_duration_ms) as min_duration,
                    MAX(task_duration_ms) as max_duration,
                    SUM(task_duration_ms) as total_duration,
                    SUM(tokens_used) as total_tokens,
                    SUM(baseline_tokens) as total_baseline,
                    ROUND(AVG(token_savings_pct)::numeric, 2) as avg_token_savings,
                    SUM(behaviors_cited) as total_behaviors,
                    SUM(compliance_checks_passed) as compliance_passed,
                    SUM(compliance_checks_total) as compliance_total
                FROM agent_performance_snapshots
                WHERE agent_id = %s
                  AND snapshot_time >= %s
                  AND snapshot_time <= %s
                  AND (%s IS NULL OR org_id = %s)
                """,
                (agent_id, start_date, end_date, org_id, org_id),
            )
            row = cur.fetchone()
            cur.close()

        if not row or row[0] is None or row[0] == 0:
            raise AgentNotFoundError(f"No performance data for agent {agent_id}")

        tasks_completed = row[0] or 0
        tasks_failed = row[1] or 0
        compliance_passed = row[11] or 0
        compliance_total = row[12] or 0
        total_tokens = row[7] or 0
        total_baseline = row[8] or 0

        success_rate = round(((tasks_completed - tasks_failed) / tasks_completed * 100), 2) if tasks_completed > 0 else 0.0
        compliance_rate = round((compliance_passed / compliance_total * 100), 2) if compliance_total > 0 else 100.0
        token_savings = round(((total_baseline - total_tokens) / total_baseline * 100), 2) if total_baseline > 0 else 0.0

        return AgentPerformanceSummary(
            agent_id=agent_id,
            agent_name=agent_id,  # Could be enriched from agent registry
            period_start=start_date,
            period_end=end_date,
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            tasks_total=row[2] or 0,
            success_rate_pct=success_rate,
            avg_task_duration_ms=int(row[3]) if row[3] else None,
            min_task_duration_ms=row[4],
            max_task_duration_ms=row[5],
            total_execution_time_ms=row[6] or 0,
            total_tokens_used=total_tokens,
            total_baseline_tokens=total_baseline,
            avg_token_savings_pct=float(row[9]) if row[9] else token_savings,
            total_behaviors_cited=row[10] or 0,
            compliance_checks_passed=compliance_passed,
            compliance_checks_total=compliance_total,
            compliance_coverage_pct=compliance_rate,
            org_id=org_id,
        )

    def get_top_performers(
        self,
        metric: str = "success_rate",
        limit: int = 10,
        period_days: int = 30,
        org_id: Optional[str] = None,
        min_tasks: int = 5,
    ) -> List[AgentPerformanceSummary]:
        """Get top performing agents by specified metric."""
        start_date = (_utc_now() - timedelta(days=period_days)).isoformat()
        end_date = _utc_now_iso()

        # Map metric to SQL ordering
        metric_map = {
            "success_rate": "success_rate DESC",
            "token_savings": "avg_token_savings DESC NULLS LAST",
            "tasks_completed": "tasks_completed DESC",
            "behaviors_cited": "total_behaviors DESC",
        }
        order_clause = metric_map.get(metric, "success_rate DESC")

        with self._pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                WITH agent_stats AS (
                    SELECT
                        agent_id,
                        COUNT(*) FILTER (WHERE task_completed) as tasks_completed,
                        COUNT(*) FILTER (WHERE task_completed AND NOT task_success) as tasks_failed,
                        ROUND(AVG(task_duration_ms)::numeric, 2) as avg_duration,
                        MIN(task_duration_ms) as min_duration,
                        MAX(task_duration_ms) as max_duration,
                        SUM(task_duration_ms) as total_duration,
                        SUM(tokens_used) as total_tokens,
                        SUM(baseline_tokens) as total_baseline,
                        ROUND(AVG(token_savings_pct)::numeric, 2) as avg_token_savings,
                        SUM(behaviors_cited) as total_behaviors,
                        SUM(compliance_checks_passed) as compliance_passed,
                        SUM(compliance_checks_total) as compliance_total,
                        CASE WHEN COUNT(*) FILTER (WHERE task_completed) > 0
                            THEN ROUND((COUNT(*) FILTER (WHERE task_success)::float /
                                  COUNT(*) FILTER (WHERE task_completed) * 100)::numeric, 2)
                            ELSE 0 END as success_rate
                    FROM agent_performance_snapshots
                    WHERE snapshot_time >= %s
                      AND snapshot_time <= %s
                      AND (%s IS NULL OR org_id = %s)
                    GROUP BY agent_id
                    HAVING COUNT(*) FILTER (WHERE task_completed) >= %s
                )
                SELECT * FROM agent_stats
                ORDER BY {order_clause}
                LIMIT %s
                """,
                (start_date, end_date, org_id, org_id, min_tasks, limit),
            )
            rows = cur.fetchall()
            cur.close()

        results = []
        for row in rows:
            tasks_completed = row[1] or 0
            tasks_failed = row[2] or 0
            compliance_passed = row[11] or 0
            compliance_total = row[12] or 0
            total_tokens = row[7] or 0
            total_baseline = row[8] or 0

            compliance_rate = round((compliance_passed / compliance_total * 100), 2) if compliance_total > 0 else 100.0
            token_savings = round(((total_baseline - total_tokens) / total_baseline * 100), 2) if total_baseline > 0 else 0.0

            results.append(AgentPerformanceSummary(
                agent_id=row[0],
                agent_name=row[0],
                period_start=start_date,
                period_end=end_date,
                tasks_completed=tasks_completed,
                tasks_failed=tasks_failed,
                tasks_total=tasks_completed,
                success_rate_pct=float(row[13]) if row[13] else 0.0,
                avg_task_duration_ms=int(row[3]) if row[3] else None,
                min_task_duration_ms=row[4],
                max_task_duration_ms=row[5],
                total_execution_time_ms=row[6] or 0,
                total_tokens_used=total_tokens,
                total_baseline_tokens=total_baseline,
                avg_token_savings_pct=float(row[9]) if row[9] else token_savings,
                total_behaviors_cited=row[10] or 0,
                compliance_checks_passed=compliance_passed,
                compliance_checks_total=compliance_total,
                compliance_coverage_pct=compliance_rate,
                org_id=org_id,
            ))
        return results

    def compare_agents(
        self,
        agent_ids: List[str],
        period_days: int = 30,
        org_id: Optional[str] = None,
    ) -> List[AgentPerformanceSummary]:
        """Compare performance metrics across multiple agents."""
        results = []
        for agent_id in agent_ids:
            try:
                summary = self.get_agent_summary(
                    agent_id=agent_id,
                    org_id=org_id,
                    period_days=period_days,
                )
                results.append(summary)
            except AgentNotFoundError:
                continue
        return results

    # ------------------------------------------------------------------
    # Alert Methods
    # ------------------------------------------------------------------

    def check_thresholds(
        self,
        agent_id: str,
        org_id: Optional[str] = None,
    ) -> List[PerformanceAlert]:
        """Check agent metrics against thresholds and create alerts if needed."""
        try:
            summary = self.get_agent_summary(agent_id=agent_id, org_id=org_id)
        except AgentNotFoundError:
            return []

        thresholds = self.get_thresholds(agent_id=agent_id, org_id=org_id)
        alerts = []

        # Check success rate
        if summary.success_rate_pct is not None and summary.success_rate_pct < thresholds.success_rate_warning:
            severity = PerformanceAlertSeverity.CRITICAL.value if summary.success_rate_pct < thresholds.success_rate_critical else PerformanceAlertSeverity.WARNING.value
            alert = self._create_alert(
                agent_id=agent_id,
                org_id=org_id,
                metric_type=PerformanceMetricType.SUCCESS_RATE.value,
                current_value=summary.success_rate_pct,
                threshold_value=thresholds.success_rate_warning,
                severity=severity,
                period_start=summary.period_start,
                period_end=summary.period_end,
            )
            if alert:
                alerts.append(alert)

        # Check token savings
        if summary.avg_token_savings_pct is not None and summary.avg_token_savings_pct < thresholds.token_savings_warning:
            severity = PerformanceAlertSeverity.CRITICAL.value if summary.avg_token_savings_pct < thresholds.token_savings_critical else PerformanceAlertSeverity.WARNING.value
            alert = self._create_alert(
                agent_id=agent_id,
                org_id=org_id,
                metric_type=PerformanceMetricType.TOKEN_EFFICIENCY.value,
                current_value=summary.avg_token_savings_pct,
                threshold_value=thresholds.token_savings_warning,
                severity=severity,
                period_start=summary.period_start,
                period_end=summary.period_end,
            )
            if alert:
                alerts.append(alert)

        # Check compliance rate
        if summary.compliance_coverage_pct is not None and summary.compliance_coverage_pct < thresholds.compliance_coverage_warning:
            severity = PerformanceAlertSeverity.CRITICAL.value if summary.compliance_coverage_pct < thresholds.compliance_coverage_critical else PerformanceAlertSeverity.WARNING.value
            alert = self._create_alert(
                agent_id=agent_id,
                org_id=org_id,
                metric_type=PerformanceMetricType.COMPLIANCE_COVERAGE.value,
                current_value=summary.compliance_coverage_pct,
                threshold_value=thresholds.compliance_coverage_warning,
                severity=severity,
                period_start=summary.period_start,
                period_end=summary.period_end,
            )
            if alert:
                alerts.append(alert)

        return alerts

    def _create_alert(
        self,
        agent_id: str,
        org_id: Optional[str],
        metric_type: str,
        current_value: float,
        threshold_value: float,
        severity: str,
        period_start: str,
        period_end: str,
    ) -> Optional[PerformanceAlert]:
        """Create an alert if one doesn't already exist for this metric."""
        alert_id = _uuid_str()
        created_at = _utc_now_iso()

        with self._pool.connection() as conn:
            cur = conn.cursor()
            # Check for existing unresolved alert
            cur.execute(
                """
                SELECT alert_id FROM agent_performance_alerts
                WHERE agent_id = %s
                  AND metric_type = %s
                  AND resolved_at IS NULL
                LIMIT 1
                """,
                (agent_id, metric_type),
            )
            if cur.fetchone():
                cur.close()
                return None  # Already have active alert

            cur.execute(
                """
                INSERT INTO agent_performance_alerts (
                    alert_id, agent_id, org_id, metric_type,
                    current_value, threshold_value, severity,
                    threshold_direction, period_start, period_end, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    alert_id, agent_id, org_id, metric_type,
                    current_value, threshold_value, severity,
                    ThresholdDirection.BELOW.value, period_start, period_end, created_at,
                ),
            )
            conn.commit()
            cur.close()

        alert = PerformanceAlert(
            alert_id=alert_id,
            created_at=created_at,
            agent_id=agent_id,
            org_id=org_id,
            metric_type=metric_type,
            severity=severity,
            current_value=current_value,
            threshold_value=threshold_value,
            threshold_direction=ThresholdDirection.BELOW.value,
            period_start=period_start,
            period_end=period_end,
        )
        self._emit_telemetry("agent_performance.alert_created", alert.to_dict())
        return alert

    def get_alerts(
        self,
        agent_id: Optional[str] = None,
        org_id: Optional[str] = None,
        severity: Optional[str] = None,
        include_resolved: bool = False,
        limit: int = 50,
    ) -> List[PerformanceAlert]:
        """Get performance alerts with optional filters."""
        with self._pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    alert_id, created_at, agent_id, org_id, metric_type,
                    severity, current_value, threshold_value, threshold_direction,
                    period_start, period_end, sample_count,
                    acknowledged_at, acknowledged_by, resolved_at, resolution_notes
                FROM agent_performance_alerts
                WHERE (%s IS NULL OR agent_id = %s)
                  AND (%s IS NULL OR org_id = %s)
                  AND (%s IS NULL OR severity = %s)
                  AND (%s OR resolved_at IS NULL)
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (
                    agent_id, agent_id,
                    org_id, org_id,
                    severity, severity,
                    include_resolved,
                    limit,
                ),
            )
            rows = cur.fetchall()
            cur.close()

        return [
            PerformanceAlert(
                alert_id=row[0],
                created_at=row[1].isoformat() if row[1] else "",
                agent_id=row[2],
                org_id=row[3],
                metric_type=row[4],
                severity=row[5],
                current_value=row[6],
                threshold_value=row[7],
                threshold_direction=row[8],
                period_start=row[9].isoformat() if row[9] else "",
                period_end=row[10].isoformat() if row[10] else "",
                sample_count=row[11] or 0,
                acknowledged_at=row[12].isoformat() if row[12] else None,
                acknowledged_by=row[13],
                resolved_at=row[14].isoformat() if row[14] else None,
                resolution_notes=row[15],
            )
            for row in rows
        ]

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> PerformanceAlert:
        """Acknowledge an alert."""
        acknowledged_at = _utc_now_iso()

        with self._pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE agent_performance_alerts
                SET acknowledged_at = %s, acknowledged_by = %s
                WHERE alert_id = %s
                RETURNING agent_id, org_id, metric_type, current_value, threshold_value,
                          severity, threshold_direction, period_start, period_end, created_at
                """,
                (acknowledged_at, acknowledged_by, alert_id),
            )
            row = cur.fetchone()
            if not row:
                cur.close()
                raise AlertNotFoundError(f"Alert {alert_id} not found")
            conn.commit()
            cur.close()

        return PerformanceAlert(
            alert_id=alert_id,
            created_at=row[9].isoformat() if row[9] else "",
            agent_id=row[0],
            org_id=row[1],
            metric_type=row[2],
            severity=row[5],
            current_value=row[3],
            threshold_value=row[4],
            threshold_direction=row[6],
            period_start=row[7].isoformat() if row[7] else "",
            period_end=row[8].isoformat() if row[8] else "",
            acknowledged_at=acknowledged_at,
            acknowledged_by=acknowledged_by,
        )

    def resolve_alert(self, alert_id: str, resolution_notes: str) -> PerformanceAlert:
        """Resolve an alert."""
        resolved_at = _utc_now_iso()

        with self._pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE agent_performance_alerts
                SET resolved_at = %s, resolution_notes = %s
                WHERE alert_id = %s
                RETURNING agent_id, org_id, metric_type, current_value, threshold_value,
                          severity, threshold_direction, period_start, period_end,
                          created_at, acknowledged_at, acknowledged_by
                """,
                (resolved_at, resolution_notes, alert_id),
            )
            row = cur.fetchone()
            if not row:
                cur.close()
                raise AlertNotFoundError(f"Alert {alert_id} not found")
            conn.commit()
            cur.close()

        self._emit_telemetry("agent_performance.alert_resolved", {"alert_id": alert_id})
        return PerformanceAlert(
            alert_id=alert_id,
            created_at=row[9].isoformat() if row[9] else "",
            agent_id=row[0],
            org_id=row[1],
            metric_type=row[2],
            severity=row[5],
            current_value=row[3],
            threshold_value=row[4],
            threshold_direction=row[6],
            period_start=row[7].isoformat() if row[7] else "",
            period_end=row[8].isoformat() if row[8] else "",
            acknowledged_at=row[10].isoformat() if row[10] else None,
            acknowledged_by=row[11],
            resolved_at=resolved_at,
            resolution_notes=resolution_notes,
        )

    # ------------------------------------------------------------------
    # Threshold Management
    # ------------------------------------------------------------------

    def get_thresholds(
        self,
        agent_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> AgentPerformanceThresholds:
        """Get thresholds for an agent (custom or defaults)."""
        with self._pool.connection() as conn:
            cur = conn.cursor()
            # Try agent-specific first, then org, then global default
            cur.execute(
                """
                SELECT
                    threshold_id, org_id, agent_id,
                    success_rate_warning, success_rate_critical,
                    token_savings_warning, token_savings_critical,
                    behavior_reuse_warning, behavior_reuse_critical,
                    compliance_coverage_warning, compliance_coverage_critical,
                    avg_duration_warning_ms, avg_duration_critical_ms,
                    utilization_low_warning, utilization_high_warning,
                    evaluation_window_hours, min_sample_size
                FROM agent_performance_thresholds
                WHERE (agent_id = %s)
                   OR (agent_id IS NULL AND org_id = %s)
                   OR (agent_id IS NULL AND org_id IS NULL)
                ORDER BY
                    CASE WHEN agent_id IS NOT NULL THEN 1
                         WHEN org_id IS NOT NULL THEN 2
                         ELSE 3 END
                LIMIT 1
                """,
                (agent_id, org_id),
            )
            row = cur.fetchone()
            cur.close()

        if row:
            return AgentPerformanceThresholds(
                threshold_id=row[0],
                org_id=row[1],
                agent_id=row[2],
                success_rate_warning=row[3],
                success_rate_critical=row[4],
                token_savings_warning=row[5],
                token_savings_critical=row[6],
                behavior_reuse_warning=row[7],
                behavior_reuse_critical=row[8],
                compliance_coverage_warning=row[9],
                compliance_coverage_critical=row[10],
                avg_duration_warning_ms=row[11],
                avg_duration_critical_ms=row[12],
                utilization_low_warning=row[13],
                utilization_high_warning=row[14],
                evaluation_window_hours=row[15],
                min_sample_size=row[16],
            )

        # Return PRD defaults
        return AgentPerformanceThresholds(
            threshold_id="default",
            success_rate_warning=PerformanceThresholds.SUCCESS_RATE_WARNING,
            success_rate_critical=PerformanceThresholds.SUCCESS_RATE_CRITICAL,
            token_savings_warning=PerformanceThresholds.TOKEN_SAVINGS_WARNING,
            token_savings_critical=PerformanceThresholds.TOKEN_SAVINGS_CRITICAL,
            behavior_reuse_warning=PerformanceThresholds.BEHAVIOR_REUSE_WARNING,
            behavior_reuse_critical=PerformanceThresholds.BEHAVIOR_REUSE_CRITICAL,
            compliance_coverage_warning=PerformanceThresholds.COMPLIANCE_COVERAGE_WARNING,
            compliance_coverage_critical=PerformanceThresholds.COMPLIANCE_COVERAGE_CRITICAL,
            avg_duration_warning_ms=PerformanceThresholds.AVG_DURATION_WARNING_MS,
            avg_duration_critical_ms=PerformanceThresholds.AVG_DURATION_CRITICAL_MS,
            utilization_low_warning=PerformanceThresholds.UTILIZATION_LOW_WARNING,
            utilization_high_warning=PerformanceThresholds.UTILIZATION_HIGH_WARNING,
            evaluation_window_hours=PerformanceThresholds.DEFAULT_EVALUATION_WINDOW_HOURS,
            min_sample_size=PerformanceThresholds.DEFAULT_MIN_SAMPLE_SIZE,
        )

    def update_thresholds(
        self,
        thresholds: Dict[str, Any],
        org_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> AgentPerformanceThresholds:
        """Update or create thresholds for a scope."""
        threshold_id = _uuid_str()
        now = _utc_now_iso()

        # Get defaults for unspecified values
        defaults = self.get_thresholds(agent_id=None, org_id=None)

        with self._pool.connection() as conn:
            cur = conn.cursor()

            # First check if threshold record exists for this scope
            # Handle NULL comparison explicitly
            if org_id is None and agent_id is None:
                cur.execute(
                    "SELECT threshold_id FROM agent_performance_thresholds WHERE org_id IS NULL AND agent_id IS NULL LIMIT 1"
                )
            elif org_id is None:
                cur.execute(
                    "SELECT threshold_id FROM agent_performance_thresholds WHERE org_id IS NULL AND agent_id = %s LIMIT 1",
                    (agent_id,)
                )
            elif agent_id is None:
                cur.execute(
                    "SELECT threshold_id FROM agent_performance_thresholds WHERE org_id = %s AND agent_id IS NULL LIMIT 1",
                    (org_id,)
                )
            else:
                cur.execute(
                    "SELECT threshold_id FROM agent_performance_thresholds WHERE org_id = %s AND agent_id = %s LIMIT 1",
                    (org_id, agent_id)
                )

            existing = cur.fetchone()

            if existing:
                # Update existing record
                existing_id = existing[0]
                cur.execute(
                    """
                    UPDATE agent_performance_thresholds SET
                        success_rate_warning = %s,
                        success_rate_critical = %s,
                        token_savings_warning = %s,
                        token_savings_critical = %s,
                        behavior_reuse_warning = %s,
                        behavior_reuse_critical = %s,
                        compliance_coverage_warning = %s,
                        compliance_coverage_critical = %s,
                        avg_duration_warning_ms = %s,
                        avg_duration_critical_ms = %s,
                        utilization_low_warning = %s,
                        utilization_high_warning = %s,
                        evaluation_window_hours = %s,
                        min_sample_size = %s,
                        updated_at = %s
                    WHERE threshold_id = %s
                    """,
                    (
                        thresholds.get("success_rate_warning", defaults.success_rate_warning),
                        thresholds.get("success_rate_critical", defaults.success_rate_critical),
                        thresholds.get("token_savings_warning", defaults.token_savings_warning),
                        thresholds.get("token_savings_critical", defaults.token_savings_critical),
                        thresholds.get("behavior_reuse_warning", defaults.behavior_reuse_warning),
                        thresholds.get("behavior_reuse_critical", defaults.behavior_reuse_critical),
                        thresholds.get("compliance_coverage_warning", defaults.compliance_coverage_warning),
                        thresholds.get("compliance_coverage_critical", defaults.compliance_coverage_critical),
                        thresholds.get("avg_duration_warning_ms", defaults.avg_duration_warning_ms),
                        thresholds.get("avg_duration_critical_ms", defaults.avg_duration_critical_ms),
                        thresholds.get("utilization_low_warning", defaults.utilization_low_warning),
                        thresholds.get("utilization_high_warning", defaults.utilization_high_warning),
                        thresholds.get("evaluation_window_hours", defaults.evaluation_window_hours),
                        thresholds.get("min_sample_size", defaults.min_sample_size),
                        now,
                        existing_id,
                    ),
                )
            else:
                # Insert new record
                cur.execute(
                    """
                    INSERT INTO agent_performance_thresholds (
                        threshold_id, org_id, agent_id,
                        success_rate_warning, success_rate_critical,
                        token_savings_warning, token_savings_critical,
                        behavior_reuse_warning, behavior_reuse_critical,
                        compliance_coverage_warning, compliance_coverage_critical,
                        avg_duration_warning_ms, avg_duration_critical_ms,
                        utilization_low_warning, utilization_high_warning,
                        evaluation_window_hours, min_sample_size,
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        threshold_id, org_id, agent_id,
                        thresholds.get("success_rate_warning", defaults.success_rate_warning),
                        thresholds.get("success_rate_critical", defaults.success_rate_critical),
                        thresholds.get("token_savings_warning", defaults.token_savings_warning),
                        thresholds.get("token_savings_critical", defaults.token_savings_critical),
                        thresholds.get("behavior_reuse_warning", defaults.behavior_reuse_warning),
                        thresholds.get("behavior_reuse_critical", defaults.behavior_reuse_critical),
                        thresholds.get("compliance_coverage_warning", defaults.compliance_coverage_warning),
                        thresholds.get("compliance_coverage_critical", defaults.compliance_coverage_critical),
                        thresholds.get("avg_duration_warning_ms", defaults.avg_duration_warning_ms),
                        thresholds.get("avg_duration_critical_ms", defaults.avg_duration_critical_ms),
                        thresholds.get("utilization_low_warning", defaults.utilization_low_warning),
                        thresholds.get("utilization_high_warning", defaults.utilization_high_warning),
                        thresholds.get("evaluation_window_hours", defaults.evaluation_window_hours),
                        thresholds.get("min_sample_size", defaults.min_sample_size),
                        now, now,
                    ),
                )
            conn.commit()
            cur.close()

        return self.get_thresholds(agent_id=agent_id, org_id=org_id)

    # ------------------------------------------------------------------
    # Daily Rollup Methods
    # ------------------------------------------------------------------

    def compute_daily_rollup(self, date: str, agent_id: str) -> AgentPerformanceDaily:
        """Compute and store daily rollup for an agent."""
        rollup_id = _uuid_str()

        with self._pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE task_completed) as tasks_completed,
                    COUNT(*) FILTER (WHERE task_completed AND NOT task_success) as tasks_failed,
                    ROUND(AVG(task_duration_ms)::numeric, 2) as avg_duration,
                    SUM(task_duration_ms) as total_duration,
                    SUM(tokens_used) as total_tokens,
                    SUM(baseline_tokens) as total_baseline,
                    ROUND(AVG(token_savings_pct)::numeric, 2) as avg_token_savings,
                    SUM(behaviors_cited) as total_behaviors,
                    SUM(compliance_checks_passed) as compliance_passed,
                    SUM(compliance_checks_total) as compliance_total,
                    MAX(org_id) as org_id,
                    MAX(project_id) as project_id
                FROM agent_performance_snapshots
                WHERE agent_id = %s
                  AND DATE(snapshot_time) = %s
                """,
                (agent_id, date),
            )
            row = cur.fetchone()
            cur.close()

        if row is None:
            raise AgentNotFoundError(f"No snapshots for agent {agent_id} on {date}")

        tasks_completed = row[0] or 0
        tasks_failed = row[1] or 0
        compliance_passed = row[8] or 0
        compliance_total = row[9] or 0
        total_tokens = row[4] or 0
        total_baseline = row[5] or 0

        success_rate = round(((tasks_completed - tasks_failed) / tasks_completed * 100), 2) if tasks_completed > 0 else 0.0
        compliance_rate = round((compliance_passed / compliance_total * 100), 2) if compliance_total > 0 else 100.0
        token_savings = round(((total_baseline - total_tokens) / total_baseline * 100), 2) if total_baseline > 0 else 0.0

        rollup = AgentPerformanceDaily(
            rollup_id=rollup_id,
            rollup_date=date,
            agent_id=agent_id,
            org_id=row[10],
            project_id=row[11],
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            success_rate_pct=success_rate,
            avg_task_duration_ms=int(row[2]) if row[2] else None,
            total_execution_time_ms=row[3] or 0,
            total_tokens_used=total_tokens,
            total_baseline_tokens=total_baseline,
            avg_token_savings_pct=float(row[6]) if row[6] else token_savings,
            total_behaviors_cited=row[7] or 0,
            compliance_checks_passed=compliance_passed,
            compliance_checks_total=compliance_total,
        )

        # Store the rollup
        with self._pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO agent_performance_daily (
                    rollup_id, rollup_date, agent_id, org_id, project_id,
                    tasks_completed, tasks_failed, success_rate_pct,
                    avg_task_duration_ms, total_execution_time_ms,
                    total_tokens_used, total_baseline_tokens, avg_token_savings_pct,
                    total_behaviors_cited, compliance_checks_passed, compliance_checks_total
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (agent_id, rollup_date) DO UPDATE SET
                    tasks_completed = EXCLUDED.tasks_completed,
                    tasks_failed = EXCLUDED.tasks_failed,
                    success_rate_pct = EXCLUDED.success_rate_pct,
                    avg_task_duration_ms = EXCLUDED.avg_task_duration_ms,
                    total_execution_time_ms = EXCLUDED.total_execution_time_ms,
                    total_tokens_used = EXCLUDED.total_tokens_used,
                    total_baseline_tokens = EXCLUDED.total_baseline_tokens,
                    avg_token_savings_pct = EXCLUDED.avg_token_savings_pct,
                    total_behaviors_cited = EXCLUDED.total_behaviors_cited,
                    compliance_checks_passed = EXCLUDED.compliance_checks_passed,
                    compliance_checks_total = EXCLUDED.compliance_checks_total
                """,
                (
                    rollup.rollup_id, rollup.rollup_date, rollup.agent_id,
                    rollup.org_id, rollup.project_id,
                    rollup.tasks_completed, rollup.tasks_failed, rollup.success_rate_pct,
                    rollup.avg_task_duration_ms, rollup.total_execution_time_ms,
                    rollup.total_tokens_used, rollup.total_baseline_tokens, rollup.avg_token_savings_pct,
                    rollup.total_behaviors_cited, rollup.compliance_checks_passed, rollup.compliance_checks_total,
                ),
            )
            conn.commit()
            cur.close()

        return rollup

    def get_daily_trend(
        self,
        agent_id: str,
        days: int = 30,
        org_id: Optional[str] = None,
    ) -> List[AgentPerformanceDaily]:
        """Get daily performance trend for an agent."""
        end_date = _utc_now().date()
        start_date = end_date - timedelta(days=days)

        with self._pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    rollup_id, rollup_date, agent_id, org_id, project_id,
                    tasks_completed, tasks_failed, success_rate_pct,
                    avg_task_duration_ms, total_execution_time_ms,
                    total_tokens_used, total_baseline_tokens, avg_token_savings_pct,
                    total_behaviors_cited, compliance_checks_passed, compliance_checks_total
                FROM agent_performance_daily
                WHERE agent_id = %s
                  AND rollup_date >= %s
                  AND rollup_date <= %s
                  AND (%s IS NULL OR org_id = %s)
                ORDER BY rollup_date ASC
                """,
                (agent_id, start_date.isoformat(), end_date.isoformat(), org_id, org_id),
            )
            rows = cur.fetchall()
            cur.close()

        return [
            AgentPerformanceDaily(
                rollup_id=row[0],
                rollup_date=row[1].isoformat() if hasattr(row[1], 'isoformat') else row[1],
                agent_id=row[2],
                org_id=row[3],
                project_id=row[4],
                tasks_completed=row[5],
                tasks_failed=row[6],
                success_rate_pct=row[7],
                avg_task_duration_ms=row[8],
                total_execution_time_ms=row[9],
                total_tokens_used=row[10],
                total_baseline_tokens=row[11],
                avg_token_savings_pct=row[12],
                total_behaviors_cited=row[13],
                compliance_checks_passed=row[14],
                compliance_checks_total=row[15],
            )
            for row in rows
        ]
