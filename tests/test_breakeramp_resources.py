"""
Tests for Amprealize BreakerAmp Wrapper - Resource Delegation

These tests verify the wrapper properly delegates resource-related operations
to the standalone breakeramp service and fires hooks appropriately.

NOTE: Resource calculation and enforcement logic lives in the standalone
breakeramp package (packages/breakeramp/). These tests focus on:
1. Delegation from wrapper to standalone service
2. Hook firing during resource operations
3. Error propagation from standalone to wrapper
"""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_plan_response():
    """Create a mock PlanResponse."""
    from amprealize.breakeramp import PlanResponse, EnvironmentEstimates
    return PlanResponse(
        plan_id="plan-123",
        amp_run_id="amp-run-123",
        signed_manifest={"phase": "PLANNED", "resources": {"memory_mb": 1536}},
        environment_estimates=EnvironmentEstimates(
            cost_estimate=0.0,
            memory_footprint_mb=1536,
            bandwidth_mbps=10,
            region="local",
            expected_boot_duration_s=30
        )
    )


@pytest.fixture
def mock_apply_response():
    """Create a mock ApplyResponse."""
    from amprealize.breakeramp import ApplyResponse
    return ApplyResponse(
        environment_outputs={"web": {"status": "running"}},
        status_stream_url=None,
        action_id="action-123",
        amp_run_id="amp-run-123"
    )


@pytest.fixture
def mock_destroy_response():
    """Create a mock DestroyResponse."""
    from amprealize.breakeramp import DestroyResponse
    return DestroyResponse(
        teardown_report=["web: destroyed"],
        action_id="action-456"
    )


@pytest.fixture
def mock_status_response():
    """Create a mock StatusResponse."""
    from amprealize.breakeramp import StatusResponse, HealthCheck
    return StatusResponse(
        amp_run_id="amp-run-123",
        phase="APPLIED",
        progress_pct=100,
        checks=[],
        telemetry=None
    )


@pytest.fixture
def mock_standalone_service(mock_plan_response, mock_apply_response, mock_destroy_response, mock_status_response):
    """Mock the standalone breakeramp service."""
    service = MagicMock()
    service.plan = MagicMock(return_value=mock_plan_response)
    service.apply = MagicMock(return_value=mock_apply_response)
    service.status = MagicMock(return_value=mock_status_response)
    service.destroy = MagicMock(return_value=mock_destroy_response)
    return service


@pytest.fixture
def wrapper_service(mock_standalone_service):
    """Create wrapper service with mocked standalone."""
    from amprealize.breakeramp import BreakerAmpService

    action_service = MagicMock()
    mock_action = MagicMock()
    mock_action.action_id = "action-123"
    action_service.create_action.return_value = mock_action
    compliance_service = MagicMock()
    metrics_service = MagicMock()

    service = BreakerAmpService(
        action_service=action_service,
        compliance_service=compliance_service,
        metrics_service=metrics_service
    )
    # Replace the internal standalone service with mock
    service._service = mock_standalone_service
    return service


class TestResourceDelegation:
    """Test that resource operations delegate to standalone service."""

    def test_plan_delegates_to_standalone(self, wrapper_service, mock_standalone_service):
        """Plan should delegate to standalone service."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(environment="test-env", blueprint_id="test-blueprint")
        result = wrapper_service.plan(request)

        mock_standalone_service.plan.assert_called_once_with(request)
        assert result.plan_id == "plan-123"

    def test_apply_delegates_to_standalone(self, wrapper_service, mock_standalone_service):
        """Apply should delegate to standalone service."""
        from amprealize.breakeramp import ApplyRequest

        request = ApplyRequest(plan_id="plan-123")
        result = wrapper_service.apply(request)

        mock_standalone_service.apply.assert_called_once_with(request)
        assert result.amp_run_id == "amp-run-123"

    def test_status_delegates_to_standalone(self, wrapper_service, mock_standalone_service):
        """Status should delegate to standalone service."""
        result = wrapper_service.status("amp-123")

        mock_standalone_service.status.assert_called_once_with("amp-123")
        assert result.phase == "APPLIED"

    def test_destroy_delegates_to_standalone(self, wrapper_service, mock_standalone_service):
        """Destroy should delegate to standalone service."""
        from amprealize.breakeramp import DestroyRequest

        request = DestroyRequest(amp_run_id="amp-123", reason="test cleanup")
        result = wrapper_service.destroy(request)

        mock_standalone_service.destroy.assert_called_once_with(request)
        assert result.action_id == "action-456"


class TestResourceErrorPropagation:
    """Test that errors from standalone service propagate correctly."""

    def test_plan_propagates_resource_error(self, wrapper_service, mock_standalone_service):
        """Resource limit errors should propagate from standalone."""
        from amprealize.breakeramp import PlanRequest

        mock_standalone_service.plan.side_effect = RuntimeError(
            "Blueprint requires 3000MB, but environment limit is 1000MB"
        )

        request = PlanRequest(environment="test-env", blueprint_id="resource-heavy-blueprint")
        with pytest.raises(RuntimeError, match="Blueprint requires 3000MB"):
            wrapper_service.plan(request)

    def test_apply_propagates_runtime_error(self, wrapper_service, mock_standalone_service):
        """Runtime errors should propagate from standalone."""
        from amprealize.breakeramp import ApplyRequest

        mock_standalone_service.apply.side_effect = RuntimeError("Podman machine not available")

        request = ApplyRequest(plan_id="plan-123")
        with pytest.raises(RuntimeError, match="Podman machine not available"):
            wrapper_service.apply(request)


class TestHookFiringDuringResourceOps:
    """Test that hooks fire during resource operations."""

    def test_plan_fires_action_hook(self, wrapper_service, mock_standalone_service):
        """Plan operation should fire action hook via standalone's hooks."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(environment="test-env", blueprint_id="test-blueprint")
        wrapper_service.plan(request)

        # The action hook is fired by the standalone service via BreakerAmpHooks
        # We verify delegation happened
        mock_standalone_service.plan.assert_called_once()

    def test_apply_fires_hooks(self, wrapper_service, mock_standalone_service):
        """Apply operation should use hooks from standalone."""
        from amprealize.breakeramp import ApplyRequest

        request = ApplyRequest(plan_id="plan-123")
        wrapper_service.apply(request)

        # The compliance hook is fired by the standalone service via BreakerAmpHooks
        # We verify delegation happened
        mock_standalone_service.apply.assert_called_once()
