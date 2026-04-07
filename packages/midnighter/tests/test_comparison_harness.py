"""Tests for the injection strategy comparison harness and regression anchors checker.

Tests cover:
- InjectionStrategy enum
- StrategyComparisonResult dataclass
- EvaluationService.compare_injection_strategies() logic
- EvaluationService._build_strategy_benchmark() prompt modification
- EvaluationService._default_strategy_context() per strategy
- EvaluationService.check_regression_anchors() threshold logic
- load_domain_benchmark() and load_regression_anchors() utilities
"""

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mdnt.evaluation import (
    Benchmark,
    BenchmarkExample,
    EvaluationMetric,
    EvaluationResult,
    EvaluationService,
    InjectionStrategy,
    StrategyComparisonResult,
    load_domain_benchmark,
    load_regression_anchors,
)


BENCHMARKS_DIR = Path(__file__).resolve().parent.parent / "benchmarks"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_example(eid: str = "ex-1", behaviors: list | None = None) -> BenchmarkExample:
    return BenchmarkExample(
        example_id=eid,
        prompt="How do I add logging?",
        expected_behaviors=behaviors if behaviors is not None else ["behavior_use_raze_for_logging"],
        context="Adding logging to a service",
        difficulty="easy",
        category="implementation",
    )


def _make_benchmark(examples: list | None = None) -> Benchmark:
    return Benchmark(
        name="test_bench",
        description="test",
        examples=examples or [_make_example()],
        version="1.0",
        created_at=datetime.utcnow(),
    )


def _make_eval_result(strategy_name: str, adherence: float = 0.8, tokens: int = 500) -> EvaluationResult:
    return EvaluationResult(
        evaluation_id=f"eval-{strategy_name}",
        model_id="gpt-4o-mini",
        benchmark_name=f"test_bench_{strategy_name}",
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        total_examples=1,
        completed_examples=1,
        metrics={
            EvaluationMetric.BEHAVIOR_ADHERENCE.value: adherence,
            EvaluationMetric.CITATION_ACCURACY.value: adherence * 0.9,
            EvaluationMetric.HALLUCINATION_RATE.value: max(0, 0.2 - adherence * 0.1),
            "total_tokens": tokens,
        },
        example_results=[],
        errors=[],
        status="completed",
    )


# ---------------------------------------------------------------------------
# InjectionStrategy enum
# ---------------------------------------------------------------------------

class TestInjectionStrategy:
    def test_values(self):
        assert InjectionStrategy.BASELINE.value == "baseline"
        assert InjectionStrategy.BCI_ONLY.value == "bci_only"
        assert InjectionStrategy.PACK_BCI.value == "pack_bci"

    def test_list_all(self):
        assert len(list(InjectionStrategy)) == 3


# ---------------------------------------------------------------------------
# StrategyComparisonResult
# ---------------------------------------------------------------------------

class TestStrategyComparisonResult:
    def test_to_dict(self):
        result = StrategyComparisonResult(
            comparison_id="cmp-1",
            model_id="gpt-4o-mini",
            benchmark_name="test",
            started_at=datetime(2025, 1, 1),
            completed_at=datetime(2025, 1, 1),
            total_examples=10,
            strategy_results={},
            strategy_metrics={"baseline": {"behavior_adherence": 0.5}},
            improvements={"bci_only": {"behavior_adherence": 0.3}},
            token_accounting={"baseline": {"total_tokens": 1000}},
            winner="bci_only",
            status="completed",
        )
        d = result.to_dict()
        assert d["winner"] == "bci_only"
        assert d["comparison_id"] == "cmp-1"
        assert "strategy_metrics" in d
        assert "token_accounting" in d


# ---------------------------------------------------------------------------
# _default_strategy_context
# ---------------------------------------------------------------------------

