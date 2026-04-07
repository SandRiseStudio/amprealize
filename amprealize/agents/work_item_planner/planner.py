"""WorkItemPlanner — formats and creates GWS-compliant work items.

This is a **formatter/creator** only. It takes a goal description and
produces properly structured work items following GWS v1.0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from amprealize.agents.work_item_planner.prompts import (
    GWS_VERSION,
    HIERARCHY,
    validate_title,
)

logger = logging.getLogger(__name__)


class Depth(str, Enum):
    """Planning depth levels."""
    GOAL_ONLY = "goal_only"
    GOAL_AND_FEATURES = "goal_and_features"
    FULL = "full"


@dataclass
class PlannedItem:
    """A single planned work item."""
    item_type: str
    title: str
    description: str = ""
    priority: str = "medium"
    labels: List[str] = field(default_factory=list)
    points: Optional[int] = None
    parent_ref: Optional[str] = None  # e.g. "goal:0", "feature:1"
    children: List[PlannedItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "item_type": self.item_type,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "labels": self.labels,
            "points": self.points,
            "parent_ref": self.parent_ref,
        }
        if self.children:
            result["children"] = [c.to_dict() for c in self.children]
        return result


@dataclass
class PlanResult:
    """Result of a planning operation."""
    gws_version: str
    depth: str
    work_items: List[PlannedItem]
    validation_errors: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.validation_errors) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gws_version": self.gws_version,
            "depth": self.depth,
            "work_items": [item.to_dict() for item in self.work_items],
            "validation_errors": self.validation_errors,
        }


class WorkItemPlanner:
    """Formats and validates GWS-compliant work item plans.

    Usage:
        planner = WorkItemPlanner()
        result = planner.plan(
            goal_title="Implement User Authentication",
            goal_description="Add OAuth2-based auth...",
            features=[
                {"title": "Add OAuth2 Provider Integration", "description": "..."},
                {"title": "Create Login and Signup Pages", "description": "..."},
            ],
            depth=Depth.GOAL_AND_FEATURES,
        )
    """

    def plan(
        self,
        goal_title: str,
        goal_description: str = "",
        features: Optional[List[Dict[str, Any]]] = None,
        tasks: Optional[List[Dict[str, Any]]] = None,
        depth: Depth = Depth.GOAL_AND_FEATURES,
        labels: Optional[List[str]] = None,
        priority: str = "medium",
    ) -> PlanResult:
        """Build a GWS-compliant work item plan.

        Args:
            goal_title: Title for the top-level goal
            goal_description: Description of the goal
            features: List of feature dicts with at minimum 'title'
            tasks: List of task dicts (only used when depth=FULL)
            depth: How deep to plan (goal_only, goal_and_features, full)
            labels: Labels to apply to all items
            priority: Default priority for the goal

        Returns:
            PlanResult with validated work items
        """
        base_labels = list(labels or [])
        if f"gws:v{GWS_VERSION}" not in base_labels:
            base_labels.append(f"gws:v{GWS_VERSION}")

        validation_errors: List[str] = []

        # Build goal
        goal = PlannedItem(
            item_type="goal",
            title=goal_title,
            description=goal_description,
            priority=priority,
            labels=list(base_labels),
        )

        # Validate goal title
        error = validate_title("goal", goal_title)
        if error:
            validation_errors.append(f"Goal: {error}")

        # Build features if requested
        if depth in (Depth.GOAL_AND_FEATURES, Depth.FULL) and features:
            for i, feat_data in enumerate(features):
                feat = PlannedItem(
                    item_type="feature",
                    title=feat_data.get("title", ""),
                    description=feat_data.get("description", ""),
                    priority=feat_data.get("priority", "medium"),
                    labels=feat_data.get("labels", list(base_labels)),
                    points=feat_data.get("points"),
                    parent_ref="goal:0",
                )
                # Validate
                feat_error = validate_title("feature", feat.title)
                if feat_error:
                    validation_errors.append(f"Feature[{i}]: {feat_error}")

                # Build tasks under this feature if depth=FULL
                if depth == Depth.FULL:
                    feature_tasks = feat_data.get("tasks", [])
                    for j, task_data in enumerate(feature_tasks):
                        task = PlannedItem(
                            item_type=task_data.get("item_type", "task"),
                            title=task_data.get("title", ""),
                            description=task_data.get("description", ""),
                            priority=task_data.get("priority", "medium"),
                            labels=task_data.get("labels", list(base_labels)),
                            points=task_data.get("points"),
                            parent_ref=f"feature:{i}",
                        )
                        task_error = validate_title(task.item_type, task.title)
                        if task_error:
                            validation_errors.append(f"Feature[{i}].Task[{j}]: {task_error}")
                        feat.children.append(task)

                goal.children.append(feat)

        # Also add top-level tasks if provided and depth is FULL
        if depth == Depth.FULL and tasks:
            for k, task_data in enumerate(tasks):
                task = PlannedItem(
                    item_type=task_data.get("item_type", "task"),
                    title=task_data.get("title", ""),
                    description=task_data.get("description", ""),
                    priority=task_data.get("priority", "medium"),
                    labels=task_data.get("labels", list(base_labels)),
                    points=task_data.get("points"),
                    parent_ref="goal:0",
                )
                task_error = validate_title(task.item_type, task.title)
                if task_error:
                    validation_errors.append(f"Task[{k}]: {task_error}")
                goal.children.append(task)

        return PlanResult(
            gws_version=GWS_VERSION,
            depth=depth.value,
            work_items=[goal],
            validation_errors=validation_errors,
        )

    def validate_items(self, items: List[Dict[str, Any]]) -> List[str]:
        """Validate a list of existing work item dicts against GWS.

        Returns list of error messages (empty = all valid).
        """
        errors: List[str] = []
        for i, item in enumerate(items):
            item_type = item.get("item_type", "task")
            title = item.get("title", "")
            error = validate_title(item_type, title)
            if error:
                item_id = item.get("item_id", item.get("id", f"index:{i}"))
                errors.append(f"{item_id}: {error}")
        return errors
