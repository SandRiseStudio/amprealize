"""Parity tests for AgentRegistryService across CLI/REST/MCP surfaces.

Validates that AgentRegistryService operations produce consistent results
regardless of which surface invokes them (CLI, REST API, MCP tools).

Following `behavior_validate_cross_surface_parity` from AGENTS.md.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - psycopg2 is optional for lint environments
    psycopg2 = None
import pytest

from amprealize.adapters import RestAgentRegistryAdapter

try:
    from amprealize.adapters import CLIAgentRegistryAdapter, MCPAgentRegistryAdapter
except ImportError:
    # CLI and MCP adapters not yet implemented — skip this module
    pytest.skip(
        "CLIAgentRegistryAdapter / MCPAgentRegistryAdapter not yet implemented",
        allow_module_level=True,
    )

from amprealize.agent_registry_service import (
    AgentRegistryService,
    AgentNotFoundError,
    AgentVersionNotFoundError,
)


NONEXISTENT_AGENT_ID = "00000000-0000-0000-0000-000000000001"


def _truncate_agent_registry_tables(dsn: str) -> None:
    """Remove all data from agent registry tables to ensure test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, ["agent_versions", "agents"])


@pytest.fixture
def agent_registry_service() -> Generator[AgentRegistryService, None, None]:
    """Create a fresh AgentRegistryService backed by PostgreSQL for each test."""
    dsn = os.environ.get("AMPREALIZE_POSTGRES_DSN") or os.environ.get("AMPREALIZE_BEHAVIOR_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_POSTGRES_DSN not set; skipping PostgreSQL parity tests")

    _truncate_agent_registry_tables(dsn)
    service = AgentRegistryService(dsn=dsn)

    try:
        yield service
    finally:
        _truncate_agent_registry_tables(dsn)
        conn = getattr(service, "_conn", None)
        if conn is not None and getattr(conn, "closed", 1) == 0:
            conn.close()


@pytest.fixture
def cli_adapter(agent_registry_service: AgentRegistryService) -> CLIAgentRegistryAdapter:
    """CLI adapter for testing."""
    return CLIAgentRegistryAdapter(agent_registry_service)


@pytest.fixture
def rest_adapter(agent_registry_service: AgentRegistryService) -> RestAgentRegistryAdapter:
    """REST adapter for testing."""
    return RestAgentRegistryAdapter(agent_registry_service)


@pytest.fixture
def mcp_adapter(agent_registry_service: AgentRegistryService) -> MCPAgentRegistryAdapter:
    """MCP adapter for testing."""
    return MCPAgentRegistryAdapter(agent_registry_service)


# ==============================================================================
# CREATE PARITY TESTS
# ==============================================================================


