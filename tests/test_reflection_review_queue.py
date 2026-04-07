"""Tests for reflection review queue: list, approve, reject candidates.

This module tests the review queue functionality across surfaces:
- CLI adapter (CLIReflectionAdapter)
- REST adapter (RestReflectionAdapter)
- MCP adapter (MCPReflectionServiceAdapter)

Covers T4.2.2: Review queue + MCP tools implementation.
"""

from __future__ import annotations

import pytest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from datetime import datetime, timezone

pytestmark = pytest.mark.unit


@dataclass
class MockReflectionCandidate:
    """Mock reflection candidate for testing."""

    id: str
    name: str
    slug: str
    confidence: float
    status: str
    role: str
    created_at: Any = None
    # MCP adapter expected fields
    summary: str = ""
    triggers: List[str] = None  # type: ignore[assignment]
    steps: List[str] = None  # type: ignore[assignment]
    keywords: List[str] = None  # type: ignore[assignment]
    reviewed_by: Optional[str] = None
    reviewed_at: Any = None
    merged_behavior_id: Optional[str] = None
    updated_at: Any = None

    def __post_init__(self) -> None:
        if self.triggers is None:
            self.triggers = []
        if self.steps is None:
            self.steps = []
        if self.keywords is None:
            self.keywords = []
        if self.created_at is None:
            self.created_at = datetime(2026, 3, 19, 10, 0, 0, tzinfo=timezone.utc)

    # Alias for MCP adapter compatibility
    @property
    def candidate_id(self) -> str:
        return self.id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "candidate_id": self.id,
            "name": self.name,
            "slug": self.slug,
            "confidence": self.confidence,
            "status": self.status,
            "role": self.role,
            "created_at": self.created_at,
        }


class MockPostgresReflectionService:
    """Mock PostgresReflectionService with list/approve/reject methods."""

    def __init__(self) -> None:
        self._candidates: List[MockReflectionCandidate] = [
            MockReflectionCandidate(
                id="cand-001",
                name="behavior_validate_inputs",
                slug="behavior_validate_inputs",
                confidence=0.85,
                status="proposed",
                role="Student",
            ),
            MockReflectionCandidate(
                id="cand-002",
                name="behavior_log_errors",
                slug="behavior_log_errors",
                confidence=0.72,
                status="proposed",
                role="Teacher",
            ),
            MockReflectionCandidate(
                id="cand-003",
                name="behavior_cache_results",
                slug="behavior_cache_results",
                confidence=0.65,
                status="approved",
                role="Student",
            ),
        ]

    def list_candidates(
        self,
        status: Optional[str] = None,
        role: Optional[str] = None,
        min_confidence: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MockReflectionCandidate]:
        """List candidates with optional filters."""
        result = self._candidates

        if status:
            result = [c for c in result if c.status == status]
        if role:
            result = [c for c in result if c.role == role]
        if min_confidence is not None:
            result = [c for c in result if c.confidence >= min_confidence]

        return result[offset : offset + limit]

    def get_candidate(self, candidate_id: str) -> Optional[MockReflectionCandidate]:
        """Get a single candidate by ID."""
        for c in self._candidates:
            if c.id == candidate_id:
                return c
        return None

    def approve_candidate(
        self,
        candidate_id: str,
        reviewed_by: str,
        merged_behavior_id: Optional[str] = None,
    ) -> MockReflectionCandidate:
        """Approve a candidate."""
        for c in self._candidates:
            if c.id == candidate_id:
                c.status = "approved"
                c.reviewed_by = reviewed_by
                if merged_behavior_id:
                    c.merged_behavior_id = merged_behavior_id
                return c
        raise ValueError(f"Candidate {candidate_id} not found")

    def reject_candidate(
        self,
        candidate_id: str,
        reviewed_by: str,
        reason: Optional[str] = None,
    ) -> MockReflectionCandidate:
        """Reject a candidate."""
        for c in self._candidates:
            if c.id == candidate_id:
                c.status = "rejected"
                c.reviewed_by = reviewed_by
                return c
        raise ValueError(f"Candidate {candidate_id} not found")

    def reflect(self, request: Any) -> Any:
        """Mock reflect method for base functionality."""
        return MagicMock(to_dict=lambda: {"candidates": [], "summary": "Mock"})


