"""Tests for domain expertise benchmark loading and validation.

Validates that:
- domain_expertise_benchmark.jsonl loads correctly
- regression_anchors.json is well-formed
- All examples conform to the BenchmarkExample schema
- Category coverage spans all TaskFamily members
- GEP phase-specific benchmarks are present
- Negative and multi-behavior examples are included
"""

import json
from pathlib import Path

import pytest


BENCHMARKS_DIR = Path(__file__).resolve().parent.parent / "benchmarks"
DOMAIN_BENCHMARK_PATH = BENCHMARKS_DIR / "domain_expertise_benchmark.jsonl"
REGRESSION_ANCHORS_PATH = BENCHMARKS_DIR / "regression_anchors.json"

# Required fields per BenchmarkExample schema in evaluation.py
REQUIRED_FIELDS = {"example_id", "prompt", "expected_behaviors"}
OPTIONAL_FIELDS = {
    "context", "expected_response_contains", "expected_response_excludes",
    "difficulty", "category",
}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}

# Categories matching TaskFamily enum + GEP phases + special categories
TASK_FAMILY_CATEGORIES = {
    "docs", "implementation", "testing", "migration",
    "config", "deployment", "incident", "general",
}
PHASE_CATEGORIES = {
    "phase_planning", "phase_implementing", "phase_reviewing", "phase_completing",
}
SPECIAL_CATEGORIES = {"negative", "multi_behavior"}
ALL_CATEGORIES = TASK_FAMILY_CATEGORIES | PHASE_CATEGORIES | SPECIAL_CATEGORIES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def domain_examples():
    """Load all examples from domain_expertise_benchmark.jsonl."""
    examples = []
    with open(DOMAIN_BENCHMARK_PATH) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                examples.append(json.loads(line))
            except json.JSONDecodeError as exc:
                pytest.fail(f"Invalid JSON on line {line_num}: {exc}")
    return examples


