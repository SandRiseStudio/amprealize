"""Parity tests for ComplianceService ensuring CLI/REST/MCP consistency."""

import os
import pytest

from amprealize.action_contracts import Actor
import os
import pytest
import psycopg2
from amprealize.adapters import CLIComplianceServiceAdapter, RestComplianceServiceAdapter, MCPComplianceServiceAdapter
from amprealize.compliance_service import ComplianceService
from amprealize.compliance_service import ComplianceService
from amprealize.storage.postgres_pool import PostgresPool


@pytest.fixture(autouse=True)
def cleanup_compliance_db():
    """Clean compliance database before each test to prevent data pollution."""
    dsn = os.getenv("AMPREALIZE_COMPLIANCE_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_COMPLIANCE_PG_DSN not set")

    from conftest import safe_truncate

    # Clean up any existing test data before the test runs
    try:
        safe_truncate(dsn, ["checklists", "checklist_steps"])
    except Exception as e:
        print(f"Cleanup BEFORE test failed: {type(e).__name__}: {e}")

    yield

    # Cleanup after test completes
    try:
        safe_truncate(dsn, ["checklists", "checklist_steps"])
    except Exception as e:
        print(f"Cleanup AFTER test failed: {type(e).__name__}: {e}")


@pytest.fixture
def compliance_service():
    """Provide a fresh ComplianceService instance for each test."""
    return ComplianceService()


@pytest.fixture
def cli_adapter(compliance_service):
    """CLI adapter fixture."""
    return CLIComplianceServiceAdapter(compliance_service)


@pytest.fixture
def rest_adapter(compliance_service):
    """REST adapter fixture."""
    return RestComplianceServiceAdapter(compliance_service)


@pytest.fixture
def mcp_adapter(compliance_service):
    """MCP adapter fixture."""
    return MCPComplianceServiceAdapter(compliance_service)


@pytest.fixture
def actor_payload():
    """Standard actor metadata for testing."""
    return {"id": "test-actor", "role": "STRATEGIST"}


class TestCreateChecklistParity:
    """Verify checklist creation works consistently across all surfaces."""

    def test_cli_create_checklist(self, cli_adapter):
        result = cli_adapter.create_checklist(
            title="Test Checklist",
            description="Test description",
            template_id=None,
            milestone="Milestone 1",
            compliance_category=["SOC2", "Internal"],
            actor_id="test-actor",
            actor_role="STRATEGIST",
        )

        assert result["title"] == "Test Checklist"
        assert result["milestone"] == "Milestone 1"
        assert "SOC2" in result["compliance_category"]
        assert result["coverage_score"] == 0.0
        assert "checklist_id" in result

    def test_rest_create_checklist(self, rest_adapter, actor_payload):
        payload = {
            "title": "Test Checklist",
            "description": "Test description",
            "milestone": "Milestone 1",
            "compliance_category": ["SOC2", "Internal"],
            "actor": actor_payload,
        }
        result = rest_adapter.create_checklist(payload)

        assert result["title"] == "Test Checklist"
        assert result["milestone"] == "Milestone 1"
        assert "SOC2" in result["compliance_category"]

    def test_mcp_create_checklist(self, mcp_adapter, actor_payload):
        payload = {
            "title": "Test Checklist",
            "description": "Test description",
            "milestone": "Milestone 1",
            "compliance_category": ["SOC2", "Internal"],
            "actor": actor_payload,
        }
        result = mcp_adapter.create_checklist(payload)

        assert result["title"] == "Test Checklist"
        assert result["milestone"] == "Milestone 1"
        assert "SOC2" in result["compliance_category"]

    def test_surface_parity_create_checklist(self, cli_adapter, rest_adapter, mcp_adapter, actor_payload):
        """Ensure all surfaces produce equivalent output structures."""

        cli_result = cli_adapter.create_checklist(
            title="Parity Test",
            description="Testing parity",
            template_id=None,
            milestone="Milestone 1",
            compliance_category=["GDPR"],
            actor_id="parity-actor",
            actor_role="STRATEGIST",
        )

        rest_payload = {
            "title": "Parity Test",
            "description": "Testing parity",
            "milestone": "Milestone 1",
            "compliance_category": ["GDPR"],
            "actor": {"id": "parity-actor", "role": "STRATEGIST"},
        }
        rest_result = rest_adapter.create_checklist(rest_payload)

        mcp_result = mcp_adapter.create_checklist(rest_payload)

        # All surfaces should return identical field structures
        assert set(cli_result.keys()) == set(rest_result.keys()) == set(mcp_result.keys())
        assert cli_result["title"] == rest_result["title"] == mcp_result["title"]
        assert cli_result["coverage_score"] == rest_result["coverage_score"] == mcp_result["coverage_score"] == 0.0


