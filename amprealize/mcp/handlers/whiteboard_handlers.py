"""MCP tool handlers for WhiteboardService.

Provides handlers for whiteboard room management, canvas manipulation,
and snapshot export. Follows the ``board_handlers.py`` pattern:
each handler is a sync function ``(service, arguments) -> Dict[str, Any]``
called via ``asyncio.to_thread()`` in ``mcp_server.py``.

Following ``behavior_prefer_mcp_tools`` — MCP provides consistent schemas
and automatic telemetry.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ==============================================================================
# Serialization Helpers
# ==============================================================================


def _serialize_value(value: Any) -> Any:
    """Recursively serialize values for JSON output."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):  # Enum
        return value.value
    if hasattr(value, "model_dump"):  # Pydantic model
        return {k: _serialize_value(v) for k, v in value.model_dump().items()}
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return str(value)


def _room_to_dict(room: Any) -> Dict[str, Any]:
    """Convert a WhiteboardRoom Pydantic model to a serializable dict."""
    if hasattr(room, "model_dump"):
        raw = room.model_dump()
    else:
        raw = dict(room) if hasattr(room, "__iter__") else {"id": str(room)}
    return {k: _serialize_value(v) for k, v in raw.items()}


def _get_user_id(arguments: Dict[str, Any]) -> str:
    """Extract user_id from explicit param or session context."""
    user_id = arguments.get("user_id")
    if not user_id:
        session = arguments.get("_session", {})
        user_id = session.get("user_id", "mcp-user")
    return str(user_id)


def _get_session_field(arguments: Dict[str, Any], field: str, default: str = "") -> str:
    """Get a field from explicit args first, then session context."""
    val = arguments.get(field)
    if val:
        return str(val)
    session = arguments.get("_session", {})
    return str(session.get(field, default))


# ==============================================================================
# Room Lifecycle Handlers
# ==============================================================================


