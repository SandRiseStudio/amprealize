"""Tests for AdherenceTracker — T3.9.4, T3.9.5, T3.4.2, T3.4.3.

Covers:
- record_phase: citation parsing, adherence scoring, overlay matching
- finalize: aggregation, overall score, compliance flag
- enforce_strict_mode: role declaration, behavior citation, mandatory overlays
- enforce_strict_mode_from_context: extraction from RuntimeContext
- telemetry: phase and run event emission
- persist_analytics_events: fine-grained analytics events
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import MagicMock, call

from amprealize.adherence_tracker import AdherenceTracker, StrictModeViolation
from amprealize.bci_contracts import (
    AdherenceResult,
    Citation,
    CitationType,
    PhaseAdherenceRecord,
    ValidateCitationsResponse,
)

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

def _make_bci_service(
    cited_names: Optional[List[str]] = None,
    role_declared: bool = False,
):
    """Create a mock BCIService whose validate_citations returns given cited names."""
    cited_names = cited_names or []
    bci = MagicMock()
    bci.validate_citations.return_value = ValidateCitationsResponse(
        total_citations=len(cited_names),
        valid_citations=[
            Citation(
                text=f"Following {name}",
                type=CitationType.EXPLICIT,
                start_index=0,
                end_index=10,
                behavior_name=name,
            )
            for name in cited_names
        ],
        invalid_citations=[],
        compliance_rate=1.0 if cited_names else 0.0,
        is_compliant=True,
        role_declared=role_declared,
    )
    return bci


def _make_telemetry():
    """Create a mock telemetry client."""
    t = MagicMock()
    t.emit_event = MagicMock()
    return t


# ------------------------------------------------------------------
# record_phase
# ------------------------------------------------------------------

class TestRecordPhase:
    """Test AdherenceTracker.record_phase."""

    def test_perfect_adherence(self):
        """All injected behaviors cited → score = 1.0."""
        bci = _make_bci_service(cited_names=["b1", "b2"], role_declared=True)
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1")
        record = tracker.record_phase(
            phase="PLANNING",
            output_text="Following b1 and b2",
            behaviors_injected=["b1", "b2"],
        )
        assert record.adherence_score == 1.0
        assert record.behaviors_cited == ["b1", "b2"]
        assert record.behaviors_missed == []
        assert record.violation_count == 0
        assert record.role_declared is True

    def test_partial_adherence(self):
        """Only some behaviors cited → fractional score."""
        bci = _make_bci_service(cited_names=["b1"])
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1")
        record = tracker.record_phase(
            phase="EXECUTING",
            output_text="Following b1",
            behaviors_injected=["b1", "b2"],
        )
        assert record.adherence_score == 0.5
        assert record.behaviors_cited == ["b1"]
        assert record.behaviors_missed == ["b2"]
        assert record.violation_count == 1

    def test_zero_adherence(self):
        """No behaviors cited → score = 0.0."""
        bci = _make_bci_service(cited_names=[])
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1")
        record = tracker.record_phase(
            phase="TESTING",
            output_text="No citations here",
            behaviors_injected=["b1", "b2"],
        )
        assert record.adherence_score == 0.0
        assert record.behaviors_missed == ["b1", "b2"]
        assert record.violation_count == 2

    def test_no_behaviors_injected(self):
        """No behaviors injected → score defaults to 1.0 (0/max(0,1))."""
        bci = _make_bci_service()
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1")
        # With no behaviors injected, BCI won't be called (empty list)
        record = tracker.record_phase(
            phase="CLARIFYING",
            output_text="some output",
            behaviors_injected=[],
        )
        # total_expected = 0, total_cited = 0, score = 0 / max(0, 1) = 0.0
        assert record.adherence_score == 0.0
        assert record.violation_count == 0

    def test_overlay_matching_case_insensitive(self):
        """Overlays are matched case-insensitively in output text."""
        bci = _make_bci_service()
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1")
        record = tracker.record_phase(
            phase="EXECUTING",
            output_text="Applied OVERLAY_SECURITY and overlay_auth patterns",
            behaviors_injected=[],
            overlays_injected=["overlay_security", "overlay_auth", "overlay_missing"],
        )
        assert "overlay_security" in record.overlays_cited
        assert "overlay_auth" in record.overlays_cited
        assert "overlay_missing" in record.overlays_missed
        assert record.adherence_score == pytest.approx(2 / 3, abs=0.01)

    def test_combined_behaviors_and_overlays(self):
        """Score combines both behaviors and overlays."""
        bci = _make_bci_service(cited_names=["b1"])
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1")
        record = tracker.record_phase(
            phase="ARCHITECTING",
            output_text="Following b1, applied overlay_sec",
            behaviors_injected=["b1", "b2"],
            overlays_injected=["overlay_sec"],
        )
        # cited: b1 + overlay_sec = 2, total: b1+b2+overlay_sec = 3
        assert record.adherence_score == pytest.approx(2 / 3, abs=0.01)
        assert record.violation_count == 1  # only b2 missed

    def test_bci_service_failure_graceful(self):
        """If BCI service raises, citations are empty but no crash."""
        bci = MagicMock()
        bci.validate_citations.side_effect = RuntimeError("BCI unavailable")
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1")
        record = tracker.record_phase(
            phase="PLANNING",
            output_text="some output",
            behaviors_injected=["b1"],
        )
        assert record.behaviors_cited == []
        assert record.behaviors_missed == ["b1"]

    def test_no_bci_service(self):
        """Works without a BCI service (None)."""
        tracker = AdherenceTracker(bci_service=None, run_id="run-1")
        record = tracker.record_phase(
            phase="PLANNING",
            output_text="output",
            behaviors_injected=["b1"],
        )
        assert record.behaviors_cited == []
        assert record.behaviors_missed == ["b1"]

    def test_record_stored(self):
        """Records are accumulated in the tracker."""
        bci = _make_bci_service(cited_names=["b1"])
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1")
        tracker.record_phase(phase="PLANNING", output_text="Following b1", behaviors_injected=["b1"])
        tracker.record_phase(phase="EXECUTING", output_text="Following b1", behaviors_injected=["b1"])
        assert len(tracker.records) == 2
        assert tracker.records[0].phase == "PLANNING"
        assert tracker.records[1].phase == "EXECUTING"

    def test_timestamp_set(self):
        """Each record gets a timestamp."""
        bci = _make_bci_service()
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1")
        record = tracker.record_phase(phase="PLANNING", output_text="x")
        assert record.timestamp is not None


# ------------------------------------------------------------------
# finalize
# ------------------------------------------------------------------

class TestFinalize:
    """Test AdherenceTracker.finalize."""

    def test_average_score(self):
        """Overall score is average of phase scores."""
        bci_full = _make_bci_service(cited_names=["b1"])
        bci_none = _make_bci_service(cited_names=[])

        tracker = AdherenceTracker(bci_service=bci_full, run_id="run-1")
        tracker.record_phase(phase="PLANNING", output_text="Following b1", behaviors_injected=["b1"])
        # Switch mock to return no citations
        tracker._bci = bci_none
        tracker.record_phase(phase="EXECUTING", output_text="none", behaviors_injected=["b1"])

        result = tracker.finalize()
        # Phase 1: score=1.0, Phase 2: score=0.0 → avg = 0.5
        assert result.overall_adherence_score == 0.5
        assert result.total_behaviors_injected == 2
        assert result.total_behaviors_cited == 1
        assert result.total_violations == 1
        assert result.is_compliant is False

    def test_empty_tracker(self):
        """No phases recorded → overall score 1.0, compliant."""
        tracker = AdherenceTracker(bci_service=None, run_id="run-1")
        result = tracker.finalize()
        assert result.overall_adherence_score == 1.0
        assert result.is_compliant is True
        assert result.phase_records == []

    def test_all_compliant(self):
        """All phases fully cited → is_compliant True."""
        bci = _make_bci_service(cited_names=["b1"])
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1")
        tracker.record_phase(phase="PLANNING", output_text="b1", behaviors_injected=["b1"])
        tracker.record_phase(phase="EXECUTING", output_text="b1", behaviors_injected=["b1"])
        result = tracker.finalize()
        assert result.is_compliant is True
        assert result.total_violations == 0

    def test_run_id_propagated(self):
        """Result carries the tracker's run_id."""
        tracker = AdherenceTracker(bci_service=None, run_id="run-abc")
        result = tracker.finalize()
        assert result.run_id == "run-abc"


