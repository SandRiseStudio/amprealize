"""Tests for WorkItemPlanner (amprealize-488)."""

import pytest

from amprealize.agents.work_item_planner.planner import (
    Depth,
    PlannedItem,
    PlanResult,
    WorkItemPlanner,
)


class TestWorkItemPlanner:
    """Test WorkItemPlanner.plan() method."""

    def setup_method(self) -> None:
        self.planner = WorkItemPlanner()

    # ── goal_only depth ───────────────────────────────────────────────────

    @pytest.mark.unit
    def test_goal_only_produces_single_item(self) -> None:
        result = self.planner.plan(
            goal_title="Implement User Authentication",
            goal_description="Add OAuth2-based auth",
            depth=Depth.GOAL_ONLY,
        )
        assert result.is_valid
        assert len(result.work_items) == 1
        assert result.work_items[0].item_type == "goal"
        assert result.work_items[0].title == "Implement User Authentication"
        assert result.depth == "goal_only"

    @pytest.mark.unit
    def test_goal_only_ignores_features(self) -> None:
        result = self.planner.plan(
            goal_title="Implement User Authentication",
            features=[{"title": "Add OAuth2 Provider Integration"}],
            depth=Depth.GOAL_ONLY,
        )
        assert result.is_valid
        assert len(result.work_items) == 1
        assert len(result.work_items[0].children) == 0

    # ── goal_and_features depth ───────────────────────────────────────────

    @pytest.mark.unit
    def test_goal_and_features_produces_hierarchy(self) -> None:
        result = self.planner.plan(
            goal_title="Implement User Authentication",
            features=[
                {"title": "Add OAuth2 Provider Integration", "points": 5},
                {"title": "Create Login and Signup Pages", "points": 3},
            ],
            depth=Depth.GOAL_AND_FEATURES,
        )
        assert result.is_valid
        assert len(result.work_items) == 1
        goal = result.work_items[0]
        assert len(goal.children) == 2
        assert goal.children[0].item_type == "feature"
        assert goal.children[0].parent_ref == "goal:0"
        assert goal.children[1].points == 3

    # ── full depth ────────────────────────────────────────────────────────

    @pytest.mark.unit
    def test_full_depth_produces_tasks(self) -> None:
        result = self.planner.plan(
            goal_title="Implement User Authentication",
            features=[
                {
                    "title": "Add OAuth2 Provider Integration",
                    "tasks": [
                        {"title": "Set up OAuth2 client library"},
                        {"title": "Write token refresh handler"},
                    ],
                },
            ],
            depth=Depth.FULL,
        )
        assert result.is_valid
        goal = result.work_items[0]
        feature = goal.children[0]
        assert len(feature.children) == 2
        assert feature.children[0].item_type == "task"
        assert feature.children[0].parent_ref == "feature:0"

    # ── Validation ────────────────────────────────────────────────────────

    @pytest.mark.unit
    def test_invalid_goal_title_caught(self) -> None:
        result = self.planner.plan(
            goal_title="Phase 1: Bad title",
            depth=Depth.GOAL_ONLY,
        )
        assert not result.is_valid
        assert len(result.validation_errors) >= 1
        assert "Goal" in result.validation_errors[0]

    @pytest.mark.unit
    def test_invalid_feature_title_caught(self) -> None:
        result = self.planner.plan(
            goal_title="Implement User Authentication",
            features=[{"title": "STORY-42 bad feature"}],
            depth=Depth.GOAL_AND_FEATURES,
        )
        assert not result.is_valid
        assert any("Feature[0]" in e for e in result.validation_errors)

    @pytest.mark.unit
    def test_invalid_task_title_caught(self) -> None:
        result = self.planner.plan(
            goal_title="Implement User Authentication",
            features=[
                {
                    "title": "Add OAuth2 Provider Integration",
                    "tasks": [{"title": "1. do thing"}],
                },
            ],
            depth=Depth.FULL,
        )
        assert not result.is_valid
        assert any("Feature[0].Task[0]" in e for e in result.validation_errors)

    # ── Labels ────────────────────────────────────────────────────────────

    @pytest.mark.unit
    def test_gws_label_auto_added(self) -> None:
        result = self.planner.plan(
            goal_title="Implement User Authentication",
            depth=Depth.GOAL_ONLY,
        )
        assert "gws:v1.0" in result.work_items[0].labels

    @pytest.mark.unit
    def test_custom_labels_preserved(self) -> None:
        result = self.planner.plan(
            goal_title="Implement User Authentication",
            labels=["phase:1", "track:backend"],
            depth=Depth.GOAL_ONLY,
        )
        labels = result.work_items[0].labels
        assert "phase:1" in labels
        assert "track:backend" in labels
        assert "gws:v1.0" in labels

    # ── to_dict ───────────────────────────────────────────────────────────

    @pytest.mark.unit
    def test_to_dict_output(self) -> None:
        result = self.planner.plan(
            goal_title="Implement User Authentication",
            features=[{"title": "Add OAuth2 Provider Integration"}],
            depth=Depth.GOAL_AND_FEATURES,
        )
        d = result.to_dict()
        assert d["gws_version"] == "1.0"
        assert d["depth"] == "goal_and_features"
        assert len(d["work_items"]) == 1
        assert "children" in d["work_items"][0]

    # ── validate_items ────────────────────────────────────────────────────

    @pytest.mark.unit
    def test_validate_items_with_valid(self) -> None:
        errors = self.planner.validate_items([
            {"item_type": "goal", "title": "Implement Something Great"},
            {"item_type": "feature", "title": "Add New Feature Here"},
        ])
        assert errors == []

    @pytest.mark.unit
    def test_validate_items_with_invalid(self) -> None:
        errors = self.planner.validate_items([
            {"item_id": "item-123", "item_type": "goal", "title": "Phase 1: Bad"},
            {"item_type": "feature", "title": "Good Feature Title Here"},
        ])
        assert len(errors) == 1
        assert "item-123" in errors[0]
