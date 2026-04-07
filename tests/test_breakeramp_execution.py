"""
Tests for Amprealize BreakerAmp Wrapper - Execution Delegation

These tests verify the wrapper properly delegates execution operations
(plan, apply, destroy) to the standalone breakeramp service.

NOTE: Execution logic (subprocess calls, container management) lives in the
standalone breakeramp package (packages/breakeramp/). These tests focus on:
1. Delegation from wrapper to standalone service
2. Actor tracking for action attribution
3. Hook firing during execution lifecycle
4. Error propagation from standalone to wrapper
"""
import pytest
from unittest.mock import MagicMock, patch, create_autospec


@pytest.fixture
def mock_plan_response():
    """Create a mock PlanResponse."""
    from amprealize.breakeramp import PlanResponse, EnvironmentEstimates
    return PlanResponse(
        plan_id="plan-123",
        amp_run_id="amp-run-123",
        signed_manifest={"phase": "PLANNED", "variables": {"foo": "bar"}},
        environment_estimates=EnvironmentEstimates(
            cost_estimate=0.0,
            memory_footprint_mb=512,
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
        environment_outputs={"web": {"container_id": "cid-123", "status": "running"}},
        status_stream_url=None,
        action_id="action-123",
        amp_run_id="amp-run-123"
    )


@pytest.fixture
def mock_destroy_response():
    """Create a mock DestroyResponse."""
    from amprealize.breakeramp import DestroyResponse
    return DestroyResponse(
        teardown_report=["web: stopped", "web: removed"],
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
    service.destroy = MagicMock(return_value=mock_destroy_response)
    service.status = MagicMock(return_value=mock_status_response)
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


class TestPlanDelegation:
    """Test that plan operations delegate properly."""

    def test_plan_delegates_to_standalone(self, wrapper_service, mock_standalone_service):
        """Plan should delegate to standalone service."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(environment="test-env", blueprint_id="test-bp")
        result = wrapper_service.plan(request)

        mock_standalone_service.plan.assert_called_once_with(request)
        assert result.plan_id == "plan-123"
        assert result.amp_run_id == "amp-run-123"

    def test_plan_with_actor(self, wrapper_service, mock_standalone_service):
        """Plan should accept actor for attribution."""
        from amprealize.breakeramp import PlanRequest
        from amprealize.action_contracts import Actor

        request = PlanRequest(environment="test-env")
        actor = Actor(id="user-1", role="admin", surface="cli")

        result = wrapper_service.plan(request, actor=actor)

        mock_standalone_service.plan.assert_called_once()
        # Actor should be stored in wrapper for action attribution
        assert wrapper_service._current_actor == actor

    def test_plan_with_variables(self, wrapper_service, mock_standalone_service):
        """Plan should pass variables to standalone."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(
            environment="test-env",
            variables={"db_host": "localhost", "port": 5432}
        )
        result = wrapper_service.plan(request)

        call_args = mock_standalone_service.plan.call_args
        passed_request = call_args[0][0]
        assert passed_request.variables == {"db_host": "localhost", "port": 5432}


class TestApplyDelegation:
    """Test that apply operations delegate properly."""

    def test_apply_delegates_to_standalone(self, wrapper_service, mock_standalone_service):
        """Apply should delegate to standalone service."""
        from amprealize.breakeramp import ApplyRequest

        request = ApplyRequest(plan_id="plan-123")
        result = wrapper_service.apply(request)

        mock_standalone_service.apply.assert_called_once_with(request)
        assert result.amp_run_id == "amp-run-123"
        assert "web" in result.environment_outputs

    def test_apply_with_actor(self, wrapper_service, mock_standalone_service):
        """Apply should accept actor for attribution."""
        from amprealize.breakeramp import ApplyRequest
        from amprealize.action_contracts import Actor

        request = ApplyRequest(plan_id="plan-123")
        actor = Actor(id="user-1", role="admin", surface="api")

        result = wrapper_service.apply(request, actor=actor)

        mock_standalone_service.apply.assert_called_once()
        assert wrapper_service._current_actor == actor

    def test_apply_propagates_errors(self, wrapper_service, mock_standalone_service):
        """Errors during apply should propagate."""
        from amprealize.breakeramp import ApplyRequest

        mock_standalone_service.apply.side_effect = RuntimeError("Container failed to start")
        request = ApplyRequest(plan_id="plan-123")

        with pytest.raises(RuntimeError, match="Container failed to start"):
            wrapper_service.apply(request)


class TestDestroyDelegation:
    """Test that destroy operations delegate properly."""

    def test_destroy_delegates_to_standalone(self, wrapper_service, mock_standalone_service):
        """Destroy should delegate to standalone service."""
        from amprealize.breakeramp import DestroyRequest

        request = DestroyRequest(amp_run_id="amp-123", reason="test cleanup")
        result = wrapper_service.destroy(request)

        mock_standalone_service.destroy.assert_called_once_with(request)
        assert result.action_id == "action-456"
        assert len(result.teardown_report) > 0

    def test_destroy_with_cascade(self, wrapper_service, mock_standalone_service):
        """Destroy should pass cascade option."""
        from amprealize.breakeramp import DestroyRequest

        request = DestroyRequest(amp_run_id="amp-123", reason="cascade test", cascade=True)
        wrapper_service.destroy(request)

        call_args = mock_standalone_service.destroy.call_args
        passed_request = call_args[0][0]
        assert passed_request.cascade is True

    def test_destroy_propagates_errors(self, wrapper_service, mock_standalone_service):
        """Errors during destroy should propagate."""
        from amprealize.breakeramp import DestroyRequest

        mock_standalone_service.destroy.side_effect = RuntimeError("Container not found")
        request = DestroyRequest(amp_run_id="amp-123", reason="error test")

        with pytest.raises(RuntimeError, match="Container not found"):
            wrapper_service.destroy(request)


class TestStatusDelegation:
    """Test that status operations delegate properly."""

    def test_status_delegates_to_standalone(self, wrapper_service, mock_standalone_service):
        """Status should delegate to standalone service."""
        result = wrapper_service.status("amp-123")

        mock_standalone_service.status.assert_called_once_with("amp-123")
        assert result.phase == "APPLIED"
        assert result.progress_pct == 100

    def test_status_for_nonexistent_environment(self, wrapper_service, mock_standalone_service):
        """Status for non-existent environment should propagate error."""
        mock_standalone_service.status.side_effect = KeyError("Environment not found")

        with pytest.raises(KeyError, match="Environment not found"):
            wrapper_service.status("nonexistent-env")
