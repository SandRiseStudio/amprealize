"""Parity tests for BehaviorService across CLI/REST/MCP surfaces.

Validates that BehaviorService operations produce consistent results
regardless of which surface invokes them (CLI, REST API, MCP tools).

Note: These tests validate structural parity - that all three surfaces
(CLI, REST, MCP) expose equivalent operations with consistent semantics.
The service returns nested structures: {"behavior": {...}, "versions": [...]}
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Generator

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - psycopg2 is optional for lint environments
    psycopg2 = None
import pytest

from amprealize.action_contracts import Actor
from amprealize.adapters import (
    CLIBehaviorServiceAdapter,
    RestBehaviorServiceAdapter,
    MCPBehaviorServiceAdapter,
)
from amprealize.behavior_service import BehaviorService, BehaviorNotFoundError, BehaviorVersionError


NONEXISTENT_BEHAVIOR_ID = "00000000-0000-0000-0000-000000000001"


def _truncate_behavior_tables(dsn: str) -> None:
    """Remove all data from behavior tables to ensure test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, ["behavior_versions", "behaviors"])


@pytest.fixture
def behavior_service() -> Generator[BehaviorService, None, None]:
    """Create a fresh BehaviorService backed by PostgreSQL for each test."""
    dsn = os.environ.get("AMPREALIZE_BEHAVIOR_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_BEHAVIOR_PG_DSN not set; skipping PostgreSQL parity tests")

    _truncate_behavior_tables(dsn)
    service = BehaviorService(dsn=dsn)

    try:
        yield service
    finally:
        _truncate_behavior_tables(dsn)
        conn = getattr(service, "_conn", None)
        if conn is not None and getattr(conn, "closed", 1) == 0:
            conn.close()


@pytest.fixture
def cli_adapter(behavior_service: BehaviorService) -> CLIBehaviorServiceAdapter:
    """CLI adapter for testing."""
    return CLIBehaviorServiceAdapter(behavior_service)


@pytest.fixture
def rest_adapter(behavior_service: BehaviorService) -> RestBehaviorServiceAdapter:
    """REST adapter for testing."""
    return RestBehaviorServiceAdapter(behavior_service)


@pytest.fixture
def mcp_adapter(behavior_service: BehaviorService) -> MCPBehaviorServiceAdapter:
    """MCP adapter for testing."""
    return MCPBehaviorServiceAdapter(behavior_service)


