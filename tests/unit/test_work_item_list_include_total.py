"""Unit tests for the Phase A list_work_items latency changes.

Covers:
- The REST handler uses a single `list_work_items(..., include_total=True)` call
  instead of a separate `count_work_items` round-trip when the client asks for
  the total.
- `BoardService.list_work_items` executes a single `run_query` when
  `include_total=True` (not one for count + one for list).
- Concurrent `list_work_items` calls from the same BoardService complete
  independently — basic thread-safety sanity for the A3 threadpool offload.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Optional, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.boards.contracts import (
    WorkItem,
    WorkItemPriority,
    WorkItemStatus,
    WorkItemType,
)
from amprealize.services.board_api_v2 import create_board_routes
from amprealize.services.board_service import BoardService


pytestmark = pytest.mark.unit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_item(item_id: str, *, title: str = "task") -> WorkItem:
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


class _FakeListService:
    """Fake service recording list_work_items / count_work_items calls."""

    def __init__(self, *, total: int = 7, item_count: int = 3) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._total = total
        self._items = [_make_item(f"task-{i:012x}") for i in range(item_count)]

    def list_work_items(self, **kwargs: Any):
        self.calls.append(("list_work_items", kwargs))
        if kwargs.get("include_total"):
            return list(self._items), self._total
        return list(self._items)

    def count_work_items(self, **kwargs: Any) -> int:
        self.calls.append(("count_work_items", kwargs))
        return self._total


def _make_rest_client(fake_service: _FakeListService) -> TestClient:
    app = FastAPI()
    app.include_router(create_board_routes(cast(BoardService, fake_service)))
    return TestClient(app)


def test_list_work_items_handler_does_not_call_count_when_include_total() -> None:
    service = _FakeListService(total=3, item_count=3)
    client = _make_rest_client(service)

    resp = client.get("/v1/work-items?include_total=true&limit=10")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 3
    assert payload["has_more"] is False

    methods = [name for name, _ in service.calls]
    assert methods == ["list_work_items"], f"expected single call, got {methods}"
    _, kwargs = service.calls[0]
    assert kwargs["include_total"] is True
    assert kwargs["limit"] == 10


def test_list_work_items_handler_uses_over_fetch_when_include_total_false() -> None:
    service = _FakeListService(total=0, item_count=11)
    client = _make_rest_client(service)

    resp = client.get("/v1/work-items?include_total=false&limit=10")
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["items"]) == 10
    assert payload["has_more"] is True

    methods = [name for name, _ in service.calls]
    assert methods == ["list_work_items"]
    _, kwargs = service.calls[0]
    assert kwargs.get("include_total", False) is False
    assert kwargs["limit"] == 11  # limit + 1 over-fetch


# ---------------------------------------------------------------------------
# BoardService.list_work_items — single run_query call when include_total=True
# ---------------------------------------------------------------------------


class _FakePool:
    """Minimal PostgresPool stand-in that records run_query invocations.

    Each executor gets a fake connection whose cursor returns a scripted
    rowset shaped like `work_items` + the extra _project_slug / _child_count /
    _completed_child_count / _total columns produced by the real query.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.run_query_calls: list[dict[str, Any]] = []

    def set_tenant_context(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def run_query(
        self,
        *,
        operation: str,
        service_prefix: str,
        executor: Any,
        telemetry: Any = None,
        actor: Any = None,
        metadata: Any = None,
    ) -> Any:
        self.run_query_calls.append({"operation": operation})
        conn = _FakeConnection(self._rows)
        return executor(conn)


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def cursor(self) -> "_FakeCursor":
        return _FakeCursor(self._rows)


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.description: Optional[list[tuple[str]]] = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, _sql: str, _values: Any = None) -> None:
        if self._rows:
            self.description = [(k,) for k in self._rows[0].keys()]
        else:
            # Minimal default columns; fetchall() returns [] anyway.
            self.description = [("id",)]

    def fetchall(self) -> list[tuple[Any, ...]]:
        if not self._rows:
            return []
        keys = list(self._rows[0].keys())
        return [tuple(r[k] for k in keys) for r in self._rows]


