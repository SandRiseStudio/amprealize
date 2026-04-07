"""
Tests for Amprealize BreakerAmp Wrapper - Bandwidth Throttling Delegation

These tests verify the wrapper properly handles bandwidth-related parameters
and delegates to the standalone breakeramp service.

NOTE: BandwidthEnforcer and throttling logic live in the standalone breakeramp
package (packages/breakeramp/). These tests focus on:
1. Passing bandwidth configuration to standalone service
2. Handling throttling events from standalone
3. Hook firing during bandwidth-related operations
"""
import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_plan_response():
    """Create a mock PlanResponse with bandwidth estimates."""
    from amprealize.breakeramp import PlanResponse, EnvironmentEstimates
    return PlanResponse(
        plan_id="plan-123",
        amp_run_id="amp-run-123",
        signed_manifest={"phase": "PLANNED"},
        environment_estimates=EnvironmentEstimates(
            cost_estimate=0.0,
            memory_footprint_mb=512,
            bandwidth_mbps=70,
            region="local",
            expected_boot_duration_s=30
        )
    )


@pytest.fixture
def mock_apply_response():
    """Create a mock ApplyResponse."""
    from amprealize.breakeramp import ApplyResponse
    return ApplyResponse(
        environment_outputs={"web": {"container_id": "cid-123"}},
        status_stream_url=None,
        action_id="action-123",
        amp_run_id="amp-123"
    )


@pytest.fixture
def mock_standalone_service(mock_plan_response, mock_apply_response):
    """Mock the standalone breakeramp service with bandwidth support."""
    service = MagicMock()
    service.plan = MagicMock(return_value=mock_plan_response)
    service.apply = MagicMock(return_value=mock_apply_response)
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
    service._service = mock_standalone_service
    return service


class TestBandwidthConfigDelegation:
    """Test that bandwidth configuration is passed to standalone."""

    def test_plan_delegates_to_standalone(
        self, wrapper_service, mock_standalone_service
    ):
        """Plan should delegate to standalone."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(environment="test-env", blueprint_id="test-blueprint")
        wrapper_service.plan(request)

        mock_standalone_service.plan.assert_called_once()

    def test_plan_returns_bandwidth_estimates(
        self, wrapper_service, mock_standalone_service
    ):
        """Plan should return bandwidth estimates from standalone."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(environment="test-env", blueprint_id="test-blueprint")
        result = wrapper_service.plan(request)

        assert result.environment_estimates.bandwidth_mbps == 70


class TestBandwidthThrottlingEvents:
    """Test that throttling events from standalone are handled."""

    def test_apply_delegates_to_standalone(
        self, wrapper_service, mock_standalone_service
    ):
        """Apply should delegate to standalone."""
        from amprealize.breakeramp import ApplyRequest

        request = ApplyRequest(plan_id="plan-123")
        result = wrapper_service.apply(request)

        mock_standalone_service.apply.assert_called_once()
        assert result.amp_run_id == "amp-123"


class TestBandwidthErrorPropagation:
    """Test that bandwidth errors propagate from standalone."""

    def test_apply_propagates_bandwidth_exceeded(
        self, wrapper_service, mock_standalone_service
    ):
        """Bandwidth exceeded errors should propagate."""
        from amprealize.breakeramp import ApplyRequest

        mock_standalone_service.apply.side_effect = RuntimeError(
            "Bandwidth limit exceeded: 150 Mbps > 100 Mbps limit"
        )

        request = ApplyRequest(plan_id="plan-123")
        with pytest.raises(RuntimeError, match="Bandwidth limit exceeded"):
            wrapper_service.apply(request)

    def test_plan_propagates_estimation_error(
        self, wrapper_service, mock_standalone_service
    ):
        """Bandwidth estimation errors should propagate."""
        from amprealize.breakeramp import PlanRequest

        mock_standalone_service.plan.side_effect = RuntimeError(
            "Cannot estimate bandwidth for blueprint"
        )

        request = PlanRequest(environment="test-env", blueprint_id="test-blueprint")
        with pytest.raises(RuntimeError, match="Cannot estimate bandwidth"):
            wrapper_service.plan(request)


class TestBandwidthWithHooks:
    """Test that hooks fire during bandwidth-related operations via delegation."""

    def test_plan_delegates_which_fires_hooks(
        self, wrapper_service, mock_standalone_service
    ):
        """Plan delegates to standalone (which fires hooks)."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(environment="test-env", blueprint_id="test-blueprint")
        wrapper_service.plan(request)

        # Delegation happened - standalone service handles hook firing
        mock_standalone_service.plan.assert_called_once()

    def test_apply_delegates_which_fires_hooks(
        self, wrapper_service, mock_standalone_service
    ):
        """Apply delegates to standalone (which fires hooks)."""
        from amprealize.breakeramp import ApplyRequest

        request = ApplyRequest(plan_id="plan-123")
        wrapper_service.apply(request)

        # Delegation happened - standalone service handles hook firing
        mock_standalone_service.apply.assert_called_once()