class TestCreateBehaviorParity:
    """Verify create behavior parity across surfaces."""

    def test_cli_create_behavior(self, cli_adapter: CLIBehaviorServiceAdapter):
        result = cli_adapter.create(
            name="Test Behavior",
            description="Test description",
            instruction="Test instruction",
            role_focus="STRATEGIST",
            trigger_keywords=["test"],
            tags=["cli-test"],
            examples=[],
            metadata={"source": "cli"},
            embedding=None,
            actor_id="cli-user",
            actor_role="STRATEGIST",
        )

        # Result has nested structure: {"behavior": {...}, "versions": [...]}
        assert "behavior" in result
        assert "versions" in result
        assert result["behavior"]["name"] == "Test Behavior"
        assert result["versions"][0]["status"] == "DRAFT"
        assert result["versions"][0]["role_focus"] == "STRATEGIST"
        assert "cli-test" in result["behavior"]["tags"]

    def test_rest_create_behavior(self, rest_adapter: RestBehaviorServiceAdapter):
        payload = {
            "name": "Test Behavior REST",
            "description": "Test description",
            "instruction": "Test instruction",
            "role_focus": "TEACHER",
            "trigger_keywords": ["test"],
            "tags": ["rest-test"],
            "examples": [],
            "metadata": {"source": "rest"},
            "actor": {"id": "rest-user", "role": "TEACHER", "surface": "REST_API"}
        }
        result = rest_adapter.create_draft(payload)

        assert "behavior" in result
        assert "versions" in result
        assert result["behavior"]["name"] == "Test Behavior REST"
        assert result["versions"][0]["status"] == "DRAFT"
        assert result["versions"][0]["role_focus"] == "TEACHER"
        assert "rest-test" in result["behavior"]["tags"]

    def test_mcp_create_behavior(self, mcp_adapter: MCPBehaviorServiceAdapter):
        payload = {
            "name": "Test Behavior MCP",
            "description": "Test description",
            "instruction": "Test instruction",
            "role_focus": "STUDENT",
            "trigger_keywords": ["test"],
            "tags": ["mcp-test"],
            "examples": [],
            "metadata": {"source": "mcp"},
            "actor": {"id": "mcp-user", "role": "STUDENT", "surface": "MCP"}
        }
        result = mcp_adapter.create(payload)

        assert "behavior" in result
        assert "versions" in result
        assert result["behavior"]["name"] == "Test Behavior MCP"
        assert result["versions"][0]["status"] == "DRAFT"
        assert result["versions"][0]["role_focus"] == "STUDENT"
        assert "mcp-test" in result["behavior"]["tags"]

    def test_surface_parity_create_behavior(
        self,
        cli_adapter: CLIBehaviorServiceAdapter,
        rest_adapter: RestBehaviorServiceAdapter,
        mcp_adapter: MCPBehaviorServiceAdapter,
    ):
        """Verify all surfaces produce structurally consistent behaviors."""

        cli_result = cli_adapter.create(
            name="Parity Test CLI",
            description="Testing parity",
            instruction="Follow parity protocol",
            role_focus="STRATEGIST",
            trigger_keywords=["parity"],
            tags=["test"],
            examples=[],
            metadata={},
            embedding=None,
            actor_id="test-user",
            actor_role="STRATEGIST",
        )

        rest_payload = {
            "name": "Parity Test REST",
            "description": "Testing parity",
            "instruction": "Follow parity protocol",
            "role_focus": "STRATEGIST",
            "trigger_keywords": ["parity"],
            "tags": ["test"],
            "examples": [],
            "metadata": {},
            "actor": {"id": "test-user", "role": "STRATEGIST", "surface": "REST_API"}
        }
        rest_result = rest_adapter.create_draft(rest_payload)

        mcp_payload = {
            "name": "Parity Test MCP",
            "description": "Testing parity",
            "instruction": "Follow parity protocol",
            "role_focus": "STRATEGIST",
            "trigger_keywords": ["parity"],
            "tags": ["test"],
            "examples": [],
            "metadata": {},
            "actor": {"id": "test-user", "role": "STRATEGIST", "surface": "MCP"}
        }
        mcp_result = mcp_adapter.create(mcp_payload)

        # All should have same nested structure: {"behavior": {...}, "versions": [...]}
        for result in [cli_result, rest_result, mcp_result]:
            assert "behavior" in result
            assert "versions" in result
            # Name will differ (CLI/REST/MCP suffix) but structure is consistent
            assert result["versions"][0]["status"] == "DRAFT"
            assert result["versions"][0]["version"] == "1.0.0"
            assert result["versions"][0]["role_focus"] == "STRATEGIST"
            assert "parity" in result["versions"][0]["trigger_keywords"]
            assert "behavior_id" in result["behavior"]
            assert "created_at" in result["behavior"]


