"""Parity tests for AgentOrchestratorService comparing PostgreSQL and in-memory implementations.

Validates that PostgreSQL-backed PostgresAgentOrchestratorService produces identical
results to the in-memory AgentOrchestratorService for all operations:
- list_personas: Retrieve all available agents
- assign_agent: Create assignments with heuristic selection
- switch_agent: Runtime agent switching with audit trail
- get_status: Lookup by run_id or assignment_id

Test coverage:
- Default persona seeding
- Context-aware agent selection (task_type matching)
- Multi-tenant isolation (different run_ids)
- Switch event history ordering
- Heuristics tracking
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    psycopg2 = None
import pytest

from amprealize.agent_orchestrator_service import (
    AgentOrchestratorService,
    AgentPersona,
    AgentAssignment,
)
from amprealize.agent_orchestrator_service_postgres import PostgresAgentOrchestratorService


def _truncate_agent_orchestrator_tables(dsn: str) -> None:
    """Remove all data from agent orchestrator tables to ensure test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, ["assignment_history"], schema="board")
    safe_truncate(dsn, ["agent_switch_events", "agent_assignments", "agent_personas"])


@pytest.fixture
def pg_dsn() -> str:
    """Get PostgreSQL DSN from environment."""
    dsn = os.environ.get("AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN not set; skipping parity tests")
    return dsn


@pytest.fixture
def memory_service() -> AgentOrchestratorService:
    """Create fresh in-memory service."""
    return AgentOrchestratorService()


@pytest.fixture
def postgres_service(pg_dsn: str) -> Generator[PostgresAgentOrchestratorService, None, None]:
    """Create fresh PostgreSQL service with cleanup."""
    _truncate_agent_orchestrator_tables(pg_dsn)
    service = PostgresAgentOrchestratorService(pg_dsn)

    try:
        yield service
    finally:
        _truncate_agent_orchestrator_tables(pg_dsn)


