"""Unit tests for assignment_history assignable_type mapping."""

import pytest

from amprealize.boards.contracts import WorkItemType
from amprealize.services.board_service import _history_assignable_type

pytestmark = pytest.mark.unit


def test_history_assignable_type_maps_goal_and_research() -> None:
    assert _history_assignable_type(WorkItemType.GOAL) == "epic"
    assert _history_assignable_type(WorkItemType.RESEARCH) == "task"
    assert _history_assignable_type(WorkItemType.TASK) == "task"
    assert _history_assignable_type(WorkItemType.FEATURE) == "feature"
