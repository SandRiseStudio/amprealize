"""Tests for QualityGateService — T4.3.3 CI quality gates.

Covers:
- QualityGateResult / QualityGateReport dataclasses
- check_behavior_approval gate
- check_pack_validation gate
- check_regression gate
- run_all_gates orchestrator
- Integration with behavior_service quality gate hook
- Integration with pack builder validate_build hook
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from mdnt.evaluation import (
    InjectionStrategy,
    QualityGateReport,
    QualityGateResult,
    QualityGateService,
    StrategyComparisonResult,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strategy_result(
    baseline_adherence: float = 0.50,
    bci_adherence: float = 0.75,
    pack_adherence: float = 0.90,
    baseline_hall: float = 0.05,
    pack_hall: float = 0.02,
) -> StrategyComparisonResult:
    return StrategyComparisonResult(
        comparison_id="test-comparison",
        model_id="gpt-4o-mini",
        benchmark_name="domain_expertise",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        total_examples=56,
        strategy_results={},
        strategy_metrics={
            "baseline": {
                "behavior_adherence": baseline_adherence,
                "citation_accuracy": 0.60,
                "hallucination_rate": baseline_hall,
            },
            "bci_only": {
                "behavior_adherence": bci_adherence,
                "citation_accuracy": 0.72,
                "hallucination_rate": 0.03,
            },
            "pack_bci": {
                "behavior_adherence": pack_adherence,
                "citation_accuracy": 0.85,
                "hallucination_rate": pack_hall,
            },
        },
        improvements={
            "baseline": {"behavior_adherence": 0, "citation_accuracy": 0},
            "bci_only": {
                "behavior_adherence": (bci_adherence - baseline_adherence) / baseline_adherence
                if baseline_adherence
                else 0,
                "citation_accuracy": 0.20,
            },
            "pack_bci": {
                "behavior_adherence": (pack_adherence - baseline_adherence) / baseline_adherence
                if baseline_adherence
                else 0,
                "citation_accuracy": 0.42,
            },
        },
        token_accounting={
            "baseline": {"total_tokens": 1000, "token_savings": 0, "token_savings_pct": 0},
            "bci_only": {"total_tokens": 900, "token_savings": 100, "token_savings_pct": 0.1},
            "pack_bci": {"total_tokens": 800, "token_savings": 200, "token_savings_pct": 0.2},
        },
        winner="pack_bci",
    )


def _make_anchors() -> dict:
    return {
        "global_thresholds": {
            "behavior_adherence": {"min": 0.70, "target": 0.85},
            "citation_accuracy": {"min": 0.65, "target": 0.80},
            "hallucination_rate": {"max": 0.10, "target": 0.05},
        },
        "comparison_thresholds": {
            "pack_bci_vs_baseline": {
                "min_improvement_behavior_adherence": 0.15,
                "min_improvement_citation_accuracy": 0.10,
                "description": "Pack+BCI must beat baseline",
            },
            "bci_only_vs_baseline": {
                "min_improvement_behavior_adherence": 0.08,
                "description": "BCI must beat baseline",
            },
            "token_efficiency": {
                "max_token_increase_percent": 15.0,
                "description": "Max token increase allowed",
            },
        },
    }


# ---------------------------------------------------------------------------
# QualityGateResult dataclass
# ---------------------------------------------------------------------------

class TestQualityGateResult:
    def test_to_dict(self):
        result = QualityGateResult(
            gate_name="test_gate",
            passed=True,
            score=0.85,
            threshold=0.70,
            details={"key": "val"},
            failures=[],
        )
        d = result.to_dict()
        assert d["gate_name"] == "test_gate"
        assert d["passed"] is True
        assert d["score"] == 0.85
        assert d["threshold"] == 0.70

    def test_to_dict_with_failures(self):
        result = QualityGateResult(
            gate_name="failing",
            passed=False,
            score=0.40,
            threshold=0.70,
            failures=["score too low"],
        )
        d = result.to_dict()
        assert d["passed"] is False
        assert len(d["failures"]) == 1


class TestQualityGateReport:
    def test_empty_report(self):
        report = QualityGateReport()
        d = report.to_dict()
        assert d["overall_passed"] is True
        assert d["total_gates"] == 0

    def test_report_with_gates(self):
        gate1 = QualityGateResult("g1", True, 0.9, 0.7)
        gate2 = QualityGateResult("g2", False, 0.5, 0.7, failures=["low"])
        report = QualityGateReport(
            gates=[gate1, gate2],
            overall_passed=False,
        )
        d = report.to_dict()
        assert d["passed_gates"] == 1
        assert d["failed_gates"] == 1
        assert d["overall_passed"] is False


# ---------------------------------------------------------------------------
# check_behavior_approval
# ---------------------------------------------------------------------------

class TestCheckBehaviorApproval:
    def setup_method(self):
        self.gate = QualityGateService()

    def test_passes_when_above_threshold(self):
        result = self.gate.check_behavior_approval("b1", adherence_score=0.85)
        assert result.passed is True
        assert result.gate_name == "pre_approval"

    def test_fails_when_below_adherence_min(self):
        result = self.gate.check_behavior_approval("b1", adherence_score=0.50)
        assert result.passed is False
        assert any("behavior_adherence" in f for f in result.failures)

    def test_fails_when_hallucination_too_high(self):
        result = self.gate.check_behavior_approval(
            "b1", adherence_score=0.85, hallucination_rate=0.15
        )
        assert result.passed is False
        assert any("hallucination_rate" in f for f in result.failures)

    def test_fails_when_citation_too_low(self):
        result = self.gate.check_behavior_approval(
            "b1", adherence_score=0.85, citation_score=0.40
        )
        assert result.passed is False
        assert any("citation_accuracy" in f for f in result.failures)

    def test_citation_zero_skips_check(self):
        # citation_score=0.0 means not measured, should not fail
        result = self.gate.check_behavior_approval(
            "b1", adherence_score=0.85, citation_score=0.0
        )
        assert result.passed is True

    def test_custom_thresholds(self):
        gate = QualityGateService(behavior_adherence_min=0.9)
        result = gate.check_behavior_approval("b1", adherence_score=0.85)
        assert result.passed is False

    def test_details_include_behavior_id(self):
        result = self.gate.check_behavior_approval("behavior_foo", adherence_score=0.90)
        assert result.details["behavior_id"] == "behavior_foo"


# ---------------------------------------------------------------------------
# check_pack_validation
# ---------------------------------------------------------------------------

class TestCheckPackValidation:
    def setup_method(self):
        self.gate = QualityGateService()

    def test_passes_with_good_metrics(self, tmp_path):
        anchors_path = tmp_path / "anchors.json"
        anchors_path.write_text(json.dumps(_make_anchors()))
        result = _make_strategy_result(
            baseline_adherence=0.72, pack_adherence=0.90
        )
        gate_result = self.gate.check_pack_validation(result, str(anchors_path))
        assert gate_result.passed is True
        assert gate_result.gate_name == "pack_validation"

    def test_fails_when_pack_adherence_below_min(self, tmp_path):
        anchors_path = tmp_path / "anchors.json"
        anchors_path.write_text(json.dumps(_make_anchors()))
        result = _make_strategy_result(
            baseline_adherence=0.50, pack_adherence=0.60
        )
        gate_result = self.gate.check_pack_validation(result, str(anchors_path))
        assert gate_result.passed is False
        assert any("behavior_adherence" in f for f in gate_result.failures)

    def test_fails_when_improvement_insufficient(self, tmp_path):
        anchors_path = tmp_path / "anchors.json"
        anchors_path.write_text(json.dumps(_make_anchors()))
        # pack barely above baseline — improvement < 15%
        result = _make_strategy_result(
            baseline_adherence=0.80, pack_adherence=0.82
        )
        gate_result = self.gate.check_pack_validation(result, str(anchors_path))
        assert gate_result.passed is False
        assert any("improvement" in f for f in gate_result.failures)

    def test_uses_default_anchors_when_none(self):
        gate = QualityGateService(anchors=_make_anchors())
        result = _make_strategy_result(
            baseline_adherence=0.72, pack_adherence=0.90
        )
        gate_result = gate.check_pack_validation(result, anchors_path=None)
        assert gate_result.passed is True


# ---------------------------------------------------------------------------
# check_regression
# ---------------------------------------------------------------------------

class TestCheckRegression:
    def setup_method(self):
        self.gate = QualityGateService()

    def test_no_regression(self):
        current = {"behavior_adherence": 0.85, "citation_accuracy": 0.80}
        previous = {"behavior_adherence": 0.83, "citation_accuracy": 0.78}
        result = self.gate.check_regression(current, previous)
        assert result.passed is True
        assert result.gate_name == "regression_check"

    def test_adherence_regression_detected(self):
        current = {"behavior_adherence": 0.70}
        previous = {"behavior_adherence": 0.85}
        result = self.gate.check_regression(current, previous)
        assert result.passed is False
        assert any("behavior_adherence" in f and "regressed" in f for f in result.failures)

    def test_hallucination_increase_detected(self):
        current = {"hallucination_rate": 0.12}
        previous = {"hallucination_rate": 0.05}
        result = self.gate.check_regression(current, previous)
        assert result.passed is False
        assert any("hallucination_rate" in f for f in result.failures)

    def test_small_regression_within_threshold(self):
        # 3% drop, default threshold is 5%
        current = {"behavior_adherence": 0.82}
        previous = {"behavior_adherence": 0.85}
        result = self.gate.check_regression(current, previous)
        assert result.passed is True

    def test_custom_regression_threshold(self):
        gate = QualityGateService(regression_threshold=0.02)
        # 3% drop now exceeds 2% threshold
        current = {"behavior_adherence": 0.82}
        previous = {"behavior_adherence": 0.85}
        result = gate.check_regression(current, previous)
        assert result.passed is False

    def test_missing_metrics_skipped(self):
        current = {"behavior_adherence": 0.85}
        previous = {"citation_accuracy": 0.80}
        result = self.gate.check_regression(current, previous)
        assert result.passed is True
        # No comparable metrics → no regression

    def test_details_include_comparisons(self):
        current = {"behavior_adherence": 0.85}
        previous = {"behavior_adherence": 0.80}
        result = self.gate.check_regression(current, previous)
        assert "comparisons" in result.details
        assert "behavior_adherence" in result.details["comparisons"]


# ---------------------------------------------------------------------------
# run_all_gates
# ---------------------------------------------------------------------------

class TestRunAllGates:
    def setup_method(self):
        self.gate = QualityGateService(anchors=_make_anchors())

    def test_all_gates_pass(self, tmp_path):
        anchors_path = tmp_path / "anchors.json"
        anchors_path.write_text(json.dumps(_make_anchors()))
        result = _make_strategy_result(baseline_adherence=0.72, pack_adherence=0.90)
        previous = {"behavior_adherence": 0.88, "citation_accuracy": 0.83}
        report = self.gate.run_all_gates(
            strategy_result=result,
            previous_metrics=previous,
            anchors_path=str(anchors_path),
        )
        assert report.overall_passed is True
        assert len(report.gates) == 2  # pack_validation + regression_check
        assert not report.regression_detected

    def test_pack_gate_only(self, tmp_path):
        anchors_path = tmp_path / "anchors.json"
        anchors_path.write_text(json.dumps(_make_anchors()))
        result = _make_strategy_result(baseline_adherence=0.72, pack_adherence=0.90)
        report = self.gate.run_all_gates(
            strategy_result=result,
            anchors_path=str(anchors_path),
        )
        assert len(report.gates) == 1
        assert report.gates[0].gate_name == "pack_validation"

    def test_empty_report_when_no_inputs(self):
        report = self.gate.run_all_gates()
        assert report.overall_passed is True
        assert len(report.gates) == 0

    def test_regression_flag_set(self, tmp_path):
        anchors_path = tmp_path / "anchors.json"
        anchors_path.write_text(json.dumps(_make_anchors()))
        result = _make_strategy_result(baseline_adherence=0.72, pack_adherence=0.90)
        previous = {"behavior_adherence": 0.99}  # big drop
        report = self.gate.run_all_gates(
            strategy_result=result,
            previous_metrics=previous,
            anchors_path=str(anchors_path),
        )
        assert report.regression_detected is True


# ---------------------------------------------------------------------------
# Integration: BehaviorService quality gate hook
# ---------------------------------------------------------------------------

class TestBehaviorServiceQualityGateHook:
    """Verify the quality_gate parameter wiring in BehaviorService.__init__."""

    def test_quality_gate_stored(self):
        """BehaviorService stores quality_gate when provided."""
        from unittest.mock import patch

        mock_gate = MagicMock()
        # BehaviorService.__init__ tries to connect to postgres, so mock it
        with patch("amprealize.behavior_service.PostgresPool"):
            with patch("amprealize.behavior_service.BehaviorService._resolve_dsn", return_value="mock_dsn"):
                from amprealize.behavior_service import BehaviorService
                bs = BehaviorService(dsn="mock", quality_gate=mock_gate)
                assert bs._quality_gate is mock_gate

    def test_no_quality_gate_by_default(self):
        with patch("amprealize.behavior_service.PostgresPool"):
            with patch("amprealize.behavior_service.BehaviorService._resolve_dsn", return_value="mock_dsn"):
                from amprealize.behavior_service import BehaviorService
                bs = BehaviorService(dsn="mock")
                assert bs._quality_gate is None


# ---------------------------------------------------------------------------
# Integration: PackBuilder validate_build hook
# ---------------------------------------------------------------------------

class TestPackBuilderValidateBuild:
    def test_skipped_when_no_gate(self):
        from amprealize.knowledge_pack.builder import PackBuilder

        mock_registry = MagicMock()
        mock_extractor = MagicMock()
        builder = PackBuilder(mock_registry, mock_extractor)
        result = builder.validate_build(MagicMock(), MagicMock())
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_delegates_to_quality_gate(self):
        from amprealize.knowledge_pack.builder import PackBuilder

        mock_gate = MagicMock()
        mock_gate.check_pack_validation.return_value = QualityGateResult(
            gate_name="pack_validation",
            passed=True,
            score=0.90,
            threshold=0.70,
        )
        mock_registry = MagicMock()
        mock_extractor = MagicMock()
        builder = PackBuilder(mock_registry, mock_extractor, quality_gate=mock_gate)
        result = builder.validate_build(MagicMock(), MagicMock())
        assert result["passed"] is True
        assert result["skipped"] is False
        mock_gate.check_pack_validation.assert_called_once()

    def test_reports_failure(self):
        from amprealize.knowledge_pack.builder import PackBuilder

        mock_gate = MagicMock()
        mock_gate.check_pack_validation.return_value = QualityGateResult(
            gate_name="pack_validation",
            passed=False,
            score=0.50,
            threshold=0.70,
            failures=["adherence too low"],
        )
        mock_registry = MagicMock()
        mock_extractor = MagicMock()
        builder = PackBuilder(mock_registry, mock_extractor, quality_gate=mock_gate)
        result = builder.validate_build(MagicMock(), MagicMock())
        assert result["passed"] is False
        assert result["skipped"] is False