class TestCLIReflectionAdapterListCandidates:
    """Tests for CLIReflectionAdapter.list_candidates."""

    def test_list_candidates_returns_all(self) -> None:
        """Should return all candidates when no filters."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.list_candidates({})

        assert "candidates" in result
        assert result["total"] == 3
        assert len(result["candidates"]) == 3

    def test_list_candidates_filter_by_status(self) -> None:
        """Should filter candidates by status."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.list_candidates({"status": "proposed"})

        assert result["total"] == 2
        for c in result["candidates"]:
            assert c["status"] == "proposed"

    def test_list_candidates_filter_by_role(self) -> None:
        """Should filter candidates by role."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.list_candidates({"role": "Student"})

        assert result["total"] == 2
        for c in result["candidates"]:
            assert c["role"] == "Student"

    def test_list_candidates_filter_by_min_confidence(self) -> None:
        """Should filter candidates by minimum confidence."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.list_candidates({"min_confidence": 0.8})

        assert result["total"] == 1
        assert result["candidates"][0]["confidence"] >= 0.8

    def test_list_candidates_pagination(self) -> None:
        """Should support pagination via limit and offset."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.list_candidates({"limit": 2, "offset": 1})

        assert result["total"] == 2  # Returns count of paginated results

    def test_list_candidates_without_postgres_service(self) -> None:
        """Should return empty result with message when PostgreSQL not available."""
        from amprealize.adapters import CLIReflectionAdapter
        from amprealize.reflection_service import ReflectionService

        # Use base ReflectionService which doesn't have list_candidates
        service = ReflectionService()
        adapter = CLIReflectionAdapter(service)

        result = adapter.list_candidates({})

        assert result["candidates"] == []
        assert result["total"] == 0
        assert "PostgreSQL" in result.get("message", "")


class TestCLIReflectionAdapterApprove:
    """Tests for CLIReflectionAdapter.approve_candidate."""

    def test_approve_candidate_success(self) -> None:
        """Should approve a candidate successfully."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.approve_candidate({
            "candidate_id": "cand-001",
            "reviewed_by": "test-reviewer",
        })

        assert result["success"] is True
        assert result["candidate_id"] == "cand-001"
        assert result["status"] == "approved"

    def test_approve_candidate_auto_approved_flag(self) -> None:
        """Should set auto_approved flag for high-confidence candidates."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        # cand-001 has confidence 0.85 >= 0.8 threshold
        result = adapter.approve_candidate({
            "candidate_id": "cand-001",
            "reviewed_by": "test-reviewer",
        })

        assert result["success"] is True
        assert result.get("auto_approved") is True

    def test_approve_candidate_missing_id(self) -> None:
        """Should fail when candidate_id is missing."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.approve_candidate({"reviewed_by": "test-reviewer"})

        assert result["success"] is False
        assert "required" in result["message"].lower()

    def test_approve_candidate_not_found(self) -> None:
        """Should fail gracefully when candidate not found."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.approve_candidate({
            "candidate_id": "nonexistent",
            "reviewed_by": "test-reviewer",
        })

        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_approve_candidate_without_postgres_service(self) -> None:
        """Should return error when PostgreSQL not available."""
        from amprealize.adapters import CLIReflectionAdapter
        from amprealize.reflection_service import ReflectionService

        service = ReflectionService()
        adapter = CLIReflectionAdapter(service)

        result = adapter.approve_candidate({
            "candidate_id": "cand-001",
            "reviewed_by": "test-reviewer",
        })

        assert result["success"] is False
        assert "PostgreSQL" in result["message"]


class TestCLIReflectionAdapterReject:
    """Tests for CLIReflectionAdapter.reject_candidate."""

    def test_reject_candidate_success(self) -> None:
        """Should reject a candidate successfully."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.reject_candidate({
            "candidate_id": "cand-001",
            "reviewed_by": "test-reviewer",
            "reason": "Duplicate of existing behavior",
        })

        assert result["success"] is True
        assert result["candidate_id"] == "cand-001"
        assert result["status"] == "rejected"
        assert result["reason"] == "Duplicate of existing behavior"

    def test_reject_candidate_without_reason(self) -> None:
        """Should allow rejection without a reason."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.reject_candidate({
            "candidate_id": "cand-002",
            "reviewed_by": "test-reviewer",
        })

        assert result["success"] is True
        assert result["reason"] is None

    def test_reject_candidate_missing_id(self) -> None:
        """Should fail when candidate_id is missing."""
        from amprealize.adapters import CLIReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = CLIReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.reject_candidate({"reviewed_by": "test-reviewer"})

        assert result["success"] is False
        assert "required" in result["message"].lower()


class TestRestReflectionAdapterListCandidates:
    """Tests for RestReflectionAdapter.list_candidates."""

    def test_list_candidates_returns_formatted_response(self) -> None:
        """Should return properly formatted response for REST."""
        from amprealize.adapters import RestReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = RestReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.list_candidates({"limit": 10})

        assert "candidates" in result
        assert "total" in result
        assert isinstance(result["candidates"], list)

    def test_list_candidates_combined_filters(self) -> None:
        """Should support combining multiple filters."""
        from amprealize.adapters import RestReflectionAdapter

        service = MockPostgresReflectionService()
        adapter = RestReflectionAdapter(service)  # type: ignore[arg-type]

        result = adapter.list_candidates({
            "status": "proposed",
            "role": "Student",
            "min_confidence": 0.8,
        })

        assert result["total"] == 1
        assert result["candidates"][0]["name"] == "behavior_validate_inputs"


class TestMCPReflectionServiceAdapterListCandidates:
    """Tests for MCPReflectionServiceAdapter.list_candidates."""

    def test_list_candidates_mcp_format(self) -> None:
        """Should return MCP-formatted response."""
        from amprealize.adapters import MCPReflectionServiceAdapter

        service = MockPostgresReflectionService()
        adapter = MCPReflectionServiceAdapter(service=service)  # type: ignore[arg-type]

        result = adapter.list_candidates({})

        assert "candidates" in result
        assert "total" in result

    def test_list_candidates_respects_filters(self) -> None:
        """Should apply status filter in MCP context."""
        from amprealize.adapters import MCPReflectionServiceAdapter

        service = MockPostgresReflectionService()
        adapter = MCPReflectionServiceAdapter(service=service)  # type: ignore[arg-type]

        result = adapter.list_candidates({"status": "approved"})

        assert result["total"] == 1
        assert result["candidates"][0]["status"] == "approved"


class TestMCPReflectionServiceAdapterApprove:
    """Tests for MCPReflectionServiceAdapter.approve_candidate."""

    def test_approve_candidate_success(self) -> None:
        """Should approve via MCP adapter."""
        from amprealize.adapters import MCPReflectionServiceAdapter

        service = MockPostgresReflectionService()
        adapter = MCPReflectionServiceAdapter(service=service)  # type: ignore[arg-type]

        result = adapter.approve_candidate({
            "candidate_id": "cand-001",
            "reviewed_by": "mcp-user",
        })

        assert result["success"] is True
        assert result["candidate_id"] == "cand-001"

    def test_approve_candidate_auto_approved_high_confidence(self) -> None:
        """Should set auto_approved flag for high-confidence candidates."""
        from amprealize.adapters import MCPReflectionServiceAdapter

        service = MockPostgresReflectionService()
        adapter = MCPReflectionServiceAdapter(service=service)  # type: ignore[arg-type]

        # cand-001 has confidence 0.85 >= 0.8 threshold
        result = adapter.approve_candidate({
            "candidate_id": "cand-001",
            "reviewed_by": "mcp-user",
        })

        assert result["success"] is True
        assert result["auto_approved"] is True


class TestMCPReflectionServiceAdapterReject:
    """Tests for MCPReflectionServiceAdapter.reject_candidate."""

    def test_reject_candidate_success(self) -> None:
        """Should reject via MCP adapter."""
        from amprealize.adapters import MCPReflectionServiceAdapter

        service = MockPostgresReflectionService()
        adapter = MCPReflectionServiceAdapter(service=service)  # type: ignore[arg-type]

        result = adapter.reject_candidate({
            "candidate_id": "cand-002",
            "reviewed_by": "mcp-user",
            "reason": "Too vague",
        })

        assert result["success"] is True
        assert result["candidate_id"] == "cand-002"


class TestCLIReflectionSubcommands:
    """Integration tests for CLI reflection subcommands."""

    def test_reflection_command_shows_help_without_subcommand(self) -> None:
        """Should show usage help when no subcommand provided."""
        import io
        import sys
        from amprealize.cli import main

        # Capture stdout
        captured = io.StringIO()
        with patch.object(sys, "stdout", captured):
            result = main(["reflection"])

        output = captured.getvalue()
        assert result == 0
        assert "extract" in output
        assert "list" in output
        assert "approve" in output
        assert "reject" in output

    def test_reflection_extract_requires_trace(self) -> None:
        """Should require --trace or --trace-file for extract."""
        import io
        import sys
        from amprealize.cli import main

        captured = io.StringIO()
        with patch.object(sys, "stderr", captured):
            result = main(["reflection", "extract"])

        assert result == 2
        assert "trace" in captured.getvalue().lower()

    def test_reflection_list_default_values(self) -> None:
        """Should use default values for list subcommand."""
        from amprealize.cli import _get_reflection_adapter
        import argparse

        with patch("amprealize.cli._get_reflection_adapter") as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.list_candidates.return_value = {"candidates": [], "total": 0}
            mock_get_adapter.return_value = mock_adapter

            from amprealize.cli import _command_reflection_list

            args = argparse.Namespace(
                limit=50,
                offset=0,
                status=None,
                role=None,
                min_confidence=None,
                output="table",
            )

            result = _command_reflection_list(args)

            assert result == 0
            mock_adapter.list_candidates.assert_called_once()
            call_payload = mock_adapter.list_candidates.call_args[0][0]
            assert call_payload["limit"] == 50
            assert call_payload["offset"] == 0
