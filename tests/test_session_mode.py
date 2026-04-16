"""Tests for Session Mode — lightweight 3-phase agent execution.

Covers:
- AgentExecutionMode enum
- ExecutionPolicy.for_session_mode() factory method
- SessionModeExecutor delegation
- AgentExecutionLoop.run() with execution_mode=SESSION
- _get_next_phase() with session skip_phases

GUIDEAI-901, GUIDEAI-909, GUIDEAI-911
"""

from __future__ import annotations

import asyncio
import pytest
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from amprealize.work_item_execution_contracts import (
    AgentExecutionMode,
    ExecutionPolicy,
    GatePolicyType,
    InternetAccessPolicy,
)
from amprealize.task_cycle_contracts import (
    CyclePhase,
    PHASE_GATES,
    VALID_TRANSITIONS,
)
from amprealize.mode_executors import SessionModeExecutor

pytestmark = pytest.mark.unit


# =============================================================================
# AgentExecutionMode enum
# =============================================================================


class TestAgentExecutionMode:
    """Tests for the AgentExecutionMode enum."""

    def test_values(self):
        assert AgentExecutionMode.GEP.value == "gep"
        assert AgentExecutionMode.SESSION.value == "session"

    def test_is_string_enum(self):
        assert isinstance(AgentExecutionMode.GEP, str)
        assert isinstance(AgentExecutionMode.SESSION, str)

    def test_from_string(self):
        assert AgentExecutionMode("gep") == AgentExecutionMode.GEP
        assert AgentExecutionMode("session") == AgentExecutionMode.SESSION


# =============================================================================
# ExecutionPolicy.for_session_mode()
# =============================================================================


class TestSessionModePolicy:
    """Tests for ExecutionPolicy.for_session_mode() factory."""

    def test_skip_phases(self):
        policy = ExecutionPolicy.for_session_mode()
        expected_skips = {"clarifying", "architecting", "testing", "fixing", "verifying"}
        assert policy.skip_phases == expected_skips

    def test_only_three_phases_remain(self):
        """Session Mode should produce a 3-phase flow: PLANNING → EXECUTING → COMPLETING."""
        policy = ExecutionPolicy.for_session_mode()
        all_phases = {p.value for p in CyclePhase if p.value not in (
            "completed", "cancelled", "failed",
        )}
        active_phases = all_phases - policy.skip_phases
        assert active_phases == {"planning", "executing", "completing"}

    def test_gates_are_soft_or_none(self):
        """No gate should be STRICT in session mode."""
        policy = ExecutionPolicy.for_session_mode()
        for phase, gate in policy.phase_gates.items():
            assert gate in (GatePolicyType.NONE, GatePolicyType.SOFT), (
                f"Phase {phase} has gate {gate}, expected NONE or SOFT"
            )

    def test_internet_enabled(self):
        policy = ExecutionPolicy.for_session_mode()
        assert policy.internet_access == InternetAccessPolicy.ENABLED

    def test_workspace_not_required(self):
        policy = ExecutionPolicy.for_session_mode()
        assert policy.require_workspace is False

    def test_follows_factory_pattern(self):
        """for_session_mode returns same type as other factory methods."""
        session = ExecutionPolicy.for_session_mode()
        research = ExecutionPolicy.for_research_agent()
        assert type(session) is type(research) is ExecutionPolicy


# =============================================================================
# Session Mode skip_phases with _get_next_phase
# =============================================================================


class TestSessionModePhaseFlow:
    """Test that session skip_phases produces correct phase transitions."""

    def _get_next_non_skipped(
        self, current: CyclePhase, skip_phases: set, visited: set | None = None,
    ) -> CyclePhase | None:
        """Simulate find_next_non_skipped logic from _get_next_phase.

        Mirrors the real implementation: skip terminal states, track visited
        to prevent infinite recursion on self-loops and cycles.
        """
        if current.value not in skip_phases:
            return current
        if visited is None:
            visited = set()
        if current in visited:
            return None
        visited = visited | {current}
        for successor in VALID_TRANSITIONS.get(current, []):
            if successor in (CyclePhase.CANCELLED, CyclePhase.FAILED):
                continue
            result = self._get_next_non_skipped(successor, skip_phases, visited)
            if result:
                return result
        return None

    def _first_candidate(self, current: CyclePhase) -> CyclePhase | None:
        """Get the first non-terminal successor (what _get_next_phase picks by default)."""
        for phase in VALID_TRANSITIONS.get(current, []):
            if phase not in (CyclePhase.CANCELLED, CyclePhase.FAILED):
                return phase
        return None

    def test_planning_to_executing(self):
        """PLANNING should jump to EXECUTING, skipping CLARIFYING and ARCHITECTING."""
        policy = ExecutionPolicy.for_session_mode()
        candidate = self._first_candidate(CyclePhase.PLANNING)
        next_phase = self._get_next_non_skipped(candidate, policy.skip_phases)
        assert next_phase == CyclePhase.EXECUTING

    def test_executing_to_completing(self):
        """EXECUTING should jump to COMPLETING, skipping TESTING/FIXING/VERIFYING."""
        policy = ExecutionPolicy.for_session_mode()
        candidate = self._first_candidate(CyclePhase.EXECUTING)
        next_phase = self._get_next_non_skipped(candidate, policy.skip_phases)
        assert next_phase == CyclePhase.COMPLETING

    def test_full_session_flow(self):
        """Walk the complete session flow: PLANNING → EXECUTING → COMPLETING."""
        policy = ExecutionPolicy.for_session_mode()
        flow = [CyclePhase.PLANNING]
        current = CyclePhase.PLANNING
        while True:
            candidate = self._first_candidate(current)
            if candidate is None:
                break
            nxt = self._get_next_non_skipped(candidate, policy.skip_phases)
            if nxt is None:
                break
            flow.append(nxt)
            current = nxt
        assert flow == [
            CyclePhase.PLANNING,
            CyclePhase.EXECUTING,
            CyclePhase.COMPLETING,
            CyclePhase.COMPLETED,
        ]


