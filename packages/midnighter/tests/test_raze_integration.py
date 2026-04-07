"""Tests for Raze integration module."""

import pytest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch


class TestRazeCostTracker:
    """Tests for RazeCostTracker."""

    def test_tracker_records_costs(self) -> None:
        """Test that tracker records costs correctly."""
        from mdnt.integrations.raze_integration import RazeCostTracker

        tracker = RazeCostTracker(source="test")

        tracker.record_cost(
            job_id="ftjob-test1",
            cost_usd=10.0,
            trained_tokens=100_000,
            model="gpt-4o-mini",
        )

        assert tracker.total_cost_usd == 10.0
        assert len(tracker.cost_records) == 1
        assert tracker.cost_records[0].job_id == "ftjob-test1"
        assert tracker.cost_records[0].model == "gpt-4o-mini"

    def test_tracker_accumulates_costs(self) -> None:
        """Test that tracker accumulates multiple costs."""
        from mdnt.integrations.raze_integration import RazeCostTracker

        tracker = RazeCostTracker(source="test")

        tracker.record_cost("job1", 5.0, 50_000, "gpt-4o-mini")
        tracker.record_cost("job2", 15.0, 150_000, "gpt-4o")
        tracker.record_cost("job3", 10.0, 100_000, "gpt-4o-mini")

        assert tracker.total_cost_usd == 30.0
        assert len(tracker.cost_records) == 3

    def test_tracker_summary(self) -> None:
        """Test cost summary generation."""
        from mdnt.integrations.raze_integration import RazeCostTracker

        tracker = RazeCostTracker(source="test")

        tracker.record_cost("job1", 10.0, 100_000, "gpt-4o-mini")
        tracker.record_cost("job2", 20.0, 200_000, "gpt-4o")
        tracker.record_cost("job3", 10.0, 100_000, "gpt-4o-mini")

        summary = tracker.get_summary()

        assert summary["total_cost_usd"] == 40.0
        assert summary["job_count"] == 3
        assert summary["total_tokens"] == 400_000
        assert summary["average_cost_per_job"] == pytest.approx(13.33, rel=0.01)

        # Check by-model breakdown
        assert "gpt-4o-mini" in summary["by_model"]
        assert "gpt-4o" in summary["by_model"]
        assert summary["by_model"]["gpt-4o-mini"]["cost_usd"] == 20.0
        assert summary["by_model"]["gpt-4o-mini"]["job_count"] == 2

    def test_empty_summary(self) -> None:
        """Test summary with no costs recorded."""
        from mdnt.integrations.raze_integration import RazeCostTracker

        tracker = RazeCostTracker(source="test")
        summary = tracker.get_summary()

        assert summary["total_cost_usd"] == 0.0
        assert summary["job_count"] == 0
        assert summary["total_tokens"] == 0

    def test_get_callback(self) -> None:
        """Test that get_callback returns a callable."""
        from mdnt.integrations.raze_integration import RazeCostTracker

        tracker = RazeCostTracker(source="test")
        callback = tracker.get_callback()

        # Use callback
        callback("job1", 5.0, 50_000, "gpt-4o-mini", {"custom": "data"})

        assert tracker.total_cost_usd == 5.0
        assert tracker.cost_records[0].metadata == {"custom": "data"}


class TestCostCallback:
    """Tests for create_cost_callback factory."""

    def test_create_cost_callback(self) -> None:
        """Test creating a cost callback function."""
        from mdnt.integrations.raze_integration import create_cost_callback

        callback = create_cost_callback(
            cost_threshold_usd=10.0,
            source="test-callback",
        )

        # Callback should work
        callback("job1", 5.0, 50_000, "gpt-4o-mini", None)

        # No way to inspect the internal tracker, but it shouldn't raise


class TestRazeHooks:
    """Tests for create_raze_hooks factory."""

    def test_create_raze_hooks_returns_hooks(self) -> None:
        """Test that create_raze_hooks returns MidnighterHooks."""
        from mdnt.integrations import create_raze_hooks
        from mdnt.hooks import MidnighterHooks

        hooks = create_raze_hooks(
            cost_threshold_usd=50.0,
            source="test-hooks",
        )

        assert isinstance(hooks, MidnighterHooks)

    def test_raze_hooks_has_cost_callback(self) -> None:
        """Test that Raze hooks include cost callback."""
        from mdnt.integrations import create_raze_hooks
        from mdnt.hooks import _noop_cost

        hooks = create_raze_hooks(source="test")

        # on_cost should not be the default noop
        assert hooks.on_cost is not _noop_cost

        # Should be callable
        hooks.on_cost("job1", 10.0, 100_000, "gpt-4o-mini", None)

    def test_raze_hooks_metric_callback(self) -> None:
        """Test that metric callback is configured."""
        from mdnt.integrations import create_raze_hooks
        from mdnt.hooks import _noop_metric

        hooks = create_raze_hooks(source="test")

        # on_metric should not be the default noop
        assert hooks.on_metric is not _noop_metric

        # Should be callable without error
        hooks.on_metric("training_started", {"job_id": "test"})

    def test_raze_hooks_action_callback(self) -> None:
        """Test that action callback is configured."""
        from mdnt.integrations import create_raze_hooks
        from mdnt.hooks import _noop_action

        hooks = create_raze_hooks(source="test")

        # on_action should not be the default noop
        assert hooks.on_action is not _noop_action

        # Should be callable without error
        hooks.on_action("corpus_created", {"corpus_id": "test"})


class TestCostHookInMidnighterHooks:
    """Tests for the on_cost hook in MidnighterHooks."""

    def test_default_cost_hook_is_noop(self) -> None:
        """Test that default cost hook is a no-op."""
        from mdnt.hooks import MidnighterHooks, _noop_cost

        hooks = MidnighterHooks()

        assert hooks.on_cost is _noop_cost

        # Should not raise
        hooks.on_cost("job1", 10.0, 100_000, "model", None)

    def test_custom_cost_hook(self) -> None:
        """Test setting a custom cost hook."""
        from mdnt.hooks import MidnighterHooks

        recorded_costs: List[Dict[str, Any]] = []

        def my_cost_hook(
            job_id: str,
            cost_usd: float,
            trained_tokens: int,
            model: str,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> None:
            recorded_costs.append({
                "job_id": job_id,
                "cost_usd": cost_usd,
                "trained_tokens": trained_tokens,
                "model": model,
            })

        hooks = MidnighterHooks(on_cost=my_cost_hook)

        hooks.on_cost("ftjob-abc", 25.50, 500_000, "gpt-4o-mini", None)

        assert len(recorded_costs) == 1
        assert recorded_costs[0]["job_id"] == "ftjob-abc"
        assert recorded_costs[0]["cost_usd"] == 25.50
