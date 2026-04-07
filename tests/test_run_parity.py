"""Parity tests for RunService across CLI/REST/MCP surfaces.

Validates that RunService operations produce consistent results
regardless of which surface invokes them (CLI, REST API, MCP tools).
"""

from __future__ import annotations

import os
from typing import Generator

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - psycopg2 is optional for lint environments
    psycopg2 = None
import pytest

from amprealize.action_contracts import Actor
from amprealize.adapters import (
    CLIRunServiceAdapter,
    RestRunServiceAdapter,
    MCPRunServiceAdapter,
)
from amprealize.run_service_postgres import PostgresRunService as RunService
from amprealize.run_service_postgres import RunNotFoundError
from amprealize.run_contracts import RunStatus


def _truncate_run_tables(dsn: str) -> None:
    """Remove all data from run tables to ensure test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, ["run_steps", "runs"])


def _seed_test_users(dsn: str) -> None:
    """Ensure test actor IDs exist in auth.users so FK constraints pass."""
    import psycopg2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for uid, email, name in [
                ("cli-user", "cli-user@example.com", "CLI User"),
                ("rest-user", "rest-user@example.com", "REST User"),
                ("mcp-user", "mcp-user@example.com", "MCP User"),
            ]:
                cur.execute(
                    """
                    INSERT INTO auth.users (id, email, display_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (uid, email, name),
                )
    finally:
        conn.close()


@pytest.fixture
def run_service() -> Generator[RunService, None, None]:
    """Create a fresh RunService backed by PostgreSQL for each test."""
    dsn = os.environ.get("AMPREALIZE_RUN_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_RUN_PG_DSN not set; skipping PostgreSQL parity tests")

    _truncate_run_tables(dsn)
    _seed_test_users(dsn)
    service = RunService(dsn=dsn)

    try:
        yield service
    finally:
        _truncate_run_tables(dsn)
        if hasattr(service, "_pool") and service._pool:
            service._pool.close()


@pytest.fixture
def cli_adapter(run_service: RunService) -> CLIRunServiceAdapter:
    """CLI adapter for testing."""
    return CLIRunServiceAdapter(run_service)


@pytest.fixture
def rest_adapter(run_service: RunService) -> RestRunServiceAdapter:
    """REST adapter for testing."""
    return RestRunServiceAdapter(run_service)


@pytest.fixture
def mcp_adapter(run_service: RunService) -> MCPRunServiceAdapter:
    """MCP adapter for testing."""
    return MCPRunServiceAdapter(run_service)


class TestCreateRunParity:
    """Verify create run parity across surfaces."""

    def test_cli_create_run(self, cli_adapter: CLIRunServiceAdapter):
        result = cli_adapter.create_run(
            actor_id="cli-user",
            actor_role="STRATEGIST",
            workflow_id="workflow-1",
            workflow_name="Test Workflow",
            behavior_ids=["b1", "b2"],
            metadata={"source": "cli"},
            initial_message="Starting test run",
        )

        assert result["run_id"]
        assert result["status"] == RunStatus.PENDING
        assert result["workflow_id"] == "workflow-1"
        assert result["workflow_name"] == "Test Workflow"
        assert result["behavior_ids"] == ["b1", "b2"]
        assert result["progress_pct"] == 0.0
        assert result["message"] == "Starting test run"
        assert result["actor"]["id"] == "cli-user"
        assert result["actor"]["surface"] == "cli"

    def test_rest_create_run(self, rest_adapter: RestRunServiceAdapter):
        payload = {
            "actor": {"id": "rest-user", "role": "TEACHER", "surface": "api"},
            "template_id": "template-1",
            "template_name": "Test Template",
            "behavior_ids": ["b3", "b4"],
            "metadata": {"source": "rest"},
            "initial_message": "REST test run",
        }
        result = rest_adapter.create_run(payload)

        assert result["run_id"]
        assert result["status"] == RunStatus.PENDING
        assert result["template_id"] == "template-1"
        assert result["template_name"] == "Test Template"
        assert result["behavior_ids"] == ["b3", "b4"]
        assert result["message"] == "REST test run"
        assert result["actor"]["id"] == "rest-user"
        assert result["actor"]["surface"] == "api"

    def test_mcp_create_run(self, mcp_adapter: MCPRunServiceAdapter):
        payload = {
            "actor": {"id": "mcp-user", "role": "STUDENT", "surface": "mcp"},
            "workflow_id": "workflow-2",
            "behavior_ids": ["b5"],
            "metadata": {"source": "mcp"},
        }
        result = mcp_adapter.create(payload)

        assert result["run_id"]
        assert result["status"] == RunStatus.PENDING
        assert result["workflow_id"] == "workflow-2"
        assert result["behavior_ids"] == ["b5"]
        assert result["actor"]["surface"] == "mcp"