class TestDefaultStrategyContext:
    def test_baseline_returns_none(self):
        ex = _make_example()
        ctx = EvaluationService._default_strategy_context(InjectionStrategy.BASELINE, ex)
        assert ctx is None

    def test_bci_only_includes_behaviors(self):
        ex = _make_example(behaviors=["behavior_use_raze_for_logging"])
        ctx = EvaluationService._default_strategy_context(InjectionStrategy.BCI_ONLY, ex)
        assert "[BCI]" in ctx
        assert "behavior_use_raze_for_logging" in ctx

    def test_pack_bci_includes_behaviors_and_context(self):
        ex = _make_example(behaviors=["behavior_use_raze_for_logging"])
        ctx = EvaluationService._default_strategy_context(InjectionStrategy.PACK_BCI, ex)
        assert "[PACK+BCI]" in ctx
        assert "behavior_use_raze_for_logging" in ctx
        assert "knowledge pack" in ctx.lower()

    def test_bci_only_empty_behaviors(self):
        ex = _make_example(behaviors=[])
        ctx = EvaluationService._default_strategy_context(InjectionStrategy.BCI_ONLY, ex)
        assert "none" in ctx


# ---------------------------------------------------------------------------
# _build_strategy_benchmark
# ---------------------------------------------------------------------------

class TestBuildStrategyBenchmark:
    def setup_method(self):
        self.service = EvaluationService(api_key="test-key")

    def test_creates_new_benchmark_per_strategy(self):
        bench = _make_benchmark()
        new = self.service._build_strategy_benchmark(
            bench, bench.examples, InjectionStrategy.BCI_ONLY
        )
        assert new.name == "test_bench_bci_only"
        assert len(new.examples) == 1

    def test_example_ids_include_strategy(self):
        bench = _make_benchmark()
        new = self.service._build_strategy_benchmark(
            bench, bench.examples, InjectionStrategy.PACK_BCI
        )
        assert new.examples[0].example_id.endswith("_pack_bci")

    def test_baseline_context_is_original(self):
        ex = _make_example()
        bench = _make_benchmark([ex])
        new = self.service._build_strategy_benchmark(
            bench, bench.examples, InjectionStrategy.BASELINE
        )
        # Baseline returns None from default_strategy_context,
        # so falls back to original context
        assert new.examples[0].context == ex.context

    def test_custom_prompt_builder(self):
        def custom(strategy, example):
            return [{"role": "system", "content": f"Custom: {strategy.value}"}]

        bench = _make_benchmark()
        new = self.service._build_strategy_benchmark(
            bench, bench.examples, InjectionStrategy.BCI_ONLY, prompt_builder=custom
        )
        assert "Custom: bci_only" in new.examples[0].context


# ---------------------------------------------------------------------------
# compare_injection_strategies (mocked evaluate_model)
# ---------------------------------------------------------------------------