def _sample_row(item_id: str, *, total: int, child: int = 0, done: int = 0) -> dict[str, Any]:
    now = _now()
    return {
        "id": item_id,
        "item_type": "task",
        "project_id": None,
        "board_id": None,
        "column_id": None,
        "parent_id": None,
        "title": "sample",
        "description": None,
        "status": "backlog",
        "priority": 2,
        "position": 0,
        "story_points": None,
        "estimated_hours": None,
        "actual_hours": None,
        "assignee_id": None,
        "assignee_type": None,
        "assigned_at": None,
        "assigned_by": None,
        "start_date": None,
        "target_date": None,
        "due_date": None,
        "started_at": None,
        "completed_at": None,
        "color": None,
        "labels": [],
        "acceptance_criteria": [],
        "checklist": [],
        "behavior_id": None,
        "run_id": None,
        "metadata": {},
        "created_at": now,
        "updated_at": now,
        "created_by": "tester",
        "org_id": None,
        "display_number": None,
        "_project_slug": None,
        "_child_count": child,
        "_completed_child_count": done,
        "_total": total,
    }


def _make_service_with_fake_pool(rows: list[dict[str, Any]]) -> tuple[BoardService, _FakePool]:
    pool = _FakePool(rows)
    service = BoardService.__new__(BoardService)
    service._pool = cast(Any, pool)
    service._telemetry = None
    service._event_handlers = []
    service._agent_validator = None
    service._parent_id_exists = None
    return service, pool


def test_list_work_items_with_include_total_emits_single_run_query() -> None:
    rows = [
        _sample_row("11111111-1111-1111-1111-111111111111", total=2),
        _sample_row("22222222-2222-2222-2222-222222222222", total=2),
    ]
    service, pool = _make_service_with_fake_pool(rows)

    items, total = service.list_work_items(include_total=True, limit=10, offset=0)  # type: ignore[misc]

    assert total == 2
    assert len(items) == 2
    assert len(pool.run_query_calls) == 1
    assert pool.run_query_calls[0]["operation"] == "work_item.list"


def test_list_work_items_with_include_total_zero_rows_returns_zero_total() -> None:
    service, pool = _make_service_with_fake_pool(rows=[])
    items, total = service.list_work_items(include_total=True, limit=10, offset=0)  # type: ignore[misc]

    assert items == []
    assert total == 0
    assert len(pool.run_query_calls) == 1


def test_list_work_items_default_return_type_is_unchanged() -> None:
    """Regression guard: existing callers that don't pass include_total get List[WorkItem]."""
    rows = [_sample_row("33333333-3333-3333-3333-333333333333", total=0)]
    service, _ = _make_service_with_fake_pool(rows)

    result = service.list_work_items(limit=10, offset=0)

    assert isinstance(result, list)
    assert len(result) == 1
    assert not isinstance(result, tuple)


# ---------------------------------------------------------------------------
# Thread-safety sanity — concurrent list_work_items calls
# ---------------------------------------------------------------------------


def test_concurrent_list_work_items_complete_independently() -> None:
    rows = [_sample_row(f"{i:08x}-1111-1111-1111-111111111111", total=1) for i in range(1)]
    service, pool = _make_service_with_fake_pool(rows)

    barrier = threading.Barrier(4)
    results: list[Any] = []
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            barrier.wait(timeout=2)
            out = service.list_work_items(include_total=True, limit=10, offset=0)
            results.append(out)
        except BaseException as exc:  # pragma: no cover - diagnostic path
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors, f"unexpected errors: {errors}"
    assert len(results) == 4
    for items, total in results:
        assert total == 1
        assert len(items) == 1
    # Four concurrent calls → four independent run_query invocations.
    assert len(pool.run_query_calls) == 4