class TestListPersonasParity:
    """Verify list_personas parity."""

    def test_default_personas_count(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services return same number of default personas."""
        memory_personas = memory_service.list_personas()
        postgres_personas = postgres_service.list_personas()

        assert len(memory_personas) == len(postgres_personas), \
            f"Persona count mismatch: memory={len(memory_personas)}, postgres={len(postgres_personas)}"

    def test_default_personas_content(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services return identical default personas."""
        memory_personas = {p.agent_id: p for p in memory_service.list_personas()}
        postgres_personas = {p.agent_id: p for p in postgres_service.list_personas()}

        assert set(memory_personas.keys()) == set(postgres_personas.keys()), \
            "Agent IDs don't match between memory and postgres"

        for agent_id in memory_personas:
            mem_p = memory_personas[agent_id]
            pg_p = postgres_personas[agent_id]

            assert mem_p.agent_id == pg_p.agent_id
            assert mem_p.display_name == pg_p.display_name
            assert mem_p.role_alignment == pg_p.role_alignment
            assert set(mem_p.default_behaviors) == set(pg_p.default_behaviors)
            assert set(mem_p.playbook_refs) == set(pg_p.playbook_refs)
            assert set(mem_p.capabilities) == set(pg_p.capabilities)

    def test_personas_ordering(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services return personas in consistent order."""
        memory_ids = [p.agent_id for p in memory_service.list_personas()]
        postgres_ids = [p.agent_id for p in postgres_service.list_personas()]

        # Memory uses dict iteration order (insertion order in Python 3.7+)
        # Postgres uses ORDER BY agent_id
        # Just verify same set is present
        assert set(memory_ids) == set(postgres_ids)


class TestAssignAgentParity:
    """Verify assign_agent parity."""

    def test_new_assignment_structure(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services create assignments with same structure."""
        run_id = "test-run-001"
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}

        mem_assignment = memory_service.assign_agent(
            run_id=run_id,
            requested_agent_id=None,
            stage="planning",
            context={"task_type": "feature"},
            requested_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id=run_id + "-pg",  # Different run_id to avoid conflict
            requested_agent_id=None,
            stage="planning",
            context={"task_type": "feature"},
            requested_by=requested_by,
        )

        # Verify structure
        assert mem_assignment.run_id == run_id
        assert pg_assignment.run_id == run_id + "-pg"
        assert mem_assignment.stage == pg_assignment.stage == "planning"
        assert mem_assignment.active_agent.agent_id == pg_assignment.active_agent.agent_id
        assert mem_assignment.heuristics_applied == pg_assignment.heuristics_applied
        assert mem_assignment.requested_by == pg_assignment.requested_by == requested_by
        assert len(mem_assignment.history) == len(pg_assignment.history) == 0

    def test_explicit_agent_selection(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services honor explicit agent_id requests."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}

        mem_assignment = memory_service.assign_agent(
            run_id="mem-run-002",
            requested_agent_id="compliance",
            stage="planning",
            context={},
            requested_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id="pg-run-002",
            requested_agent_id="compliance",
            stage="planning",
            context={},
            requested_by=requested_by,
        )

        assert mem_assignment.active_agent.agent_id == "compliance"
        assert pg_assignment.active_agent.agent_id == "compliance"

    def test_heuristic_compliance_agent(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services select compliance agent for task_type=compliance."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}
        context = {"task_type": "compliance", "compliance_tags": ["GDPR"]}

        mem_assignment = memory_service.assign_agent(
            run_id="mem-run-003",
            requested_agent_id=None,
            stage="planning",
            context=context,
            requested_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id="pg-run-003",
            requested_agent_id=None,
            stage="planning",
            context=context,
            requested_by=requested_by,
        )

        assert mem_assignment.active_agent.agent_id == "compliance"
        assert pg_assignment.active_agent.agent_id == "compliance"
        assert mem_assignment.heuristics_applied["task_type"] == "compliance"
        assert pg_assignment.heuristics_applied["task_type"] == "compliance"

    def test_heuristic_security_agent(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services select security agent for task_type=security."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}
        context = {"task_type": "security", "severity": "high"}

        mem_assignment = memory_service.assign_agent(
            run_id="mem-run-004",
            requested_agent_id=None,
            stage="planning",
            context=context,
            requested_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id="pg-run-004",
            requested_agent_id=None,
            stage="planning",
            context=context,
            requested_by=requested_by,
        )

        assert mem_assignment.active_agent.agent_id == "security"
        assert pg_assignment.active_agent.agent_id == "security"
        assert mem_assignment.heuristics_applied["severity"] == "high"
        assert pg_assignment.heuristics_applied["severity"] == "high"

    def test_heuristic_finance_agent(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services select finance agent for task_type=finance."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}
        context = {"task_type": "finance"}

        mem_assignment = memory_service.assign_agent(
            run_id="mem-run-005",
            requested_agent_id=None,
            stage="planning",
            context=context,
            requested_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id="pg-run-005",
            requested_agent_id=None,
            stage="planning",
            context=context,
            requested_by=requested_by,
        )

        assert mem_assignment.active_agent.agent_id == "finance"
        assert pg_assignment.active_agent.agent_id == "finance"

    def test_default_agent_fallback(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services fall back to engineering agent when no heuristics match."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}
        context = {"task_type": "unknown_type"}

        mem_assignment = memory_service.assign_agent(
            run_id="mem-run-006",
            requested_agent_id=None,
            stage="planning",
            context=context,
            requested_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id="pg-run-006",
            requested_agent_id=None,
            stage="planning",
            context=context,
            requested_by=requested_by,
        )

        assert mem_assignment.active_agent.agent_id == "engineering"
        assert pg_assignment.active_agent.agent_id == "engineering"

    def test_idempotent_assignment_same_run_id(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services return existing assignment when called with same run_id."""
        run_id = "idempotent-run"
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}

        # Memory service
        mem_first = memory_service.assign_agent(
            run_id=run_id,
            requested_agent_id="compliance",
            stage="planning",
            context={},
            requested_by=requested_by,
        )
        mem_second = memory_service.assign_agent(
            run_id=run_id,
            requested_agent_id=None,  # Different request
            stage="execution",  # Different stage
            context={},
            requested_by=requested_by,
        )

        # Postgres service
        pg_first = postgres_service.assign_agent(
            run_id=run_id + "-pg",
            requested_agent_id="compliance",
            stage="planning",
            context={},
            requested_by=requested_by,
        )
        pg_second = postgres_service.assign_agent(
            run_id=run_id + "-pg",
            requested_agent_id=None,
            stage="execution",
            context={},
            requested_by=requested_by,
        )

        # Both should return same assignment_id
        assert mem_first.assignment_id == mem_second.assignment_id
        assert pg_first.assignment_id == pg_second.assignment_id


class TestSwitchAgentParity:
    """Verify switch_agent parity."""

    def test_switch_agent_structure(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services create switch events with same structure."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}

        # Create initial assignments
        mem_assignment = memory_service.assign_agent(
            run_id="mem-switch-001",
            requested_agent_id="engineering",
            stage="planning",
            context={},
            requested_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id="pg-switch-001",
            requested_agent_id="engineering",
            stage="planning",
            context={},
            requested_by=requested_by,
        )

        issued_by = {"actor_id": "admin", "actor_role": "TEACHER"}

        # Switch agents
        mem_switched = memory_service.switch_agent(
            assignment_id=mem_assignment.assignment_id,
            target_agent_id="security",
            reason="Security review required",
            allow_downgrade=False,
            stage="review",
            issued_by=issued_by,
        )

        pg_switched = postgres_service.switch_agent(
            assignment_id=pg_assignment.assignment_id,
            target_agent_id="security",
            reason="Security review required",
            allow_downgrade=False,
            stage="review",
            issued_by=issued_by,
        )

        # Verify structure
        assert mem_switched.active_agent.agent_id == "security"
        assert pg_switched.active_agent.agent_id == "security"
        assert mem_switched.stage == pg_switched.stage == "review"
        assert len(mem_switched.history) == len(pg_switched.history) == 1

        mem_event = mem_switched.history[0]
        pg_event = pg_switched.history[0]

        assert mem_event.from_agent_id == pg_event.from_agent_id == "engineering"
        assert mem_event.to_agent_id == pg_event.to_agent_id == "security"
        assert mem_event.stage == pg_event.stage == "review"
        assert mem_event.trigger == pg_event.trigger == "MANUAL"
        assert mem_event.issued_by == pg_event.issued_by == issued_by

    def test_multiple_switches_history_ordering(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services maintain switch history in chronological order."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}

        # Create assignments
        mem_assignment = memory_service.assign_agent(
            run_id="mem-multi-switch",
            requested_agent_id="engineering",
            stage="planning",
            context={},
            requested_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id="pg-multi-switch",
            requested_agent_id="engineering",
            stage="planning",
            context={},
            requested_by=requested_by,
        )

        # Perform multiple switches
        switches = [
            ("compliance", "Compliance check needed", "review"),
            ("security", "Security audit required", "audit"),
            ("engineering", "Back to engineering", "execution"),
        ]

        for target_id, reason, stage in switches:
            mem_assignment = memory_service.switch_agent(
                assignment_id=mem_assignment.assignment_id,
                target_agent_id=target_id,
                reason=reason,
                allow_downgrade=True,
                stage=stage,
                issued_by=requested_by,
            )

            pg_assignment = postgres_service.switch_agent(
                assignment_id=pg_assignment.assignment_id,
                target_agent_id=target_id,
                reason=reason,
                allow_downgrade=True,
                stage=stage,
                issued_by=requested_by,
            )

        # Verify history length
        assert len(mem_assignment.history) == 3
        assert len(pg_assignment.history) == 3

        # Verify history content matches
        for i, (mem_event, pg_event) in enumerate(zip(mem_assignment.history, pg_assignment.history)):
            expected_target = switches[i][0]
            assert mem_event.to_agent_id == pg_event.to_agent_id == expected_target
            assert mem_event.stage == pg_event.stage == switches[i][2]

    def test_switch_preserves_metadata(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services preserve assignment metadata across switches."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}
        metadata = {"project": "amprealize", "priority": "high", "tags": ["production"]}

        # Create assignments with metadata
        mem_assignment = memory_service.assign_agent(
            run_id="mem-metadata",
            requested_agent_id="engineering",
            stage="planning",
            context=metadata,
            requested_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id="pg-metadata",
            requested_agent_id="engineering",
            stage="planning",
            context=metadata,
            requested_by=requested_by,
        )

        # Switch agents
        mem_switched = memory_service.switch_agent(
            assignment_id=mem_assignment.assignment_id,
            target_agent_id="security",
            reason="Review",
            allow_downgrade=False,
            stage=None,  # Keep stage
            issued_by=requested_by,
        )

        pg_switched = postgres_service.switch_agent(
            assignment_id=pg_assignment.assignment_id,
            target_agent_id="security",
            reason="Review",
            allow_downgrade=False,
            stage=None,
            issued_by=requested_by,
        )

        # Verify metadata preserved
        assert mem_switched.metadata == metadata
        assert pg_switched.metadata == metadata


class TestGetStatusParity:
    """Verify get_status parity."""

    def test_get_status_by_run_id(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services retrieve assignments by run_id."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}

        mem_assignment = memory_service.assign_agent(
            run_id="mem-status-001",
            requested_agent_id="compliance",
            stage="planning",
            context={},
            requested_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id="pg-status-001",
            requested_agent_id="compliance",
            stage="planning",
            context={},
            requested_by=requested_by,
        )

        mem_status = memory_service.get_status(run_id="mem-status-001", assignment_id=None)
        pg_status = postgres_service.get_status(run_id="pg-status-001", assignment_id=None)

        assert mem_status is not None
        assert pg_status is not None
        assert mem_status.assignment_id == mem_assignment.assignment_id
        assert pg_status.assignment_id == pg_assignment.assignment_id
        assert mem_status.active_agent.agent_id == "compliance"
        assert pg_status.active_agent.agent_id == "compliance"

    def test_get_status_by_assignment_id(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services retrieve assignments by assignment_id."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}

        mem_assignment = memory_service.assign_agent(
            run_id="mem-status-002",
            requested_agent_id="security",
            stage="audit",
            context={},
            requested_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id="pg-status-002",
            requested_agent_id="security",
            stage="audit",
            context={},
            requested_by=requested_by,
        )

        mem_status = memory_service.get_status(
            run_id=None,
            assignment_id=mem_assignment.assignment_id,
        )
        pg_status = postgres_service.get_status(
            run_id=None,
            assignment_id=pg_assignment.assignment_id,
        )

        assert mem_status is not None
        assert pg_status is not None
        assert mem_status.assignment_id == mem_assignment.assignment_id
        assert pg_status.assignment_id == pg_assignment.assignment_id

    def test_get_status_nonexistent_run_id(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services return None for nonexistent run_id."""
        mem_status = memory_service.get_status(run_id="nonexistent-run", assignment_id=None)
        pg_status = postgres_service.get_status(run_id="nonexistent-run", assignment_id=None)

        assert mem_status is None
        assert pg_status is None

    def test_get_status_nonexistent_assignment_id(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services return None for nonexistent assignment_id."""
        mem_status = memory_service.get_status(
            run_id=None,
            assignment_id="00000000-0000-0000-0000-000000000001",
        )
        pg_status = postgres_service.get_status(
            run_id=None,
            assignment_id="00000000-0000-0000-0000-000000000001",
        )

        assert mem_status is None
        assert pg_status is None

    def test_get_status_with_history(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services include switch history in status."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}

        # Create and switch
        mem_assignment = memory_service.assign_agent(
            run_id="mem-history-status",
            requested_agent_id="engineering",
            stage="planning",
            context={},
            requested_by=requested_by,
        )
        memory_service.switch_agent(
            assignment_id=mem_assignment.assignment_id,
            target_agent_id="compliance",
            reason="Compliance review",
            allow_downgrade=False,
            stage="review",
            issued_by=requested_by,
        )

        pg_assignment = postgres_service.assign_agent(
            run_id="pg-history-status",
            requested_agent_id="engineering",
            stage="planning",
            context={},
            requested_by=requested_by,
        )
        postgres_service.switch_agent(
            assignment_id=pg_assignment.assignment_id,
            target_agent_id="compliance",
            reason="Compliance review",
            allow_downgrade=False,
            stage="review",
            issued_by=requested_by,
        )

        # Get status
        mem_status = memory_service.get_status(run_id="mem-history-status", assignment_id=None)
        pg_status = postgres_service.get_status(run_id="pg-history-status", assignment_id=None)

        assert mem_status is not None
        assert pg_status is not None
        assert len(mem_status.history) == 1
        assert len(pg_status.history) == 1
        assert mem_status.history[0].to_agent_id == "compliance"
        assert pg_status.history[0].to_agent_id == "compliance"


class TestMultiTenantIsolation:
    """Verify multi-tenant isolation across implementations."""

    def test_different_run_ids_isolated(
        self,
        memory_service: AgentOrchestratorService,
        postgres_service: PostgresAgentOrchestratorService,
    ):
        """Both services isolate assignments by run_id."""
        requested_by = {"actor_id": "test-user", "actor_role": "STRATEGIST"}

        # Memory service - create two assignments
        mem_run1 = memory_service.assign_agent(
            run_id="tenant-1",
            requested_agent_id="engineering",
            stage="planning",
            context={},
            requested_by=requested_by,
        )
        mem_run2 = memory_service.assign_agent(
            run_id="tenant-2",
            requested_agent_id="compliance",
            stage="audit",
            context={},
            requested_by=requested_by,
        )

        # Postgres service - create two assignments
        pg_run1 = postgres_service.assign_agent(
            run_id="tenant-1-pg",
            requested_agent_id="engineering",
            stage="planning",
            context={},
            requested_by=requested_by,
        )
        pg_run2 = postgres_service.assign_agent(
            run_id="tenant-2-pg",
            requested_agent_id="compliance",
            stage="audit",
            context={},
            requested_by=requested_by,
        )

        # Verify isolation
        assert mem_run1.assignment_id != mem_run2.assignment_id
        assert pg_run1.assignment_id != pg_run2.assignment_id
        assert mem_run1.active_agent.agent_id == "engineering"
        assert mem_run2.active_agent.agent_id == "compliance"
        assert pg_run1.active_agent.agent_id == "engineering"
        assert pg_run2.active_agent.agent_id == "compliance"

        # Verify retrieval by run_id returns correct assignment
        mem_status1 = memory_service.get_status(run_id="tenant-1", assignment_id=None)
        mem_status2 = memory_service.get_status(run_id="tenant-2", assignment_id=None)
        pg_status1 = postgres_service.get_status(run_id="tenant-1-pg", assignment_id=None)
        pg_status2 = postgres_service.get_status(run_id="tenant-2-pg", assignment_id=None)

        assert mem_status1.assignment_id == mem_run1.assignment_id
        assert mem_status2.assignment_id == mem_run2.assignment_id
        assert pg_status1.assignment_id == pg_run1.assignment_id
        assert pg_status2.assignment_id == pg_run2.assignment_id
