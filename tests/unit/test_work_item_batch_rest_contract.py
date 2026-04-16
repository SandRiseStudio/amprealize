from datetime import datetime, timezone
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.boards.contracts import WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType
from amprealize.services.board_api_v2 import create_board_routes
from amprealize.services.board_service import BoardService


pytestmark = pytest.mark.unit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_item(item_id: str, *, title: str) -> WorkItem:
    return WorkItem(
        item_id=item_id,
        item_type=WorkItemType.TASK,
        title=title,
        status=WorkItemStatus.BACKLOG,
        priority=WorkItemPriority.MEDIUM,
        created_at=_now(),
        updated_at=_now(),
        created_by="tester",
    )


class FakeBoardService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_work_items_batch(self, item_ids: list[str], *, org_id: str | None = None) -> list[WorkItem]:
        self.calls.append(("get_work_items_batch", {"item_ids": item_ids, "org_id": org_id}))
        return [
            _make_item("task-123456789abc", title="First task"),
            _make_item("task-abcdef123456", title="Second task"),
        ]


def _make_rest_client(fake_service: FakeBoardService) -> TestClient:
    app = FastAPI()
    app.include_router(create_board_routes(cast(BoardService, fake_service)))
    return TestClient(app)


def test_rest_batch_get_work_items_returns_items_total_and_missing_ids() -> None:
    service = FakeBoardService()
    client = _make_rest_client(service)

    resp = client.post(
        "/v1/work-items/batch",
        json={"item_ids": ["task-123456789abc", "task-abcdef123456", "task-ffffffffffff"]},
    )
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["total"] == 2
    assert [item["item_id"] for item in payload["items"]] == ["task-123456789abc", "task-abcdef123456"]
    assert payload["missing_ids"] == ["task-ffffffffffff"]

    method, call = service.calls[-1]
    assert method == "get_work_items_batch"
    assert call["item_ids"] == ["task-123456789abc", "task-abcdef123456", "task-ffffffffffff"]


def test_rest_batch_get_work_items_validates_max_ids() -> None:
    service = FakeBoardService()
    client = _make_rest_client(service)

    resp = client.post("/v1/work-items/batch", json={"item_ids": [f"task-{index}" for index in range(101)]})
    assert resp.status_code == 422