# ------------------------------------------------------------------
# enforce_strict_mode (T3.4.3)
# ------------------------------------------------------------------

class TestStrictMode:
    """Test strict-mode policy enforcement."""

    def test_strict_role_violation(self):
        """Strict role declaration flag triggers violation when role not declared."""
        record = PhaseAdherenceRecord(
            phase="PLANNING",
            behaviors_injected=["b1"],
            behaviors_cited=["b1"],
            role_declared=False,
        )
        tracker = AdherenceTracker(bci_service=None, run_id="run-1")
        with pytest.raises(StrictModeViolation) as exc_info:
            tracker.enforce_strict_mode(record, strict_role_declaration=True)
        assert "role declaration required" in str(exc_info.value)

    def test_strict_role_passes(self):
        """Role declared → no violation."""
        record = PhaseAdherenceRecord(
            phase="PLANNING",
            role_declared=True,
        )
        tracker = AdherenceTracker(bci_service=None, run_id="run-1")
        violations = tracker.enforce_strict_mode(record, strict_role_declaration=True)
        assert violations == []

    def test_strict_behavior_citation_violation(self):
        """Missing behaviors triggers violation."""
        record = PhaseAdherenceRecord(
            phase="EXECUTING",
            behaviors_injected=["b1", "b2"],
            behaviors_cited=["b1"],
            behaviors_missed=["b2"],
        )
        tracker = AdherenceTracker(bci_service=None, run_id="run-1")
        with pytest.raises(StrictModeViolation) as exc_info:
            tracker.enforce_strict_mode(record, strict_behavior_citation=True)
        assert "b2" in str(exc_info.value)

    def test_strict_behavior_citation_passes(self):
        """All cited → no violation."""
        record = PhaseAdherenceRecord(
            phase="EXECUTING",
            behaviors_injected=["b1"],
            behaviors_cited=["b1"],
            behaviors_missed=[],
        )
        tracker = AdherenceTracker(bci_service=None, run_id="run-1")
        violations = tracker.enforce_strict_mode(record, strict_behavior_citation=True)
        assert violations == []

    def test_mandatory_overlay_violation(self):
        """Mandatory overlay not cited → violation."""
        record = PhaseAdherenceRecord(
            phase="TESTING",
            overlays_cited=["o1"],
        )
        tracker = AdherenceTracker(bci_service=None, run_id="run-1")
        with pytest.raises(StrictModeViolation) as exc_info:
            tracker.enforce_strict_mode(record, mandatory_overlays=["o1", "o2"])
        assert "o2" in str(exc_info.value)

    def test_no_raise_returns_warnings(self):
        """raise_on_violation=False → returns list instead of raising."""
        record = PhaseAdherenceRecord(
            phase="PLANNING",
            role_declared=False,
        )
        tracker = AdherenceTracker(bci_service=None, run_id="run-1")
        violations = tracker.enforce_strict_mode(
            record,
            strict_role_declaration=True,
            raise_on_violation=False,
        )
        assert len(violations) == 1
        assert "role declaration" in violations[0]

    def test_multiple_violations(self):
        """Multiple strict flags can produce multiple violations."""
        record = PhaseAdherenceRecord(
            phase="PLANNING",
            role_declared=False,
            behaviors_missed=["b1"],
            overlays_cited=[],
        )
        tracker = AdherenceTracker(bci_service=None, run_id="run-1")
        violations = tracker.enforce_strict_mode(
            record,
            strict_role_declaration=True,
            strict_behavior_citation=True,
            mandatory_overlays=["o1"],
            raise_on_violation=False,
        )
        assert len(violations) == 3

    def test_strict_mode_emits_telemetry(self):
        """Strict-mode violations emit telemetry."""
        telemetry = _make_telemetry()
        record = PhaseAdherenceRecord(phase="PLANNING", role_declared=False)
        tracker = AdherenceTracker(bci_service=None, run_id="run-1", telemetry=telemetry)
        tracker.enforce_strict_mode(
            record, strict_role_declaration=True, raise_on_violation=False
        )
        telemetry.emit_event.assert_called_once()
        args = telemetry.emit_event.call_args
        assert args.kwargs["event_type"] == "bci.strict_mode_violation"

    def test_no_violations_no_telemetry(self):
        """No violations → no strict-mode telemetry."""
        telemetry = _make_telemetry()
        record = PhaseAdherenceRecord(phase="PLANNING", role_declared=True)
        tracker = AdherenceTracker(bci_service=None, run_id="run-1", telemetry=telemetry)
        tracker.enforce_strict_mode(record, strict_role_declaration=True)
        telemetry.emit_event.assert_not_called()


