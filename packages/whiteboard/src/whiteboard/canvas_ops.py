"""Canvas operations for tldraw JSON manipulation.

Standalone module — zero amprealize deps.  Operates directly on the
tldraw document JSON (``canvas_state``) stored by WhiteboardService.

A tldraw document is a dict keyed by record IDs.  Shape records have
``"typeName": "shape"`` and carry an ``x``/``y`` position plus a
``props`` dict whose contents vary by shape type (``"geo"``, ``"note"``,
``"text"``, ``"arrow"``, ``"draw"``, ``"frame"``, etc.).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_STICKY_WIDTH = 200
DEFAULT_STICKY_HEIGHT = 200
DEFAULT_TEXT_SIZE = "m"
AGENT_BADGE = "\U0001F9E0"  # 🧠

# Auto-layout grid for sequential sticky placement
_GRID_COLS = 4
_GRID_GAP_X = 240
_GRID_GAP_Y = 260
_GRID_ORIGIN_X = 100
_GRID_ORIGIN_Y = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    """Return a tldraw-compatible record id prefixed with ``shape:``."""
    return f"shape:{uuid.uuid4().hex[:16]}"


def _shape_count(canvas: Dict[str, Any]) -> int:
    """Count shapes currently on the canvas."""
    return sum(
        1
        for v in canvas.values()
        if isinstance(v, dict) and v.get("typeName") == "shape"
    )


def _auto_position(canvas: Dict[str, Any]) -> tuple[float, float]:
    """Compute next grid position based on current shape count."""
    idx = _shape_count(canvas)
    col = idx % _GRID_COLS
    row = idx // _GRID_COLS
    x = _GRID_ORIGIN_X + col * _GRID_GAP_X
    y = _GRID_ORIGIN_Y + row * _GRID_GAP_Y
    return float(x), float(y)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_shape(
    canvas: Dict[str, Any],
    shape_data: Dict[str, Any],
    *,
    created_by: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], str]:
    """Merge an arbitrary tldraw shape record into *canvas*.

    Parameters
    ----------
    canvas:
        The current ``canvas_state`` dict (mutated in place **and** returned).
    shape_data:
        A partial or full tldraw shape record.  Must include at least
        ``type`` (e.g. ``"geo"``, ``"note"``).  ``id``, ``x``, ``y`` are
        auto-generated when absent.
    created_by:
        Optional user/agent identifier stamped into ``meta.created_by``.

    Returns
    -------
    (canvas, shape_id):
        The mutated canvas dict and the ID of the inserted shape.
    """
    shape_id = shape_data.get("id") or _new_id()
    x = shape_data.get("x")
    y = shape_data.get("y")
    if x is None or y is None:
        ax, ay = _auto_position(canvas)
        x = x if x is not None else ax
        y = y if y is not None else ay

    merged_meta = dict(shape_data.get("meta") or {})
    if meta:
        merged_meta.update(meta)
    merged_meta.setdefault("created_by", created_by)
    merged_meta.setdefault("created_at", datetime.now(timezone.utc).isoformat())

    record: Dict[str, Any] = {
        "id": shape_id,
        "typeName": "shape",
        "type": shape_data.get("type", "geo"),
        "x": x,
        "y": y,
        "rotation": shape_data.get("rotation", 0),
        "isLocked": shape_data.get("isLocked", False),
        "parentId": shape_data.get("parentId", "page:page"),
        "index": shape_data.get("index", f"a{_shape_count(canvas) + 1}"),
        "props": shape_data.get("props", {}),
        "meta": merged_meta,
    }

    canvas[shape_id] = record
    return canvas, shape_id


def add_sticky_note(
    canvas: Dict[str, Any],
    text: str,
    *,
    x: Optional[float] = None,
    y: Optional[float] = None,
    color: str = "yellow",
    created_by: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], str]:
    """Add a sticky-note shape (tldraw ``note`` type).

    Returns (canvas, shape_id).
    """
    shape_data: Dict[str, Any] = {
        "type": "note",
        "props": {
            "color": color,
            "size": DEFAULT_TEXT_SIZE,
            "text": text,
            "font": "draw",
            "align": "middle",
            "verticalAlign": "middle",
            "url": "",
        },
    }
    if x is not None:
        shape_data["x"] = x
    if y is not None:
        shape_data["y"] = y
    return add_shape(canvas, shape_data, created_by=created_by, meta=meta)


def add_text_annotation(
    canvas: Dict[str, Any],
    text: str,
    *,
    x: Optional[float] = None,
    y: Optional[float] = None,
    color: str = "black",
    created_by: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], str]:
    """Add a text annotation (tldraw ``text`` type).

    Returns (canvas, shape_id).
    """
    shape_data: Dict[str, Any] = {
        "type": "text",
        "props": {
            "color": color,
            "size": DEFAULT_TEXT_SIZE,
            "text": text,
            "font": "draw",
            "align": "start",
            "autoSize": True,
            "w": 300,
        },
    }
    if x is not None:
        shape_data["x"] = x
    if y is not None:
        shape_data["y"] = y
    return add_shape(canvas, shape_data, created_by=created_by, meta=meta)


def _extract_shape_text(props: Dict[str, Any], shape_type: str) -> str:
    """Extract a human-readable label from shape props."""
    if not isinstance(props, dict):
        return ""
    if isinstance(props.get("text"), str) and props.get("text"):
        return props["text"]
    if isinstance(props.get("name"), str) and props.get("name"):
        return props["name"]
    if isinstance(props.get("label"), str) and props.get("label"):
        return props["label"]
    if shape_type == "geo" and isinstance(props.get("geo"), str):
        return props["geo"]
    return ""


def read_canvas_summary(canvas: Dict[str, Any]) -> Dict[str, Any]:
    """Extract an LLM-friendly summary of canvas content.

    Returns a dict with:
    - ``shape_count``: total shapes
    - ``shapes``: list of ``{id, type, text, position, created_by}``
    - ``text_elements``: extracted text from all shapes that contain text
    - ``connections``: list of arrow connections ``{from_id, to_id, label}``
    """
    shapes: List[Dict[str, Any]] = []
    text_elements: List[str] = []
    connections: List[Dict[str, Any]] = []

    for key, record in canvas.items():
        if not isinstance(record, dict):
            continue
        if record.get("typeName") != "shape":
            continue

        props = record.get("props", {})
        shape_type = record.get("type", "unknown")
        text = _extract_shape_text(props, shape_type)
        meta = record.get("meta", {})

        entry: Dict[str, Any] = {
            "id": record.get("id", key),
            "type": shape_type,
            "text": text,
            "position": {"x": record.get("x", 0), "y": record.get("y", 0)},
            "created_by": meta.get("created_by", ""),
            "color": props.get("color", ""),
            "category": meta.get("category", ""),
        }
        shapes.append(entry)

        if text:
            text_elements.append(text)

        # Arrow shapes encode connections
        if shape_type == "arrow":
            start = props.get("start", {})
            end = props.get("end", {})
            conn: Dict[str, Any] = {
                "from_id": start.get("boundShapeId"),
                "to_id": end.get("boundShapeId"),
                "label": props.get("text", ""),
            }
            connections.append(conn)

    return {
        "shape_count": len(shapes),
        "shapes": shapes,
        "text_elements": text_elements,
        "connections": connections,
    }