class TestCreateAgentParity:
    """Verify create agent parity across surfaces."""

    def test_cli_create_agent(self, cli_adapter: CLIAgentRegistryAdapter):
        """CLI: Create agent with all required fields."""
        result = cli_adapter.create_agent(
            name="CLI Test Agent",
            description="Agent created via CLI",
            role_alignment="STUDENT",
            mission="Help with CLI tasks",
            capabilities=["code_review", "testing"],
            default_behaviors=["behavior_use_raze_for_logging"],
            visibility="PRIVATE",
            actor_id="cli-user",
        )

        # Result should have nested structure: {"agent": {...}, "versions": [...]}
        assert "agent" in result
        assert "versions" in result
        assert result["agent"]["name"] == "CLI Test Agent"
        assert result["agent"]["description"] == "Agent created via CLI"
        assert result["agent"]["visibility"] == "PRIVATE"
        assert result["agent"]["status"] == "DRAFT"
        assert len(result["versions"]) == 1
        assert result["versions"][0]["version"] == "1.0.0"
        assert result["versions"][0]["role_alignment"] == "STUDENT"
        assert result["versions"][0]["mission"] == "Help with CLI tasks"
        assert "code_review" in result["versions"][0]["capabilities"]

    def test_rest_create_agent(self, rest_adapter: RestAgentRegistryAdapter):
        """REST: Create agent via API payload."""
        payload = {
            "name": "REST Test Agent",
            "description": "Agent created via REST API",
            "role_alignment": "TEACHER",
            "mission": "Help with API tasks",
            "capabilities": ["documentation", "examples"],
            "default_behaviors": ["behavior_update_docs_after_changes"],
            "visibility": "ORGANIZATION",
            "actor": {"id": "rest-user", "role": "admin", "surface": "api"}
        }
        result = rest_adapter.create_agent(payload)

        assert "agent" in result
        assert "versions" in result
        assert result["agent"]["name"] == "REST Test Agent"
        assert result["agent"]["description"] == "Agent created via REST API"
        assert result["agent"]["visibility"] == "ORGANIZATION"
        assert result["agent"]["status"] == "DRAFT"
        assert len(result["versions"]) == 1
        assert result["versions"][0]["role_alignment"] == "TEACHER"
        assert result["versions"][0]["mission"] == "Help with API tasks"

    def test_mcp_create_agent(self, mcp_adapter: MCPAgentRegistryAdapter):
        """MCP: Create agent via tool payload."""
        payload = {
            "name": "MCP Test Agent",
            "description": "Agent created via MCP",
            "role_alignment": "STRATEGIST",
            "mission": "Help with MCP tasks",
            "capabilities": ["analysis", "planning"],
            "default_behaviors": ["behavior_curate_behavior_handbook"],
            "visibility": "PUBLIC",
            "actor": {"id": "mcp-user", "role": "admin", "surface": "mcp"}
        }
        result = mcp_adapter.create_agent(payload)

        # MCP returns a different format optimized for tool output
        assert "agent_id" in result
        assert result["name"] == "MCP Test Agent"
        assert result["version"] == "1.0.0"
        assert result["status"] == "DRAFT"
        assert "_links" in result


class TestCreateAgentFieldParity:
    """Verify all surfaces produce consistent fields in created agents."""

    def test_all_surfaces_generate_uuid_agent_id(
        self,
        cli_adapter: CLIAgentRegistryAdapter,
        rest_adapter: RestAgentRegistryAdapter,
        mcp_adapter: MCPAgentRegistryAdapter,
    ):
        """All surfaces should generate valid UUID agent_id."""
        # CLI
        cli_result = cli_adapter.create_agent(
            name="UUID Test CLI", description="Test", role_alignment="STUDENT"
        )
        cli_id = cli_result["agent"]["agent_id"]
        uuid.UUID(cli_id)  # Validates UUID format

        # REST
        rest_result = rest_adapter.create_agent({
            "name": "UUID Test REST", "description": "Test", "role_alignment": "STUDENT",
            "actor": {"id": "test"}
        })
        rest_id = rest_result["agent"]["agent_id"]
        uuid.UUID(rest_id)

        # MCP
        mcp_result = mcp_adapter.create_agent({
            "name": "UUID Test MCP", "description": "Test", "role_alignment": "STUDENT",
            "actor": {"id": "test"}
        })
        mcp_id = mcp_result["agent_id"]
        uuid.UUID(mcp_id)

    def test_all_surfaces_set_timestamps(
        self,
        cli_adapter: CLIAgentRegistryAdapter,
        rest_adapter: RestAgentRegistryAdapter,
        mcp_adapter: MCPAgentRegistryAdapter,
    ):
        """All surfaces should set created_at and updated_at timestamps."""
        # CLI
        cli_result = cli_adapter.create_agent(
            name="Timestamp Test CLI", description="Test", role_alignment="STUDENT"
        )
        assert "created_at" in cli_result["agent"]
        assert "updated_at" in cli_result["agent"]

        # REST
        rest_result = rest_adapter.create_agent({
            "name": "Timestamp Test REST", "description": "Test", "role_alignment": "STUDENT",
            "actor": {"id": "test"}
        })
        assert "created_at" in rest_result["agent"]
        assert "updated_at" in rest_result["agent"]


# ==============================================================================
# LIST PARITY TESTS
# ==============================================================================