# ------------------------------------------------------------------
# enforce_strict_mode_from_context (T3.4.3)
# ------------------------------------------------------------------

class TestStrictModeFromContext:
    """Test convenience method extracting strict flags from a context object."""

    def test_extracts_flags(self):
        """Extracts strict flags from context attributes."""
        @dataclass
        class FakeContext:
            strict_role_declaration: bool = True
            strict_behavior_citation: bool = False
            mandatory_overlays: Optional[List[str]] = None

        record = PhaseAdherenceRecord(phase="PLANNING", role_declared=False)
        ctx = FakeContext(strict_role_declaration=True)
        tracker = AdherenceTracker(bci_service=None, run_id="run-1")
        with pytest.raises(StrictModeViolation):
            tracker.enforce_strict_mode_from_context(record, ctx)

    def test_missing_attrs_safe(self):
        """Context missing attrs → defaults to False/None."""
        record = PhaseAdherenceRecord(phase="PLANNING", role_declared=False)
        tracker = AdherenceTracker(bci_service=None, run_id="run-1")
        # Plain object with no strict attrs → no violations
        violations = tracker.enforce_strict_mode_from_context(
            record, object(), raise_on_violation=False
        )
        assert violations == []


# ------------------------------------------------------------------
# Telemetry (T3.9.5)
# ------------------------------------------------------------------