class TestGetRunParity:
    """Verify get run parity across surfaces."""

    def test_cli_get_run(self, cli_adapter: CLIRunServiceAdapter):
        # Create a run first
        created = cli_adapter.create_run(
            actor_id="cli-user",
            actor_role="STRATEGIST",
            workflow_id="workflow-1",
        )
        run_id = created["run_id"]

        # Get the run
        result = cli_adapter.get_run(run_id)

        assert result["run_id"] == run_id
        assert result["status"] == RunStatus.PENDING
        assert result["workflow_id"] == "workflow-1"

    def test_rest_get_run(self, rest_adapter: RestRunServiceAdapter):
        # Create via REST
        payload = {
            "actor": {"id": "rest-user", "role": "TEACHER", "surface": "REST_API"},
            "template_id": "template-1",
        }
        created = rest_adapter.create_run(payload)
        run_id = created["run_id"]

        # Get the run
        result = rest_adapter.get_run(run_id)

        assert result["run_id"] == run_id
        assert result["template_id"] == "template-1"

    def test_mcp_get_run(self, mcp_adapter: MCPRunServiceAdapter):
        # Create via MCP
        payload = {
            "actor": {"id": "mcp-user", "role": "STUDENT", "surface": "MCP"},
            "workflow_id": "workflow-2",
        }
        created = mcp_adapter.create(payload)
        run_id = created["run_id"]

        # Get the run
        result = mcp_adapter.get(run_id)

        assert result["run_id"] == run_id
        assert result["workflow_id"] == "workflow-2"


class TestListRunsParity:
    """Verify list runs parity across surfaces."""

    def test_cli_list_runs(self, cli_adapter: CLIRunServiceAdapter):
        # Create two runs
        cli_adapter.create_run(
            actor_id="cli-user",
            actor_role="STRATEGIST",
            workflow_id="workflow-1",
        )
        cli_adapter.create_run(
            actor_id="cli-user",
            actor_role="STRATEGIST",
            workflow_id="workflow-2",
        )

        # List all
        result = cli_adapter.list_runs()
        assert len(result) == 2

        # Filter by workflow
        result = cli_adapter.list_runs(workflow_id="workflow-1")
        assert len(result) == 1
        assert result[0]["workflow_id"] == "workflow-1"

    def test_rest_list_runs(self, rest_adapter: RestRunServiceAdapter):
        # Create runs
        payload1 = {
            "actor": {"id": "rest-user", "role": "TEACHER", "surface": "REST_API"},
            "template_id": "template-1",
        }
        payload2 = {
            "actor": {"id": "rest-user", "role": "TEACHER", "surface": "REST_API"},
            "template_id": "template-2",
        }
        rest_adapter.create_run(payload1)
        rest_adapter.create_run(payload2)

        # List all
        result = rest_adapter.list_runs({})
        assert len(result) == 2

        # Filter by template
        result = rest_adapter.list_runs({"template_id": "template-1"})
        assert len(result) == 1
        assert result[0]["template_id"] == "template-1"

    def test_mcp_list_runs(self, mcp_adapter: MCPRunServiceAdapter):
        # Create runs
        payload1 = {
            "actor": {"id": "mcp-user", "role": "STUDENT", "surface": "MCP"},
            "workflow_id": "workflow-1",
        }
        payload2 = {
            "actor": {"id": "mcp-user", "role": "STUDENT", "surface": "MCP"},
            "workflow_id": "workflow-2",
        }
        mcp_adapter.create(payload1)
        mcp_adapter.create(payload2)

        # List all
        result = mcp_adapter.list({})
        assert len(result) == 2