# =============================================================================
# SessionModeExecutor
# =============================================================================


class TestSessionModeExecutor:
    """Tests for the SessionModeExecutor wrapper."""

    def test_execute_passes_session_mode(self):
        """SessionModeExecutor should pass execution_mode=SESSION to the loop."""
        loop = AsyncMock()
        loop.run = AsyncMock(return_value={"status": "completed"})

        request = SimpleNamespace(
            user_id="u1",
            org_id="org1",
            project_id="proj1",
        )
        resolved = SimpleNamespace(
            run_id="run-123",
            cycle_id="cyc-123",
            request=request,
            model_id="claude-opus-4-6",
        )

        executor = SessionModeExecutor()
        result = asyncio.get_event_loop().run_until_complete(
            executor.execute(
                resolved, loop,
                work_item=MagicMock(),
                agent=MagicMock(),
                agent_version=MagicMock(),
                exec_policy=ExecutionPolicy.for_session_mode(),
            )
        )

        loop.run.assert_called_once()
        call_kwargs = loop.run.call_args.kwargs
        assert call_kwargs["execution_mode"] == AgentExecutionMode.SESSION
        assert call_kwargs["run_id"] == "run-123"

    def test_setup_delegates_to_inner(self):
        """setup() should delegate to inner executor if present."""
        inner = AsyncMock()
        inner.setup = AsyncMock()
        executor = SessionModeExecutor(inner_executor=inner)

        resolved = SimpleNamespace(run_id="run-1")
        asyncio.get_event_loop().run_until_complete(executor.setup(resolved))
        inner.setup.assert_called_once_with(resolved)

    def test_setup_noop_without_inner(self):
        """setup() should be a no-op when no inner executor."""
        executor = SessionModeExecutor()
        resolved = SimpleNamespace(run_id="run-1")
        asyncio.get_event_loop().run_until_complete(executor.setup(resolved))

    def test_cleanup_delegates_to_inner(self):
        """cleanup() should delegate to inner executor if present."""
        inner = AsyncMock()
        inner.cleanup = AsyncMock()
        executor = SessionModeExecutor(inner_executor=inner)

        resolved = SimpleNamespace(run_id="run-1")
        asyncio.get_event_loop().run_until_complete(executor.cleanup(resolved))
        inner.cleanup.assert_called_once_with(resolved)

    def test_cleanup_noop_without_inner(self):
        """cleanup() should be a no-op when no inner executor."""
        executor = SessionModeExecutor()
        resolved = SimpleNamespace(run_id="run-1")
        asyncio.get_event_loop().run_until_complete(executor.cleanup(resolved))


# =============================================================================
# ExecutionPolicy comparison: Session vs GEP vs Research
# =============================================================================


class TestSessionModeComparison:
    """Compare session mode with other execution policies."""

    def test_session_skips_more_than_research(self):
        """Session mode should skip more phases than research agent."""
        session = ExecutionPolicy.for_session_mode()
        research = ExecutionPolicy.for_research_agent()
        assert session.skip_phases > research.skip_phases

    def test_session_skips_more_than_architect(self):
        """Session mode should skip more phases than architect agent."""
        session = ExecutionPolicy.for_session_mode()
        architect = ExecutionPolicy.for_architect_agent()
        assert session.skip_phases > architect.skip_phases

    def test_engineering_skips_nothing(self):
        """Engineering agent should not skip any phases."""
        engineering = ExecutionPolicy.for_engineering_agent()
        assert engineering.skip_phases == set()

    def test_session_has_no_strict_gates(self):
        """Session mode never blocks on gates (no STRICT)."""
        session = ExecutionPolicy.for_session_mode()
        assert GatePolicyType.STRICT not in session.phase_gates.values()

    def test_engineering_has_strict_verifying(self):
        """Engineering has STRICT verifying gate — session does not."""
        engineering = ExecutionPolicy.for_engineering_agent()
        session = ExecutionPolicy.for_session_mode()
        assert engineering.phase_gates.get("verifying") == GatePolicyType.STRICT
        assert session.phase_gates.get("verifying") != GatePolicyType.STRICT