class TestRecordStepParity:
    """Verify step recording works consistently across all surfaces."""

    @pytest.fixture
    def checklist_id(self, cli_adapter):
        """Create a checklist for step tests."""
        result = cli_adapter.create_checklist(
            title="Step Test Checklist",
            description="",
            template_id=None,
            milestone=None,
            compliance_category=["Internal"],
            actor_id="test-actor",
            actor_role="STRATEGIST",
        )
        return result["checklist_id"]

    def test_cli_record_step(self, cli_adapter, checklist_id):
        step = cli_adapter.record_step(
            checklist_id=checklist_id,
            title="Test Step",
            status="COMPLETED",
            evidence={"artifact_path": "test.py"},
            behaviors_cited=["behavior_test"],
            related_run_id=None,
            actor_id="test-actor",
            actor_role="STRATEGIST",
        )

        assert step["title"] == "Test Step"
        assert step["status"] == "COMPLETED"
        assert step["evidence"]["artifact_path"] == "test.py"
        assert "behavior_test" in step["behaviors_cited"]
        assert "step_id" in step

    def test_rest_record_step(self, rest_adapter, checklist_id, actor_payload):
        payload = {
            "checklist_id": checklist_id,
            "title": "Test Step",
            "status": "COMPLETED",
            "evidence": {"artifact_path": "test.py"},
            "behaviors_cited": ["behavior_test"],
            "actor": actor_payload,
        }
        step = rest_adapter.record_step(payload)

        assert step["title"] == "Test Step"
        assert step["status"] == "COMPLETED"

    def test_mcp_record_step(self, mcp_adapter, checklist_id, actor_payload):
        payload = {
            "checklist_id": checklist_id,
            "title": "Test Step",
            "status": "COMPLETED",
            "evidence": {"artifact_path": "test.py"},
            "behaviors_cited": ["behavior_test"],
            "actor": actor_payload,
        }
        step = mcp_adapter.record_step(payload)

        assert step["title"] == "Test Step"
        assert step["status"] == "COMPLETED"


class TestValidationParity:
    """Verify checklist validation works consistently across all surfaces."""

    @pytest.fixture
    def checklist_with_steps(self, cli_adapter):
        """Create a checklist with multiple steps."""
        checklist_result = cli_adapter.create_checklist(
            title="Validation Test",
            description="",
            template_id=None,
            milestone="Milestone 1",
            compliance_category=["SOC2"],
            actor_id="test-actor",
            actor_role="STRATEGIST",
        )
        checklist_id = checklist_result["checklist_id"]

        # Add completed step
        cli_adapter.record_step(
            checklist_id=checklist_id,
            title="Completed Step",
            status="COMPLETED",
            evidence={},
            behaviors_cited=[],
            related_run_id=None,
            actor_id="test-actor",
            actor_role="STRATEGIST",
        )

        # Add pending step
        cli_adapter.record_step(
            checklist_id=checklist_id,
            title="Pending Step",
            status="PENDING",
            evidence={},
            behaviors_cited=[],
            related_run_id=None,
            actor_id="test-actor",
            actor_role="STRATEGIST",
        )

        return checklist_id

    def test_cli_validate(self, cli_adapter, checklist_with_steps):
        result = cli_adapter.validate_checklist(
            checklist_id=checklist_with_steps,
            actor_id="test-actor",
            actor_role="STRATEGIST",
        )

        assert result["valid"] is False  # Has pending step
        assert result["coverage_score"] == 0.5  # 1 of 2 completed
        assert "Pending Step" in result["missing_steps"]
        assert len(result["failed_steps"]) == 0

    def test_rest_validate(self, rest_adapter, checklist_with_steps, actor_payload):
        payload = {"checklist_id": checklist_with_steps, "actor": actor_payload}
        result = rest_adapter.validate_checklist(payload)

        assert result["valid"] is False
        assert result["coverage_score"] == 0.5

    def test_mcp_validate(self, mcp_adapter, checklist_with_steps, actor_payload):
        payload = {"checklist_id": checklist_with_steps, "actor": actor_payload}
        result = mcp_adapter.validate_checklist(payload)

        assert result["valid"] is False
        assert result["coverage_score"] == 0.5


class TestListChecklistsParity:
    """Verify listing operations work consistently across all surfaces."""

    @pytest.fixture
    def multiple_checklists(self, cli_adapter):
        """Create multiple checklists for filtering tests."""
        cli_adapter.create_checklist(
            title="Milestone 1 Checklist",
            description="",
            template_id=None,
            milestone="Milestone 1",
            compliance_category=["SOC2"],
            actor_id="test-actor",
            actor_role="STRATEGIST",
        )

        cli_adapter.create_checklist(
            title="Milestone 2 Checklist",
            description="",
            template_id=None,
            milestone="Milestone 2",
            compliance_category=["GDPR"],
            actor_id="test-actor",
            actor_role="STRATEGIST",
        )

    def test_cli_list_all(self, cli_adapter, multiple_checklists):
        results = cli_adapter.list_checklists()
        assert len(results) == 2

    def test_cli_list_filtered_by_milestone(self, cli_adapter, multiple_checklists):
        results = cli_adapter.list_checklists(milestone="Milestone 1")
        assert len(results) == 1
        assert results[0]["milestone"] == "Milestone 1"

    def test_rest_list(self, rest_adapter, multiple_checklists):
        results = rest_adapter.list_checklists({})
        assert len(results) == 2

    def test_mcp_list(self, mcp_adapter, multiple_checklists):
        results = mcp_adapter.list_checklists({})
        assert len(results) == 2


class TestErrorHandling:
    """Verify error handling is consistent across surfaces."""

    def test_cli_get_nonexistent_checklist(self, cli_adapter):
        # Use a valid UUID format that won't exist in the database
        nonexistent_uuid = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(Exception) as exc_info:
            cli_adapter.get_checklist(nonexistent_uuid)
        assert "not found" in str(exc_info.value).lower()

    def test_rest_get_nonexistent_checklist(self, rest_adapter):
        # Use a valid UUID format that won't exist in the database
        nonexistent_uuid = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(Exception) as exc_info:
            rest_adapter.get_checklist(nonexistent_uuid)
        assert "not found" in str(exc_info.value).lower()

    def test_mcp_get_nonexistent_checklist(self, mcp_adapter):
        # Use a valid UUID format that won't exist in the database
        nonexistent_uuid = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(Exception) as exc_info:
            mcp_adapter.get_checklist(nonexistent_uuid)
        assert "not found" in str(exc_info.value).lower()
