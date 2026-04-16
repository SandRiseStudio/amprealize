"""MCP tool handlers for BrainstormBridge.

Provides brainstorming-specific whiteboard orchestration handlers using the same
sync handler pattern as other MCP domains.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .whiteboard_handlers import _get_session_field, _get_user_id

logger = logging.getLogger(__name__)


def handle_open_whiteboard(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Open or reuse a brainstorm whiteboard for the current session."""
    topic = arguments.get("topic") or "Brainstorm Session"
    session_id = arguments.get("session_id") or _get_session_field(arguments, "session_id")
    created_by = _get_user_id(arguments)
    phase = arguments.get("phase")
    metadata = arguments.get("metadata") or {}

    try:
        payload = service.open_whiteboard(
            session_id=session_id,
            topic=topic,
            created_by=created_by,
            phase=phase,
            metadata=metadata,
        )
        return {
            "success": True,
            **payload,
            "message": "Brainstorm whiteboard ready",
        }
    except Exception as e:
        logger.error("brainstorm.openWhiteboard failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


def handle_add_idea(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Add a brainstorm idea or theme to the board."""
    room_id = arguments.get("room_id")
    if not room_id:
        return {"success": False, "error": "room_id is required"}

    idea = arguments.get("idea") or arguments.get("text")
    if not idea:
        return {"success": False, "error": "idea is required"}

    created_by = _get_user_id(arguments)
    category = arguments.get("category")
    idea_type = (arguments.get("idea_type") or arguments.get("kind") or "idea").lower()
    x = arguments.get("x")
    y = arguments.get("y")

    try:
        if idea_type == "theme":
            payload = service.add_theme_to_board(
                room_id,
                idea,
                connected_ideas=arguments.get("connected_ideas") or [],
                created_by=created_by,
                x=x,
                y=y,
            )
            message = "Theme added to brainstorm board"
        else:
            payload = service.add_idea_to_board(
                room_id,
                idea,
                category=category,
                created_by=created_by,
                x=x,
                y=y,
            )
            message = "Idea added to brainstorm board"

        return {
            "success": True,
            **payload,
            "idea_type": idea_type,
            "message": message,
        }
    except Exception as e:
        logger.error("brainstorm.addIdea failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


def handle_summarize_board(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Summarize brainstorm content from the board."""
    room_id = arguments.get("room_id")
    if not room_id:
        return {"success": False, "error": "room_id is required"}

    try:
        payload = service.summarize_board(room_id)
        return {
            "success": True,
            **payload,
            "message": "Brainstorm board summarized",
        }
    except Exception as e:
        logger.error("brainstorm.summarizeBoard failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


def handle_close_session(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Export and close the brainstorm whiteboard room."""
    room_id = arguments.get("room_id")
    if not room_id:
        return {"success": False, "error": "room_id is required"}

    export_format = arguments.get("format", "json")

    try:
        payload = service.close_session(room_id, export_format=export_format)
        return {
            "success": True,
            **payload,
            "message": "Brainstorm whiteboard closed",
        }
    except Exception as e:
        logger.error("brainstorm.closeSession failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


BRAINSTORM_HANDLERS: Dict[str, Any] = {
    "brainstorm.openWhiteboard": handle_open_whiteboard,
    "brainstorm.addIdea": handle_add_idea,
    "brainstorm.summarizeBoard": handle_summarize_board,
    "brainstorm.closeSession": handle_close_session,
}