class TestListAgentsParity:
    """Verify list agents parity across surfaces."""

    def test_cli_list_all(self, cli_adapter: CLIAgentRegistryAdapter):
        """CLI: List all agents."""
        # Create some test agents
        cli_adapter.create_agent(name="List Test 1", description="Test", role_alignment="STUDENT")
        cli_adapter.create_agent(name="List Test 2", description="Test", role_alignment="TEACHER")

        result = cli_adapter.list_agents()

        assert isinstance(result, list)
        assert len(result) >= 2
        # list_agents returns [{"agent": {...}, "active_version": {...}}, ...]
        names = [a["agent"]["name"] for a in result]
        assert "List Test 1" in names
        assert "List Test 2" in names

    def test_rest_list_all(self, rest_adapter: RestAgentRegistryAdapter):
        """REST: List all agents."""
        # Create some test agents
        rest_adapter.create_agent({
            "name": "REST List Test 1", "description": "Test", "role_alignment": "STUDENT",
            "actor": {"id": "test"}
        })
        rest_adapter.create_agent({
            "name": "REST List Test 2", "description": "Test", "role_alignment": "TEACHER",
            "actor": {"id": "test"}
        })

        result = rest_adapter.list_agents()

        assert isinstance(result, list)
        assert len(result) >= 2

    def test_mcp_list_all(self, mcp_adapter: MCPAgentRegistryAdapter):
        """MCP: List all agents."""
        # Create some test agents
        mcp_adapter.create_agent({
            "name": "MCP List Test 1", "description": "Test", "role_alignment": "STUDENT",
            "actor": {"id": "test"}
        })
        mcp_adapter.create_agent({
            "name": "MCP List Test 2", "description": "Test", "role_alignment": "TEACHER",
            "actor": {"id": "test"}
        })

        result = mcp_adapter.list_agents({})

        assert "agents" in result
        assert "count" in result
        assert result["count"] >= 2
        assert "_links" in result

    def test_list_filtered_by_status(
        self,
        cli_adapter: CLIAgentRegistryAdapter,
        rest_adapter: RestAgentRegistryAdapter,
        mcp_adapter: MCPAgentRegistryAdapter,
    ):
        """All surfaces should filter by status consistently."""
        # Create a draft agent
        cli_adapter.create_agent(name="Status Filter Test", description="Test", role_alignment="STUDENT")

        # CLI - list_agents returns [{"agent": {...}, "active_version": {...}}, ...]
        cli_result = cli_adapter.list_agents(status="DRAFT")
        assert all(a["agent"]["status"] == "DRAFT" for a in cli_result)

        # REST - same nested structure
        rest_result = rest_adapter.list_agents({"status": "DRAFT"})
        assert all(a["agent"]["status"] == "DRAFT" for a in rest_result)

        # MCP - agents list contains nested {"agent": {...}, "active_version": {...}}
        mcp_result = mcp_adapter.list_agents({"status": "DRAFT"})
        assert all(a["agent"]["status"] == "DRAFT" for a in mcp_result["agents"])


# ==============================================================================
# GET PARITY TESTS
# ==============================================================================


class TestGetAgentParity:
    """Verify get agent parity across surfaces."""

    def test_cli_get_agent(self, cli_adapter: CLIAgentRegistryAdapter):
        """CLI: Get agent by ID."""
        created = cli_adapter.create_agent(
            name="Get Test Agent", description="Test", role_alignment="STUDENT"
        )
        agent_id = created["agent"]["agent_id"]

        result = cli_adapter.get_agent(agent_id)

        assert "agent" in result
        assert "versions" in result
        assert result["agent"]["agent_id"] == agent_id
        assert result["agent"]["name"] == "Get Test Agent"

    def test_rest_get_agent(self, rest_adapter: RestAgentRegistryAdapter):
        """REST: Get agent by ID."""
        created = rest_adapter.create_agent({
            "name": "REST Get Test", "description": "Test", "role_alignment": "TEACHER",
            "actor": {"id": "test"}
        })
        agent_id = created["agent"]["agent_id"]

        result = rest_adapter.get_agent(agent_id)

        assert "agent" in result
        assert "versions" in result
        assert result["agent"]["agent_id"] == agent_id

    def test_mcp_get_agent(self, mcp_adapter: MCPAgentRegistryAdapter):
        """MCP: Get agent by ID."""
        created = mcp_adapter.create_agent({
            "name": "MCP Get Test", "description": "Test", "role_alignment": "STRATEGIST",
            "actor": {"id": "test"}
        })
        agent_id = created["agent_id"]

        result = mcp_adapter.get_agent({"agent_id": agent_id})

        assert "agent" in result
        assert "versions" in result
        assert result["agent"]["agent_id"] == agent_id