@pytest.fixture(scope="module")
def regression_anchors():
    """Load regression_anchors.json."""
    with open(REGRESSION_ANCHORS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Domain benchmark JSONL tests
# ---------------------------------------------------------------------------

class TestDomainBenchmarkLoading:
    """Verify the domain expertise benchmark loads and is well-formed."""

    def test_file_exists(self):
        assert DOMAIN_BENCHMARK_PATH.exists(), "domain_expertise_benchmark.jsonl not found"

    def test_non_empty(self, domain_examples):
        assert len(domain_examples) > 0, "Benchmark has no examples"

    def test_minimum_example_count(self, domain_examples):
        """Plan requires 5-10 tasks per TaskFamily category."""
        assert len(domain_examples) >= 40, (
            f"Expected at least 40 examples (5 per 8 categories), got {len(domain_examples)}"
        )

    def test_all_required_fields_present(self, domain_examples):
        for ex in domain_examples:
            missing = REQUIRED_FIELDS - set(ex.keys())
            assert not missing, (
                f"Example {ex.get('example_id', '?')} missing fields: {missing}"
            )

    def test_no_unknown_fields(self, domain_examples):
        all_allowed = REQUIRED_FIELDS | OPTIONAL_FIELDS
        for ex in domain_examples:
            unknown = set(ex.keys()) - all_allowed
            assert not unknown, (
                f"Example {ex.get('example_id', '?')} has unknown fields: {unknown}"
            )

    def test_unique_example_ids(self, domain_examples):
        ids = [ex["example_id"] for ex in domain_examples]
        duplicates = [eid for eid in ids if ids.count(eid) > 1]
        assert not duplicates, f"Duplicate example_ids: {set(duplicates)}"

    def test_valid_difficulty_values(self, domain_examples):
        for ex in domain_examples:
            diff = ex.get("difficulty", "medium")
            assert diff in VALID_DIFFICULTIES, (
                f"Example {ex['example_id']} has invalid difficulty '{diff}'"
            )

    def test_valid_categories(self, domain_examples):
        for ex in domain_examples:
            cat = ex.get("category", "general")
            assert cat in ALL_CATEGORIES, (
                f"Example {ex['example_id']} has unknown category '{cat}'"
            )

    def test_expected_behaviors_is_list(self, domain_examples):
        for ex in domain_examples:
            assert isinstance(ex["expected_behaviors"], list), (
                f"Example {ex['example_id']}: expected_behaviors must be a list"
            )

    def test_prompts_non_empty(self, domain_examples):
        for ex in domain_examples:
            assert ex["prompt"].strip(), (
                f"Example {ex['example_id']} has empty prompt"
            )


class TestDomainBenchmarkCoverage:
    """Verify category coverage requirements."""

    def test_all_task_families_covered(self, domain_examples):
        """Every TaskFamily should have at least one example."""
        present = {ex.get("category") for ex in domain_examples}
        missing = TASK_FAMILY_CATEGORIES - present
        assert not missing, f"Missing TaskFamily categories: {missing}"

    def test_min_examples_per_task_family(self, domain_examples):
        """Plan requires 5-10 tasks per TaskFamily category."""
        from collections import Counter
        counts = Counter(
            ex.get("category") for ex in domain_examples
            if ex.get("category") in TASK_FAMILY_CATEGORIES
        )
        for cat in TASK_FAMILY_CATEGORIES:
            assert counts.get(cat, 0) >= 5, (
                f"Category '{cat}' has only {counts.get(cat, 0)} examples (need >= 5)"
            )

    def test_gep_phase_benchmarks_present(self, domain_examples):
        """Plan requires GEP-phase-specific benchmarks."""
        present = {ex.get("category") for ex in domain_examples}
        missing = PHASE_CATEGORIES - present
        assert not missing, f"Missing GEP phase categories: {missing}"

    def test_negative_examples_present(self, domain_examples):
        negatives = [ex for ex in domain_examples if ex.get("category") == "negative"]
        assert len(negatives) >= 2, "Need at least 2 negative examples"
        for neg in negatives:
            assert neg["expected_behaviors"] == [], (
                f"Negative example {neg['example_id']} should have empty expected_behaviors"
            )

    def test_multi_behavior_examples_present(self, domain_examples):
        multi = [ex for ex in domain_examples if ex.get("category") == "multi_behavior"]
        assert len(multi) >= 1, "Need at least 1 multi-behavior example"
        for m in multi:
            assert len(m["expected_behaviors"]) >= 2, (
                f"Multi-behavior example {m['example_id']} should expect 2+ behaviors"
            )

    def test_difficulty_distribution(self, domain_examples):
        """Ensure a mix of difficulties."""
        from collections import Counter
        counts = Counter(ex.get("difficulty", "medium") for ex in domain_examples)
        assert counts.get("easy", 0) >= 5, "Need at least 5 easy examples"
        assert counts.get("medium", 0) >= 10, "Need at least 10 medium examples"
        assert counts.get("hard", 0) >= 5, "Need at least 5 hard examples"


class TestDomainBenchmarkBehaviorRefs:
    """Validate behavior references are plausible."""

    def test_behavior_names_prefixed(self, domain_examples):
        """All non-empty behavior refs should start with 'behavior_'."""
        for ex in domain_examples:
            for bname in ex["expected_behaviors"]:
                assert bname.startswith("behavior_"), (
                    f"Example {ex['example_id']}: behavior '{bname}' missing 'behavior_' prefix"
                )

    def test_no_duplicate_behaviors_per_example(self, domain_examples):
        for ex in domain_examples:
            bs = ex["expected_behaviors"]
            assert len(bs) == len(set(bs)), (
                f"Example {ex['example_id']} has duplicate behaviors"
            )


# ---------------------------------------------------------------------------
# Regression anchors tests
# ---------------------------------------------------------------------------

class TestRegressionAnchorsLoading:
    """Verify regression_anchors.json is well-formed."""

    def test_file_exists(self):
        assert REGRESSION_ANCHORS_PATH.exists(), "regression_anchors.json not found"

    def test_has_global_thresholds(self, regression_anchors):
        assert "global_thresholds" in regression_anchors

    def test_global_threshold_keys(self, regression_anchors):
        expected_keys = {
            "behavior_adherence", "citation_accuracy", "hallucination_rate",
            "mean_reciprocal_rank", "ndcg_at_5", "ndcg_at_10",
        }
        actual = set(regression_anchors["global_thresholds"].keys())
        missing = expected_keys - actual
        assert not missing, f"Missing global threshold keys: {missing}"

    def test_has_per_category_thresholds(self, regression_anchors):
        assert "per_category_thresholds" in regression_anchors

    def test_per_category_covers_task_families(self, regression_anchors):
        cats = set(regression_anchors["per_category_thresholds"].keys())
        missing = TASK_FAMILY_CATEGORIES - cats
        assert not missing, f"Missing per-category thresholds: {missing}"

    def test_has_comparison_thresholds(self, regression_anchors):
        assert "comparison_thresholds" in regression_anchors
        ct = regression_anchors["comparison_thresholds"]
        assert "pack_bci_vs_baseline" in ct
        assert "bci_only_vs_baseline" in ct
        assert "token_efficiency" in ct

    def test_threshold_values_in_range(self, regression_anchors):
        """All min/target thresholds should be between 0 and 1."""
        for metric, vals in regression_anchors["global_thresholds"].items():
            for key in ("min", "target", "max"):
                if key in vals:
                    v = vals[key]
                    assert 0.0 <= v <= 1.0, (
                        f"global_thresholds.{metric}.{key} = {v} out of [0,1] range"
                    )

    def test_has_difficulty_multipliers(self, regression_anchors):
        assert "difficulty_multipliers" in regression_anchors
        dm = regression_anchors["difficulty_multipliers"]
        for d in ("easy", "medium", "hard"):
            assert d in dm, f"Missing difficulty multiplier for '{d}'"


# ---------------------------------------------------------------------------
# Cross-file consistency
# ---------------------------------------------------------------------------

class TestBenchmarkAnchorsConsistency:
    """Verify benchmark and anchors are consistent."""

    def test_anchor_total_matches_benchmark(self, domain_examples, regression_anchors):
        """regression_anchors.total_examples should match actual count."""
        expected = regression_anchors.get("total_examples")
        actual = len(domain_examples)
        assert expected == actual, (
            f"regression_anchors.total_examples={expected} but benchmark has {actual} examples"
        )

    def test_all_benchmark_categories_have_anchors(self, domain_examples, regression_anchors):
        """Every category in the benchmark should have a threshold entry."""
        benchmark_cats = {ex.get("category") for ex in domain_examples}
        anchor_cats = set(regression_anchors.get("per_category_thresholds", {}).keys())
        missing = benchmark_cats - anchor_cats
        assert not missing, f"Benchmark categories without anchor thresholds: {missing}"