class TestCompareInjectionStrategies:
    def setup_method(self):
        self.service = EvaluationService(api_key="test-key")

    @pytest.mark.asyncio
    async def test_returns_strategy_comparison_result(self):
        # Mock evaluate_model to return canned results
        call_count = 0

        async def mock_eval(model_id, benchmark, **kwargs):
            nonlocal call_count
            call_count += 1
            strategy_name = benchmark.name.split("_")[-1]  # last segment
            adherence = {"baseline": 0.5, "only": 0.7, "bci": 0.85}
            return _make_eval_result(
                strategy_name,
                adherence=adherence.get(strategy_name, 0.6),
                tokens=500 + call_count * 100,
            )

        self.service.evaluate_model = mock_eval

        bench = _make_benchmark()
        result = await self.service.compare_injection_strategies(
            "gpt-4o-mini", bench
        )
        assert isinstance(result, StrategyComparisonResult)
        assert result.status == "completed"
        assert len(result.strategy_metrics) == 3

    @pytest.mark.asyncio
    async def test_improvements_over_baseline(self):
        async def mock_eval(model_id, benchmark, **kwargs):
            name = benchmark.name
            if "baseline" in name:
                return _make_eval_result("baseline", adherence=0.5, tokens=1000)
            elif "bci_only" in name:
                return _make_eval_result("bci_only", adherence=0.7, tokens=800)
            else:
                return _make_eval_result("pack_bci", adherence=0.9, tokens=700)

        self.service.evaluate_model = mock_eval

        result = await self.service.compare_injection_strategies(
            "gpt-4o-mini", _make_benchmark()
        )
        # BCI should show improvement over baseline
        bci_imp = result.improvements[InjectionStrategy.BCI_ONLY.value]
        assert bci_imp[EvaluationMetric.BEHAVIOR_ADHERENCE.value] > 0

        # Pack+BCI should show higher improvement
        pack_imp = result.improvements[InjectionStrategy.PACK_BCI.value]
        assert pack_imp[EvaluationMetric.BEHAVIOR_ADHERENCE.value] > bci_imp[EvaluationMetric.BEHAVIOR_ADHERENCE.value]

    @pytest.mark.asyncio
    async def test_token_accounting(self):
        async def mock_eval(model_id, benchmark, **kwargs):
            name = benchmark.name
            if "baseline" in name:
                return _make_eval_result("baseline", tokens=1000)
            elif "bci_only" in name:
                return _make_eval_result("bci_only", tokens=800)
            else:
                return _make_eval_result("pack_bci", tokens=700)

        self.service.evaluate_model = mock_eval

        result = await self.service.compare_injection_strategies(
            "gpt-4o-mini", _make_benchmark()
        )
        baseline_tokens = result.token_accounting[InjectionStrategy.BASELINE.value]
        assert baseline_tokens["token_savings"] == 0
        assert baseline_tokens["total_tokens"] == 1000

        bci_tokens = result.token_accounting[InjectionStrategy.BCI_ONLY.value]
        assert bci_tokens["token_savings"] == 200  # 1000 - 800
        assert bci_tokens["token_savings_pct"] == 0.2

    @pytest.mark.asyncio
    async def test_winner_is_best_adherence(self):
        async def mock_eval(model_id, benchmark, **kwargs):
            name = benchmark.name
            if "baseline" in name:
                return _make_eval_result("baseline", adherence=0.5)
            elif "bci_only" in name:
                return _make_eval_result("bci_only", adherence=0.7)
            else:
                return _make_eval_result("pack_bci", adherence=0.9)

        self.service.evaluate_model = mock_eval

        result = await self.service.compare_injection_strategies(
            "gpt-4o-mini", _make_benchmark()
        )
        assert result.winner == InjectionStrategy.PACK_BCI.value

    @pytest.mark.asyncio
    async def test_subset_strategies(self):
        async def mock_eval(model_id, benchmark, **kwargs):
            return _make_eval_result("x", adherence=0.6, tokens=500)

        self.service.evaluate_model = mock_eval

        result = await self.service.compare_injection_strategies(
            "gpt-4o-mini",
            _make_benchmark(),
            strategies=[InjectionStrategy.BASELINE, InjectionStrategy.BCI_ONLY],
        )
        assert len(result.strategy_metrics) == 2
        assert InjectionStrategy.PACK_BCI.value not in result.strategy_metrics

    @pytest.mark.asyncio
    async def test_benchmark_not_found_raises(self):
        with pytest.raises(ValueError, match="Benchmark not found"):
            await self.service.compare_injection_strategies(
                "gpt-4o-mini", "nonexistent_benchmark"
            )


# ---------------------------------------------------------------------------
# check_regression_anchors
# ---------------------------------------------------------------------------

