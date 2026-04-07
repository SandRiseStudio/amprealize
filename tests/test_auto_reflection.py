"""Tests for the E4 auto-reflection trigger in AgentExecutionLoop.

Verifies that _try_post_run_reflection fires correctly after
successful run completion, gated by the feature.auto_reflection flag.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from amprealize.task_cycle_contracts import CyclePhase

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def _make_phase_outputs() -> Dict[CyclePhase, Dict[str, Any]]:
    """Build a representative set of phase outputs for a completed run."""
    return {
        CyclePhase.PLANNING: {
            "plan": "1. Parse user input\n2. Validate schema\n3. Persist to DB",
        },
        CyclePhase.ARCHITECTING: {
            "summary": "Chose layered architecture with service/repository split",
        },
        CyclePhase.EXECUTING: {
            "summary": "Implemented UserService.create() with Pydantic validation",
            "files_changed": 3,
        },
        CyclePhase.TESTING: {
            "summary": "Added 4 unit tests covering happy path and validation errors",
        },
        CyclePhase.COMPLETING: {
            "summary": "All phases passed. PR #42 created.",
            "completed_at": "2026-03-19T12:00:00Z",
        },
    }


def _build_loop(**overrides: Any):
    """Build an AgentExecutionLoop with mocked dependencies."""
    from amprealize.agent_execution_loop import AgentExecutionLoop

    defaults = dict(
        run_service=MagicMock(),
        task_cycle_service=MagicMock(),
        telemetry=MagicMock(),
        bci_service=MagicMock(),
    )
    defaults.update(overrides)
    return AgentExecutionLoop(**defaults)


def _build_loop_with_flag(auto_reflection_enabled: bool, **overrides: Any):
    """Build a loop with auto_reflection flag set explicitly."""
    from amprealize.feature_flags import FeatureFlag, FeatureFlagService

    svc = FeatureFlagService(flags=[
        FeatureFlag(name="feature.auto_reflection", enabled=auto_reflection_enabled),
        FeatureFlag(name="feature.early_knowledge_alignment", enabled=True),
    ])
    return _build_loop(feature_flag_service=svc, **overrides)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAutoReflectionGating:
    """Verify the feature-flag gating behaviour."""

    def test_reflection_skipped_when_flag_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When feature.auto_reflection is disabled, _try_post_run_reflection is a no-op."""
        loop = _build_loop_with_flag(auto_reflection_enabled=False)
        loop._run_post_run_reflection = MagicMock()

        loop._try_post_run_reflection("run-123", _make_phase_outputs())

        loop._run_post_run_reflection.assert_not_called()

    def test_reflection_fires_when_flag_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When feature.auto_reflection is enabled, reflection runs."""
        loop = _build_loop_with_flag(auto_reflection_enabled=True)
        loop._run_post_run_reflection = MagicMock()

        loop._try_post_run_reflection("run-456", _make_phase_outputs())

        loop._run_post_run_reflection.assert_called_once_with("run-456", _make_phase_outputs())


class TestAutoReflectionExecution:
    """Verify the reflection pipeline is invoked correctly."""

    def test_builds_trace_from_phase_outputs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Trace text should concatenate phase summaries in order."""
        mock_reflect_response = MagicMock()
        mock_reflect_response.candidates = []

        mock_reflection_svc = MagicMock()
        mock_reflection_svc.reflect.return_value = mock_reflect_response

        loop = _build_loop_with_flag(auto_reflection_enabled=True)

        with patch("amprealize.reflection_service.ReflectionService", return_value=mock_reflection_svc):
            loop._run_post_run_reflection("run-789", _make_phase_outputs())

        # ReflectionService.reflect should have been called
        mock_reflection_svc.reflect.assert_called_once()
        request = mock_reflection_svc.reflect.call_args[0][0]

        # Trace text should include content from multiple phases
        assert "[PLANNING]" in request.trace_text
        assert "[ARCHITECTING]" in request.trace_text
        assert "[EXECUTING]" in request.trace_text
        assert "[COMPLETING]" in request.trace_text
        assert request.run_id == "run-789"

    def test_emits_telemetry_for_each_candidate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each reflection candidate should emit a typed telemetry event."""
        from amprealize.reflection_contracts import (
            ReflectionCandidate,
            ReflectionQualityScores,
            ReflectResponse,
        )

        mock_candidate = ReflectionCandidate(
            slug="behavior_parse_user_input",
            display_name="Parse User Input",
            instruction="Parse and validate user input before persistence.",
            summary="Input parsing pattern",
            supporting_steps=["Parse user input", "Validate schema"],
            examples=[],
            quality_scores=ReflectionQualityScores(
                clarity=0.85, generality=0.7, reusability=0.8, correctness=0.9,
            ),
            confidence=0.82,
            tags=["parse", "input", "validation"],
        )
        mock_response = ReflectResponse(
            run_id="run-tel",
            trace_step_count=5,
            candidates=[mock_candidate],
            summary="1 candidate extracted",
        )

        mock_reflection_svc = MagicMock()
        mock_reflection_svc.reflect.return_value = mock_response

        telemetry = MagicMock()
        loop = _build_loop_with_flag(auto_reflection_enabled=True, telemetry=telemetry)

        with patch("amprealize.reflection_service.ReflectionService", return_value=mock_reflection_svc), \
             patch.object(loop, "_persist_reflection_candidates"):
            loop._run_post_run_reflection("run-tel", _make_phase_outputs())

        # Should emit reflection.candidate_extracted event
        telemetry.emit_event.assert_called()
        call_kwargs = telemetry.emit_event.call_args_list[-1][1]
        assert call_kwargs["event_type"] == "reflection.candidate_extracted"
        assert call_kwargs["payload"]["candidate_id"] == "behavior_parse_user_input"
        assert call_kwargs["payload"]["confidence"] == 0.82

    def test_no_candidates_no_telemetry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When reflection produces no candidates, telemetry is not emitted."""
        mock_response = MagicMock()
        mock_response.candidates = []

        mock_reflection_svc = MagicMock()
        mock_reflection_svc.reflect.return_value = mock_response

        telemetry = MagicMock()
        loop = _build_loop_with_flag(auto_reflection_enabled=True, telemetry=telemetry)

        with patch("amprealize.reflection_service.ReflectionService", return_value=mock_reflection_svc):
            loop._run_post_run_reflection("run-empty", _make_phase_outputs())

        telemetry.emit_event.assert_not_called()

    def test_empty_phase_outputs_skips_reflection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no phase has summary/plan content, reflection is skipped."""
        loop = _build_loop_with_flag(auto_reflection_enabled=True)

        with patch("amprealize.reflection_service.ReflectionService") as mock_cls:
            loop._run_post_run_reflection("run-noop", {})

        mock_cls.assert_not_called()


class TestAutoReflectionErrorHandling:
    """Verify that reflection failures don't block run completion."""

    def test_reflection_exception_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If reflection raises, _try_post_run_reflection swallows it."""
        loop = _build_loop_with_flag(auto_reflection_enabled=True)
        loop._run_post_run_reflection = MagicMock(side_effect=RuntimeError("boom"))

        # Should not raise
        loop._try_post_run_reflection("run-err", _make_phase_outputs())

    def test_persistence_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If PostgresReflectionService fails, it's caught and logged."""
        from amprealize.reflection_contracts import (
            ReflectionCandidate,
            ReflectionQualityScores,
            ReflectResponse,
        )

        mock_candidate = ReflectionCandidate(
            slug="behavior_test",
            display_name="Test",
            instruction="Test instruction.",
            summary="Test summary",
            supporting_steps=["Step 1"],
            examples=[],
            quality_scores=ReflectionQualityScores(
                clarity=0.8, generality=0.7, reusability=0.75, correctness=0.9,
            ),
            confidence=0.75,
            tags=["test"],
        )
        mock_response = ReflectResponse(
            run_id="run-pfail",
            trace_step_count=3,
            candidates=[mock_candidate],
        )

        mock_reflection_svc = MagicMock()
        mock_reflection_svc.reflect.return_value = mock_response

        loop = _build_loop_with_flag(auto_reflection_enabled=True)

        with patch("amprealize.reflection_service.ReflectionService", return_value=mock_reflection_svc), \
             patch.object(loop, "_persist_reflection_candidates", side_effect=RuntimeError("DB connection failed")):
            # Should NOT raise despite persistence failure
            loop._try_post_run_reflection("run-pfail", _make_phase_outputs())
