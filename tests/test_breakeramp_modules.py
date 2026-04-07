"""
Tests for Amprealize BreakerAmp Wrapper - Module Filtering Delegation

These tests verify the wrapper properly passes module filtering parameters
to the standalone breakeramp service.

NOTE: Module filtering logic (resolving blueprints, filtering services by module)
lives in the standalone breakeramp package (packages/breakeramp/). These tests focus on:
1. Passing active_modules parameter to standalone service
2. Verifying response structure when modules are filtered
3. Hook firing during module-filtered plans
"""
import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_plan_response_all_services():
    """Create a mock PlanResponse with all services."""
    from amprealize.breakeramp import PlanResponse, EnvironmentEstimates
    return PlanResponse(
        plan_id="plan-123",
        amp_run_id="amp-run-123",
        signed_manifest={
            "phase": "PLANNED",
            "blueprint": {
                "services": {
                    "redis": {"image": "redis", "module": "datastores"},
                    "postgres": {"image": "postgres", "module": "datastores"},
                    "api": {"image": "api", "module": "app"},
                    "worker": {"image": "worker", "module": "app"},
                }
            }
        },
        environment_estimates=EnvironmentEstimates(
            cost_estimate=0.0,
            memory_footprint_mb=2048,
            bandwidth_mbps=10,
            region="local",
            expected_boot_duration_s=60
        )
    )


@pytest.fixture
def mock_plan_response_datastores_only():
    """Create a mock PlanResponse with only datastores services."""
    from amprealize.breakeramp import PlanResponse, EnvironmentEstimates
    return PlanResponse(
        plan_id="plan-123",
        amp_run_id="amp-run-123",
        signed_manifest={
            "phase": "PLANNED",
            "blueprint": {
                "services": {
                    "redis": {"image": "redis", "module": "datastores"},
                    "postgres": {"image": "postgres", "module": "datastores"},
                }
            }
        },
        environment_estimates=EnvironmentEstimates(
            cost_estimate=0.0,
            memory_footprint_mb=1024,
            bandwidth_mbps=10,
            region="local",
            expected_boot_duration_s=30
        )
    )


@pytest.fixture
def mock_standalone_service(mock_plan_response_all_services):
    """Mock the standalone breakeramp service with module filtering support."""
    service = MagicMock()
    service.plan = MagicMock(return_value=mock_plan_response_all_services)
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


class TestModuleFilteringDelegation:
    """Test that module filtering parameters are passed to standalone."""

    def test_plan_passes_active_modules_to_standalone(
        self, wrapper_service, mock_standalone_service
    ):
        """Active modules should be passed to standalone plan via PlanRequest."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(
            environment="test-env",
            blueprint_id="test-blueprint",
            active_modules=["datastores"]
        )
        wrapper_service.plan(request)

        # Verify standalone was called with request containing active_modules
        mock_standalone_service.plan.assert_called_once()
        call_args = mock_standalone_service.plan.call_args
        passed_request = call_args[0][0]
        assert passed_request.active_modules == ["datastores"]

    def test_plan_without_modules_passes_none(
        self, wrapper_service, mock_standalone_service
    ):
        """No modules filter should pass None to standalone."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(environment="test-env", blueprint_id="test-blueprint")
        wrapper_service.plan(request)

        mock_standalone_service.plan.assert_called_once()
        call_args = mock_standalone_service.plan.call_args
        passed_request = call_args[0][0]
        assert passed_request.active_modules is None

    def test_plan_with_multiple_modules(
        self, wrapper_service, mock_standalone_service
    ):
        """Multiple modules should be passed correctly."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(
            environment="test-env",
            blueprint_id="test-blueprint",
            active_modules=["datastores", "app"]
        )
        wrapper_service.plan(request)

        mock_standalone_service.plan.assert_called_once()
        call_args = mock_standalone_service.plan.call_args
        passed_request = call_args[0][0]
        assert passed_request.active_modules == ["datastores", "app"]


class TestModuleFilteringResponse:
    """Test that module-filtered responses are returned correctly."""

    def test_filtered_plan_returns_subset(
        self, wrapper_service, mock_standalone_service, mock_plan_response_datastores_only
    ):
        """Filtered plan should return only matching services."""
        from amprealize.breakeramp import PlanRequest

        # Configure standalone to return filtered result
        mock_standalone_service.plan.return_value = mock_plan_response_datastores_only

        request = PlanRequest(
            environment="test-env",
            blueprint_id="test-blueprint",
            active_modules=["datastores"]
        )
        result = wrapper_service.plan(request)

        services = result.signed_manifest["blueprint"]["services"]
        assert len(services) == 2
        assert "redis" in services
        assert "postgres" in services
        assert "api" not in services

    def test_unfiltered_plan_returns_all(
        self, wrapper_service, mock_standalone_service
    ):
        """Unfiltered plan should return all services."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(environment="test-env", blueprint_id="test-blueprint")
        result = wrapper_service.plan(request)

        services = result.signed_manifest["blueprint"]["services"]
        assert len(services) == 4


class TestModuleFilteringWithHooks:
    """Test that hooks fire correctly during module-filtered operations."""

    def test_filtered_plan_delegates_to_standalone(self, wrapper_service, mock_standalone_service):
        """Module-filtered plan should delegate to standalone (which fires hooks)."""
        from amprealize.breakeramp import PlanRequest

        request = PlanRequest(
            environment="test-env",
            blueprint_id="test-blueprint",
            active_modules=["datastores"]
        )
        wrapper_service.plan(request)

        # Delegation happened - standalone service handles hook firing
        mock_standalone_service.plan.assert_called_once()