class TestGetNonexistentAgentParity:
    """Verify error handling for nonexistent agents across surfaces."""

    def test_cli_get_nonexistent(self, cli_adapter: CLIAgentRegistryAdapter):
        """CLI: Get nonexistent agent raises error."""
        with pytest.raises(AgentNotFoundError):
            cli_adapter.get_agent(NONEXISTENT_AGENT_ID)

    def test_rest_get_nonexistent(self, rest_adapter: RestAgentRegistryAdapter):
        """REST: Get nonexistent agent raises error."""
        with pytest.raises(AgentNotFoundError):
            rest_adapter.get_agent(NONEXISTENT_AGENT_ID)

    def test_mcp_get_nonexistent(self, mcp_adapter: MCPAgentRegistryAdapter):
        """MCP: Get nonexistent agent raises error."""
        with pytest.raises(AgentNotFoundError):
            mcp_adapter.get_agent({"agent_id": NONEXISTENT_AGENT_ID})


# ==============================================================================
# SEARCH PARITY TESTS
# ==============================================================================


class TestSearchAgentsParity:
    """Verify search agents parity across surfaces."""

    def test_cli_search(self, cli_adapter: CLIAgentRegistryAdapter):
        """CLI: Search agents by query."""
        cli_adapter.create_agent(
            name="Searchable Agent CLI",
            description="An agent for testing search",
            role_alignment="STUDENT",
            capabilities=["code_review"],
            visibility="PUBLIC",  # Make visible for search
        )

        result = cli_adapter.search_agents(query="searchable", limit=10)

        assert isinstance(result, list)
        assert len(result) >= 1
        # Search returns [{"agent": {...}, "active_version": {...}, "score": ...}, ...]
        assert any("searchable" in a["agent"]["name"].lower() for a in result)

    def test_rest_search(self, rest_adapter: RestAgentRegistryAdapter):
        """REST: Search agents by query."""
        rest_adapter.create_agent({
            "name": "Searchable Agent REST",
            "description": "An agent for testing search",
            "role_alignment": "TEACHER",
            "capabilities": ["documentation"],
            "visibility": "PUBLIC",  # Make visible for search
            "actor": {"id": "test"}
        })

        result = rest_adapter.search_agents({"query": "searchable"})

        assert isinstance(result, list)
        assert len(result) >= 1

    def test_mcp_search(self, mcp_adapter: MCPAgentRegistryAdapter):
        """MCP: Search agents by query."""
        mcp_adapter.create_agent({
            "name": "Searchable Agent MCP",
            "description": "An agent for testing search",
            "role_alignment": "STRATEGIST",
            "capabilities": ["analysis"],
            "visibility": "PUBLIC",  # Make visible for search
            "actor": {"id": "test"}
        })

        result = mcp_adapter.search_agents({"query": "searchable"})

        assert "results" in result
        assert "count" in result
        assert result["count"] >= 1


