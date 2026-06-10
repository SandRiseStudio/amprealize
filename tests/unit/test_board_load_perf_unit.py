"""Unit tests for board load perf helpers (no Postgres / Alembic).

Following `behavior_design_test_strategy` (Student).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from amprealize.boards.contracts import WorkItem, WorkItemType
from amprealize.services.board_service import BoardService

pytestmark = pytest.mark.unit


def _goal_item(suffix_hex: str) -> WorkItem:
    now = datetime.now(timezone.utc)
    return WorkItem(
        item_id=f"goal-{suffix_hex}",
        item_type=WorkItemType.GOAL,
        title="G",
        created_at=now,
        updated_at=now,
        created_by="tester",
        parent_id=None,
    )


def test_list_work_items_board_pages_dedupes_sorted_offsets_and_total() -> None:
    svc = BoardService.__new__(BoardService)
    calls: list[tuple[int, int, bool]] = []

    def fake_list(
        *,
        board_id: str,
        org_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        include_total: bool = False,
        **kwargs: object,
    ):
        calls.append((offset, limit, include_total))
        total = 5
        slice_n = min(limit, max(0, total - offset))
        items = [_goal_item(f"{i:012x}") for i in range(offset, offset + slice_n)]
        if include_total:
            return items, total
        return items

    svc.list_work_items = fake_list  # type: ignore[method-assign]

    pages, total = svc.list_work_items_board_pages(
        "00000000-0000-4000-8000-00000000feed",
        2,
        [4, 0, 2, 0],
        org_id="org-x",
        include_total_from_first_zero=True,
    )

    assert total == 5
    assert calls == [(0, 2, True), (2, 2, False), (4, 2, False)]
    assert [p[0] for p in pages] == [0, 2, 4]
    assert [len(p[1]) for p in pages] == [2, 2, 1]
    assert pages[0][2] is True
    assert pages[1][2] is True
    assert pages[2][2] is False


def test_list_work_items_board_pages_include_total_on_first_sorted_offset() -> None:
    """First sub-query after sort should use include_total even when min offset != 0."""
    svc = BoardService.__new__(BoardService)
    calls: list[tuple[int, bool]] = []

    def fake_list(
        *,
        board_id: str,
        org_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        include_total: bool = False,
        **kwargs: object,
    ):
        calls.append((offset, include_total))
        total = 1203
        slice_n = min(limit, max(0, total - offset))
        items = [_goal_item(f"{i:012x}") for i in range(offset, offset + slice_n)]
        if include_total:
            return items, total
        return items

    svc.list_work_items = fake_list  # type: ignore[method-assign]

    _pages, total = svc.list_work_items_board_pages(
        "00000000-0000-4000-8000-00000000feed",
        100,
        [400, 100, 200],
        org_id="org-x",
        include_total_from_first_zero=True,
    )

    assert total == 1203
    assert calls == [(100, True), (200, False), (400, False)]


def test_list_board_progress_rollups_preloaded_skips_db_list() -> None:
    svc = BoardService.__new__(BoardService)
    svc.list_work_items = MagicMock()
    svc.get_board = MagicMock()
    root = _goal_item("a" * 12)
    rollups = svc.list_board_progress_rollups(
        "00000000-0000-4000-8000-00000000beef",
        org_id="org-x",
        preloaded_items=[root],
    )
    svc.list_work_items.assert_not_called()
    svc.get_board.assert_not_called()
    assert len(rollups) == 1
    assert rollups[0].item_id == root.item_id
