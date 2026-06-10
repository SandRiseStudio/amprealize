"""Unit tests for board/work item MCP handler routing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from amprealize.boards.contracts import WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType
from amprealize.mcp.handlers.board_handlers import (
    BOARD_HANDLERS,
    COLUMN_HANDLERS,
    WORK_ITEM_HANDLERS,
    _mcp_coalesce_points,
    handle_create_work_item,
    handle_get_work_item,
    handle_get_work_items_batch,
    handle_list_work_items,
    handle_post_comment,
    handle_update_work_item,
)
from amprealize.mcp.handlers.work_item_execution_handlers import get_work_item_execution_tools


pytestmark = pytest.mark.unit


def test_mcp_coalesce_points_preserves_zero_and_prefers_points_key() -> None:
    assert _mcp_coalesce_points({"points": 0}) == 0
    assert _mcp_coalesce_points({"story_points": 0}) == 0
    assert _mcp_coalesce_points({"points": 5}) == 5
    assert _mcp_coalesce_points({"story_points": 3}) == 3
    assert _mcp_coalesce_points({"points": 1, "story_points": 9}) == 1
    assert _mcp_coalesce_points({}) is None


class _FakeCommentService:
    def resolve_work_item_id(self, identifier: str, org_id=None, project_id=None) -> str:
        return identifier

    def add_comment(self, **kwargs):
        return {
            "work_item_id": kwargs["work_item_id"],
            "author_id": kwargs["author_id"],
            "author_type": kwargs["author_type"],
            "content": kwargs["content"],
        }


def test_board_and_work_item_manifests_have_handlers() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest_names = {
        json.loads(path.read_text())["name"]
        for path in (root / "mcp" / "tools").glob("*.json")
        if path.name.startswith(("board.", "boards.", "columns.", "workItems."))
    }
    execution_names = {tool["name"] for tool in get_work_item_execution_tools()}
    handled_names = set(BOARD_HANDLERS) | set(COLUMN_HANDLERS) | set(WORK_ITEM_HANDLERS) | execution_names

    assert manifest_names - handled_names == set()


def test_post_comment_defaults_author_from_session() -> None:
    result = handle_post_comment(
        _FakeCommentService(),
        {
            "work_item_id": "task-123",
            "body": "Looks good.",
            "_session": {"user_id": "user-123"},
        },
    )

    assert result["success"] is True
    assert result["comment"]["author_id"] == "user-123"


def test_post_comment_defaults_author_from_user_id_and_agent_role() -> None:
    result = handle_post_comment(
        _FakeCommentService(),
        {
            "work_item_id": "guideai-1052",
            "body": "Completed guideai-1052.",
            "user_id": "cursor-agent",
            "actor_role": "Student",
            "actor_surface": "mcp",
        },
    )

    assert result["success"] is True
    assert result["comment"]["author_id"] == "cursor-agent"
    assert result["comment"]["author_type"] == "agent"


class _FakeListWorkItemsService:
    def __init__(self) -> None:
        self.calls = []

    def _item(self) -> WorkItem:
        return WorkItem(
            item_id="task-123456789abc",
            item_type=WorkItemType.TASK,
            project_id="proj-123",
            board_id="board-123",
            parent_id="feature-123456789abc",
            title="Investigate slow work item calls",
            description="Long detail should not be returned in default list mode.",
            status=WorkItemStatus.IN_PROGRESS,
            priority=WorkItemPriority.HIGH,
            labels=["performance"],
            created_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 28, 1, tzinfo=timezone.utc),
            created_by="tester",
            display_number=42,
            display_id="amprealize-42",
            child_count=3,
            completed_child_count=1,
            progress_percent=33.3,
        )

    def list_work_items(self, **kwargs):
        self.calls.append(kwargs)
        return [self._item()], 10

    def create_work_item(self, request, actor, *, org_id=None):
        return self._item()

    def get_work_item(self, item_id, *, org_id=None):
        return self._item()

    def get_work_items_batch(self, item_ids, *, org_id=None):
        return [self._item()]

    def update_work_item(self, item_id, request, actor, *, org_id=None):
        return self._item()

    def resolve_work_item_id(self, identifier, org_id=None, project_id=None):
        return identifier


def test_list_work_items_defaults_to_brief_and_inline_total() -> None:
    service = _FakeListWorkItemsService()

    result = handle_list_work_items(service, {"project_id": "proj-123"})

    assert result["success"] is True
    assert result["brief"] is True
    assert result["limit"] == 25
    assert result["total"] == 10
    assert result["has_more"] is True
    assert service.calls[0]["include_total"] is True
    assert result["items"][0]["display_id"] == "amprealize-42"
    assert "description" not in result["items"][0]


def test_list_work_items_can_return_full_records() -> None:
    service = _FakeListWorkItemsService()

    result = handle_list_work_items(
        service,
        {"project_id": "proj-123", "brief": False, "limit": 5},
    )

    assert result["brief"] is False
    assert result["limit"] == 5
    assert result["items"][0]["description"] == "Long detail should not be returned in default list mode."


def test_create_update_and_batch_default_to_brief_records() -> None:
    service = _FakeListWorkItemsService()

    create_result = handle_create_work_item(
        service,
        {"item_type": "task", "project_id": "proj-123", "title": "Create compact response"},
    )
    update_result = handle_update_work_item(
        service,
        {"item_id": "task-123456789abc", "title": "Update compact response"},
    )
    batch_result = handle_get_work_items_batch(
        service,
        {"item_ids": ["task-123456789abc"]},
    )

    assert create_result["brief"] is True
    assert update_result["brief"] is True
    assert batch_result["brief"] is True
    assert "description" not in create_result["item"]
    assert "description" not in update_result["item"]
    assert "description" not in batch_result["items"][0]


def test_get_work_item_stays_full_detail_by_default_but_supports_brief() -> None:
    service = _FakeListWorkItemsService()

    full_result = handle_get_work_item(service, {"item_id": "task-123456789abc"})
    brief_result = handle_get_work_item(
        service,
        {"item_id": "task-123456789abc", "brief": True},
    )

    assert full_result["brief"] is False
    assert full_result["item"]["description"] == "Long detail should not be returned in default list mode."
    assert brief_result["brief"] is True
    assert "description" not in brief_result["item"]


def test_list_work_items_passes_text_search_to_board_service() -> None:
    """handle_list_work_items must forward text_search to list_work_items."""
    service = _FakeListWorkItemsService()

    handle_list_work_items(
        service,
        {"project_id": "proj-123", "text_search": "agent execution"},
    )

    assert service.calls[0].get("text_search") == "agent execution"


def test_list_work_items_passes_title_search_to_board_service() -> None:
    """handle_list_work_items must forward title_search to list_work_items."""
    service = _FakeListWorkItemsService()

    handle_list_work_items(
        service,
        {"project_id": "proj-123", "title_search": "routing fix"},
    )

    assert service.calls[0].get("title_search") == "routing fix"


def test_list_work_items_text_and_title_search_coexist() -> None:
    """text_search and title_search can both be provided simultaneously."""
    service = _FakeListWorkItemsService()

    handle_list_work_items(
        service,
        {
            "project_id": "proj-123",
            "text_search": "execution",
            "title_search": "phase",
        },
    )

    call = service.calls[0]
    assert call.get("text_search") == "execution"
    assert call.get("title_search") == "phase"
