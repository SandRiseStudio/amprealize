"""MCP handler parity tests for brainstorm and whiteboard tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from amprealize.mcp.handlers.brainstorm_handlers import (
    BRAINSTORM_HANDLERS,
    BrainstormToolValidationError,
    handle_add_idea,
)
from amprealize.mcp.handlers.whiteboard_handlers import (
    WHITEBOARD_HANDLERS,
    WhiteboardToolValidationError,
    handle_read_canvas,
)


pytestmark = pytest.mark.unit


def _manifest_names(prefix: str) -> set[str]:
    root = Path(__file__).resolve().parents[1]
    return {
        json.loads(path.read_text())["name"]
        for path in (root / "mcp" / "tools").glob(f"{prefix}*.json")
    }


def test_brainstorm_manifests_have_handlers() -> None:
    assert _manifest_names("brainstorm.") == set(BRAINSTORM_HANDLERS)


def test_whiteboard_manifests_have_handlers() -> None:
    public_handlers = set(WHITEBOARD_HANDLERS) - {"whiteboard.createRoom"}
    assert _manifest_names("whiteboard.") == public_handlers


def test_brainstorm_missing_room_id_raises_validation_error() -> None:
    with pytest.raises(BrainstormToolValidationError):
        handle_add_idea(MagicMock(), {"idea": "Try live demos"})


def test_whiteboard_read_canvas_uses_session_room_id() -> None:
    service = MagicMock()
    service.get_room.return_value = object()
    service.get_canvas_state.return_value = {}
    service.read_canvas_summary.return_value = {"shape_count": 0, "shapes": [], "text_elements": [], "connections": []}

    result = handle_read_canvas(service, {"_session": {"room_id": "room-123"}})

    assert result["success"] is True
    assert result["room_id"] == "room-123"
    service.get_room.assert_called_once_with("room-123")


def test_whiteboard_missing_room_id_raises_validation_error() -> None:
    with pytest.raises(WhiteboardToolValidationError):
        handle_read_canvas(MagicMock(), {})