def handle_create_room(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a new whiteboard room.

    Rooms must originate from a brainstorm session — use
    ``brainstorm.openWhiteboard`` instead.  Direct calls are rejected
    unless the caller includes ``metadata.source = "brainstorm_bridge"``.

    MCP Tool: whiteboard.createRoom
    """
    from whiteboard.models import RoomCreateRequest

    metadata = arguments.get("metadata") or {}
    if metadata.get("source") != "brainstorm_bridge":
        return {
            "success": False,
            "error": (
                "Whiteboard rooms are created via brainstorm sessions. "
                "Use brainstorm.openWhiteboard to start a session."
            ),
        }

    title = arguments.get("title", "Untitled Whiteboard")
    session_id = arguments.get("session_id") or _get_session_field(arguments, "session_id")
    created_by = _get_user_id(arguments)

    request = RoomCreateRequest(
        session_id=session_id,
        title=title,
        created_by=created_by,
        metadata=metadata,
    )

    try:
        response = service.create_room(request)
        return {
            "success": True,
            "room": _room_to_dict(response.room),
            "message": f"Room '{title}' created",
        }
    except Exception as e:
        logger.error("whiteboard.createRoom failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


def handle_list_rooms(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List whiteboard rooms with optional filters.

    MCP Tool: whiteboard.listRooms
    """
    session_id = arguments.get("session_id")
    status = arguments.get("status")
    limit = arguments.get("limit", 50)
    offset = arguments.get("offset", 0)

    # Convert string status to enum if provided
    status_enum = None
    if status:
        from whiteboard.models import RoomStatus
        try:
            status_enum = RoomStatus(status)
        except ValueError:
            return {"success": False, "error": f"Invalid status: {status}"}

    user_id = _get_user_id(arguments)

    try:
        rooms = service.list_rooms(
            session_id=session_id,
            status=status_enum,
            visible_to_user_id=user_id,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "rooms": [_room_to_dict(r) for r in rooms],
            "total": len(rooms),
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error("whiteboard.listRooms failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


def handle_join_room(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Join a whiteboard room as a participant.

    MCP Tool: whiteboard.joinRoom
    """
    room_id = arguments.get("room_id")
    if not room_id:
        return {"success": False, "error": "room_id is required"}

    user_id = _get_user_id(arguments)

    try:
        room = service.join_room(room_id, user_id)
        if room is None:
            return {"success": False, "error": f"Room not found or not active: {room_id}"}
        return {
            "success": True,
            "room": _room_to_dict(room),
            "message": f"Joined room {room_id}",
        }
    except Exception as e:
        logger.error("whiteboard.joinRoom failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


def handle_save_canvas(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Save canvas state for a room.

    MCP Tool: whiteboard.saveCanvas
    """
    room_id = arguments.get("room_id")
    if not room_id:
        return {"success": False, "error": "room_id is required"}

    canvas_state = arguments.get("canvas_state")
    if canvas_state is None:
        return {"success": False, "error": "canvas_state is required"}

    try:
        room = service.save_canvas_state(room_id, canvas_state)
        if room is None:
            return {"success": False, "error": f"Room not found: {room_id}"}
        return {
            "success": True,
            "room_id": room_id,
            "updated_at": room.updated_at.isoformat() if getattr(room, "updated_at", None) else None,
            "message": "Canvas state saved",
        }
    except Exception as e:
        logger.error("whiteboard.saveCanvas failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


def handle_export_snapshot(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Export a canvas snapshot in the requested format.

    MCP Tool: whiteboard.exportSnapshot
    """
    from whiteboard.models import SnapshotExportRequest, SnapshotFormat

    room_id = arguments.get("room_id")
    if not room_id:
        return {"success": False, "error": "room_id is required"}

    fmt_str = arguments.get("format", "json")
    try:
        fmt = SnapshotFormat(fmt_str)
    except ValueError:
        return {"success": False, "error": f"Invalid format: {fmt_str}. Use json, png, or svg."}

    try:
        request = SnapshotExportRequest(room_id=room_id, format=fmt)
        response = service.export_snapshot(request)
        if response is None:
            return {"success": False, "error": f"Room not found: {room_id}"}
        snapshot = {
            "room_id": room_id,
            "format": fmt.value,
            "data": _serialize_value(response.data),
            "exported_at": response.exported_at.isoformat(),
        }
        return {
            "success": True,
            "room_id": room_id,
            "format": fmt.value,
            "data": _serialize_value(response.data),
            "exported_at": response.exported_at.isoformat(),
            "snapshot": snapshot,
        }
    except Exception as e:
        logger.error("whiteboard.exportSnapshot failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


# ==============================================================================
# Agent Canvas Manipulation Handlers
# ==============================================================================


def handle_add_shape(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Add a shape to a whiteboard canvas.

    Reads current canvas_state, merges the new shape via canvas_ops,
    and persists back.

    MCP Tool: whiteboard.addShape
    """
    room_id = arguments.get("room_id")
    if not room_id:
        return {"success": False, "error": "room_id is required"}

    shape = arguments.get("shape")
    if shape is not None and not isinstance(shape, dict):
        return {"success": False, "error": "shape must be an object when provided"}

    shape_type = arguments.get("shape_type", "note")
    text = arguments.get("text", "")
    color = arguments.get("color", "yellow")
    x = arguments.get("x")
    y = arguments.get("y")
    width = arguments.get("width")
    height = arguments.get("height")
    metadata = arguments.get("metadata") or {}

    if shape is None:
        if shape_type == "note":
            shape = {
                "type": "note",
                "props": {
                    "text": text,
                    "color": color,
                    "size": "m",
                    "font": "draw",
                    "align": "middle",
                    "verticalAlign": "middle",
                    "url": "",
                },
            }
        elif shape_type == "text":
            shape = {
                "type": "text",
                "props": {
                    "text": text,
                    "color": color,
                    "size": "m",
                    "font": "draw",
                    "align": "start",
                    "autoSize": True,
                    "w": width or 300,
                },
            }
        else:
            shape = {
                "type": shape_type,
                "props": {
                    "geo": "rectangle",
                    "text": text,
                    "color": color,
                    "w": width or 240,
                    "h": height or 140,
                    "fill": "none",
                    "dash": "draw",
                    "size": "m",
                    "font": "draw",
                    "align": "middle",
                    "verticalAlign": "middle",
                },
            }

    shape = dict(shape)

    # Optional explicit position overrides shape-level x/y
    position = arguments.get("position")
    if isinstance(position, dict):
        x = position.get("x", x)
        y = position.get("y", y)
    if x is not None:
        shape["x"] = x
    if y is not None:
        shape["y"] = y
    if metadata:
        merged_meta = dict(shape.get("meta") or {})
        merged_meta.update(metadata)
        shape["meta"] = merged_meta

    user_id = _get_user_id(arguments)

    try:
        result = service.add_shape(
            room_id,
            shape,
            created_by=user_id,
            meta=metadata,
        )
        if result is None:
            return {"success": False, "error": f"Room not found: {room_id}"}

        _, shape_id = result

        return {
            "success": True,
            "room_id": room_id,
            "shape_id": shape_id,
            "message": f"Shape added to room {room_id}",
        }
    except Exception as e:
        logger.error("whiteboard.addShape failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


def handle_read_canvas(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Read canvas content in an LLM-friendly format.

    Returns a structured summary of shapes, text elements, and connections
    suitable for agent consumption.

    MCP Tool: whiteboard.readCanvas
    """
    room_id = arguments.get("room_id")
    if not room_id:
        return {"success": False, "error": "room_id is required"}

    fmt = arguments.get("format", "summary")

    try:
        room = service.get_room(room_id)
        if room is None:
            return {"success": False, "error": f"Room not found: {room_id}"}

        canvas = service.get_canvas_state(room_id) or {}

        if fmt == "raw":
            return {
                "success": True,
                "room_id": room_id,
                "format": "raw",
                "canvas": _serialize_value(canvas),
                "canvas_state": _serialize_value(canvas),
            }

        summary = service.read_canvas_summary(room_id) or {
            "shape_count": 0,
            "shapes": [],
            "text_elements": [],
            "connections": [],
        }
        return {
            "success": True,
            "room_id": room_id,
            "format": "summary",
            "canvas": summary,
            **summary,
        }
    except Exception as e:
        logger.error("whiteboard.readCanvas failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


def handle_annotate(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Add a text annotation to a whiteboard canvas.

    Convenience wrapper — creates a text shape at the specified position.

    MCP Tool: whiteboard.annotate
    """
    room_id = arguments.get("room_id")
    if not room_id:
        return {"success": False, "error": "room_id is required"}

    text = arguments.get("text")
    if not text:
        return {"success": False, "error": "text is required"}

    position = arguments.get("position", {})
    x = arguments.get("x")
    y = arguments.get("y")
    if isinstance(position, dict):
        x = position.get("x", x)
        y = position.get("y", y)
    color = arguments.get("color", "violet")
    user_id = _get_user_id(arguments)
    metadata = arguments.get("metadata") or {}

    try:
        result = service.add_text_annotation(
            room_id,
            text,
            x=x,
            y=y,
            color=color,
            created_by=user_id,
            meta=metadata,
        )
        if result is None:
            return {"success": False, "error": f"Room not found: {room_id}"}

        _, shape_id = result

        return {
            "success": True,
            "room_id": room_id,
            "shape_id": shape_id,
            "message": f"Annotation added to room {room_id}",
        }
    except Exception as e:
        logger.error("whiteboard.annotate failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


def handle_list_snapshots(service: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """List persisted whiteboard snapshots for the current user."""
    room_id: Optional[str] = arguments.get("room_id")
    session_id: Optional[str] = arguments.get("session_id")
    limit: int = int(arguments.get("limit", 50))
    offset: int = int(arguments.get("offset", 0))

    # Extract caller identity from session context
    session_ctx = arguments.get("_session", {})
    user_id: Optional[str] = session_ctx.get("user_id")

    try:
        storage = getattr(service, "_storage", None)
        if storage is None:
            return {"success": False, "error": "Snapshot storage not available."}

        list_fn = getattr(storage, "list_snapshots", None)
        if list_fn is None:
            return {"success": False, "error": "list_snapshots not supported by storage backend."}

        snapshots: List[Any] = list_fn(
            room_id=room_id,
            session_id=session_id,
            created_by=user_id,
            limit=limit,
            offset=offset,
        )

        serialized = []
        for snap in snapshots:
            d: Dict[str, Any] = _serialize_value(snap)
            # Trim heavy payload fields from list response
            d.pop("data", None)
            d.pop("canvas_elements", None)
            serialized.append(d)

        return {
            "success": True,
            "snapshots": serialized,
            "total": len(serialized),
        }
    except Exception as e:
        logger.error("whiteboard.listSnapshots failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


# ==============================================================================
# Handler Registry
# ==============================================================================


WHITEBOARD_HANDLERS: Dict[str, Any] = {
    "whiteboard.createRoom": handle_create_room,
    "whiteboard.listRooms": handle_list_rooms,
    "whiteboard.joinRoom": handle_join_room,
    "whiteboard.saveCanvas": handle_save_canvas,
    "whiteboard.exportSnapshot": handle_export_snapshot,
    "whiteboard.addShape": handle_add_shape,
    "whiteboard.readCanvas": handle_read_canvas,
    "whiteboard.annotate": handle_annotate,
    "whiteboard.listSnapshots": handle_list_snapshots,
}