class TestUpdateRunParity:
    """Verify update run parity across surfaces."""

    def test_cli_update_run(self, cli_adapter: CLIRunServiceAdapter):
        # Create a run
        created = cli_adapter.create_run(
            actor_id="cli-user",
            actor_role="STRATEGIST",
            workflow_id="workflow-1",
        )
        run_id = created["run_id"]

        # Update progress
        result = cli_adapter.update_run(
            run_id,
            status=RunStatus.RUNNING,
            progress_pct=50.0,
            message="Halfway done",
            step_id="step-1",
            step_name="Processing",
        )

        assert result["run_id"] == run_id
        assert result["status"] == RunStatus.RUNNING
        assert result["progress_pct"] == 50.0
        assert result["message"] == "Halfway done"
        assert result["current_step"] == "step-1"

    def test_rest_update_run(self, rest_adapter: RestRunServiceAdapter):
        # Create via REST
        payload = {
            "actor": {"id": "rest-user", "role": "TEACHER", "surface": "REST_API"},
            "template_id": "template-1",
        }
        created = rest_adapter.create_run(payload)
        run_id = created["run_id"]

        # Update
        update_payload = {
            "status": RunStatus.RUNNING,
            "progress_pct": 75.0,
            "message": "Almost done",
        }
        result = rest_adapter.update_run(run_id, update_payload)

        assert result["status"] == RunStatus.RUNNING
        assert result["progress_pct"] == 75.0
        assert result["message"] == "Almost done"

    def test_mcp_update_run(self, mcp_adapter: MCPRunServiceAdapter):
        # Create via MCP
        payload = {
            "actor": {"id": "mcp-user", "role": "STUDENT", "surface": "MCP"},
            "workflow_id": "workflow-1",
        }
        created = mcp_adapter.create(payload)
        run_id = created["run_id"]

        # Update
        update_payload = {
            "status": RunStatus.RUNNING,
            "progress_pct": 25.0,
        }
        result = mcp_adapter.update(run_id, update_payload)

        assert result["status"] == RunStatus.RUNNING
        assert result["progress_pct"] == 25.0


class TestCompleteRunParity:
    """Verify complete run parity across surfaces."""

    def test_cli_complete_run(self, cli_adapter: CLIRunServiceAdapter):
        # Create and complete
        created = cli_adapter.create_run(
            actor_id="cli-user",
            actor_role="STRATEGIST",
            workflow_id="workflow-1",
        )
        run_id = created["run_id"]

        result = cli_adapter.complete_run(
            run_id,
            status=RunStatus.COMPLETED,
            outputs={"result": "success"},
            message="Finished successfully",
        )

        assert result["status"] == RunStatus.COMPLETED
        assert result["progress_pct"] == 100.0
        assert result["outputs"]["result"] == "success"
        assert result["message"] == "Finished successfully"
        assert result["completed_at"] is not None
        assert result["duration_ms"] is not None

    def test_rest_complete_run(self, rest_adapter: RestRunServiceAdapter):
        # Create via REST
        payload = {
            "actor": {"id": "rest-user", "role": "TEACHER", "surface": "REST_API"},
            "template_id": "template-1",
        }
        created = rest_adapter.create_run(payload)
        run_id = created["run_id"]

        # Complete
        completion_payload = {
            "status": RunStatus.FAILED,
            "error": "Test error",
            "message": "Run failed",
        }
        result = rest_adapter.complete_run(run_id, completion_payload)

        assert result["status"] == RunStatus.FAILED
        assert result["error"] == "Test error"
        assert result["completed_at"] is not None

    def test_mcp_complete_run(self, mcp_adapter: MCPRunServiceAdapter):
        # Create via MCP
        payload = {
            "actor": {"id": "mcp-user", "role": "STUDENT", "surface": "MCP"},
            "workflow_id": "workflow-1",
        }
        created = mcp_adapter.create(payload)
        run_id = created["run_id"]

        # Complete
        completion_payload = {
            "status": RunStatus.COMPLETED,
            "outputs": {"data": "test"},
        }
        result = mcp_adapter.complete(run_id, completion_payload)

        assert result["status"] == RunStatus.COMPLETED
        assert result["outputs"]["data"] == "test"