class TestListBehaviorsParity:
    """Verify list behaviors parity across surfaces."""

    def test_cli_list_all(self, cli_adapter: CLIBehaviorServiceAdapter):
        # Create a behavior first
        cli_adapter.create(
            name="List Test",
            description="Test",
            instruction="Test",
            role_focus="STRATEGIST",
            trigger_keywords=[],
            tags=[],
            examples=[],
            metadata={},
            embedding=None,
            actor_id="test",
            actor_role="STRATEGIST",
        )

        result = cli_adapter.list(status=None, tags=[], role_focus=None)
        # list_behaviors returns [{"behavior": {...}, "active_version": {...}}]
        assert len(result) >= 1
        assert any(item["behavior"]["name"] == "List Test" for item in result)

    def test_cli_list_filtered_by_role(self, cli_adapter: CLIBehaviorServiceAdapter):
        cli_adapter.create(
            name="Teacher Behavior",
            description="Test",
            instruction="Test",
            role_focus="TEACHER",
            trigger_keywords=[],
            tags=[],
            examples=[],
            metadata={},
            embedding=None,
            actor_id="test",
            actor_role="TEACHER",
        )

        result = cli_adapter.list(status=None, tags=[], role_focus="TEACHER")
        assert len(result) >= 1
        assert all(item["active_version"]["role_focus"] == "TEACHER" for item in result if item["active_version"])

    def test_rest_list(self, rest_adapter: RestBehaviorServiceAdapter):
        rest_adapter.create_draft({
            "name": "REST List Test",
            "description": "Test",
            "instruction": "Test",
            "role_focus": "STUDENT",
            "tags": ["rest"],
            "trigger_keywords": [],
            "examples": [],
            "metadata": {},
            "actor": {"id": "test", "role": "STUDENT", "surface": "REST_API"}
        })

        result = rest_adapter.list_behaviors({"tags": ["rest"]})
        assert len(result) >= 1
        assert all("rest" in item["behavior"].get("tags", []) for item in result)

    def test_mcp_list(self, mcp_adapter: MCPBehaviorServiceAdapter):
        mcp_adapter.create({
            "name": "MCP List Test",
            "description": "Test",
            "instruction": "Test",
            "role_focus": "STRATEGIST",
            "tags": ["mcp"],
            "trigger_keywords": [],
            "examples": [],
            "metadata": {},
            "actor": {"id": "test", "role": "STRATEGIST", "surface": "MCP"}
        })

        result = mcp_adapter.list({"role_focus": "STRATEGIST"})
        assert len(result) >= 1


class TestSearchBehaviorsParity:
    """Verify search behaviors parity across surfaces."""

    def test_cli_search(self, cli_adapter: CLIBehaviorServiceAdapter):
        cli_adapter.create(
            name="Searchable Behavior",
            description="A behavior about searching",
            instruction="Search for things",
            role_focus="STRATEGIST",
            trigger_keywords=["search", "find"],
            tags=[],
            examples=[],
            metadata={},
            embedding=None,

            actor_id="test",
            actor_role="STRATEGIST",
        )

        result = cli_adapter.search(
            query="search for things",
            tags=[],
            role_focus=None,
            status=None,
            limit=25,
            actor_id="test",
            actor_role="STRATEGIST",
        )
        # Search should return results (may be empty if no embedding)
        assert isinstance(result, list)

    def test_rest_search(self, rest_adapter: RestBehaviorServiceAdapter):
        rest_adapter.create_draft({
            "name": "REST Searchable",
            "description": "REST searchable behavior",
            "instruction": "REST search instruction",
            "role_focus": "TEACHER",
            "trigger_keywords": ["rest", "search"],
            "tags": [],
            "examples": [],
            "metadata": {},
            "actor": {"id": "test", "role": "TEACHER", "surface": "REST_API"}
        })

        result = rest_adapter.search_behaviors({
            "query": "REST search",
            "limit": 25,
            "actor": {"id": "test", "role": "TEACHER", "surface": "REST_API"}
        })
        assert isinstance(result, list)

    def test_mcp_search(self, mcp_adapter: MCPBehaviorServiceAdapter):
        mcp_adapter.create({
            "name": "MCP Searchable",
            "description": "MCP searchable behavior",
            "instruction": "MCP search instruction",
            "role_focus": "STUDENT",
            "trigger_keywords": ["mcp", "search"],
            "tags": [],
            "examples": [],
            "metadata": {},
            "actor": {"id": "test", "role": "STUDENT", "surface": "MCP"}
        })

        result = mcp_adapter.search({
            "query": "MCP search",
            "limit": 25,
            "actor": {"id": "test", "role": "STUDENT", "surface": "MCP"}
        })
        assert isinstance(result, list)


