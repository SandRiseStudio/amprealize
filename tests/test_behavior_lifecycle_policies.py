"""Tests for T4.2.3 — Behavior lifecycle policies.

Covers:
- BehaviorService.promote_candidate_to_behavior()
- BehaviorService.list_expiring_behaviors()
- BehaviorService.flag_stale_behaviors()
- BehaviorService.check_overlay_compliance()
- MCP adapter candidate-to-behavior promotion wiring
- CLI adapter candidate-to-behavior promotion wiring
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

@dataclass
class MockStoredCandidate:
    """Minimal stored candidate for testing promotion."""
    id: str = "cand-001"
    name: str = "behavior_cache_invalidation"
    summary: str = "Invalidate cache after writes"
    triggers: List[str] = field(default_factory=lambda: ["cache", "write"])
    steps: List[str] = field(default_factory=lambda: ["Check cache", "Invalidate"])
    confidence: float = 0.85
    status: str = "approved"
    role: str = "Student"
    keywords: List[str] = field(default_factory=lambda: ["cache", "invalidation"])
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    merged_behavior_id: Optional[str] = None
    updated_at: Optional[datetime] = None
    created_at: datetime = field(
        default_factory=lambda: datetime(2026, 3, 19, 10, 0, 0, tzinfo=timezone.utc)
    )

    @property
    def candidate_id(self) -> str:
        return self.id


class MockPostgresService:
    """Mock reflection service supporting candidate ops."""

    def __init__(self) -> None:
        self._candidates: Dict[str, MockStoredCandidate] = {}
        self._behavior_service: Optional[Any] = None

    def get_candidate(self, candidate_id: str) -> Optional[MockStoredCandidate]:
        return self._candidates.get(candidate_id)

    def approve_candidate(
        self,
        candidate_id: str,
        reviewed_by: str,
        merged_behavior_id: Optional[str] = None,
    ) -> MockStoredCandidate:
        c = self._candidates.get(candidate_id)
        if not c:
            raise ValueError(f"Not found: {candidate_id}")
        c.status = "merged" if merged_behavior_id else "approved"
        c.reviewed_by = reviewed_by
        c.merged_behavior_id = merged_behavior_id
        return c

    def reject_candidate(
        self,
        candidate_id: str,
        reviewed_by: str,
        reason: Optional[str] = None,
    ) -> MockStoredCandidate:
        c = self._candidates.get(candidate_id)
        if not c:
            raise ValueError(f"Not found: {candidate_id}")
        c.status = "rejected"
        c.reviewed_by = reviewed_by
        return c

    def list_candidates(self, **kwargs: Any) -> list:
        return list(self._candidates.values())


class MockTelemetryClient:
    """Captures telemetry events for assertions."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def emit_event(self, event_type: str, payload: Any = None, actor: Any = None) -> None:
        self.events.append({"event_type": event_type, "payload": payload, "actor": actor})

    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    @classmethod
    def noop(cls) -> "MockTelemetryClient":
        return cls()


class MockPool:
    """Minimal PostgresPool mock."""

    def __init__(self, rows: Optional[list] = None) -> None:
        self._rows = rows or []
        self._transaction_calls: List[str] = []
        self._conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = self._rows
        cursor.fetchone.return_value = self._rows[0] if self._rows else None
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        self._conn.cursor.return_value = cursor
        self._conn.__enter__ = lambda s: s
        self._conn.__exit__ = MagicMock(return_value=False)

    def connection(self):
        return self._conn

    def run_transaction(self, label: str, **kwargs: Any) -> Any:
        self._transaction_calls.append(label)
        executor = kwargs.get("executor")
        if executor:
            return executor(self._conn)
        return None


class MockActor:
    """Minimal actor for BehaviorService calls."""

    def __init__(self, id: str = "test-user", type: str = "user", role: str = "developer", surface: str = "test") -> None:
        self.id = id
        self.type = type
        self.role = role
        self.surface = surface


# ============================================================================
# Tests: promote_candidate_to_behavior
# ============================================================================


