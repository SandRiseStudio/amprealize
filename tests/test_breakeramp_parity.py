import pytest
from unittest.mock import MagicMock
from amprealize.adapters import MCPBreakerAmpAdapter
from amprealize.breakeramp import (
    BreakerAmpService,
    PlanRequest,
    PlanResponse,
    EnvironmentEstimates,
    ApplyRequest,
    ApplyResponse,
    StatusResponse,
    HealthCheck,
    DestroyRequest,
    DestroyResponse,
)
from amprealize.action_contracts import Actor
from datetime import datetime

@pytest.mark.unit
class TestBreakerAmpParity:
    @pytest.fixture
    def mock_service(self):
        return MagicMock(spec=BreakerAmpService)

    @pytest.fixture
    def adapter(self, mock_service):
        return MCPBreakerAmpAdapter(service=mock_service)

    def test_plan_parity(self, adapter, mock_service):
        # Setup
        mock_service.plan.return_value = PlanResponse(
            plan_id="plan-123",
            amp_run_id="amp-123",
            signed_manifest={"resource": "vm"},
            environment_estimates=EnvironmentEstimates(
                cost_estimate=10.0,
                memory_footprint_mb=1024,
                region="us-east-1",
                expected_boot_duration_s=60
            )
        )

        # Execute
        result = adapter.plan(
            blueprint_id="web-app",
            environment="staging",
            lifetime="2h",
            compliance_tier="high",
            checklist_id="chk-123",
            behaviors=["behavior_1"],
            variables={"env": "staging"}
        )

        # Verify
        assert result["plan_id"] == "plan-123"
        assert result["amp_run_id"] == "amp-123"

        # Verify service call
        mock_service.plan.assert_called_once()
        args, _ = mock_service.plan.call_args
        plan_req, actor = args

        assert plan_req.blueprint_id == "web-app"
        assert plan_req.lifetime == "2h"
        assert plan_req.compliance_tier == "high"
        assert plan_req.checklist_id == "chk-123"
        assert plan_req.behaviors == ["behavior_1"]
        assert plan_req.variables == {"env": "staging"}
        assert actor.surface == "mcp"

    def test_apply_parity(self, adapter, mock_service):
        # Setup
        mock_service.apply.return_value = ApplyResponse(
            environment_outputs={"url": "http://example.com"},
            action_id="action-456",
            amp_run_id="amp-789"
        )

        # Execute
        result = adapter.apply(plan_id="plan-123")

        # Verify
        assert result["action_id"] == "action-456"
        assert result["environment_outputs"]["url"] == "http://example.com"

        # Verify service call
        mock_service.apply.assert_called_once()
        call_args = mock_service.apply.call_args
        request = call_args[0][0]

        assert isinstance(request, ApplyRequest)
        assert request.plan_id == "plan-123"

    def test_status_parity(self, adapter, mock_service):
        # Setup
        mock_service.status.return_value = StatusResponse(
            amp_run_id="amp-456",
            phase="RUNNING",
            progress_pct=100,
            checks=[
                HealthCheck(name="http", status="ok", last_probe=datetime.now())
            ]
        )

        # Execute
        result = adapter.status(run_id="amp-456")

        # Verify
        assert result["amp_run_id"] == "amp-456"
        assert result["phase"] == "RUNNING"
        assert result["progress_pct"] == 100

        # Verify service call
        mock_service.status.assert_called_once_with("amp-456")

    def test_destroy_parity(self, adapter, mock_service):
        # Setup
        mock_service.destroy.return_value = DestroyResponse(
            teardown_report=["Stopped VM", "Deleted Volume"],
            action_id="action-789"
        )

        # Execute
        result = adapter.destroy(run_id="amp-456", cascade=True)

        # Verify
        assert result["action_id"] == "action-789"
        assert len(result["teardown_report"]) == 2

        # Verify service call
        mock_service.destroy.assert_called_once()
        call_args = mock_service.destroy.call_args
        request = call_args[0][0]

        assert isinstance(request, DestroyRequest)
        assert request.amp_run_id == "amp-456"
        assert request.cascade is True

    def test_list_blueprints_parity(self, adapter, mock_service):
        """Test list_blueprints returns blueprints with HATEOAS links."""
        # Setup
        mock_service.list_blueprints.return_value = [
            {"id": "postgres-dev", "path": "/blueprints/postgres-dev.yaml", "source": "package"},
            {"id": "custom", "path": "/user/blueprints/custom.yaml", "source": "user"},
        ]

        # Execute - all sources
        result = adapter.list_blueprints(source="all")

        # Verify
        assert result["count"] == 2
        assert len(result["blueprints"]) == 2
        assert result["blueprints"][0]["id"] == "postgres-dev"
        assert result["blueprints"][0]["source"] == "package"
        assert result["blueprints"][1]["source"] == "user"
        assert "_links" in result
        assert result["_links"]["plan"] == "/v1/breakeramp/plan"

        # Verify service call
        mock_service.list_blueprints.assert_called_once()

    def test_list_blueprints_filters_by_source(self, adapter, mock_service):
        """Test list_blueprints filters by package/user source."""
        mock_service.list_blueprints.return_value = [
            {"id": "postgres-dev", "path": "/blueprints/postgres-dev.yaml", "source": "package"},
            {"id": "custom", "path": "/user/blueprints/custom.yaml", "source": "user"},
        ]

        # Filter by package only
        result = adapter.list_blueprints(source="package")

        assert result["count"] == 1
        assert result["blueprints"][0]["source"] == "package"

    def test_list_environments_parity(self, adapter, mock_service):
        """Test list_environments returns active environments with HATEOAS links."""
        # Setup
        mock_service.list_environments.return_value = [
            {
                "amp_run_id": "amp-123",
                "environment": "development",
                "phase": "running",
                "blueprint_id": "postgres-dev",
                "created_at": "2025-06-01T10:00:00Z"
            },
            {
                "amp_run_id": "amp-456",
                "environment": "staging",
                "phase": "stopped",
                "blueprint_id": "web-app",
                "created_at": "2025-06-01T12:00:00Z"
            }
        ]

        # Execute
        result = adapter.list_environments(phase="all")

        # Verify
        assert result["count"] == 2
        assert len(result["environments"]) == 2
        assert result["environments"][0]["amp_run_id"] == "amp-123"
        assert result["environments"][0]["phase"] == "running"
        assert "_links" in result
        assert "status" in result["_links"]
        assert "destroy" in result["_links"]

        # Verify service call
        mock_service.list_environments.assert_called_once()

    def test_list_environments_filters_by_phase(self, adapter, mock_service):
        """Test list_environments filters by phase."""
        mock_service.list_environments.return_value = [
            {"amp_run_id": "amp-123", "phase": "running"},
            {"amp_run_id": "amp-456", "phase": "stopped"},
        ]

        # Filter by running only
        result = adapter.list_environments(phase="running")

        assert result["count"] == 1
        assert result["environments"][0]["phase"] == "running"

    def test_configure_parity(self, adapter, mock_service):
        """Test configure (formerly bootstrap) creates config with HATEOAS links."""
        # Setup
        mock_service.configure.return_value = {
            "environment_file": "/config/breakeramp/environments.yaml",
            "environment_status": "created",
            "blueprints_dir": None,
            "blueprints": []
        }

        # Execute
        result = adapter.configure(
            config_dir="/config/breakeramp",
            include_blueprints=False,
            force=False
        )

        # Verify
        assert result["environment_file"] == "/config/breakeramp/environments.yaml"
        assert result["environment_status"] == "created"
        assert "_links" in result
        assert result["_links"]["list_blueprints"] == "/v1/breakeramp/blueprints"
        assert result["_links"]["plan"] == "/v1/breakeramp/plan"

        # Verify service call
        mock_service.configure.assert_called_once()

    def test_configure_with_blueprints(self, adapter, mock_service):
        """Test configure copies blueprints when requested."""
        # Setup
        mock_service.configure.return_value = {
            "environment_file": "/config/breakeramp/environments.yaml",
            "environment_status": "created",
            "blueprints_dir": "/config/breakeramp/blueprints",
            "blueprints": [
                {"blueprint": "postgres-dev", "status": "copied", "path": "/config/breakeramp/blueprints/postgres-dev.yaml"},
                {"blueprint": "web-app", "status": "copied", "path": "/config/breakeramp/blueprints/web-app.yaml"}
            ]
        }

        # Execute
        result = adapter.configure(
            config_dir="/config/breakeramp",
            include_blueprints=True,
            blueprints=["postgres-dev", "web-app"],
            force=True
        )

        # Verify
        assert result["blueprints_dir"] == "/config/breakeramp/blueprints"
        assert len(result["blueprints"]) == 2
        assert result["blueprints"][0]["status"] == "copied"

        # Verify service call arguments
        call_kwargs = mock_service.configure.call_args[1]
        assert call_kwargs["include_blueprints"] is True
        assert call_kwargs["force"] is True
        assert "postgres-dev" in call_kwargs["blueprints"]