class TestLifecycleParity:
    """Verify full lifecycle operations parity (submit/approve/deprecate)."""

    def test_cli_submit_behavior(self, cli_adapter: CLIBehaviorServiceAdapter):
        # Create draft
        created = cli_adapter.create(
            name="Submit Test",
            description="Test",
            instruction="Test",
            role_focus="STRATEGIST",
            trigger_keywords=[],
            tags=[],
            examples=[],
            metadata={},
            embedding=None,
            actor_id="test",
            actor_role="STRATEGIST",
        )

        # Submit for review
        result = cli_adapter.submit(
            behavior_id=created["behavior"]["behavior_id"],
            version=created["versions"][0]["version"],
            actor_id="test",
            actor_role="STRATEGIST",
        )

        assert result["versions"][0]["status"] == "IN_REVIEW"
        assert result["behavior"]["behavior_id"] == created["behavior"]["behavior_id"]

    def test_rest_submit_behavior(self, rest_adapter: RestBehaviorServiceAdapter):
        # Create draft
        created = rest_adapter.create_draft({
            "name": "REST Submit Test",
            "description": "Test",
            "instruction": "Test",
            "role_focus": "TEACHER",
            "trigger_keywords": [],
            "tags": [],
            "examples": [],
            "metadata": {},
            "actor": {"id": "test", "role": "TEACHER", "surface": "REST_API"}
        })

        # Submit for review
        result = rest_adapter.submit_for_review(
            behavior_id=created["behavior"]["behavior_id"],
            version=created["versions"][0]["version"],
            payload={"actor": {"id": "test", "role": "TEACHER", "surface": "REST_API"}}
        )

        assert result["versions"][0]["status"] == "IN_REVIEW"

    def test_mcp_submit_behavior(self, mcp_adapter: MCPBehaviorServiceAdapter):
        # Create draft
        created = mcp_adapter.create({
            "name": "MCP Submit Test",
            "description": "Test",
            "instruction": "Test",
            "role_focus": "STUDENT",
            "trigger_keywords": [],
            "tags": [],
            "examples": [],
            "metadata": {},
            "actor": {"id": "test", "role": "STUDENT", "surface": "MCP"}
        })

        # Submit for review
        result = mcp_adapter.submit({
            "behavior_id": created["behavior"]["behavior_id"],
            "version": created["versions"][0]["version"],
            "actor": {"id": "test", "role": "STUDENT", "surface": "MCP"}
        })

        assert result["versions"][0]["status"] == "IN_REVIEW"

    def test_approve_parity(
        self,
        cli_adapter: CLIBehaviorServiceAdapter,
        rest_adapter: RestBehaviorServiceAdapter,
        mcp_adapter: MCPBehaviorServiceAdapter,
    ):
        """Verify approve operation consistency."""
        from datetime import datetime, timezone

        effective_from = datetime.now(timezone.utc).isoformat()

        # CLI approve
        cli_created = cli_adapter.create(
            name="CLI Approve Test", description="Test", instruction="Test",
            role_focus="STRATEGIST", trigger_keywords=[], tags=[], examples=[],
            metadata={}, embedding=None,
            actor_id="test", actor_role="STRATEGIST"
        )
        cli_adapter.submit(
            cli_created["behavior"]["behavior_id"], cli_created["versions"][0]["version"],
            actor_id="test", actor_role="STRATEGIST"
        )
        cli_approved = cli_adapter.approve(
            behavior_id=cli_created["behavior"]["behavior_id"],
            version=cli_created["versions"][0]["version"],
            effective_from=effective_from,
            approval_action_id=None,
            actor_id="approver",
            actor_role="COMPLIANCE",
        )
        assert cli_approved["versions"][0]["status"] == "APPROVED"

        # REST approve
        rest_created = rest_adapter.create_draft({
            "name": "REST Approve Test", "description": "Test", "instruction": "Test",
            "role_focus": "TEACHER", "trigger_keywords": [], "tags": [],
            "examples": [], "metadata": {},
            "actor": {"id": "test", "role": "TEACHER", "surface": "REST_API"}
        })
        rest_adapter.submit_for_review(
            rest_created["behavior"]["behavior_id"], rest_created["versions"][0]["version"],
            payload={"actor": {"id": "test", "role": "TEACHER", "surface": "REST_API"}}
        )
        rest_approved = rest_adapter.approve(
            behavior_id=rest_created["behavior"]["behavior_id"],
            payload={
                "version": rest_created["versions"][0]["version"],
                "effective_from": effective_from,
                "actor": {"id": "approver", "role": "COMPLIANCE", "surface": "REST_API"}
            }
        )
        assert rest_approved["versions"][0]["status"] == "APPROVED"

        # MCP approve
        mcp_created = mcp_adapter.create({
            "name": "MCP Approve Test", "description": "Test", "instruction": "Test",
            "role_focus": "STUDENT", "trigger_keywords": [], "tags": [],
            "examples": [], "metadata": {},
            "actor": {"id": "test", "role": "STUDENT", "surface": "MCP"}
        })
        mcp_adapter.submit({
            "behavior_id": mcp_created["behavior"]["behavior_id"],
            "version": mcp_created["versions"][0]["version"],
            "actor": {"id": "test", "role": "STUDENT", "surface": "MCP"}
        })
        mcp_approved = mcp_adapter.approve({
            "behavior_id": mcp_created["behavior"]["behavior_id"],
            "version": mcp_created["versions"][0]["version"],
            "effective_from": effective_from,
            "actor": {"id": "approver", "role": "COMPLIANCE", "surface": "MCP"}
        })
        assert mcp_approved["versions"][0]["status"] == "APPROVED"