class TestPromoteCandidateToBehavior:
    """BehaviorService.promote_candidate_to_behavior()."""

    def test_promote_delegates_to_propose_behavior(self) -> None:
        """Should call propose_behavior with candidate data."""
        from amprealize.behavior_service import BehaviorService

        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = MockTelemetryClient()
        service._pool = MockPool()

        # Mock propose_behavior
        service.propose_behavior = MagicMock(return_value={
            "behavior_id": "beh-123",
            "version": 1,
            "status": "APPROVED",
            "auto_approved": True,
        })

        actor = MockActor()
        result = service.promote_candidate_to_behavior(
            candidate_name="behavior_cache_invalidation",
            candidate_summary="Invalidate cache after writes",
            candidate_triggers=["cache", "write"],
            candidate_steps=["Check cache", "Invalidate"],
            candidate_keywords=["cache"],
            candidate_confidence=0.9,
            candidate_role="Student",
            actor=actor,
        )

        assert result["behavior_id"] == "beh-123"
        assert result["auto_approved"] is True
        service.propose_behavior.assert_called_once()
        call_args = service.propose_behavior.call_args
        request = call_args[0][0]
        assert request.name == "behavior_cache_invalidation"
        assert request.confidence_score == 0.9

    def test_promote_adds_prefix_if_missing(self) -> None:
        """Should add 'behavior_' prefix if not present."""
        from amprealize.behavior_service import BehaviorService

        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = MockTelemetryClient()
        service._pool = MockPool()
        service.propose_behavior = MagicMock(return_value={"behavior_id": "beh-456"})

        actor = MockActor()
        service.promote_candidate_to_behavior(
            candidate_name="cache_invalidation",
            candidate_summary="Summary",
            candidate_triggers=[],
            candidate_steps=[],
            candidate_keywords=[],
            candidate_confidence=0.5,
            actor=actor,
        )

        request = service.propose_behavior.call_args[0][0]
        assert request.name == "behavior_cache_invalidation"

    def test_promote_preserves_existing_prefix(self) -> None:
        """Should not double-prefix behavior_ names."""
        from amprealize.behavior_service import BehaviorService

        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = MockTelemetryClient()
        service._pool = MockPool()
        service.propose_behavior = MagicMock(return_value={"behavior_id": "beh-789"})

        actor = MockActor()
        service.promote_candidate_to_behavior(
            candidate_name="behavior_already_prefixed",
            candidate_summary="Summary",
            candidate_triggers=[],
            candidate_steps=[],
            candidate_keywords=[],
            candidate_confidence=0.7,
            actor=actor,
        )

        request = service.propose_behavior.call_args[0][0]
        assert request.name == "behavior_already_prefixed"

    def test_promote_joins_steps_as_instruction(self) -> None:
        """Steps list should be joined with newlines for instruction."""
        from amprealize.behavior_service import BehaviorService

        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = MockTelemetryClient()
        service._pool = MockPool()
        service.propose_behavior = MagicMock(return_value={"behavior_id": "beh-x"})

        actor = MockActor()
        service.promote_candidate_to_behavior(
            candidate_name="behavior_test",
            candidate_summary="Summary",
            candidate_triggers=[],
            candidate_steps=["Step 1", "Step 2", "Step 3"],
            candidate_keywords=[],
            candidate_confidence=0.5,
            actor=actor,
        )

        request = service.propose_behavior.call_args[0][0]
        assert request.instruction == "Step 1\nStep 2\nStep 3"


# ============================================================================
# Tests: list_expiring_behaviors
# ============================================================================


class TestListExpiringBehaviors:
    """BehaviorService.list_expiring_behaviors()."""

    def test_returns_stale_behaviors(self) -> None:
        """Should return behaviors older than the cutoff."""
        from amprealize.behavior_service import BehaviorService

        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        rows = [
            ("beh-1", "behavior_old", "Old behavior", 1, old_date, ["tag1"]),
        ]

        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = MockTelemetryClient()
        service._pool = MockPool(rows=rows)
        service._dsn = "postgresql://test"

        # Mock _ensure_connection to return pool's connection
        service._ensure_connection = lambda: service._pool.connection()

        result = service.list_expiring_behaviors(days=30)

        assert len(result) == 1
        assert result[0]["behavior_id"] == "beh-1"
        assert result[0]["name"] == "behavior_old"
        assert result[0]["stale_days"] >= 59  # ~60 days

    def test_returns_empty_when_all_fresh(self) -> None:
        """No stale behaviors should return empty list."""
        from amprealize.behavior_service import BehaviorService

        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = MockTelemetryClient()
        service._pool = MockPool(rows=[])
        service._dsn = "postgresql://test"
        service._ensure_connection = lambda: service._pool.connection()

        result = service.list_expiring_behaviors(days=30)
        assert result == []

    def test_stale_days_calculation(self) -> None:
        """Stale days should be difference between now and updated_at."""
        from amprealize.behavior_service import BehaviorService

        target_days = 45
        old_date = (datetime.now(timezone.utc) - timedelta(days=target_days)).isoformat()
        rows = [("beh-2", "behavior_stale", "Desc", 2, old_date, [])]

        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = MockTelemetryClient()
        service._pool = MockPool(rows=rows)
        service._dsn = "postgresql://test"
        service._ensure_connection = lambda: service._pool.connection()

        result = service.list_expiring_behaviors(days=30)
        assert len(result) == 1
        assert result[0]["stale_days"] >= target_days - 1  # allow 1 day tolerance