class TestTelemetry:
    """Test phase and run telemetry emission."""

    def test_phase_telemetry_emitted(self):
        """record_phase emits bci.phase_adherence event."""
        telemetry = _make_telemetry()
        bci = _make_bci_service(cited_names=["b1"])
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1", telemetry=telemetry)
        tracker.record_phase(phase="PLANNING", output_text="b1", behaviors_injected=["b1"])

        calls = [c for c in telemetry.emit_event.call_args_list
                 if c.kwargs.get("event_type") == "bci.phase_adherence"]
        assert len(calls) == 1
        payload = calls[0].kwargs["payload"]
        assert payload["phase"] == "PLANNING"
        assert payload["run_id"] == "run-1"
        assert payload["adherence_score"] == 1.0

    def test_run_telemetry_emitted(self):
        """finalize emits bci.run_adherence event."""
        telemetry = _make_telemetry()
        bci = _make_bci_service(cited_names=["b1"])
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1", telemetry=telemetry)
        tracker.record_phase(phase="PLANNING", output_text="b1", behaviors_injected=["b1"])
        tracker.finalize()

        calls = [c for c in telemetry.emit_event.call_args_list
                 if c.kwargs.get("event_type") == "bci.run_adherence"]
        assert len(calls) == 1
        payload = calls[0].kwargs["payload"]
        assert payload["run_id"] == "run-1"
        assert payload["overall_adherence_score"] == 1.0

    def test_no_telemetry_client(self):
        """No telemetry client → no crash."""
        bci = _make_bci_service(cited_names=["b1"])
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1", telemetry=None)
        tracker.record_phase(phase="PLANNING", output_text="b1", behaviors_injected=["b1"])
        tracker.finalize()  # Should not raise