class TestUpdateBehaviorParity:
    """Verify update behavior parity across surfaces."""

    def test_cli_update(self, cli_adapter: CLIBehaviorServiceAdapter):
        created = cli_adapter.create(
            name="Update Test", description="Original", instruction="Original",
            role_focus="STRATEGIST", trigger_keywords=[], tags=[], examples=[],
            metadata={}, embedding=None,
            actor_id="test", actor_role="STRATEGIST"
        )

        updated = cli_adapter.update(
            behavior_id=created["behavior"]["behavior_id"],
            version=created["versions"][0]["version"],
            instruction="Updated instruction",
            description=None,
            trigger_keywords=None,
            tags=[],
            examples=[],
            metadata={},
            embedding=None,
            actor_id="test",
            actor_role="STRATEGIST",
        )

        assert updated["behavior"]["behavior_id"] == created["behavior"]["behavior_id"]
        assert updated["versions"][0]["status"] == "DRAFT"

    def test_rest_update(self, rest_adapter: RestBehaviorServiceAdapter):
        created = rest_adapter.create_draft({
            "name": "REST Update Test", "description": "Original", "instruction": "Original",
            "role_focus": "TEACHER", "trigger_keywords": [], "tags": [],
            "examples": [], "metadata": {},
            "actor": {"id": "test", "role": "TEACHER", "surface": "REST_API"}
        })

        updated = rest_adapter.update_draft(
            behavior_id=created["behavior"]["behavior_id"],
            version=created["versions"][0]["version"],
            payload={
                "instruction": "Updated instruction",
                "actor": {"id": "test", "role": "TEACHER", "surface": "REST_API"}
            }
        )

        assert updated["behavior"]["behavior_id"] == created["behavior"]["behavior_id"]
        assert updated["versions"][0]["status"] == "DRAFT"

    def test_mcp_update(self, mcp_adapter: MCPBehaviorServiceAdapter):
        created = mcp_adapter.create({
            "name": "MCP Update Test", "description": "Original", "instruction": "Original",
            "role_focus": "STUDENT", "trigger_keywords": [], "tags": [],
            "examples": [], "metadata": {},
            "actor": {"id": "test", "role": "STUDENT", "surface": "MCP"}
        })

        updated = mcp_adapter.update({
            "behavior_id": created["behavior"]["behavior_id"],
            "version": created["versions"][0]["version"],
            "instruction": "Updated instruction",
            "actor": {"id": "test", "role": "STUDENT", "surface": "MCP"}
        })

        assert updated["behavior"]["behavior_id"] == created["behavior"]["behavior_id"]
        assert updated["versions"][0]["status"] == "DRAFT"