class TestCheckRegressionAnchors:
    def setup_method(self):
        self.service = EvaluationService(api_key="test-key")
        self.anchors = {
            "global_thresholds": {
                "behavior_adherence": {"min": 0.7, "target": 0.85},
                "hallucination_rate": {"max": 0.10, "target": 0.05},
            },
            "comparison_thresholds": {
                "pack_bci_vs_baseline": {
                    "min_improvement_behavior_adherence": 0.15,
                    "description": "Pack+BCI must beat baseline",
                },
                "token_efficiency": {
                    "max_token_increase_percent": 15.0,
                    "description": "Max token increase",
                },
            },
        }

    def _make_strategy_result(
        self,
        baseline_adherence=0.5,
        bci_adherence=0.7,
        pack_adherence=0.9,
        baseline_hall=0.05,
    ) -> StrategyComparisonResult:
        return StrategyComparisonResult(
            comparison_id="test",
            model_id="gpt-4o-mini",
            benchmark_name="test",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            total_examples=10,
            strategy_results={},
            strategy_metrics={
                "baseline": {
                    "behavior_adherence": baseline_adherence,
                    "hallucination_rate": baseline_hall,
                    "total_tokens": 1000,
                },
                "bci_only": {
                    "behavior_adherence": bci_adherence,
                    "hallucination_rate": 0.03,
                    "total_tokens": 900,
                },
                "pack_bci": {
                    "behavior_adherence": pack_adherence,
                    "hallucination_rate": 0.02,
                    "total_tokens": 800,
                },
            },
            improvements={
                "baseline": {"behavior_adherence": 0},
                "bci_only": {"behavior_adherence": (bci_adherence - baseline_adherence) / baseline_adherence if baseline_adherence else 0},
                "pack_bci": {"behavior_adherence": (pack_adherence - baseline_adherence) / baseline_adherence if baseline_adherence else 0},
            },
            token_accounting={
                "baseline": {"total_tokens": 1000, "token_savings": 0, "token_savings_pct": 0},
                "bci_only": {"total_tokens": 900, "token_savings": 100, "token_savings_pct": 0.1},
                "pack_bci": {"total_tokens": 800, "token_savings": 200, "token_savings_pct": 0.2},
            },
            winner="pack_bci",
        )

    def test_all_passing(self, tmp_path):
        anchors_path = tmp_path / "anchors.json"
        anchors_path.write_text(json.dumps(self.anchors))
        # All strategies above global min 0.7; pack_bci improvement > 15% over baseline
        result = self._make_strategy_result(
            baseline_adherence=0.72,
            bci_adherence=0.80,
            pack_adherence=0.90,
        )
        check = self.service.check_regression_anchors(result, str(anchors_path))
        assert check["passed"] is True, f"Unexpected failures: {check['failures']}"
        assert len(check["failures"]) == 0

    def test_adherence_below_min_fails(self, tmp_path):
        anchors_path = tmp_path / "anchors.json"
        anchors_path.write_text(json.dumps(self.anchors))
        result = self._make_strategy_result(baseline_adherence=0.3)
        check = self.service.check_regression_anchors(result, str(anchors_path))
        assert check["passed"] is False
        baseline_failures = [
            f for f in check["failures"]
            if f.get("strategy") == "baseline" and "behavior_adherence" in f.get("failure", "")
        ]
        assert len(baseline_failures) > 0

    def test_hallucination_above_max_fails(self, tmp_path):
        anchors_path = tmp_path / "anchors.json"
        anchors_path.write_text(json.dumps(self.anchors))
        result = self._make_strategy_result(baseline_hall=0.20)
        check = self.service.check_regression_anchors(result, str(anchors_path))
        assert check["passed"] is False

    def test_insufficient_improvement_fails(self, tmp_path):
        anchors_path = tmp_path / "anchors.json"
        anchors_path.write_text(json.dumps(self.anchors))
        # pack_bci barely beats baseline
        result = self._make_strategy_result(
            baseline_adherence=0.8, pack_adherence=0.82
        )
        check = self.service.check_regression_anchors(result, str(anchors_path))
        pack_failures = [
            f for f in check["failures"]
            if "pack_bci_vs_baseline" in f.get("failure", "")
        ]
        assert len(pack_failures) > 0

    def test_token_increase_fails(self, tmp_path):
        anchors = dict(self.anchors)
        anchors["comparison_thresholds"]["token_efficiency"]["max_token_increase_percent"] = 5.0
        anchors_path = tmp_path / "anchors.json"
        anchors_path.write_text(json.dumps(anchors))
        # Simulate token increase
        result = self._make_strategy_result()
        result.token_accounting["bci_only"] = {
            "total_tokens": 1200,
            "token_savings": -200,
            "token_savings_pct": -0.20,
        }
        check = self.service.check_regression_anchors(result, str(anchors_path))
        token_failures = [
            f for f in check["failures"]
            if "Token increase" in f.get("failure", "")
        ]
        assert len(token_failures) > 0


# ---------------------------------------------------------------------------
# Utility loaders
# ---------------------------------------------------------------------------

class TestLoadUtilities:
    def test_load_domain_benchmark(self):
        bench = load_domain_benchmark(str(BENCHMARKS_DIR))
        assert bench.name == "domain_expertise"
        assert len(bench.examples) > 40

    def test_load_domain_benchmark_example_types(self):
        bench = load_domain_benchmark(str(BENCHMARKS_DIR))
        for ex in bench.examples:
            assert isinstance(ex, BenchmarkExample)
            assert ex.example_id
            assert ex.prompt

    def test_load_regression_anchors(self):
        anchors = load_regression_anchors(str(BENCHMARKS_DIR))
        assert "global_thresholds" in anchors
        assert "per_category_thresholds" in anchors
        assert "comparison_thresholds" in anchors
