"""Regression: workItems.update must not invoke complete_with_descendants."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from amprealize.mcp.handlers.board_handlers import handle_update_work_item
from amprealize.boards.contracts import (
    UpdateWorkItemRequest,
    WorkItem,
    WorkItemStatus,
    WorkItemType,
)

pytestmark = pytest.mark.unit


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeBoardService:
    def __init__(self) -> None:
        self.complete_calls = 0

    def resolve_work_item_id(self, identifier: str, org_id=None, project_id=None) -> str:
        return identifier

    def complete_with_descendants(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.complete_calls += 1
        raise AssertionError("complete_with_descendants must not be invoked from MCP update")

    def update_work_item(self, item_id: str, request: UpdateWorkItemRequest, actor, org_id=None) -> WorkItem:
        return WorkItem(
            item_id=item_id,
            item_type=WorkItemType.TASK,
            title="stub",
            status=request.status or WorkItemStatus.BACKLOG,
            created_at=_now(),
            updated_at=_now(),
            created_by="test",
        )


def test_workitems_update_ignores_cascade_to_children() -> None:
    fake = _FakeBoardService()
    out = handle_update_work_item(
        fake,
        {
            "item_id": "task-aaaaaaaaaaaa",
            "status": "done",
            "cascade_to_children": True,
        },
    )
    assert out["success"] is True
    assert out["item"]["status"] == "done"
    assert "cascade_result" not in out
    assert fake.complete_calls == 0
