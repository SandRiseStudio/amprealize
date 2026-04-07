"""Tests for breakeramp models."""

import pytest
from pydantic import ValidationError

from breakeramp import (
    Blueprint,
    ServiceSpec,
    PlanRequest,
    PlanResponse,
    ApplyRequest,
    ApplyResponse,
    StatusResponse,
    DestroyRequest,
    DestroyResponse,
    EnvironmentDefinition,
    RuntimeConfig,
    InfrastructureConfig,
    EnvironmentEstimates,
    HealthCheck,
    TelemetryData,
    AuditEntry,
    StatusEvent,
)


class TestServiceSpec:
    """Tests for ServiceSpec model."""

    def test_create_minimal(self):
        """ServiceSpec can be created with just an image."""
        spec = ServiceSpec(image="postgres:16")
        assert spec.image == "postgres:16"
        assert spec.ports == []
        assert spec.environment == {}
        assert spec.volumes == []
        assert spec.command is None

    def test_create_full(self):
        """ServiceSpec can be created with all fields."""
        spec = ServiceSpec(
            image="postgres:16-alpine",
            ports=["5432:5432", "5433:5433"],
            environment={"POSTGRES_PASSWORD": "secret"},
            volumes=["/data:/var/lib/postgresql/data"],
            command=["postgres", "-c", "shared_buffers=256MB"],
            cpu_cores=2.0,
            memory_mb=1024,
            bandwidth_mbps=100,
            module="datastores",
        )
        assert spec.image == "postgres:16-alpine"
        assert len(spec.ports) == 2
        assert spec.environment["POSTGRES_PASSWORD"] == "secret"
        assert spec.cpu_cores == 2.0
        assert spec.memory_mb == 1024
        assert spec.bandwidth_mbps == 100
        assert spec.module == "datastores"

    def test_missing_image_raises(self):
        """ServiceSpec requires image field."""
        with pytest.raises(ValidationError):
            ServiceSpec()  # type: ignore


class TestBlueprint:
    """Tests for Blueprint model."""

    def test_create_blueprint(self, sample_blueprint):
        """Blueprint can be created with services."""
        assert sample_blueprint.name == "test-blueprint"
        assert sample_blueprint.version == "1.0.0"
        assert "postgres" in sample_blueprint.services
        assert "redis" in sample_blueprint.services

    def test_validate_topology_valid(self, sample_blueprint):
        """Valid blueprint passes topology validation."""
        errors = sample_blueprint.validate_topology()
        assert errors == []

    def test_validate_topology_empty_services(self):
        """Empty services fail topology validation."""
        blueprint = Blueprint(name="empty", version="1.0", services={})
        errors = blueprint.validate_topology()
        assert any("at least one service" in e for e in errors)

    def test_validate_topology_invalid_port(self):
        """Invalid port mapping fails topology validation."""
        blueprint = Blueprint(
            name="bad-ports",
            version="1.0",
            services={
                "web": ServiceSpec(
                    image="nginx",
                    ports=["8080"],  # Missing :container
                )
            },
        )
        errors = blueprint.validate_topology()
        assert any("invalid port mapping" in e.lower() for e in errors)

    def test_validate_topology_missing_image(self):
        """Missing image fails topology validation."""
        # Create with empty image string (bypasses pydantic validation)
        blueprint = Blueprint(
            name="no-image",
            version="1.0",
            services={
                "web": ServiceSpec(image=""),
            },
        )
        errors = blueprint.validate_topology()
        assert any("missing image" in e.lower() for e in errors)


class TestEnvironmentDefinition:
    """Tests for EnvironmentDefinition model."""

    def test_create_minimal(self):
        """EnvironmentDefinition can be created with just name."""
        env = EnvironmentDefinition(name="development")
        assert env.name == "development"
        assert env.default_compliance_tier == "standard"
        assert env.default_lifetime == "90m"

    def test_create_full(self):
        """EnvironmentDefinition can be created with all fields."""
        env = EnvironmentDefinition(
            name="production",
            description="Production environment",
            default_compliance_tier="strict",
            default_lifetime="4h",
            active_modules=["datastores", "observability"],
            runtime=RuntimeConfig(
                provider="podman",
                memory_limit_mb=8192,
            ),
            infrastructure=InfrastructureConfig(
                blueprint_id="prod-stack",
                teardown_on_exit=False,
            ),
            variables={"region": "us-east-1"},
        )
        assert env.name == "production"
        assert env.default_compliance_tier == "strict"
        assert env.runtime.provider == "podman"
        assert env.infrastructure.blueprint_id == "prod-stack"