# ============================================================================
# Tests: flag_stale_behaviors
# ============================================================================


class TestFlagStaleBehaviors:
    """BehaviorService.flag_stale_behaviors()."""

    def test_emits_telemetry_for_each_flagged(self) -> None:
        """Should emit one telemetry event per flagged behavior."""
        from amprealize.behavior_service import BehaviorService

        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        rows = [
            ("beh-a", "behavior_a", "Desc A", 1, old_date, []),
            ("beh-b", "behavior_b", "Desc B", 2, old_date, []),
        ]

        telemetry = MockTelemetryClient()
        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = telemetry
        service._pool = MockPool(rows=rows)
        service._dsn = "postgresql://test"
        service._ensure_connection = lambda: service._pool.connection()

        actor = MockActor()
        result = service.flag_stale_behaviors(stale_days=90, actor=actor)

        assert result["flagged_count"] == 2
        assert len(result["flagged_behavior_ids"]) == 2
        stale_events = [e for e in telemetry.events if e["event_type"] == "behaviors.flagged_stale"]
        assert len(stale_events) == 2

    def test_returns_zero_when_none_stale(self) -> None:
        """No stale behaviors should return zero flagged."""
        from amprealize.behavior_service import BehaviorService

        telemetry = MockTelemetryClient()
        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = telemetry
        service._pool = MockPool(rows=[])
        service._dsn = "postgresql://test"
        service._ensure_connection = lambda: service._pool.connection()

        actor = MockActor()
        result = service.flag_stale_behaviors(stale_days=90, actor=actor)

        assert result["flagged_count"] == 0
        assert result["flagged_behavior_ids"] == []

    def test_threshold_days_in_response(self) -> None:
        """Response should include the threshold used."""
        from amprealize.behavior_service import BehaviorService

        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = MockTelemetryClient()
        service._pool = MockPool(rows=[])
        service._dsn = "postgresql://test"
        service._ensure_connection = lambda: service._pool.connection()

        result = service.flag_stale_behaviors(stale_days=45, actor=MockActor())
        assert result["threshold_days"] == 45


# ============================================================================
# Tests: check_overlay_compliance
# ============================================================================


class TestCheckOverlayCompliance:
    """BehaviorService.check_overlay_compliance()."""

    def test_flags_low_citation_rate(self) -> None:
        """Behaviors with low citation_rate should be flagged."""
        from amprealize.behavior_service import BehaviorService

        active_rows = [
            ("beh-x", "behavior_x", "Desc X"),
        ]

        telemetry = MockTelemetryClient()
        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = telemetry
        service._pool = MockPool(rows=active_rows)
        service._dsn = "postgresql://test"
        service._ensure_connection = lambda: service._pool.connection()

        # Mock get_effectiveness_metrics to return low citation rate
        service.get_effectiveness_metrics = MagicMock(return_value={
            "retrieval_count": 100,
            "citation_count": 10,  # 10% citation rate
        })

        actor = MockActor()
        result = service.check_overlay_compliance(
            min_citation_rate=0.3,
            lookback_days=30,
            actor=actor,
        )

        assert result["flagged_count"] == 1
        assert result["flagged_behaviors"][0]["citation_rate"] == 0.1
        compliance_events = [e for e in telemetry.events if e["event_type"] == "behaviors.poor_compliance"]
        assert len(compliance_events) == 1

    def test_does_not_flag_good_citation_rate(self) -> None:
        """Behaviors with good citation rates should not be flagged."""
        from amprealize.behavior_service import BehaviorService

        active_rows = [
            ("beh-y", "behavior_y", "Desc Y"),
        ]

        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = MockTelemetryClient()
        service._pool = MockPool(rows=active_rows)
        service._dsn = "postgresql://test"
        service._ensure_connection = lambda: service._pool.connection()

        service.get_effectiveness_metrics = MagicMock(return_value={
            "retrieval_count": 100,
            "citation_count": 80,  # 80% citation rate
        })

        result = service.check_overlay_compliance(
            min_citation_rate=0.3,
            lookback_days=30,
            actor=MockActor(),
        )

        assert result["flagged_count"] == 0

    def test_skips_zero_retrieval_count(self) -> None:
        """Behaviors with zero retrievals should not be flagged."""
        from amprealize.behavior_service import BehaviorService

        active_rows = [("beh-z", "behavior_z", "Desc Z")]

        service = BehaviorService.__new__(BehaviorService)
        service._telemetry = MockTelemetryClient()
        service._pool = MockPool(rows=active_rows)
        service._dsn = "postgresql://test"
        service._ensure_connection = lambda: service._pool.connection()

        service.get_effectiveness_metrics = MagicMock(return_value={
            "retrieval_count": 0,
            "citation_count": 0,
        })

        result = service.check_overlay_compliance(
            min_citation_rate=0.3,
            lookback_days=30,
            actor=MockActor(),
        )

        assert result["flagged_count"] == 0


