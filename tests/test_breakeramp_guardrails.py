"""Tests for Amprealize BreakerAmp wrapper's guardrail behavior.

These tests verify the wrapper correctly integrates with amprealize services,
NOT the core breakeramp functionality (which is tested in packages/breakeramp/).
"""

import pytest
from unittest.mock import MagicMock, patch
from amprealize.breakeramp import BreakerAmpService, PlanRequest, ApplyRequest, DestroyRequest
from amprealize.action_contracts import Actor


@pytest.fixture
def mock_services():
    """Provide mock amprealize services."""
    action_svc = MagicMock()
    action_svc.create_action.return_value = MagicMock(action_id="action-123")

    return {
        "action_service": action_svc,
        "compliance_service": MagicMock(),
        "metrics_service": MagicMock(),
    }


@pytest.fixture
def mock_executor():
    """Provide a mock executor to avoid real container operations."""
    executor = MagicMock()
    executor.run_container.return_value = "container-123"
    executor.list_containers.return_value = []
    return executor


@pytest.fixture
def service(mock_services, mock_executor):
    """Create service with mocked dependencies."""
    return BreakerAmpService(
        executor=mock_executor,
        **mock_services,
    )


@pytest.fixture
def actor():
    """Provide a test actor."""
    return Actor(id="test-user", role="engineer", surface="cli")


class TestRedisBootstrapGuardrail:
    """Tests for Redis availability guardrail in the wrapper."""

    def test_redis_not_required_proceeds(self, service, actor):
        """Plan proceeds when blueprint doesn't require Redis."""
        # Mock the standalone service's plan method
        mock_response = MagicMock()
        mock_response.plan_id = "plan-123"
        service._service.plan = MagicMock(return_value=mock_response)

        # Mock blueprint resolution to return a non-Redis blueprint
        service._service._resolve_blueprint = MagicMock(return_value=MagicMock(
            services={"web": MagicMock(image="nginx:latest")}
        ))
        service._service.environments = {"development": MagicMock(default_blueprint="web-only")}

        request = PlanRequest(
            blueprint_id="web-only",
            environment="development",
        )

        # Should not raise
        result = service.plan(request, actor)
        assert result.plan_id == "plan-123"

    @patch.object(BreakerAmpService, '_check_redis_available', return_value=True)
    def test_redis_required_and_available_proceeds(self, mock_redis_check, service, actor):
        """Plan proceeds when Redis is required and available."""
        mock_response = MagicMock()
        mock_response.plan_id = "plan-456"
        service._service.plan = MagicMock(return_value=mock_response)

        # Mock blueprint with Redis service
        service._service._resolve_blueprint = MagicMock(return_value=MagicMock(
            services={"redis": MagicMock(image="redis:7-alpine")}
        ))
        service._service.environments = {"development": MagicMock(default_blueprint=None)}

        request = PlanRequest(
            blueprint_id="redis-blueprint",
            environment="development",
        )

        result = service.plan(request, actor)
        assert result.plan_id == "plan-456"


class TestActorTracking:
    """Tests for actor tracking in the wrapper."""

    def test_plan_tracks_actor(self, service, actor):
        """Plan operation stores the actor for action tracking."""
        mock_response = MagicMock()
        mock_response.plan_id = "plan-789"
        service._service.plan = MagicMock(return_value=mock_response)
        service._service._resolve_blueprint = MagicMock(return_value=MagicMock(services={}))
        service._service.environments = {"dev": MagicMock(default_blueprint=None)}

        request = PlanRequest(blueprint_id="test", environment="dev")
        service.plan(request, actor)

        # Verify actor was tracked
        assert service._current_actor == actor

    def test_plan_uses_default_actor_when_none_provided(self, service):
        """Plan uses default actor when none is provided."""
        mock_response = MagicMock()
        service._service.plan = MagicMock(return_value=mock_response)
        service._service._resolve_blueprint = MagicMock(return_value=MagicMock(services={}))
        service._service.environments = {"dev": MagicMock(default_blueprint=None)}

        request = PlanRequest(blueprint_id="test", environment="dev")
        service.plan(request, actor=None)

        # Should use default actor
        assert service._current_actor is None  # Not overwritten
        # The _get_actor method returns default when _current_actor is None
        assert service._get_actor().id == "breakeramp-service"


class TestServiceDelegation:
    """Tests for proper delegation to standalone service."""

    def test_plan_delegates_to_standalone(self, service, actor):
        """Plan correctly delegates to standalone BreakerAmpService."""
        mock_response = MagicMock()
        mock_response.plan_id = "plan-delegated"
        service._service.plan = MagicMock(return_value=mock_response)
        service._service._resolve_blueprint = MagicMock(return_value=MagicMock(services={}))
        service._service.environments = {"dev": MagicMock(default_blueprint=None)}

        request = PlanRequest(blueprint_id="test", environment="dev")
        result = service.plan(request, actor)

        # Verify delegation
        service._service.plan.assert_called_once_with(request)
        assert result == mock_response

    def test_apply_delegates_to_standalone(self, service, actor):
        """Apply correctly delegates to standalone service."""
        mock_response = MagicMock()
        mock_response.amp_run_id = "amp-123"
        service._service.apply = MagicMock(return_value=mock_response)

        request = ApplyRequest(plan_id="plan-123")
        result = service.apply(request, actor)

        service._service.apply.assert_called_once_with(request)
        assert result == mock_response

    def test_destroy_delegates_to_standalone(self, service):
        """Destroy correctly delegates to standalone service."""
        mock_response = MagicMock()
        service._service.destroy = MagicMock(return_value=mock_response)

        request = DestroyRequest(amp_run_id="amp-123", reason="test")
        result = service.destroy(request)

        service._service.destroy.assert_called_once_with(request)
        assert result == mock_response

    def test_status_delegates_to_standalone(self, service):
        """Status correctly delegates to standalone service."""
        mock_response = MagicMock()
        mock_response.phase = "APPLIED"
        service._service.status = MagicMock(return_value=mock_response)

        result = service.status("amp-123")

        service._service.status.assert_called_once_with("amp-123")
        assert result.phase == "APPLIED"