class TestSearchFiltersParity:
    """Verify search filters work consistently across surfaces."""

    def test_search_by_role_alignment(
        self,
        cli_adapter: CLIAgentRegistryAdapter,
        rest_adapter: RestAgentRegistryAdapter,
        mcp_adapter: MCPAgentRegistryAdapter,
    ):
        """All surfaces should filter by role_alignment."""
        # Create and publish agents with different role alignments (must be ACTIVE for role_alignment filter)
        student = cli_adapter.create_agent(
            name="Student Agent", description="Test", role_alignment="STUDENT", visibility="PUBLIC"
        )
        cli_adapter.publish_agent(agent_id=student["agent"]["agent_id"], version="1.0.0")

        teacher = cli_adapter.create_agent(
            name="Teacher Agent", description="Test", role_alignment="TEACHER", visibility="PUBLIC"
        )
        cli_adapter.publish_agent(agent_id=teacher["agent"]["agent_id"], version="1.0.0")

        # CLI - search returns [{"agent": {...}, "active_version": {...}, "score": ...}, ...]
        cli_result = cli_adapter.search_agents(query="Agent", role_alignment="STUDENT")
        cli_names = [a["agent"]["name"] for a in cli_result]

        # REST - same nested structure
        rest_result = rest_adapter.search_agents({"query": "Agent", "role_alignment": "STUDENT"})
        rest_names = [a["agent"]["name"] for a in rest_result]

        # MCP - results list contains same nested structure
        mcp_result = mcp_adapter.search_agents({"query": "Agent", "role_alignment": "STUDENT"})
        mcp_names = [a["agent"]["name"] for a in mcp_result["results"]]

        # All should find the student agent
        assert any("Student" in n for n in cli_names)
        assert any("Student" in n for n in rest_names)
        assert any("Student" in n for n in mcp_names)


# ==============================================================================
# PUBLISH PARITY TESTS
# ==============================================================================


class TestPublishAgentParity:
    """Verify publish agent parity across surfaces."""

    def test_cli_publish_agent(self, cli_adapter: CLIAgentRegistryAdapter):
        """CLI: Publish a draft agent."""
        created = cli_adapter.create_agent(
            name="Publish Test CLI", description="Test", role_alignment="STUDENT"
        )
        agent_id = created["agent"]["agent_id"]

        result = cli_adapter.publish_agent(agent_id=agent_id, version="1.0.0")

        assert "agent" in result
        # After publishing, the latest published version should be set
        published_versions = [v for v in result["versions"] if v["status"] == "ACTIVE"]
        assert len(published_versions) == 1
        assert published_versions[0]["version"] == "1.0.0"

    def test_rest_publish_agent(self, rest_adapter: RestAgentRegistryAdapter):
        """REST: Publish a draft agent."""
        created = rest_adapter.create_agent({
            "name": "Publish Test REST", "description": "Test", "role_alignment": "TEACHER",
            "actor": {"id": "test"}
        })
        agent_id = created["agent"]["agent_id"]

        result = rest_adapter.publish_agent(agent_id, {"version": "1.0.0", "actor": {"id": "test"}})

        assert "agent" in result
        published_versions = [v for v in result["versions"] if v["status"] == "ACTIVE"]
        assert len(published_versions) == 1

    def test_mcp_publish_agent(self, mcp_adapter: MCPAgentRegistryAdapter):
        """MCP: Publish a draft agent."""
        created = mcp_adapter.create_agent({
            "name": "Publish Test MCP", "description": "Test", "role_alignment": "STRATEGIST",
            "actor": {"id": "test"}
        })
        agent_id = created["agent_id"]

        result = mcp_adapter.publish_agent({
            "agent_id": agent_id, "version": "1.0.0", "actor": {"id": "test"}
        })

        assert "agent_id" in result
        assert result["status"] == "ACTIVE"
        assert "message" in result


# ==============================================================================
# DEPRECATE PARITY TESTS
# ==============================================================================


