"""Tests for BreakerAmpService."""

import pytest
from pathlib import Path

from breakeramp import (
    BreakerAmpService,
    BreakerAmpHooks,
    PlanRequest,
    ApplyRequest,
    DestroyRequest,
    Blueprint,
    ServiceSpec,
    EnvironmentDefinition,
)
from breakeramp.service import BandwidthEnforcer


class TestBreakerAmpServiceInit:
    """Tests for BreakerAmpService initialization."""

    def test_init_with_mock_executor(self, mock_executor, temp_base_dir):
        """Service initializes with mock executor."""
        service = BreakerAmpService(
            executor=mock_executor,
            base_dir=temp_base_dir,
        )
        assert service.executor is mock_executor
        assert service.base_dir == temp_base_dir

    def test_init_creates_directories(self, mock_executor, temp_base_dir):
        """Service creates required directories on init."""
        service = BreakerAmpService(
            executor=mock_executor,
            base_dir=temp_base_dir,
        )
        assert service.manifests_dir.exists()
        assert service.environments_dir.exists()
        assert service.user_blueprints_dir.exists()

    def test_init_registers_default_environments(self, mock_executor, temp_base_dir):
        """Service registers default environments."""
        service = BreakerAmpService(
            executor=mock_executor,
            base_dir=temp_base_dir,
        )
        # Default environments should be registered
        assert "development" in service.environments
        assert "staging" in service.environments
        assert "production" in service.environments

    def test_init_with_hooks(self, mock_executor, temp_base_dir):
        """Service accepts custom hooks."""
        actions = []

        def track_action(action_type, details):
            actions.append((action_type, details))
            return "test-action"

        hooks = BreakerAmpHooks(on_action=track_action)
        service = BreakerAmpService(
            executor=mock_executor,
            hooks=hooks,
            base_dir=temp_base_dir,
        )
        assert service.hooks is hooks


class TestEnvironmentManagement:
    """Tests for environment registration and management."""

    def test_register_environment(self, service):
        """Can register a custom environment."""
        custom_env = EnvironmentDefinition(
            name="custom-test",
            description="Custom test environment",
            default_compliance_tier="strict",
        )
        service.register_environment(custom_env)

        assert "custom-test" in service.environments
        assert service.environments["custom-test"].default_compliance_tier == "strict"

    def test_register_environment_overwrites(self, service):
        """Registering same environment overwrites."""
        env1 = EnvironmentDefinition(name="test-env", description="First")
        env2 = EnvironmentDefinition(name="test-env", description="Second")

        service.register_environment(env1)
        service.register_environment(env2)

        assert service.environments["test-env"].description == "Second"


class TestBlueprintManagement:
    """Tests for blueprint loading and listing."""

    def test_list_blueprints(self, service):
        """Can list available blueprints."""
        blueprints = service.list_blueprints()
        # Should return a list (may be empty or have packaged blueprints)
        assert isinstance(blueprints, list)

    def test_resolve_blueprint_from_file(self, service, sample_blueprint_file):
        """Can resolve blueprint from file path."""
        blueprint = service._resolve_blueprint(str(sample_blueprint_file))
        assert blueprint.name == "test-blueprint"
        assert "postgres" in blueprint.services

    def test_resolve_blueprint_not_found(self, service):
        """Raises error for non-existent blueprint."""
        with pytest.raises(ValueError, match="not found"):
            service._resolve_blueprint("nonexistent-blueprint")


class TestPlanOperation:
    """Tests for the plan operation."""

    def test_plan_with_blueprint_file(self, service, sample_blueprint_file):
        """Can plan with a blueprint file."""
        request = PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
        )
        response = service.plan(request)

        assert response.plan_id is not None
        assert response.amp_run_id is not None
        assert "blueprint" in response.signed_manifest
        assert response.environment_estimates.memory_footprint_mb > 0

    def test_plan_creates_manifest(self, service, sample_blueprint_file):
        """Plan creates a manifest file."""
        request = PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
        )
        response = service.plan(request)

        # Manifest should be stored
        manifest_path = service.manifests_dir / f"{response.plan_id}.json"
        assert manifest_path.exists()

    def test_plan_with_variables(self, service, sample_blueprint_file):
        """Plan accepts variable overrides."""
        request = PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
            variables={"custom_var": "custom_value"},
        )
        response = service.plan(request)

        # Variables should be in manifest
        assert response.signed_manifest.get("variables", {}).get("custom_var") == "custom_value"

    def test_plan_with_lifetime(self, service, sample_blueprint_file):
        """Plan accepts lifetime setting."""
        request = PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
            lifetime="2h",
        )
        response = service.plan(request)

        assert response.signed_manifest.get("lifetime") == "2h"