class TestErrorHandlingParity:
    """Verify error handling consistency across surfaces."""

    def test_cli_get_nonexistent(self, cli_adapter: CLIBehaviorServiceAdapter):
        with pytest.raises(BehaviorNotFoundError):
            cli_adapter.get(NONEXISTENT_BEHAVIOR_ID, None)

    def test_rest_get_nonexistent(self, rest_adapter: RestBehaviorServiceAdapter):
        with pytest.raises(BehaviorNotFoundError):
            rest_adapter.get_behavior(NONEXISTENT_BEHAVIOR_ID, None)

    def test_mcp_get_nonexistent(self, mcp_adapter: MCPBehaviorServiceAdapter):
        with pytest.raises(BehaviorNotFoundError):
            mcp_adapter.get({"behavior_id": NONEXISTENT_BEHAVIOR_ID})

    def test_update_nonexistent_behavior(
        self,
        cli_adapter: CLIBehaviorServiceAdapter,
        rest_adapter: RestBehaviorServiceAdapter,
        mcp_adapter: MCPBehaviorServiceAdapter,
    ):
        """Verify all surfaces reject updating nonexistent behaviors."""

        # CLI - update raises BehaviorVersionError when version not found
        with pytest.raises(BehaviorVersionError):
            cli_adapter.update(
                behavior_id=NONEXISTENT_BEHAVIOR_ID,
                version="1.0.0",
                instruction="Updated",
                description=None, trigger_keywords=None, tags=[],
                examples=[], metadata={}, embedding=None,
                actor_id="test", actor_role="STRATEGIST"
            )

        # REST
        with pytest.raises(BehaviorVersionError):
            rest_adapter.update_draft(
                behavior_id=NONEXISTENT_BEHAVIOR_ID,
                version="1.0.0",
                payload={
                    "instruction": "Updated",
                    "actor": {"id": "test", "role": "STRATEGIST", "surface": "REST_API"}
                }
            )

        # MCP
        with pytest.raises(BehaviorVersionError):
            mcp_adapter.update({
                "behavior_id": NONEXISTENT_BEHAVIOR_ID,
                "version": "1.0.0",
                "instruction": "Updated",
                "actor": {"id": "test", "role": "STRATEGIST", "surface": "MCP"}
            })


class TestDeleteDraftParity:
    """Verify delete draft parity across surfaces."""

    def test_cli_delete_draft(self, cli_adapter: CLIBehaviorServiceAdapter):
        created = cli_adapter.create(
            name="Delete Test", description="Test", instruction="Test",
            role_focus="STRATEGIST", trigger_keywords=[], tags=[],
            examples=[], metadata={}, embedding=None,
            actor_id="test", actor_role="STRATEGIST"
        )

        cli_adapter.delete_draft(
            behavior_id=created["behavior"]["behavior_id"],
            version=created["versions"][0]["version"],
            actor_id="test",
            actor_role="STRATEGIST",
        )

        # Should raise BehaviorNotFoundError when getting deleted behavior
        with pytest.raises(BehaviorNotFoundError):
            cli_adapter.get(created["behavior"]["behavior_id"], created["versions"][0]["version"])

    def test_rest_delete_draft(self, rest_adapter: RestBehaviorServiceAdapter):
        created = rest_adapter.create_draft({
            "name": "REST Delete Test", "description": "Test", "instruction": "Test",
            "role_focus": "TEACHER", "trigger_keywords": [], "tags": [],
            "examples": [], "metadata": {},
            "actor": {"id": "test", "role": "TEACHER", "surface": "REST_API"}
        })

        rest_adapter.delete_draft(
            behavior_id=created["behavior"]["behavior_id"],
            version=created["versions"][0]["version"],
            payload={"actor": {"id": "test", "role": "TEACHER", "surface": "REST_API"}}
        )

        # Should raise BehaviorNotFoundError when getting deleted behavior
        with pytest.raises(BehaviorNotFoundError):
            rest_adapter.get_behavior(created["behavior"]["behavior_id"], created["versions"][0]["version"])

    def test_mcp_delete_draft(self, mcp_adapter: MCPBehaviorServiceAdapter):
        created = mcp_adapter.create({
            "name": "MCP Delete Test", "description": "Test", "instruction": "Test",
            "role_focus": "STUDENT", "trigger_keywords": [], "tags": [],
            "examples": [], "metadata": {},
            "actor": {"id": "test", "role": "STUDENT", "surface": "MCP"}
        })

        mcp_adapter.delete_draft({
            "behavior_id": created["behavior"]["behavior_id"],
            "version": created["versions"][0]["version"],
            "actor": {"id": "test", "role": "STUDENT", "surface": "MCP"}
        })

        # Should raise BehaviorNotFoundError when getting deleted behavior
        with pytest.raises(BehaviorNotFoundError):
            mcp_adapter.get({"behavior_id": created["behavior"]["behavior_id"], "version": created["versions"][0]["version"]})
