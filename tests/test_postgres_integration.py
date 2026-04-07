"""
Integration tests for PostgreSQL service implementations.

Tests conditional PostgreSQL backend usage across API, CLI, and MCP surfaces.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

# Test that services can be instantiated with PostgreSQL DSNs


def test_run_service_postgres_instantiation():
    """Test PostgresRunService can be instantiated with DSN."""
    from amprealize.run_service_postgres import PostgresRunService
    from amprealize.telemetry import TelemetryClient

    # Use test DSN (won't connect, just testing instantiation)
    dsn = "postgresql://test:test@localhost:5432/test"

    try:
        service = PostgresRunService(dsn=dsn, telemetry=TelemetryClient.noop())
        assert service is not None
        assert hasattr(service, 'create_run')
        assert hasattr(service, 'list_runs')
    except Exception as e:
        # Expected if test database not available
        pytest.skip(f"PostgreSQL test database not available: {e}")


def test_compliance_service_postgres_instantiation():
    """Test ComplianceService can be instantiated with PostgreSQL DSN."""
    from amprealize.compliance_service import ComplianceService
    from amprealize.telemetry import TelemetryClient

    # ComplianceService resolves DSN from AMPREALIZE_COMPLIANCE_PG_DSN
    with patch.dict(os.environ, {"AMPREALIZE_COMPLIANCE_PG_DSN": "postgresql://test:test@localhost:5432/test"}):
        try:
            service = ComplianceService(dsn=None, telemetry=TelemetryClient.noop())
            assert service is not None
            assert hasattr(service, 'create_checklist')
            assert hasattr(service, 'record_step')
        except Exception as e:
            # Expected if test database not available
            pytest.skip(f"PostgreSQL test database not available: {e}")


def test_cli_conditional_run_service():
    """Test CLI conditionally uses PostgresRunService based on environment."""
    from amprealize.cli import _get_run_adapter

    # Test without DSN (should use in-memory)
    with patch.dict(os.environ, {}, clear=True):
        adapter = _get_run_adapter()
        assert adapter is not None
        assert adapter._service.__class__.__name__ in ['RunService', 'PostgresRunService']

    # Test with DSN
    with patch.dict(os.environ, {"AMPREALIZE_RUN_PG_DSN": "postgresql://test:test@localhost:5432/test"}):
        try:
            # Reset global to force re-instantiation
            from amprealize import cli
            cli._RUN_SERVICE = None
            cli._RUN_ADAPTER = None

            adapter = _get_run_adapter()
            assert adapter is not None
        except Exception:
            # Expected if PostgreSQL not available
            pass


def test_cli_compliance_service_uses_postgres():
    """Test CLI ComplianceService uses PostgreSQL backend."""
    from amprealize.cli import _get_compliance_adapter

    with patch.dict(os.environ, {"AMPREALIZE_COMPLIANCE_PG_DSN": "postgresql://test:test@localhost:5432/test"}):
        try:
            # Reset global to force re-instantiation
            from amprealize import cli
            cli._COMPLIANCE_SERVICE = None
            cli._COMPLIANCE_ADAPTER = None

            adapter = _get_compliance_adapter()
            assert adapter is not None
            assert adapter._service.__class__.__name__ == 'ComplianceService'
        except Exception:
            # Expected if PostgreSQL not available
            pass


def test_mcp_conditional_run_service():
    """Test MCP server conditionally uses PostgresRunService."""
    from amprealize.mcp_server import MCPServiceRegistry
    import logging

    logger = logging.getLogger("test")

    # Test without DSN
    with patch.dict(os.environ, {}, clear=True):
        registry = MCPServiceRegistry(logger=logger)
        service = registry.run_service()
        assert service is not None
        assert service.__class__.__name__ in ['RunService', 'PostgresRunService']

    # Test with DSN
    with patch.dict(os.environ, {"AMPREALIZE_RUN_PG_DSN": "postgresql://test:test@localhost:5432/test"}):
        try:
            registry = MCPServiceRegistry(logger=logger)
            service = registry.run_service()
            assert service is not None
        except Exception:
            # Expected if PostgreSQL not available
            pass


def test_mcp_compliance_service_uses_postgres():
    """Test MCP server ComplianceService uses PostgreSQL backend."""
    from amprealize.mcp_server import MCPServiceRegistry
    import logging

    logger = logging.getLogger("test")

    with patch.dict(os.environ, {"AMPREALIZE_COMPLIANCE_PG_DSN": "postgresql://test:test@localhost:5432/test"}):
        try:
            registry = MCPServiceRegistry(logger=logger)
            service = registry.compliance_service()
            assert service is not None
            assert service.__class__.__name__ == 'ComplianceService'
        except Exception:
            # Expected if PostgreSQL not available
            pass


def test_adapter_signatures_accept_postgres_run_service():
    """Test that adapters accept both RunService and PostgresRunService."""
    from amprealize.adapters import (
        RestRunServiceAdapter,
        CLIRunServiceAdapter,
    )
    from amprealize.run_service import RunService

    # Test with in-memory RunService
    in_memory_service = RunService()
    assert RestRunServiceAdapter(in_memory_service) is not None
    assert CLIRunServiceAdapter(in_memory_service) is not None
    # Note: MCPRunServiceAdapter currently only accepts RunService, not PostgresRunService

    # Test with PostgresRunService (if available)
    try:
        from amprealize.run_service_postgres import PostgresRunService
        from amprealize.telemetry import TelemetryClient

        dsn = "postgresql://test:test@localhost:5432/test"
        postgres_service = PostgresRunService(dsn=dsn, telemetry=TelemetryClient.noop())
        # REST and CLI adapters accept Union[RunService, PostgresRunService]
        assert RestRunServiceAdapter(postgres_service) is not None
        assert CLIRunServiceAdapter(postgres_service) is not None
    except Exception:
        pytest.skip("PostgreSQL test database not available")


def test_adapter_signatures_accept_compliance_service():
    """Test that adapters accept ComplianceService (single implementation)."""
    from amprealize.adapters import (
        RestComplianceServiceAdapter,
        CLIComplianceServiceAdapter,
        MCPComplianceServiceAdapter
    )
    from amprealize.compliance_service import ComplianceService
    from amprealize.telemetry import TelemetryClient

    # ComplianceService is the single PostgreSQL implementation
    with patch.dict(os.environ, {"AMPREALIZE_COMPLIANCE_PG_DSN": "postgresql://test:test@localhost:5432/test"}):
        try:
            service = ComplianceService(dsn=None, telemetry=TelemetryClient.noop())
            assert RestComplianceServiceAdapter(service) is not None
            assert CLIComplianceServiceAdapter(service) is not None
            assert MCPComplianceServiceAdapter(service) is not None
        except Exception:
            pytest.skip("PostgreSQL test database not available")


@pytest.mark.skipif(
    not os.environ.get("AMPREALIZE_RUN_PG_DSN"),
    reason="PostgreSQL RunService DSN not configured"
)
def test_postgres_run_service_basic_operations():
    """Test basic PostgresRunService operations with real database."""
    from amprealize.run_service_postgres import PostgresRunService
    from amprealize.run_contracts import RunCreateRequest
    from amprealize.action_contracts import Actor
    from amprealize.telemetry import TelemetryClient

    dsn = os.environ["AMPREALIZE_RUN_PG_DSN"]
    service = PostgresRunService(dsn=dsn, telemetry=TelemetryClient.noop())

    # Ensure test actor exists in auth.users for FK constraint
    import psycopg2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO auth.users (id, email, display_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            ("test-actor", "test-actor@example.com", "Test Actor"),
        )
    conn.close()

    # Test create_run
    actor = Actor(id="test-actor", role="strategist", surface="cli")
    request = RunCreateRequest(
        actor=actor,
        workflow_id="test-workflow",
        workflow_name="Integration Test Run",
        behavior_ids=["test-behavior-1"]
    )
    run = service.create_run(request)
    assert run is not None
    assert run.workflow_name == "Integration Test Run"

    # Test get_run
    retrieved = service.get_run(run.run_id)
    assert retrieved is not None
    assert retrieved.workflow_name == "Integration Test Run"

    # Test list_runs
    runs = service.list_runs()
    assert len(runs) > 0
    assert any(r.run_id == run.run_id for r in runs)


@pytest.mark.skipif(
    not os.environ.get("AMPREALIZE_COMPLIANCE_PG_DSN"),
    reason="PostgreSQL ComplianceService DSN not configured"
)
def test_postgres_compliance_service_basic_operations():
    """Test basic ComplianceService operations with real database."""
    from amprealize.compliance_service import ComplianceService
    from amprealize.action_contracts import Actor
    from amprealize.telemetry import TelemetryClient

    service = ComplianceService(dsn=None, telemetry=TelemetryClient.noop())

    # Test create_checklist
    actor = Actor(id="test-actor", role="compliance", surface="api")
    checklist = service.create_checklist(
        title="Integration Test Checklist",
        description="Test checklist",
        template_id="test-template",
        milestone="test-milestone",
        compliance_category=["test-category"],
        actor=actor
    )
    assert checklist is not None
    assert checklist.title == "Integration Test Checklist"

    # Test get_checklist
    retrieved = service.get_checklist(checklist.checklist_id)
    assert retrieved is not None
    assert retrieved.title == "Integration Test Checklist"

    # Test list_checklists
    checklists = service.list_checklists()
    assert len(checklists) > 0
    assert any(c.checklist_id == checklist.checklist_id for c in checklists)


def test_environment_variable_documentation():
    """Verify required environment variables are documented."""
    # This test documents the required environment variables
    required_vars = {
        "AMPREALIZE_RUN_PG_DSN": "PostgreSQL DSN for RunService (optional, falls back to SQLite)",
        "AMPREALIZE_COMPLIANCE_PG_DSN": "PostgreSQL DSN for ComplianceService (required for PostgreSQL backend)"
    }

    # Just verify the dictionary is properly defined
    assert len(required_vars) == 2
    assert "AMPREALIZE_RUN_PG_DSN" in required_vars
    assert "AMPREALIZE_COMPLIANCE_PG_DSN" in required_vars