class TestDeprecateAgentParity:
    """Verify deprecate agent parity across surfaces."""

    def test_rest_deprecate_agent(self, rest_adapter: RestAgentRegistryAdapter):
        """REST: Deprecate a published agent."""
        created = rest_adapter.create_agent({
            "name": "Deprecate Test REST", "description": "Test", "role_alignment": "TEACHER",
            "actor": {"id": "test"}
        })
        agent_id = created["agent"]["agent_id"]

        # First publish it
        rest_adapter.publish_agent(agent_id, {"version": "1.0.0", "actor": {"id": "test"}})

        # Then deprecate it
        result = rest_adapter.deprecate_agent(agent_id, {
            "version": "1.0.0",
            "reason": "Superseded by v2",
            "actor": {"id": "test"}
        })

        assert "agent" in result
        deprecated_versions = [v for v in result["versions"] if v["status"] == "DEPRECATED"]
        assert len(deprecated_versions) == 1

    def test_mcp_deprecate_agent(self, mcp_adapter: MCPAgentRegistryAdapter):
        """MCP: Deprecate a published agent."""
        created = mcp_adapter.create_agent({
            "name": "Deprecate Test MCP", "description": "Test", "role_alignment": "STRATEGIST",
            "actor": {"id": "test"}
        })
        agent_id = created["agent_id"]

        # First publish it
        mcp_adapter.publish_agent({
            "agent_id": agent_id, "version": "1.0.0", "actor": {"id": "test"}
        })

        # Then deprecate it
        result = mcp_adapter.deprecate_agent({
            "agent_id": agent_id,
            "version": "1.0.0",
            "reason": "No longer maintained",
            "actor": {"id": "test"}
        })

        assert "agent_id" in result
        assert result["status"] == "DEPRECATED"


# ==============================================================================
# RESPONSE FORMAT PARITY TESTS
# ==============================================================================


class TestResponseFormatParity:
    """Verify response formats are consistent where expected."""

    def test_agent_fields_match_contract(
        self,
        cli_adapter: CLIAgentRegistryAdapter,
        rest_adapter: RestAgentRegistryAdapter,
    ):
        """All surfaces should return agents with fields matching the contract."""
        required_agent_fields = {
            "agent_id", "name", "slug", "description", "tags",
            "visibility", "status", "owner_id", "is_builtin",
            "created_at", "updated_at", "latest_version"
        }
        required_version_fields = {
            "version_id", "agent_id", "version", "status",
            "role_alignment", "mission", "capabilities", "default_behaviors"
        }

        # CLI
        cli_result = cli_adapter.create_agent(
            name="Fields Test CLI", description="Test", role_alignment="STUDENT"
        )
        cli_agent_fields = set(cli_result["agent"].keys())
        cli_version_fields = set(cli_result["versions"][0].keys())

        assert required_agent_fields.issubset(cli_agent_fields), \
            f"CLI missing agent fields: {required_agent_fields - cli_agent_fields}"
        assert required_version_fields.issubset(cli_version_fields), \
            f"CLI missing version fields: {required_version_fields - cli_version_fields}"

        # REST
        rest_result = rest_adapter.create_agent({
            "name": "Fields Test REST", "description": "Test", "role_alignment": "TEACHER",
            "actor": {"id": "test"}
        })
        rest_agent_fields = set(rest_result["agent"].keys())
        rest_version_fields = set(rest_result["versions"][0].keys())

        assert required_agent_fields.issubset(rest_agent_fields), \
            f"REST missing agent fields: {required_agent_fields - rest_agent_fields}"
        assert required_version_fields.issubset(rest_version_fields), \
            f"REST missing version fields: {required_version_fields - rest_version_fields}"


class TestTimestampFormatParity:
    """Verify timestamp formats are consistent across surfaces."""

    def test_timestamps_are_iso_format(
        self,
        cli_adapter: CLIAgentRegistryAdapter,
        rest_adapter: RestAgentRegistryAdapter,
    ):
        """All surfaces should return ISO-format timestamps."""
        # CLI
        cli_result = cli_adapter.create_agent(
            name="Timestamp Format CLI", description="Test", role_alignment="STUDENT"
        )
        cli_created = cli_result["agent"]["created_at"]
        # Should be parseable as ISO datetime
        if isinstance(cli_created, str):
            datetime.fromisoformat(cli_created.replace("Z", "+00:00"))

        # REST
        rest_result = rest_adapter.create_agent({
            "name": "Timestamp Format REST", "description": "Test", "role_alignment": "TEACHER",
            "actor": {"id": "test"}
        })
        rest_created = rest_result["agent"]["created_at"]
        if isinstance(rest_created, str):
            datetime.fromisoformat(rest_created.replace("Z", "+00:00"))


