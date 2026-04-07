"""Tests for Amprealize BreakerAmp wrapper's telemetry and compliance hooks.

These tests verify that the wrapper correctly wires hooks to amprealize services
(ActionService, ComplianceService, MetricsService). The actual telemetry
emission is triggered by the standalone breakeramp package via hooks.
"""

import pytest
from unittest.mock import MagicMock, ANY
from amprealize.breakeramp import (
    BreakerAmpService,
    PlanRequest,
    ApplyRequest,
    DestroyRequest,
)
from amprealize.action_contracts import Actor


@pytest.mark.unit
class TestBreakerAmpServiceTelemetry:
    """Tests for telemetry hook integration."""

    @pytest.fixture
    def mock_action_service(self):
        mock = MagicMock()
        mock.create_action.return_value = MagicMock(action_id="act-123")
        return mock

    @pytest.fixture
    def mock_compliance_service(self):
        return MagicMock()

    @pytest.fixture
    def mock_metrics_service(self):
        return MagicMock()

    @pytest.fixture
    def mock_executor(self):
        """Mock executor to avoid real container operations."""
        executor = MagicMock()
        executor.run_container.return_value = "container-123"
        executor.list_containers.return_value = []
        return executor

    @pytest.fixture
    def service(self, mock_action_service, mock_compliance_service, mock_metrics_service, mock_executor):
        return BreakerAmpService(
            action_service=mock_action_service,
            compliance_service=mock_compliance_service,
            metrics_service=mock_metrics_service,
            executor=mock_executor,
        )

    @pytest.fixture
    def actor(self):
        return Actor(id="test-user", role="engineer", surface="cli")

    def test_hooks_are_wired_to_services(self, service, mock_action_service, mock_compliance_service, mock_metrics_service):
        """Verify hooks are properly wired to amprealize services."""
        # The service should have hooks that call amprealize services
        assert service._service.hooks is not None
        assert service._service.hooks.on_action is not None
        assert service._service.hooks.on_compliance_step is not None
        assert service._service.hooks.on_metric is not None

    def test_on_action_hook_calls_action_service(self, service, mock_action_service, actor):
        """The on_action hook should call ActionService.create_action."""
        # Set actor context
        service._current_actor = actor

        # Trigger the hook directly (simulating what standalone service does)
        # Signature: _on_action(action_type, payload, run_id=None, behaviors=None)
        action_id = service._on_action(
            action_type="breakeramp.plan",
            payload={"description": "test plan", "blueprint_id": "test-bp"},
            run_id="run-123",
            behaviors=["behavior_use_breakeramp_for_environments"],
        )

        # Should have called ActionService
        mock_action_service.create_action.assert_called_once()
        call_args = mock_action_service.create_action.call_args
        # The wrapper creates ActionCreateRequest with artifact_path = f"breakeramp/{action_type}"
        request = call_args[0][0]
        assert request.artifact_path == "breakeramp/breakeramp.plan"
        assert "breakeramp.plan" in request.summary
        assert action_id == "act-123"

    def test_on_compliance_hook_calls_compliance_service(self, service, mock_compliance_service, actor):
        """The on_compliance_step hook should call ComplianceService.record_step."""
        service._current_actor = actor

        # Trigger the hook directly
        # Actual signature: _on_compliance_step(checklist_id, step_id, status, evidence=None)
        service._on_compliance_step(
            checklist_id="checklist-123",
            step_id="plan_created",
            status="passed",
            evidence={"plan_id": "plan-123"},
        )

        # Should have called ComplianceService
        mock_compliance_service.record_step.assert_called_once()

    def test_on_metric_hook_calls_metrics_service(self, service, mock_metrics_service, actor):
        """The on_metric hook should call MetricsService.emit_event."""
        service._current_actor = actor

        # Trigger the hook directly
        # Actual signature: _on_metric(event_name, payload, actor=None)
        # Note: The hook uses the actor parameter directly, not _current_actor
        service._on_metric(
            event_name="breakeramp.plan.created",
            payload={"plan_id": "plan-123"},
            actor={"id": "test-user", "role": "engineer"},  # Dict form, not Actor
        )

        # Should have called MetricsService with the actor dict
        mock_metrics_service.emit_event.assert_called_once_with(
            "breakeramp.plan.created",
            {"plan_id": "plan-123"},
            actor={"id": "test-user", "role": "engineer"},
        )

    def test_plan_sets_actor_for_hooks(self, service, actor):
        """Plan operation should set actor context for hook calls."""
        # Mock standalone service to avoid real operations
        mock_response = MagicMock(plan_id="plan-123")
        service._service.plan = MagicMock(return_value=mock_response)
        service._service._resolve_blueprint = MagicMock(return_value=MagicMock(services={}))
        service._service.environments = {"dev": MagicMock(default_blueprint=None)}

        request = PlanRequest(blueprint_id="test", environment="dev")
        service.plan(request, actor)

        # Actor should be set for subsequent hook calls
        assert service._current_actor == actor

    def test_apply_sets_actor_for_hooks(self, service, actor):
        """Apply operation should set actor context for hook calls."""
        mock_response = MagicMock(amp_run_id="amp-123")
        service._service.apply = MagicMock(return_value=mock_response)

        request = ApplyRequest(plan_id="plan-123")
        service.apply(request, actor)

        assert service._current_actor == actor

    def test_metrics_service_optional(self, mock_action_service, mock_compliance_service, mock_executor):
        """Service works without MetricsService (optional)."""
        service = BreakerAmpService(
            action_service=mock_action_service,
            compliance_service=mock_compliance_service,
            metrics_service=None,
            executor=mock_executor,
        )

        # Should not raise when metric hook is triggered
        service._on_metric("test.event", {"key": "value"})