class TestRuntimeConfig:
    """Tests for RuntimeConfig model."""

    def test_defaults(self):
        """RuntimeConfig has sensible defaults."""
        config = RuntimeConfig()
        assert config.provider == "native"
        assert config.auto_start is False
        assert config.auto_init is False
        assert config.auto_scaling_strategy == "fail"

    def test_podman_config(self):
        """RuntimeConfig can be configured for Podman."""
        config = RuntimeConfig(
            provider="podman",
            podman_machine="amprealize-dev",
            auto_start=True,
            memory_limit_mb=4096,
            cpu_limit=4,
        )
        assert config.provider == "podman"
        assert config.podman_machine == "amprealize-dev"


class TestPlanRequest:
    """Tests for PlanRequest model."""

    def test_create_minimal(self):
        """PlanRequest requires environment."""
        req = PlanRequest(environment="development")
        assert req.environment == "development"
        assert req.blueprint_id is None
        assert req.behaviors == []

    def test_create_full(self):
        """PlanRequest with all fields."""
        req = PlanRequest(
            blueprint_id="postgres-dev",
            environment="staging",
            lifetime="2h",
            compliance_tier="strict",
            checklist_id="chk-123",
            behaviors=["behavior_use_breakeramp"],
            variables={"db_name": "testdb"},
            active_modules=["datastores"],
            force_podman=True,
        )
        assert req.blueprint_id == "postgres-dev"
        assert req.compliance_tier == "strict"
        assert "behavior_use_breakeramp" in req.behaviors


class TestPlanResponse:
    """Tests for PlanResponse model."""

    def test_create(self):
        """PlanResponse can be created."""
        resp = PlanResponse(
            plan_id="plan-123",
            amp_run_id="run-456",
            signed_manifest={"blueprint": "test", "services": {}},
            environment_estimates=EnvironmentEstimates(
                cost_estimate=0.0,
                memory_footprint_mb=1024,
                bandwidth_mbps=50,
                region="local",
                expected_boot_duration_s=30,
            ),
        )
        assert resp.plan_id == "plan-123"
        assert resp.amp_run_id == "run-456"
        assert resp.environment_estimates.memory_footprint_mb == 1024


class TestApplyModels:
    """Tests for Apply request/response models."""

    def test_apply_request_with_plan_id(self):
        """ApplyRequest can reference a plan."""
        req = ApplyRequest(plan_id="plan-123")
        assert req.plan_id == "plan-123"
        assert req.watch is True

    def test_apply_request_with_manifest(self):
        """ApplyRequest can include direct manifest."""
        req = ApplyRequest(
            manifest={"blueprint": "test", "services": {}},
            watch=False,
        )
        assert req.manifest is not None
        assert req.watch is False

    def test_apply_response(self):
        """ApplyResponse can be created."""
        resp = ApplyResponse(
            environment_outputs={"postgres": {"container_id": "abc123"}},
            action_id="action-456",
            amp_run_id="run-789",
        )
        assert "postgres" in resp.environment_outputs
        assert resp.action_id == "action-456"


class TestStatusModels:
    """Tests for Status-related models."""

    def test_health_check(self):
        """HealthCheck can be created."""
        from datetime import datetime
        check = HealthCheck(
            name="postgres",
            status="healthy",
            last_probe=datetime.now(),
        )
        assert check.name == "postgres"
        assert check.status == "healthy"

    def test_telemetry_data(self):
        """TelemetryData can be created."""
        data = TelemetryData(
            token_savings_pct=45.0,
            behavior_reuse_pct=80.0,
        )
        assert data.token_savings_pct == 45.0

    def test_audit_entry(self):
        """AuditEntry can be created."""
        entry = AuditEntry(
            timestamp="2025-11-25T10:00:00Z",
            type="ACTION",
            summary="Environment planned",
            details={"plan_id": "plan-123"},
        )
        assert entry.type == "ACTION"

    def test_status_response(self):
        """StatusResponse can be created."""
        resp = StatusResponse(
            amp_run_id="run-123",
            phase="APPLIED",
            progress_pct=100,
            checks=[],
        )
        assert resp.phase == "APPLIED"
        assert resp.progress_pct == 100

    def test_status_event(self):
        """StatusEvent can be created."""
        event = StatusEvent(
            timestamp="2025-11-25T10:00:00Z",
            status="provisioning",
            message="Starting postgres container",
        )
        assert event.status == "provisioning"


class TestDestroyModels:
    """Tests for Destroy request/response models."""

    def test_destroy_request(self):
        """DestroyRequest can be created."""
        req = DestroyRequest(
            amp_run_id="run-123",
            reason="Testing complete",
        )
        assert req.amp_run_id == "run-123"
        assert req.cascade is True

    def test_destroy_response(self):
        """DestroyResponse can be created."""
        resp = DestroyResponse(
            teardown_report=["postgres", "redis"],
            action_id="action-789",
        )
        assert len(resp.teardown_report) == 2