# ============================================================================
# Tests: MCP adapter promotion wiring
# ============================================================================


class TestMCPAdapterPromotion:
    """MCPReflectionServiceAdapter.approve_candidate with merge_to_handbook."""

    def test_approve_with_merge_calls_promote(self) -> None:
        """When merge_to_handbook=True, should attempt to promote candidate."""
        from amprealize.adapters import MCPReflectionServiceAdapter

        service = MockPostgresService()
        candidate = MockStoredCandidate()
        service._candidates[candidate.id] = candidate

        adapter = MCPReflectionServiceAdapter(service=service)  # type: ignore[arg-type]

        # Mock _promote_candidate
        adapter._promote_candidate = MagicMock(return_value="beh-promoted-123")

        result = adapter.approve_candidate({
            "candidate_id": "cand-001",
            "reviewed_by": "reviewer-1",
            "merge_to_handbook": True,
        })

        assert result["success"] is True
        assert result["behavior_id"] == "beh-promoted-123"
        adapter._promote_candidate.assert_called_once()

    def test_approve_without_merge_skips_promote(self) -> None:
        """When merge_to_handbook=False, should NOT call _promote_candidate."""
        from amprealize.adapters import MCPReflectionServiceAdapter

        service = MockPostgresService()
        candidate = MockStoredCandidate()
        service._candidates[candidate.id] = candidate

        adapter = MCPReflectionServiceAdapter(service=service)  # type: ignore[arg-type]
        adapter._promote_candidate = MagicMock()

        result = adapter.approve_candidate({
            "candidate_id": "cand-001",
            "reviewed_by": "reviewer-1",
            "merge_to_handbook": False,
        })

        assert result["success"] is True
        assert result["behavior_id"] is None
        adapter._promote_candidate.assert_not_called()

    def test_promote_failure_returns_none_behavior_id(self) -> None:
        """If _promote_candidate fails, behavior_id should be None."""
        from amprealize.adapters import MCPReflectionServiceAdapter

        service = MockPostgresService()
        candidate = MockStoredCandidate()
        service._candidates[candidate.id] = candidate

        adapter = MCPReflectionServiceAdapter(service=service)  # type: ignore[arg-type]
        adapter._promote_candidate = MagicMock(return_value=None)

        result = adapter.approve_candidate({
            "candidate_id": "cand-001",
            "reviewed_by": "reviewer-1",
            "merge_to_handbook": True,
        })

        assert result["success"] is True
        assert result["behavior_id"] is None


# ============================================================================
# Tests: CLI adapter promotion wiring
# ============================================================================


class TestCLIAdapterPromotion:
    """CLIReflectionAdapter.approve_candidate with merge_to_handbook."""

    def test_approve_with_merge_calls_promote(self) -> None:
        """When merge_to_handbook=True, should call _promote_candidate_cli."""
        from amprealize.adapters import CLIReflectionAdapter

        # Use MagicMock without spec so approve_candidate is available
        mock_service = MagicMock()
        mock_candidate = MockStoredCandidate()
        mock_service.approve_candidate.return_value = mock_candidate

        adapter = CLIReflectionAdapter(service=mock_service)
        adapter._promote_candidate_cli = MagicMock(return_value="beh-cli-123")

        result = adapter.approve_candidate({
            "candidate_id": "cand-001",
            "reviewed_by": "cli-user",
            "merge_to_handbook": True,
        })

        assert result["success"] is True
        assert result["merge_requested"] is True
        assert result["merged_behavior_id"] == "beh-cli-123"
        adapter._promote_candidate_cli.assert_called_once()

    def test_approve_without_merge_skips_promote(self) -> None:
        """When merge_to_handbook absent, no promotion attempted."""
        from amprealize.adapters import CLIReflectionAdapter

        mock_service = MagicMock()
        mock_candidate = MockStoredCandidate(confidence=0.5)
        mock_service.approve_candidate.return_value = mock_candidate

        adapter = CLIReflectionAdapter(service=mock_service)
        adapter._promote_candidate_cli = MagicMock()

        result = adapter.approve_candidate({
            "candidate_id": "cand-001",
            "reviewed_by": "cli-user",
        })

        assert result["success"] is True
        adapter._promote_candidate_cli.assert_not_called()
