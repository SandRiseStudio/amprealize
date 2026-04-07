"""Parity tests for WorkflowService across CLI/REST/MCP surfaces.

Validates that WorkflowService operations produce consistent results
regardless of which surface invokes them (CLI, REST API, MCP tools).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Generator

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - psycopg2 optional for lint envs
    psycopg2 = None

import pytest

from amprealize.action_contracts import Actor
from amprealize.adapters import (
    CLIWorkflowServiceAdapter,
    RestWorkflowServiceAdapter,
    MCPWorkflowServiceAdapter,
)
from amprealize.workflow_service import WorkflowService


NONEXISTENT_TEMPLATE_ID = "00000000-0000-0000-0000-000000000001"


def _truncate_workflow_tables(dsn: str) -> None:
    """Clear workflow tables to maintain test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, ["workflow_runs", "workflow_templates"])


@pytest.fixture
def workflow_service() -> Generator[WorkflowService, None, None]:
    """Create a fresh PostgreSQL-backed WorkflowService for each test."""
    dsn = os.environ.get("AMPREALIZE_WORKFLOW_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_WORKFLOW_PG_DSN not set; skipping PostgreSQL parity tests")

    _truncate_workflow_tables(dsn)
    service = WorkflowService(dsn=dsn)

    try:
        yield service
    finally:
        _truncate_workflow_tables(dsn)
        conn = getattr(service, "_conn", None)
        if conn is not None and getattr(conn, "closed", 1) == 0:
            conn.close()


@pytest.fixture
def cli_adapter(workflow_service: WorkflowService) -> CLIWorkflowServiceAdapter:
    """CLI adapter for testing."""
    return CLIWorkflowServiceAdapter(workflow_service)


@pytest.fixture
def rest_adapter(workflow_service: WorkflowService) -> RestWorkflowServiceAdapter:
    """REST adapter for testing."""
    return RestWorkflowServiceAdapter(workflow_service)


@pytest.fixture
def mcp_adapter(workflow_service: WorkflowService) -> MCPWorkflowServiceAdapter:
    """MCP adapter for testing."""
    return MCPWorkflowServiceAdapter(workflow_service)


@pytest.fixture
def sample_steps() -> list[Dict[str, Any]]:
    """Sample workflow steps for testing."""
    return [
        {
            "step_id": "step-1",
            "name": "Analyze Request",
            "description": "Break down the request",
            "prompt_template": "Analyze: {{REQUEST}}\n{{BEHAVIORS}}",
            "behavior_injection_point": "{{BEHAVIORS}}",
            "required_behaviors": [],
            "validation_rules": {},
            "metadata": {}
        },
        {
            "step_id": "step-2",
            "name": "Execute Plan",
            "description": "Carry out the plan",
            "prompt_template": "Execute: {{PLAN}}\n{{BEHAVIORS}}",
            "behavior_injection_point": "{{BEHAVIORS}}",
            "required_behaviors": [],
            "validation_rules": {},
            "metadata": {}
        }
    ]