# ------------------------------------------------------------------
# persist_analytics_events (T3.4.2)
# ------------------------------------------------------------------

class TestAnalyticsPersistence:
    """Test fine-grained analytics event emission."""

    def test_adoption_events(self):
        """Cited behaviors emit analytics.recommendation_adoption events."""
        telemetry = _make_telemetry()
        bci = _make_bci_service(cited_names=["b1"])
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1", telemetry=telemetry)
        tracker.record_phase(phase="PLANNING", output_text="b1", behaviors_injected=["b1", "b2"])
        tracker.persist_analytics_events()

        adoption_calls = [
            c for c in telemetry.emit_event.call_args_list
            if c.kwargs.get("event_type") == "analytics.recommendation_adoption"
        ]
        assert len(adoption_calls) == 1
        assert adoption_calls[0].kwargs["payload"]["behavior_name"] == "b1"
        assert adoption_calls[0].kwargs["payload"]["adopted"] is True

    def test_missing_guidance_events(self):
        """Missed behaviors emit analytics.missing_guidance events."""
        telemetry = _make_telemetry()
        bci = _make_bci_service(cited_names=["b1"])
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1", telemetry=telemetry)
        tracker.record_phase(
            phase="PLANNING", output_text="b1",
            behaviors_injected=["b1", "b2", "b3"],
        )
        tracker.persist_analytics_events()

        missing_calls = [
            c for c in telemetry.emit_event.call_args_list
            if c.kwargs.get("event_type") == "analytics.missing_guidance"
        ]
        assert len(missing_calls) == 2  # b2 and b3
        names = {c.kwargs["payload"]["behavior_name"] for c in missing_calls}
        assert names == {"b2", "b3"}

    def test_citation_compliance_events(self):
        """Each phase emits analytics.citation_compliance event."""
        telemetry = _make_telemetry()
        bci = _make_bci_service(cited_names=["b1"])
        tracker = AdherenceTracker(bci_service=bci, run_id="run-1", telemetry=telemetry)
        tracker.record_phase(phase="P1", output_text="b1", behaviors_injected=["b1"])
        tracker.record_phase(phase="P2", output_text="b1", behaviors_injected=["b1"])
        tracker.persist_analytics_events()

        compliance_calls = [
            c for c in telemetry.emit_event.call_args_list
            if c.kwargs.get("event_type") == "analytics.citation_compliance"
        ]
        assert len(compliance_calls) == 2

    def test_no_telemetry_noop(self):
        """No telemetry → persist_analytics_events is a no-op."""
        tracker = AdherenceTracker(bci_service=None, run_id="run-1", telemetry=None)
        tracker.persist_analytics_events()  # Should not raise


# ------------------------------------------------------------------
# StrictModeViolation exception
# ------------------------------------------------------------------

class TestStrictModeViolationException:
    """Test the exception class itself."""

    def test_violations_attribute(self):
        exc = StrictModeViolation(["v1", "v2"])
        assert exc.violations == ["v1", "v2"]
        assert "v1" in str(exc)
        assert "v2" in str(exc)

    def test_empty_violations(self):
        exc = StrictModeViolation([])
        assert exc.violations == []
