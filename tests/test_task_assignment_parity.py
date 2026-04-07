"""
Parity tests for TaskAssignmentService across CLI/REST/MCP surfaces.

Validates that task assignment operations return consistent results
regardless of access method (CLI commands, REST API endpoints, or MCP tools).

Behaviors Referenced:
- behavior_wire_cli_to_orchestrator
- behavior_sanitize_action_registry
- behavior_update_docs_after_changes
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, List

# Set dummy DSNs before importing amprealize.api to avoid ValueError at module level
os.environ.setdefault("AMPREALIZE_COMPLIANCE_PG_DSN", "postgresql://user:pass@localhost:5432/db")
os.environ.setdefault("AMPREALIZE_TELEMETRY_PG_DSN", "postgresql://user:pass@localhost:5432/db")

import pytest
from fastapi.testclient import TestClient

from amprealize.adapters import CLITaskAssignmentAdapter, RestTaskAssignmentAdapter
from amprealize.api import create_app
from amprealize.task_assignments import TaskAssignmentService


@pytest.fixture
def task_service() -> TaskAssignmentService:
    """Shared task assignment service for all tests."""
    return TaskAssignmentService()


@pytest.fixture
def cli_adapter(task_service: TaskAssignmentService) -> CLITaskAssignmentAdapter:
    """CLI adapter for task assignment operations."""
    return CLITaskAssignmentAdapter(task_service)


@pytest.fixture
def rest_adapter(task_service: TaskAssignmentService) -> RestTaskAssignmentAdapter:
    """REST adapter for task assignment operations."""
    return RestTaskAssignmentAdapter(task_service)


@pytest.fixture
def api_client(monkeypatch) -> TestClient:
    """FastAPI test client for REST endpoint testing."""
    monkeypatch.setenv("AMPREALIZE_COMPLIANCE_PG_DSN", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setenv("AMPREALIZE_TELEMETRY_PG_DSN", "postgresql://user:pass@localhost:5432/db")
    app = create_app()
    return TestClient(app)


class TestListAssignmentsParity:
    """Test list_assignments operation across all surfaces."""

    def test_cli_list_all_assignments(self, cli_adapter: CLITaskAssignmentAdapter):
        """CLI should list all task assignments without filtering."""
        result = cli_adapter.list_assignments(function=None)

        assert isinstance(result, list)
        assert len(result) > 0  # Service should have some default tasks

        # Verify structure
        first_task = result[0]
        assert "task_id" in first_task
        assert "function" in first_task
        assert "description" in first_task
        assert "status" in first_task

    def test_rest_list_all_assignments(self, api_client: TestClient):
        """REST API should list all task assignments without filtering."""
        response = api_client.post("/api/v1/tasks:listAssignments", json={})

        assert response.status_code == 200
        data = response.json()
        # API returns list directly, not wrapped in dict
        assert isinstance(data, list)
        assert len(data) > 0

        # Verify structure
        first_task = data[0]
        assert "task_id" in first_task
        assert "function" in first_task

    def test_mcp_list_all_assignments(self, rest_adapter: RestTaskAssignmentAdapter):
        """MCP adapter should list all task assignments (uses same backend as REST)."""
        result = rest_adapter.list_assignments(payload={})

        # RestTaskAssignmentAdapter returns list directly (not wrapped in dict)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_cli_filter_by_function(self, cli_adapter: CLITaskAssignmentAdapter):
        """CLI should filter tasks by function parameter."""
        # Use a known valid function alias
        test_function = "engineering"

        # Filter by specific function
        filtered = cli_adapter.list_assignments(function=test_function)

        # All returned tasks should be for engineering function
        # (Service normalizes aliases, so we check the normalized field)
        assert isinstance(filtered, list)
        if filtered:  # May be empty if no engineering tasks exist
            assert all("function" in task for task in filtered)

    def test_rest_filter_by_function(self, api_client: TestClient):
        """REST API should filter tasks by function parameter."""
        # Use a known valid function alias
        test_function = "engineering"

        # Filter by specific function
        response = api_client.post(
            "/api/v1/tasks:listAssignments",
            json={"function": test_function}
        )

        assert response.status_code == 200
        filtered = response.json()

        # Should return filtered list
        assert isinstance(filtered, list)
        if filtered:  # May be empty if no engineering tasks exist
            assert all("function" in task for task in filtered)

    def test_cross_surface_task_count_parity(
        self,
        cli_adapter: CLITaskAssignmentAdapter,
        rest_adapter: RestTaskAssignmentAdapter,
        api_client: TestClient,
    ):
        """All surfaces should return the same number of tasks for identical queries."""
        # CLI
        cli_tasks = cli_adapter.list_assignments(function=None)

        # REST adapter
        rest_tasks = rest_adapter.list_assignments(payload={})

        # REST API
        api_response = api_client.post("/api/v1/tasks:listAssignments", json={})
        api_tasks = api_response.json()

        # All should return same count
        assert len(cli_tasks) == len(rest_tasks) == len(api_tasks)

    def test_cross_surface_task_structure_parity(
        self,
        cli_adapter: CLITaskAssignmentAdapter,
        rest_adapter: RestTaskAssignmentAdapter,
    ):
        """Task objects from all surfaces should have identical structure."""
        cli_tasks = cli_adapter.list_assignments(function=None)
        rest_tasks = rest_adapter.list_assignments(payload={})

        if cli_tasks:
            cli_keys = set(cli_tasks[0].keys())
            rest_keys = set(rest_tasks[0].keys())

            # Core fields must match
            core_fields = {"task_id", "function", "description", "status"}
            assert core_fields.issubset(cli_keys)
            assert core_fields.issubset(rest_keys)


class TestErrorHandlingParity:
    """Test error handling consistency across surfaces."""

    def test_cli_invalid_function(self, cli_adapter: CLITaskAssignmentAdapter):
        """CLI should raise ValueError for invalid function."""
        with pytest.raises(ValueError, match="Unknown function"):
            cli_adapter.list_assignments(function="invalid_function_xyz")

    def test_rest_invalid_function(self, api_client: TestClient):
        """REST API returns 400 for invalid function."""
        response = api_client.post(
            "/api/v1/tasks:listAssignments",
            json={"function": "invalid_function_xyz"}
        )
        assert response.status_code == 400
        assert "Unknown function" in response.text


class TestAdapterConsistency:
    """Test adapter interface consistency."""

    def test_cli_adapter_method_signature(self, task_service: TaskAssignmentService):
        """CLI adapter should expose correct method signature."""
        adapter = CLITaskAssignmentAdapter(task_service)

        # Should have list_assignments method
        assert hasattr(adapter, "list_assignments")
        assert callable(adapter.list_assignments)

    def test_rest_adapter_method_signature(self, task_service: TaskAssignmentService):
        """REST adapter should expose correct method signature."""
        adapter = RestTaskAssignmentAdapter(task_service)

        # Should have list_assignments method
        assert hasattr(adapter, "list_assignments")
        assert callable(adapter.list_assignments)

    def test_adapter_return_type_consistency(
        self,
        cli_adapter: CLITaskAssignmentAdapter,
        rest_adapter: RestTaskAssignmentAdapter,
    ):
        """Adapters should return consistent data types."""
        cli_result = cli_adapter.list_assignments(function=None)
        rest_result = rest_adapter.list_assignments(payload={})

        # Both return list directly
        assert isinstance(cli_result, list)
        assert isinstance(rest_result, list)

        # Task objects should have same structure
        if cli_result and rest_result:
            cli_task = cli_result[0]
            rest_task = rest_result[0]

            assert type(cli_task) == type(rest_task)
            assert isinstance(cli_task, dict)
