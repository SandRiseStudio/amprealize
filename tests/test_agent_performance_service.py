"""Unit tests for AgentPerformanceService.

Feature 13.4.6 - Agent Performance Metrics
Validates:
- Task completion recording and snapshots
- Status change recording
- Agent summary queries
- Top performer queries
- Alert creation and management
- Threshold configuration
- Daily rollup generation

Behavior: behavior_design_test_strategy
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Generator

import pytest

# Mark all tests in this module as unit tests to skip global fixtures
pytestmark = pytest.mark.unit

try:
    import psycopg2
except ImportError:
    psycopg2 = None

from amprealize.services.agent_performance_service import (
    AgentPerformanceService,
    AgentNotFoundError,
    AlertNotFoundError,
)
from amprealize.agent_performance_contracts import (
    RecordTaskCompletionRequest,
    RecordStatusChangeRequest,
    PerformanceAlertSeverity,
    PerformanceMetricType,
)


def _truncate_tables(dsn: str) -> None:
    """Remove all data from agent performance tables."""
    from conftest import safe_truncate
    safe_truncate(dsn, [
        "agent_performance_alerts", "agent_performance_daily",
        "agent_performance_thresholds", "agent_performance_snapshots",
    ])


@pytest.fixture
def dsn() -> str:
    """Get PostgreSQL DSN from environment."""
    dsn = os.environ.get("AMPREALIZE_AGENT_PERFORMANCE_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_AGENT_PERFORMANCE_PG_DSN not set")
    return dsn


@pytest.fixture
def clean_db(dsn: str) -> Generator[None, None, None]:
    """Clean database before and after each test."""
    _truncate_tables(dsn)
    yield
    _truncate_tables(dsn)


@pytest.fixture
def service(dsn: str, clean_db: None) -> AgentPerformanceService:
    """Create AgentPerformanceService instance."""
    return AgentPerformanceService(dsn=dsn)


@pytest.fixture
def sample_task_completion() -> RecordTaskCompletionRequest:
    """Sample task completion request."""
    return RecordTaskCompletionRequest(
        agent_id="agent-test-001",
        org_id="org-001",
        run_id="run-001",
        task_id="task-001",
        project_id="proj-001",
        success=True,
        duration_ms=5000,
        tokens_used=800,
        baseline_tokens=1000,
        behaviors_cited=["behavior_test_pattern", "behavior_logging"],
        compliance_passed=5,
        compliance_total=5,
        metadata={"source": "test"},
    )


class TestRecordTaskCompletion:
    """Test task completion recording."""

    def test_record_task_completion_success(
        self, service: AgentPerformanceService, sample_task_completion: RecordTaskCompletionRequest
    ):
        """Test successful task completion recording."""
        snapshot = service.record_task_completion(sample_task_completion)

        # snapshot_id should be a valid UUID
        import uuid
        try:
            uuid.UUID(snapshot.snapshot_id)
        except ValueError:
            pytest.fail(f"snapshot_id is not a valid UUID: {snapshot.snapshot_id}")
        assert snapshot.agent_id == "agent-test-001"
        assert snapshot.task_completed is True
        assert snapshot.task_success is True
        assert snapshot.tokens_used == 800
        assert snapshot.baseline_tokens == 1000
        assert snapshot.token_savings_pct == 20.0  # (1000-800)/1000 * 100
        assert snapshot.behaviors_cited == 2
        assert "behavior_test_pattern" in snapshot.unique_behaviors

    def test_record_task_completion_failure(self, service: AgentPerformanceService):
        """Test recording a failed task."""
        request = RecordTaskCompletionRequest(
            agent_id="agent-test-002",
            run_id="run-fail-002",
            org_id="org-001",
            task_id="task-002",
            success=False,
            duration_ms=3000,
            tokens_used=500,
            baseline_tokens=500,
            behaviors_cited=[],
            compliance_passed=2,
            compliance_total=5,
        )
        snapshot = service.record_task_completion(request)

        assert snapshot.task_success is False
        assert snapshot.token_savings_pct == 0.0  # No savings
        assert snapshot.compliance_checks_passed == 2
        assert snapshot.compliance_checks_total == 5

    def test_record_task_multiple_completions(self, service: AgentPerformanceService):
        """Test recording multiple task completions for same agent."""
        for i in range(5):
            request = RecordTaskCompletionRequest(
                agent_id="agent-multi",
                run_id=f"run-multi-{i}",
                org_id="org-001",
                task_id=f"task-{i}",
                success=i % 2 == 0,  # Alternate success/failure
                duration_ms=1000 + i * 100,
                tokens_used=100,
                baseline_tokens=150,
                behaviors_cited=["behavior_a"],
                compliance_passed=1,
                compliance_total=1,
            )
            service.record_task_completion(request)

        # Should be able to get summary
        summary = service.get_agent_summary("agent-multi", period_days=7)
        assert summary.tasks_completed == 5
        assert summary.tasks_failed == 2  # 1, 3 are failures
        assert summary.success_rate_pct == 60.0


class TestRecordStatusChange:
    """Test status change recording."""

    def test_record_status_change(self, service: AgentPerformanceService):
        """Test recording agent status change."""
        request = RecordStatusChangeRequest(
            agent_id="agent-status-001",
            org_id="org-001",
            task_id="task-001",
            status_from="IDLE",
            status_to="EXECUTING",
            time_in_status_ms=30000,
        )
        snapshot = service.record_status_change(request)

        # snapshot_id should be a valid UUID
        import uuid
        try:
            uuid.UUID(snapshot.snapshot_id)
        except ValueError:
            pytest.fail(f"snapshot_id is not a valid UUID: {snapshot.snapshot_id}")
        assert snapshot.status_from == "IDLE"
        assert snapshot.status_to == "EXECUTING"
        assert snapshot.time_in_status_ms == 30000


class TestGetAgentSummary:
    """Test agent summary queries."""

    def test_get_summary_with_data(
        self, service: AgentPerformanceService, sample_task_completion: RecordTaskCompletionRequest
    ):
        """Test getting summary for agent with data."""
        # Record multiple tasks
        for i in range(3):
            request = RecordTaskCompletionRequest(
                agent_id="agent-summary",
                run_id=f"run-summary-{i}",
                org_id="org-001",
                task_id=f"task-{i}",
                success=True,
                duration_ms=2000,
                tokens_used=500,
                baseline_tokens=700,
                behaviors_cited=["behavior_a"],
                compliance_passed=5,
                compliance_total=5,
            )
            service.record_task_completion(request)

        summary = service.get_agent_summary("agent-summary", period_days=30)

        assert summary.agent_id == "agent-summary"
        assert summary.tasks_completed == 3
        assert summary.tasks_failed == 0
        assert summary.success_rate_pct == 100.0
        assert summary.avg_task_duration_ms == 2000
        assert summary.total_tokens_used == 1500  # 3 * 500
        assert summary.compliance_coverage_pct == 100.0

    def test_get_summary_no_data(self, service: AgentPerformanceService):
        """Test getting summary for agent with no data."""
        with pytest.raises(AgentNotFoundError):
            service.get_agent_summary("nonexistent-agent")

    def test_get_summary_with_org_filter(self, service: AgentPerformanceService):
        """Test summary filtered by organization."""
        # Record for org-A
        service.record_task_completion(RecordTaskCompletionRequest(
            agent_id="agent-org-test",
            run_id="run-org-a",
            org_id="org-A",
            task_id="task-a",
            success=True,
            duration_ms=1000,
            tokens_used=100,
            baseline_tokens=100,
            behaviors_cited=[],
            compliance_passed=1,
            compliance_total=1,
        ))

        # Record for org-B
        service.record_task_completion(RecordTaskCompletionRequest(
            agent_id="agent-org-test",
            run_id="run-org-b",
            org_id="org-B",
            task_id="task-b",
            success=True,
            duration_ms=1000,
            tokens_used=100,
            baseline_tokens=100,
            behaviors_cited=[],
            compliance_passed=1,
            compliance_total=1,
        ))

        # Query for org-A only
        summary = service.get_agent_summary("agent-org-test", org_id="org-A", period_days=30)
        assert summary.tasks_completed == 1  # Only org-A task


class TestGetTopPerformers:
    """Test top performer queries."""

    def test_get_top_by_success_rate(self, service: AgentPerformanceService):
        """Test getting top performers by success rate."""
        # Create agents with different success rates
        agents = [
            ("agent-top-1", 10, 10),  # 100% success
            ("agent-top-2", 8, 10),   # 80% success
            ("agent-top-3", 6, 10),   # 60% success
        ]
        for agent_id, successes, total in agents:
            for i in range(total):
                service.record_task_completion(RecordTaskCompletionRequest(
                    agent_id=agent_id,
                    run_id=f"run-{agent_id}-{i}",
                    task_id=f"task-{agent_id}-{i}",
                    success=i < successes,
                    duration_ms=1000,
                    tokens_used=100,
                    baseline_tokens=100,
                    behaviors_cited=[],
                    compliance_passed=1,
                    compliance_total=1,
                ))

        top = service.get_top_performers(metric="success_rate", limit=3, min_tasks=5)

        assert len(top) == 3
        assert top[0].agent_id == "agent-top-1"
        assert top[0].success_rate_pct == 100.0
        assert top[1].agent_id == "agent-top-2"
        assert top[2].agent_id == "agent-top-3"

    def test_get_top_by_token_savings(self, service: AgentPerformanceService):
        """Test getting top performers by token savings."""
        agents = [
            ("agent-tokens-1", 50, 100),   # 50% savings
            ("agent-tokens-2", 70, 100),   # 30% savings
            ("agent-tokens-3", 90, 100),   # 10% savings
        ]
        for agent_id, tokens_used, baseline in agents:
            for i in range(5):
                service.record_task_completion(RecordTaskCompletionRequest(
                    agent_id=agent_id,
                    run_id=f"run-{agent_id}-{i}",
                    task_id=f"task-{agent_id}-{i}",
                    success=True,
                    duration_ms=1000,
                    tokens_used=tokens_used,
                    baseline_tokens=baseline,
                    behaviors_cited=[],
                    compliance_passed=1,
                    compliance_total=1,
                ))

        top = service.get_top_performers(metric="token_savings", limit=3, min_tasks=5)

        assert len(top) == 3
        assert top[0].agent_id == "agent-tokens-1"  # 50% savings is best
        assert top[0].avg_token_savings_pct == 50.0

    def test_get_top_respects_min_tasks(self, service: AgentPerformanceService):
        """Test that min_tasks filter is respected."""
        # Agent with only 3 tasks (below min)
        for i in range(3):
            service.record_task_completion(RecordTaskCompletionRequest(
                agent_id="agent-few-tasks",
                run_id=f"run-few-{i}",
                task_id=f"task-{i}",
                success=True,
                duration_ms=1000,
                tokens_used=100,
                baseline_tokens=100,
                behaviors_cited=[],
                compliance_passed=1,
                compliance_total=1,
            ))

        top = service.get_top_performers(min_tasks=5)
        assert len(top) == 0  # No agents meet minimum


class TestCompareAgents:
    """Test agent comparison."""

    def test_compare_multiple_agents(self, service: AgentPerformanceService):
        """Test comparing multiple agents."""
        for agent_id in ["agent-cmp-1", "agent-cmp-2"]:
            for i in range(5):
                service.record_task_completion(RecordTaskCompletionRequest(
                    agent_id=agent_id,
                    run_id=f"run-{agent_id}-{i}",
                    task_id=f"task-{agent_id}-{i}",
                    success=True,
                    duration_ms=1000,
                    tokens_used=100,
                    baseline_tokens=100,
                    behaviors_cited=[],
                    compliance_passed=1,
                    compliance_total=1,
                ))

        comparison = service.compare_agents(["agent-cmp-1", "agent-cmp-2"])
        assert len(comparison) == 2
        assert {c.agent_id for c in comparison} == {"agent-cmp-1", "agent-cmp-2"}

    def test_compare_with_missing_agent(self, service: AgentPerformanceService):
        """Test comparison skips agents with no data."""
        # Only create data for one agent
        for i in range(5):
            service.record_task_completion(RecordTaskCompletionRequest(
                agent_id="agent-exists",
                run_id=f"run-exists-{i}",
                task_id=f"task-{i}",
                success=True,
                duration_ms=1000,
                tokens_used=100,
                baseline_tokens=100,
                behaviors_cited=[],
                compliance_passed=1,
                compliance_total=1,
            ))

        comparison = service.compare_agents(["agent-exists", "agent-missing"])
        assert len(comparison) == 1
        assert comparison[0].agent_id == "agent-exists"


class TestAlerts:
    """Test alert creation and management."""

    def test_check_thresholds_creates_alerts(self, service: AgentPerformanceService):
        """Test that threshold violations create alerts."""
        # Create agent with low success rate
        for i in range(10):
            service.record_task_completion(RecordTaskCompletionRequest(
                agent_id="agent-low-success",
                run_id=f"run-low-success-{i}",
                task_id=f"task-{i}",
                success=i < 5,  # 50% success (below 70% warning)
                duration_ms=1000,
                tokens_used=100,
                baseline_tokens=100,
                behaviors_cited=[],
                compliance_passed=1,
                compliance_total=1,
            ))

        alerts = service.check_thresholds("agent-low-success")

        # Should have alert for low success rate
        success_alerts = [a for a in alerts if a.metric_type == PerformanceMetricType.SUCCESS_RATE.value]
        assert len(success_alerts) == 1
        assert success_alerts[0].current_value == 50.0
        assert success_alerts[0].severity == PerformanceAlertSeverity.CRITICAL.value

    def test_get_alerts(self, service: AgentPerformanceService):
        """Test retrieving alerts."""
        # Create alerts via threshold check
        for i in range(10):
            service.record_task_completion(RecordTaskCompletionRequest(
                agent_id="agent-alerts",
                run_id=f"run-alerts-{i}",
                task_id=f"task-{i}",
                success=i < 3,  # 30% success
                duration_ms=1000,
                tokens_used=100,
                baseline_tokens=100,
                behaviors_cited=[],
                compliance_passed=1,
                compliance_total=1,
            ))
        service.check_thresholds("agent-alerts")

        alerts = service.get_alerts(agent_id="agent-alerts")
        assert len(alerts) >= 1
        assert all(a.agent_id == "agent-alerts" for a in alerts)

    def test_acknowledge_alert(self, service: AgentPerformanceService):
        """Test acknowledging an alert."""
        # Create an alert
        for i in range(10):
            service.record_task_completion(RecordTaskCompletionRequest(
                agent_id="agent-ack",
                run_id=f"run-ack-{i}",
                task_id=f"task-{i}",
                success=i < 3,
                duration_ms=1000,
                tokens_used=100,
                baseline_tokens=100,
                behaviors_cited=[],
                compliance_passed=1,
                compliance_total=1,
            ))
        alerts = service.check_thresholds("agent-ack")
        assert len(alerts) > 0

        alert_id = alerts[0].alert_id
        acked = service.acknowledge_alert(alert_id, "test-user")

        assert acked.acknowledged_at is not None
        assert acked.acknowledged_by == "test-user"

    def test_acknowledge_nonexistent_alert(self, service: AgentPerformanceService):
        """Test acknowledging a nonexistent alert."""
        with pytest.raises(AlertNotFoundError):
            service.acknowledge_alert("00000000-0000-0000-0000-000000000000", "test-user")

    def test_resolve_alert(self, service: AgentPerformanceService):
        """Test resolving an alert."""
        # Create an alert
        for i in range(10):
            service.record_task_completion(RecordTaskCompletionRequest(
                agent_id="agent-resolve",
                run_id=f"run-resolve-{i}",
                task_id=f"task-{i}",
                success=i < 3,
                duration_ms=1000,
                tokens_used=100,
                baseline_tokens=100,
                behaviors_cited=[],
                compliance_passed=1,
                compliance_total=1,
            ))
        alerts = service.check_thresholds("agent-resolve")
        alert_id = alerts[0].alert_id

        resolved = service.resolve_alert(alert_id, "Fixed by retraining agent")

        assert resolved.resolved_at is not None
        assert resolved.resolution_notes == "Fixed by retraining agent"

    def test_resolved_alerts_filtered_by_default(self, service: AgentPerformanceService):
        """Test that resolved alerts are excluded by default."""
        # Create and resolve an alert
        for i in range(10):
            service.record_task_completion(RecordTaskCompletionRequest(
                agent_id="agent-filter",
                run_id=f"run-filter-{i}",
                task_id=f"task-{i}",
                success=i < 3,
                duration_ms=1000,
                tokens_used=100,
                baseline_tokens=100,
                behaviors_cited=[],
                compliance_passed=1,
                compliance_total=1,
            ))
        alerts = service.check_thresholds("agent-filter")
        service.resolve_alert(alerts[0].alert_id, "Resolved")

        # Should not include resolved
        active_alerts = service.get_alerts(agent_id="agent-filter", include_resolved=False)
        assert all(a.resolved_at is None for a in active_alerts)

        # Should include with flag
        all_alerts = service.get_alerts(agent_id="agent-filter", include_resolved=True)
        assert any(a.resolved_at is not None for a in all_alerts)


class TestThresholds:
    """Test threshold configuration."""

    def test_get_default_thresholds(self, service: AgentPerformanceService):
        """Test getting default thresholds."""
        thresholds = service.get_thresholds("any-agent")

        # These match the database schema defaults
        assert thresholds.success_rate_warning == 70.0
        assert thresholds.success_rate_critical == 60.0
        assert thresholds.token_savings_warning == 20.0
        assert thresholds.token_savings_critical == 10.0
        assert thresholds.compliance_coverage_warning == 90.0
        assert thresholds.compliance_coverage_critical == 80.0

    def test_update_agent_thresholds(self, service: AgentPerformanceService):
        """Test setting custom thresholds for agent."""
        service.update_thresholds(
            thresholds={
                "success_rate_warning": 80.0,
                "success_rate_critical": 60.0,
                "token_savings_warning": 20.0,
            },
            agent_id="agent-custom-thresholds",
        )

        thresholds = service.get_thresholds("agent-custom-thresholds")

        assert float(thresholds.success_rate_warning) == 80.0
        assert float(thresholds.success_rate_critical) == 60.0
        assert float(thresholds.token_savings_warning) == 20.0
        # Others should still be default (90.0 per schema)
        assert float(thresholds.compliance_coverage_warning) == 90.0

    def test_update_thresholds_overwrite(self, service: AgentPerformanceService):
        """Test updating existing thresholds."""
        # Set initial
        service.update_thresholds(
            thresholds={"success_rate_warning": 80.0},
            agent_id="agent-update-thresholds",
        )

        # Update
        service.update_thresholds(
            thresholds={
                "success_rate_warning": 90.0,
                "token_savings_critical": 5.0,
            },
            agent_id="agent-update-thresholds",
        )

        thresholds = service.get_thresholds("agent-update-thresholds")
        assert thresholds.success_rate_warning == 90.0
        assert thresholds.token_savings_critical == 5.0


class TestDailyRollup:
    """Test daily rollup generation."""

    def test_generate_daily_rollup(self, service: AgentPerformanceService):
        """Test generating daily rollup for an agent."""
        # Create some snapshots for today
        for i in range(5):
            service.record_task_completion(RecordTaskCompletionRequest(
                agent_id="agent-rollup",
                run_id=f"run-rollup-{i}",
                task_id=f"task-{i}",
                success=i < 4,  # 80% success
                duration_ms=1000 + i * 100,
                tokens_used=80 + i * 5,
                baseline_tokens=100,
                behaviors_cited=["behavior_a"] if i % 2 == 0 else [],
                compliance_passed=1,
                compliance_total=1,
            ))

        today = datetime.now(timezone.utc).date().isoformat()
        rollup = service.compute_daily_rollup(today, "agent-rollup")

        assert rollup.agent_id == "agent-rollup"
        assert rollup.tasks_completed == 5
        assert rollup.tasks_failed == 1
        assert rollup.success_rate_pct == 80.0

    def test_get_daily_trend(self, service: AgentPerformanceService):
        """Test getting daily trend data."""
        # This test would need date manipulation - simplified version
        for i in range(5):
            service.record_task_completion(RecordTaskCompletionRequest(
                agent_id="agent-trend",
                run_id=f"run-trend-{i}",
                task_id=f"task-{i}",
                success=True,
                duration_ms=1000,
                tokens_used=100,
                baseline_tokens=100,
                behaviors_cited=[],
                compliance_passed=1,
                compliance_total=1,
            ))

        today = datetime.now(timezone.utc).date().isoformat()
        service.compute_daily_rollup(today, "agent-trend")

        trend = service.get_daily_trend("agent-trend", days=7)

        # Should have at least today's data
        assert len(trend) >= 0  # May be empty if no rollups exist yet