# ==============================================================================
# ERROR HANDLING PARITY TESTS
# ==============================================================================


class TestErrorHandlingParity:
    """Verify error handling is consistent across surfaces."""

    def test_invalid_role_alignment_rejected(
        self,
        rest_adapter: RestAgentRegistryAdapter,
        mcp_adapter: MCPAgentRegistryAdapter,
    ):
        """All surfaces should reject invalid role_alignment values."""
        # REST
        with pytest.raises(ValueError):
            rest_adapter.create_agent({
                "name": "Invalid Role", "description": "Test",
                "role_alignment": "invalid_role",
                "actor": {"id": "test"}
            })

        # MCP
        with pytest.raises(ValueError):
            mcp_adapter.create_agent({
                "name": "Invalid Role MCP", "description": "Test",
                "role_alignment": "invalid_role",
                "actor": {"id": "test"}
            })

    def test_invalid_visibility_rejected(
        self,
        rest_adapter: RestAgentRegistryAdapter,
        mcp_adapter: MCPAgentRegistryAdapter,
    ):
        """All surfaces should reject invalid visibility values."""
        # REST
        with pytest.raises(ValueError):
            rest_adapter.create_agent({
                "name": "Invalid Visibility", "description": "Test",
                "role_alignment": "STUDENT",
                "visibility": "invalid_visibility",
                "actor": {"id": "test"}
            })

        # MCP
        with pytest.raises(ValueError):
            mcp_adapter.create_agent({
                "name": "Invalid Visibility MCP", "description": "Test",
                "role_alignment": "STUDENT",
                "visibility": "invalid_visibility",
                "actor": {"id": "test"}
            })


# ==============================================================================
# PAGINATION PARITY TESTS
# ==============================================================================


class TestPaginationParity:
    """Verify pagination works consistently across surfaces."""

    def test_limit_respected(
        self,
        cli_adapter: CLIAgentRegistryAdapter,
        rest_adapter: RestAgentRegistryAdapter,
        mcp_adapter: MCPAgentRegistryAdapter,
    ):
        """All surfaces should respect the limit parameter."""
        # Create several agents
        for i in range(5):
            cli_adapter.create_agent(
                name=f"Pagination Test {i}", description="Test", role_alignment="STUDENT"
            )

        # CLI with limit
        cli_result = cli_adapter.list_agents(limit=2)
        assert len(cli_result) <= 2

        # REST with limit
        rest_result = rest_adapter.list_agents({"limit": 2})
        assert len(rest_result) <= 2

        # MCP with limit
        mcp_result = mcp_adapter.list_agents({"limit": 2})
        assert len(mcp_result["agents"]) <= 2


# ==============================================================================
# IDEMPOTENCY TESTS
# ==============================================================================


class TestIdempotencyParity:
    """Verify operations are idempotent where expected."""

    def test_get_is_idempotent(
        self,
        cli_adapter: CLIAgentRegistryAdapter,
        rest_adapter: RestAgentRegistryAdapter,
    ):
        """Multiple gets should return the same result."""
        created = cli_adapter.create_agent(
            name="Idempotency Test", description="Test", role_alignment="STUDENT"
        )
        agent_id = created["agent"]["agent_id"]

        # Multiple gets should be identical
        result1 = cli_adapter.get_agent(agent_id)
        result2 = cli_adapter.get_agent(agent_id)

        assert result1["agent"]["agent_id"] == result2["agent"]["agent_id"]
        assert result1["agent"]["name"] == result2["agent"]["name"]

        # Same for REST
        rest_result1 = rest_adapter.get_agent(agent_id)
        rest_result2 = rest_adapter.get_agent(agent_id)

        assert rest_result1["agent"]["agent_id"] == rest_result2["agent"]["agent_id"]