class TestCancelRunParity:
    """Verify cancel run parity across surfaces."""

    def test_cli_cancel_run(self, cli_adapter: CLIRunServiceAdapter):
        # Create and cancel
        created = cli_adapter.create_run(
            actor_id="cli-user",
            actor_role="STRATEGIST",
            workflow_id="workflow-1",
        )
        run_id = created["run_id"]

        result = cli_adapter.cancel_run(run_id, reason="User requested")

        assert result["status"] == RunStatus.CANCELLED
        assert result["message"] == "User requested"
        assert result["completed_at"] is not None

    def test_rest_cancel_run(self, rest_adapter: RestRunServiceAdapter):
        # Create via REST
        payload = {
            "actor": {"id": "rest-user", "role": "TEACHER", "surface": "REST_API"},
            "template_id": "template-1",
        }
        created = rest_adapter.create_run(payload)
        run_id = created["run_id"]

        # Cancel
        result = rest_adapter.cancel_run(run_id, {"reason": "Timeout"})

        assert result["status"] == RunStatus.CANCELLED
        assert result["message"] == "Timeout"

    def test_mcp_cancel_run(self, mcp_adapter: MCPRunServiceAdapter):
        # Create via MCP
        payload = {
            "actor": {"id": "mcp-user", "role": "STUDENT", "surface": "MCP"},
            "workflow_id": "workflow-1",
        }
        created = mcp_adapter.create(payload)
        run_id = created["run_id"]

        # Cancel
        result = mcp_adapter.cancel(run_id, {"reason": "Error"})

        assert result["status"] == RunStatus.CANCELLED


class TestRunNotFoundParity:
    """Verify error handling parity across surfaces."""

    def test_cli_get_nonexistent_run(self, cli_adapter: CLIRunServiceAdapter):
        with pytest.raises(RunNotFoundError):
            cli_adapter.get_run("00000000-0000-0000-0000-000000000001")

    def test_rest_get_nonexistent_run(self, rest_adapter: RestRunServiceAdapter):
        with pytest.raises(RunNotFoundError):
            rest_adapter.get_run("00000000-0000-0000-0000-000000000002")

    def test_mcp_get_nonexistent_run(self, mcp_adapter: MCPRunServiceAdapter):
        with pytest.raises(RunNotFoundError):
            mcp_adapter.get("00000000-0000-0000-0000-000000000003")


class TestStepTrackingParity:
    """Verify step tracking works consistently across surfaces."""

    def test_step_tracking(self, cli_adapter: CLIRunServiceAdapter):
        # Create run
        created = cli_adapter.create_run(
            actor_id="cli-user",
            actor_role="STRATEGIST",
            workflow_id="workflow-1",
        )
        run_id = created["run_id"]

        # Add first step
        cli_adapter.update_run(
            run_id,
            step_id="step-1",
            step_name="Initialize",
            step_status=RunStatus.RUNNING,
            progress_pct=10.0,
        )

        # Add second step
        cli_adapter.update_run(
            run_id,
            step_id="step-2",
            step_name="Process",
            step_status=RunStatus.RUNNING,
            progress_pct=50.0,
        )

        # Get run and verify steps
        result = cli_adapter.get_run(run_id)
        assert len(result["steps"]) == 2
        assert result["steps"][0]["step_id"] == "step-1"
        assert result["steps"][0]["name"] == "Initialize"
        assert result["steps"][1]["step_id"] == "step-2"
        assert result["steps"][1]["name"] == "Process"