class TestCreateTemplateParity:
    """Verify create template parity across surfaces."""

    def test_cli_create_template(self, cli_adapter: CLIWorkflowServiceAdapter, sample_steps: list):
        result = cli_adapter.create_template(
            name="Test Template",
            description="Test description",
            role_focus="STRATEGIST",
            steps=sample_steps,
            tags=["test"],
            metadata={"source": "cli"},
            actor_id="cli-user",
            actor_role="STRATEGIST",
        )

        assert result["name"] == "Test Template"
        assert result["role_focus"] == "STRATEGIST"
        assert len(result["steps"]) == 2
        assert "test" in result["tags"]
        assert result["created_by"]["surface"] == "CLI"

    def test_rest_create_template(self, rest_adapter: RestWorkflowServiceAdapter, sample_steps: list):
        payload = {
            "name": "Test Template",
            "description": "Test description",
            "role_focus": "TEACHER",
            "steps": sample_steps,
            "tags": ["test"],
            "metadata": {"source": "rest"},
            "actor": {"id": "rest-user", "role": "TEACHER", "surface": "REST_API"}
        }
        result = rest_adapter.create_template(payload)

        assert result["name"] == "Test Template"
        assert result["role_focus"] == "TEACHER"
        assert len(result["steps"]) == 2
        assert "test" in result["tags"]
        assert result["created_by"]["surface"] == "REST_API"

    def test_mcp_create_template(self, mcp_adapter: MCPWorkflowServiceAdapter, sample_steps: list):
        payload = {
            "name": "Test Template",
            "description": "Test description",
            "role_focus": "STUDENT",
            "steps": sample_steps,
            "tags": ["test"],
            "metadata": {"source": "mcp"},
            "actor": {"id": "mcp-user", "role": "STUDENT", "surface": "MCP"}
        }
        result = mcp_adapter.create_template(payload)

        assert result["name"] == "Test Template"
        assert result["role_focus"] == "STUDENT"
        assert len(result["steps"]) == 2
        assert "test" in result["tags"]
        assert result["created_by"]["surface"] == "MCP"

    def test_surface_parity_create_template(
        self,
        cli_adapter: CLIWorkflowServiceAdapter,
        rest_adapter: RestWorkflowServiceAdapter,
        mcp_adapter: MCPWorkflowServiceAdapter,
        sample_steps: list
    ):
        """Verify all surfaces produce structurally consistent templates."""

        cli_result = cli_adapter.create_template(
            name="Parity Test",
            description="Testing parity",
            role_focus="MULTI_ROLE",
            steps=sample_steps,
            tags=["parity"],
            metadata={},
            actor_id="test-user",
            actor_role="STRATEGIST",
        )

        rest_payload = {
            "name": "Parity Test",
            "description": "Testing parity",
            "role_focus": "MULTI_ROLE",
            "steps": sample_steps,
            "tags": ["parity"],
            "metadata": {},
            "actor": {"id": "test-user", "role": "STRATEGIST", "surface": "REST_API"}
        }
        rest_result = rest_adapter.create_template(rest_payload)

        mcp_payload = {
            "name": "Parity Test",
            "description": "Testing parity",
            "role_focus": "MULTI_ROLE",
            "steps": sample_steps,
            "tags": ["parity"],
            "metadata": {},
            "actor": {"id": "test-user", "role": "STRATEGIST", "surface": "MCP"}
        }
        mcp_result = mcp_adapter.create_template(mcp_payload)

        # All should have same structure (different IDs/timestamps/surfaces OK)
        for result in [cli_result, rest_result, mcp_result]:
            assert result["name"] == "Parity Test"
            assert result["role_focus"] == "MULTI_ROLE"
            assert len(result["steps"]) == 2
            assert "parity" in result["tags"]
            assert "template_id" in result
            assert "created_at" in result


class TestListTemplatesParity:
    """Verify list templates parity across surfaces."""

    def test_cli_list_all(self, cli_adapter: CLIWorkflowServiceAdapter, sample_steps: list):
        # Create a template first
        cli_adapter.create_template(
            name="List Test",
            description="Test",
            role_focus="STRATEGIST",
            steps=sample_steps,
            tags=None,
            metadata=None,
            actor_id="test",
            actor_role="STRATEGIST",
        )

        result = cli_adapter.list_templates(role_focus=None, tags=None)
        assert len(result) >= 1
        assert any(t["name"] == "List Test" for t in result)
        assert any(t["created_by"]["surface"] == "CLI" for t in result if t["name"] == "List Test")

    def test_cli_list_filtered_by_role(self, cli_adapter: CLIWorkflowServiceAdapter, sample_steps: list):
        cli_adapter.create_template(
            name="Teacher Template",
            description="Test",
            role_focus="TEACHER",
            steps=sample_steps,
            tags=None,
            metadata=None,
            actor_id="test",
            actor_role="TEACHER",
        )

        result = cli_adapter.list_templates(role_focus="TEACHER", tags=None)
        assert len(result) >= 1
        assert all(t["role_focus"] == "TEACHER" for t in result)

    def test_rest_list(self, rest_adapter: RestWorkflowServiceAdapter, sample_steps: list):
        rest_adapter.create_template({
            "name": "REST List Test",
            "description": "Test",
            "role_focus": "STUDENT",
            "steps": sample_steps,
            "tags": ["rest"],
            "metadata": {},
            "actor": {"id": "test", "role": "STUDENT", "surface": "REST_API"}
        })

        result = rest_adapter.list_templates({"tags": ["rest"]})
        assert len(result) >= 1
        assert all("rest" in t.get("tags", []) for t in result)
        assert all(t["created_by"]["surface"] == "REST_API" for t in result)

    def test_mcp_list(self, mcp_adapter: MCPWorkflowServiceAdapter, sample_steps: list):
        mcp_adapter.create_template({
            "name": "MCP List Test",
            "description": "Test",
            "role_focus": "STRATEGIST",
            "steps": sample_steps,
            "tags": ["mcp"],
            "metadata": {},
            "actor": {"id": "test", "role": "STRATEGIST", "surface": "MCP"}
        })

        result = mcp_adapter.list_templates({"role_focus": "STRATEGIST"})
        assert len(result) >= 1
        assert all(t["created_by"]["surface"] == "MCP" for t in result)


