"""Unit tests for brainstorm-to-whiteboard integration.

Following behavior_design_test_strategy (Student):
- exercise the concrete BrainstormBridge against in-memory whiteboard storage
- verify MCP handlers route arguments correctly to the bridge
- cover happy-path reuse, idea/theme creation, and close/export behavior
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from amprealize.mcp.handlers.brainstorm_handlers import (
    BRAINSTORM_HANDLERS,
    handle_add_idea,
    handle_close_session,
    handle_open_whiteboard,
    handle_summarize_board,
)
from amprealize.services.brainstorm_bridge import BrainstormBridge
from whiteboard import InMemoryStorage, WhiteboardService
from whiteboard.models import RoomStatus

pytestmark = pytest.mark.unit


@pytest.fixture
def bridge() -> BrainstormBridge:
    """Concrete bridge wired to in-memory whiteboard storage."""
    whiteboard_service = WhiteboardService(storage=InMemoryStorage())
    return BrainstormBridge(
        whiteboard_service=whiteboard_service,
        base_url="http://localhost:3000",
        sync_base_url="ws://localhost:8787/ws/whiteboard",
    )


class TestBrainstormBridge:
    def test_open_whiteboard_reuses_active_room(self, bridge: BrainstormBridge) -> None:
        first = bridge.open_whiteboard(
            session_id="session-123",
            topic="Launch ideas",
            created_by="agent-1",
        )
        second = bridge.open_whiteboard(
            session_id="session-123",
            topic="Launch ideas",
            created_by="agent-1",
        )

        assert first["room_id"] == second["room_id"]
        assert first["reused"] is False
        assert second["reused"] is True
        assert second["room_url"] == f"http://localhost:3000/whiteboard/{first['room_id']}"
        assert second["sync_url"] == f"ws://localhost:8787/ws/whiteboard/{first['room_id']}"

    def test_add_idea_and_theme_are_reflected_in_summary(self, bridge: BrainstormBridge) -> None:
        room = bridge.open_whiteboard(
            session_id="session-ideas",
            topic="Retention experiments",
            created_by="agent-2",
        )

        bridge.add_idea_to_board(
            room["room_id"],
            "Weekly office hours",
            category="engagement",
            created_by="agent-2",
        )
        bridge.add_theme_to_board(
            room["room_id"],
            "High-touch support",
            connected_ideas=["Weekly office hours"],
            created_by="agent-2",
        )

        summary = bridge.summarize_board(room["room_id"])

        assert summary["shape_count"] >= 2
        assert any(
            idea["text"] == "Weekly office hours" and idea["category"] == "engagement"
            for idea in summary["ideas"]
        )
        assert any(
            theme["theme"] == "High-touch support"
            and theme["connected_ideas"] == ["Weekly office hours"]
            for theme in summary["themes"]
        )

    def test_close_session_exports_snapshot_and_closes_room(self, bridge: BrainstormBridge) -> None:
        room = bridge.open_whiteboard(
            session_id="session-close",
            topic="Wrap-up",
            created_by="agent-3",
        )
        bridge.add_idea_to_board(
            room["room_id"],
            "Document next steps",
            category="action-items",
            created_by="agent-3",
        )

        result = bridge.close_session(room["room_id"])
        stored_room = bridge._whiteboard.get_room(room["room_id"])

        assert result["room_id"] == room["room_id"]
        assert result["snapshot_format"] == "json"
        assert isinstance(result["snapshot_data"], dict)
        assert stored_room is not None
        assert stored_room.status == RoomStatus.CLOSED
        assert result["room_status"] == "closed"


class TestBrainstormHandlers:
    def test_registry_contains_expected_tools(self) -> None:
        assert set(BRAINSTORM_HANDLERS) == {
            "brainstorm.openWhiteboard",
            "brainstorm.addIdea",
            "brainstorm.summarizeBoard",
            "brainstorm.closeSession",
        }

    def test_open_whiteboard_uses_session_context(self) -> None:
        service = MagicMock()
        service.open_whiteboard.return_value = {
            "room_id": "room-123",
            "room_url": "http://localhost:3000/whiteboard/room-123",
            "title": "Brainstorm: Launch",
            "session_id": "session-ctx",
            "status": "active",
            "participant_ids": [],
            "metadata": {},
            "reused": False,
        }

        result = handle_open_whiteboard(
            service,
            {
                "topic": "Launch",
                "_session": {"session_id": "session-ctx", "user_id": "user-42"},
            },
        )

        assert result["success"] is True
        service.open_whiteboard.assert_called_once_with(
            session_id="session-ctx",
            topic="Launch",
            created_by="user-42",
            phase=None,
            metadata={},
        )

    def test_add_idea_routes_theme_requests(self) -> None:
        service = MagicMock()
        service.add_theme_to_board.return_value = {
            "room_id": "room-123",
            "shape_id": "shape-999",
            "theme": "Support cluster",
            "connected_ideas": ["Weekly office hours"],
        }

        result = handle_add_idea(
            service,
            {
                "room_id": "room-123",
                "idea": "Support cluster",
                "kind": "theme",
                "connected_ideas": ["Weekly office hours"],
                "_session": {"user_id": "agent-7"},
            },
        )

        assert result["success"] is True
        assert result["idea_type"] == "theme"
        service.add_theme_to_board.assert_called_once_with(
            "room-123",
            "Support cluster",
            connected_ideas=["Weekly office hours"],
            created_by="agent-7",
            x=None,
            y=None,
        )

    def test_summarize_and_close_handlers_delegate(self) -> None:
        service = MagicMock()
        service.summarize_board.return_value = {
            "room_id": "room-123",
            "shape_count": 3,
            "ideas": [{"text": "Idea A"}],
            "themes": [],
            "connections": [],
            "summary": {"shape_count": 3},
        }
        service.close_session.return_value = {
            "room_id": "room-123",
            "snapshot_format": "json",
            "snapshot_data": {},
            "exported_at": "2026-01-01T00:00:00+00:00",
            "room_status": "closed",
        }

        summary_result = handle_summarize_board(service, {"room_id": "room-123"})
        close_result = handle_close_session(service, {"room_id": "room-123", "format": "json"})

        assert summary_result["success"] is True
        assert close_result["success"] is True
        service.summarize_board.assert_called_once_with("room-123")
        service.close_session.assert_called_once_with("room-123", export_format="json")