class TestApplyOperation:
    """Tests for the apply operation."""

    def test_apply_with_plan_id(self, service, mock_executor, sample_blueprint_file):
        """Can apply a previously created plan."""
        # First create a plan
        plan_req = PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
        )
        plan_resp = service.plan(plan_req)

        # Then apply it
        apply_req = ApplyRequest(plan_id=plan_resp.plan_id)
        apply_resp = service.apply(apply_req)

        assert apply_resp.amp_run_id == plan_resp.amp_run_id
        assert apply_resp.action_id is not None
        assert "postgres" in apply_resp.environment_outputs
        assert "redis" in apply_resp.environment_outputs

    def test_apply_runs_containers(self, service, mock_executor, sample_blueprint_file):
        """Apply runs containers via executor."""
        plan_req = PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
        )
        plan_resp = service.plan(plan_req)

        apply_req = ApplyRequest(plan_id=plan_resp.plan_id)
        service.apply(apply_req)

        # Mock executor should have received run calls
        assert len(mock_executor.run_calls) == 2  # postgres + redis

    def test_apply_with_direct_manifest(self, service, sample_blueprint):
        """Can apply with direct manifest (no plan_id)."""
        manifest = {
            "blueprint": sample_blueprint.model_dump(),
            "environment": "development",
            "lifetime": "1h",
        }

        apply_req = ApplyRequest(manifest=manifest)
        apply_resp = service.apply(apply_req)

        assert apply_resp.amp_run_id is not None


class TestStatusOperation:
    """Tests for the status operation."""

    def test_status_after_apply(self, service, mock_executor, sample_blueprint_file):
        """Can get status after apply."""
        # Plan and apply
        plan_req = PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
        )
        plan_resp = service.plan(plan_req)
        apply_resp = service.apply(ApplyRequest(plan_id=plan_resp.plan_id))

        # Get status
        status = service.status(apply_resp.amp_run_id)

        assert status.amp_run_id == apply_resp.amp_run_id
        assert status.phase in ["APPLIED", "PROVISIONING", "RUNNING"]
        assert status.progress_pct >= 0


class TestDestroyOperation:
    """Tests for the destroy operation."""

    def test_destroy_after_apply(self, service, mock_executor, sample_blueprint_file):
        """Can destroy an applied environment."""
        # Plan and apply
        plan_req = PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
        )
        plan_resp = service.plan(plan_req)
        apply_resp = service.apply(ApplyRequest(plan_id=plan_resp.plan_id))

        # Destroy
        destroy_req = DestroyRequest(
            amp_run_id=apply_resp.amp_run_id,
            reason="Test cleanup",
        )
        destroy_resp = service.destroy(destroy_req)

        assert len(destroy_resp.teardown_report) > 0
        assert destroy_resp.action_id is not None

    def test_destroy_stops_containers(self, service, mock_executor, sample_blueprint_file):
        """Destroy stops and removes containers."""
        # Plan and apply
        plan_req = PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
        )
        plan_resp = service.plan(plan_req)
        service.apply(ApplyRequest(plan_id=plan_resp.plan_id))

        # Destroy
        destroy_req = DestroyRequest(
            amp_run_id=plan_resp.amp_run_id,
            reason="Test cleanup",
        )
        service.destroy(destroy_req)

        # Mock executor should have stop/remove calls
        assert len(mock_executor.stop_calls) >= 2
        assert len(mock_executor.remove_calls) >= 2