class TestRunWorkflowParity:
    """Verify workflow execution parity across surfaces."""

    def test_cli_run_workflow(self, cli_adapter: CLIWorkflowServiceAdapter, sample_steps: list):
        # Create template
        template = cli_adapter.create_template(
            name="Run Test",
            description="Test",
            role_focus="STRATEGIST",
            steps=sample_steps,
            tags=None,
            metadata=None,
            actor_id="test",
            actor_role="STRATEGIST",
        )

        # Run it
        run = cli_adapter.run_workflow(
            template_id=template["template_id"],
            behavior_ids=None,
            metadata={"test": "cli"},
            actor_id="runner",
            actor_role="STRATEGIST",
        )

        assert run["template_id"] == template["template_id"]
        assert run["status"] == "PENDING"
        assert "run_id" in run
        assert run["metadata"]["test"] == "cli"
        assert run["actor"]["surface"] == "CLI"

    def test_rest_run_workflow(self, rest_adapter: RestWorkflowServiceAdapter, sample_steps: list):
        # Create template
        template = rest_adapter.create_template({
            "name": "REST Run Test",
            "description": "Test",
            "role_focus": "TEACHER",
            "steps": sample_steps,
            "tags": [],
            "metadata": {},
            "actor": {"id": "test", "role": "TEACHER", "surface": "REST_API"}
        })

        # Run it
        run = rest_adapter.run_workflow({
            "template_id": template["template_id"],
            "behavior_ids": [],
            "metadata": {"test": "rest"},
            "actor": {"id": "runner", "role": "TEACHER", "surface": "REST_API"}
        })

        assert run["template_id"] == template["template_id"]
        assert run["status"] == "PENDING"
        assert "run_id" in run
        assert run["actor"]["surface"] == "REST_API"

    def test_mcp_run_workflow(self, mcp_adapter: MCPWorkflowServiceAdapter, sample_steps: list):
        # Create template
        template = mcp_adapter.create_template({
            "name": "MCP Run Test",
            "description": "Test",
            "role_focus": "STUDENT",
            "steps": sample_steps,
            "tags": [],
            "metadata": {},
            "actor": {"id": "test", "role": "STUDENT", "surface": "MCP"}
        })

        # Run it
        run = mcp_adapter.run_workflow({
            "template_id": template["template_id"],
            "behavior_ids": [],
            "metadata": {"test": "mcp"},
            "actor": {"id": "runner", "role": "STUDENT", "surface": "MCP"}
        })

        assert run["template_id"] == template["template_id"]
        assert run["status"] == "PENDING"
        assert "run_id" in run
        assert run["actor"]["surface"] == "MCP"


class TestErrorHandling:
    """Verify error handling consistency across surfaces."""

    def test_cli_get_nonexistent_template(self, cli_adapter: CLIWorkflowServiceAdapter):
        result = cli_adapter.get_template(NONEXISTENT_TEMPLATE_ID)
        assert result is None

    def test_rest_get_nonexistent_template(self, rest_adapter: RestWorkflowServiceAdapter):
        result = rest_adapter.get_template(NONEXISTENT_TEMPLATE_ID)
        assert result is None

    def test_mcp_get_nonexistent_template(self, mcp_adapter: MCPWorkflowServiceAdapter):
        result = mcp_adapter.get_template(NONEXISTENT_TEMPLATE_ID)
        assert result is None

    def test_cli_run_nonexistent_template(self, cli_adapter: CLIWorkflowServiceAdapter):
        with pytest.raises(ValueError, match="Template not found"):
            cli_adapter.run_workflow(
                template_id=NONEXISTENT_TEMPLATE_ID,
                behavior_ids=None,
                metadata=None,
                actor_id="test",
                actor_role="STRATEGIST",
            )

    def test_rest_run_nonexistent_template(self, rest_adapter: RestWorkflowServiceAdapter):
        with pytest.raises(ValueError, match="Template not found"):
            rest_adapter.run_workflow({
                "template_id": NONEXISTENT_TEMPLATE_ID,
                "behavior_ids": [],
                "metadata": {},
                "actor": {"id": "test", "role": "STRATEGIST", "surface": "REST_API"}
            })

    def test_mcp_run_nonexistent_template(self, mcp_adapter: MCPWorkflowServiceAdapter):
        with pytest.raises(ValueError, match="Template not found"):
            mcp_adapter.run_workflow({
                "template_id": NONEXISTENT_TEMPLATE_ID,
                "behavior_ids": [],
                "metadata": {},
                "actor": {"id": "test", "role": "STRATEGIST", "surface": "MCP"}
            })