class TestHooksIntegration:
    """Tests for hooks integration."""

    def test_plan_triggers_action_hook(self, service_with_hooks, sample_blueprint_file):
        """Plan operation triggers action hook."""
        service, actions, _, _ = service_with_hooks

        # Use blueprint file path directly (no need to copy)
        request = PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
        )
        service.plan(request)

        # Should have recorded action
        assert len(actions) > 0
        action_types = [a[0] for a in actions]
        assert any("plan" in t.lower() for t in action_types)

    def test_apply_triggers_hooks(self, service_with_hooks, sample_blueprint_file):
        """Apply operation triggers action and compliance hooks."""
        service, actions, compliance_steps, metrics = service_with_hooks

        # Plan and apply using direct file path
        plan_resp = service.plan(PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
        ))
        service.apply(ApplyRequest(plan_id=plan_resp.plan_id))

        # Should have recorded actions for apply
        assert len(actions) > 1

    def test_destroy_triggers_hooks(self, service_with_hooks, sample_blueprint_file):
        """Destroy operation triggers hooks."""
        service, actions, _, _ = service_with_hooks

        # Full lifecycle using direct file path
        plan_resp = service.plan(PlanRequest(
            blueprint_id=str(sample_blueprint_file),
            environment="development",
        ))
        apply_resp = service.apply(ApplyRequest(plan_id=plan_resp.plan_id))
        service.destroy(DestroyRequest(
            amp_run_id=apply_resp.amp_run_id,
            reason="Test cleanup",
        ))

        # Should have recorded destroy action
        action_types = [a[0] for a in actions]
        assert any("destroy" in t.lower() for t in action_types)


class TestBandwidthEnforcer:
    """Tests for BandwidthEnforcer."""

    def test_no_limit_always_passes(self):
        """Without limit, all bandwidth is allowed."""
        enforcer = BandwidthEnforcer(limit_mbps=None)
        stats = {"container-1": {"net_input_bytes": 1000000, "net_output_bytes": 1000000}}
        assert enforcer.check_usage(stats) is True

    def test_with_limit_under_threshold(self):
        """Bandwidth under limit passes."""
        enforcer = BandwidthEnforcer(limit_mbps=100)
        stats = {"container-1": {"net_input_bytes": 1000, "net_output_bytes": 1000}}

        # First call establishes baseline
        enforcer.check_usage(stats)

        # Second call with minimal increase should pass
        import time
        time.sleep(0.1)  # Small delay for realistic test
        stats2 = {"container-1": {"net_input_bytes": 1100, "net_output_bytes": 1100}}
        assert enforcer.check_usage(stats2) is True

    def test_get_current_usage(self):
        """Can get current usage."""
        enforcer = BandwidthEnforcer(limit_mbps=100)
        stats = {"container-1": {"net_input_bytes": 1000, "net_output_bytes": 1000}}
        usage = enforcer.get_current_usage_mbps(stats)
        assert isinstance(usage, float)


class TestListEnvironmentsReconciliation:
    """Tests for list_environments reconciliation with container reality."""

    def test_list_environments_empty(self, service):
        """Returns empty list when no environments."""
        result = service.list_environments()
        assert result == []

    def test_list_environments_no_reconcile(self, service):
        """Can skip reconciliation for faster listing."""
        result = service.list_environments(reconcile=False)
        assert isinstance(result, list)

    def test_list_environments_cleans_stale(self, service):
        """Auto-cleanup removes stale state files."""
        import json

        # Create a fake stale environment state file
        stale_path = service.environments_dir / "amp-fake-stale-12345.json"
        stale_path.write_text(json.dumps({
            "amp_run_id": "amp-fake-stale-12345",
            "environment": "development",
            "phase": "APPLIED",
            "blueprint_id": "test-blueprint",
            "created_at": "2025-01-01T00:00:00",
        }))

        # List with auto_cleanup=True (default)
        result = service.list_environments(reconcile=True, auto_cleanup=True)

        # Stale file should be removed (no containers match)
        assert not stale_path.exists()
        # Result should not include the stale environment
        assert all(env["amp_run_id"] != "amp-fake-stale-12345" for env in result)

    def test_list_environments_keeps_stale_when_requested(self, service):
        """Can keep stale entries when auto_cleanup=False."""
        import json

        # Create a fake stale environment state file
        stale_path = service.environments_dir / "amp-keep-stale-67890.json"
        stale_path.write_text(json.dumps({
            "amp_run_id": "amp-keep-stale-67890",
            "environment": "development",
            "phase": "APPLIED",
            "blueprint_id": "test-blueprint",
            "created_at": "2025-01-01T00:00:00",
        }))

        try:
            # List with auto_cleanup=False
            result = service.list_environments(reconcile=True, auto_cleanup=False)

            # Stale file should still exist
            assert stale_path.exists()
            # Result should include the stale environment with STALE status
            stale_env = next((e for e in result if e["amp_run_id"] == "amp-keep-stale-67890"), None)
            assert stale_env is not None
            assert stale_env.get("actual_status") == "STALE"
            assert stale_env.get("container_count") == 0
        finally:
            # Cleanup
            if stale_path.exists():
                stale_path.unlink()
