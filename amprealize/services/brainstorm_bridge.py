"""Brainstorm bridge service tying brainstorm sessions to whiteboard rooms.

Bridges the Brainstorm playbook to the standalone whiteboard package by:
- opening or reusing brainstorm-scoped whiteboard rooms,
- translating brainstorm ideas into sticky notes / frames,
- summarizing board content for agent consumption, and
- exporting + closing rooms when a session wraps up.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from whiteboard.models import (
	RoomCreateRequest,
	RoomStatus,
	SnapshotExportRequest,
	SnapshotFormat,
	WhiteboardRoom,
	WhiteboardSnapshot,
)

logger = logging.getLogger(__name__)

_CATEGORY_COLORS = ["yellow", "green", "blue", "violet", "orange", "red"]
_CATEGORY_COLUMN_WIDTH = 320
_CATEGORY_ROW_HEIGHT = 240
_CATEGORY_ORIGIN_X = 120
_CATEGORY_ORIGIN_Y = 140
_FRAME_WIDTH = 520
_FRAME_MIN_HEIGHT = 240


class BrainstormBridge:
	"""Translate brainstorm concepts into whiteboard operations."""

	def __init__(
		self,
		*,
		whiteboard_service: Any,
		base_url: str = "http://localhost:8080",
		sync_base_url: Optional[str] = None,
		console_base_url: Optional[str] = None,
	) -> None:
		self._whiteboard = whiteboard_service
		self._base_url = base_url.rstrip("/")
		self._sync_base_url = sync_base_url.rstrip("/") if sync_base_url else None
		# URL for the web console whiteboard lobby (env-aware).
		# Defaults to the console dev server when not set.
		self._console_base_url = (console_base_url or "http://localhost:5173").rstrip("/")

	def open_whiteboard(
		self,
		session_id: str,
		topic: str,
		*,
		created_by: str,
		phase: Optional[str] = None,
		metadata: Optional[Dict[str, Any]] = None,
	) -> Dict[str, Any]:
		"""Create or reuse a brainstorm-scoped whiteboard room."""
		resolved_session_id = session_id or self._default_session_id(created_by, topic)
		existing = self._find_active_room_for_session(resolved_session_id)
		if existing is not None:
			return self._room_payload(existing, reused=True)

		room_metadata = {
			"source": "brainstorm_bridge",
			"room_kind": "brainstorm",
			"brainstorm_session_id": resolved_session_id,
			"topic": topic,
		}
		if phase:
			room_metadata["phase"] = phase
		if metadata:
			room_metadata.update(metadata)

		title = f"Brainstorm: {topic}" if topic else "Brainstorm Whiteboard"
		response = self._whiteboard.create_room(
			RoomCreateRequest(
				session_id=resolved_session_id,
				title=title[:255],
				created_by=created_by,
				metadata=room_metadata,
			)
		)
		return self._room_payload(response.room, reused=False)

	def add_idea_to_board(
		self,
		room_id: str,
		idea: str,
		*,
		category: Optional[str] = None,
		created_by: str,
		x: Optional[float] = None,
		y: Optional[float] = None,
	) -> Dict[str, Any]:
		"""Add a brainstorm idea as a sticky note on the board."""
		room = self._require_room(room_id)

		if x is None or y is None:
			clustered = self._category_position(room, category)
			if x is None:
				x = clustered[0]
			if y is None:
				y = clustered[1]

		color = self._category_color(category)
		meta = {
			"source": "brainstorm_bridge",
			"idea_type": "idea",
		}
		if category:
			meta["category"] = category

		result = self._whiteboard.add_sticky_note(
			room_id,
			idea,
			x=x,
			y=y,
			color=color,
			created_by=created_by,
			meta=meta,
		)
		if result is None:
			raise ValueError(f"Whiteboard room {room_id} not found")

		_, shape_id = result
		return {
			"room_id": room_id,
			"shape_id": shape_id,
			"idea": idea,
			"category": category,
			"color": color,
		}

	def add_theme_to_board(
		self,
		room_id: str,
		theme: str,
		*,
		connected_ideas: Optional[List[str]] = None,
		created_by: str,
		x: Optional[float] = None,
		y: Optional[float] = None,
	) -> Dict[str, Any]:
		"""Add a frame representing a brainstorm theme or cluster."""
		room = self._require_room(room_id)
		if x is None or y is None:
			x, y = self._next_theme_position(room)

		ideas = connected_ideas or []
		shape = {
			"type": "frame",
			"x": x,
			"y": y,
			"props": {
				"name": theme,
				"w": _FRAME_WIDTH,
				"h": max(_FRAME_MIN_HEIGHT, 160 + (len(ideas) * 40)),
			},
		}
		meta = {
			"source": "brainstorm_bridge",
			"idea_type": "theme",
			"connected_ideas": ideas,
		}
		result = self._whiteboard.add_shape(
			room_id,
			shape,
			created_by=created_by,
			meta=meta,
		)
		if result is None:
			raise ValueError(f"Whiteboard room {room_id} not found")

		_, shape_id = result
		return {
			"room_id": room_id,
			"shape_id": shape_id,
			"theme": theme,
			"connected_ideas": ideas,
		}

	def summarize_board(self, room_id: str) -> Dict[str, Any]:
		"""Return a brainstorm-oriented summary of the board contents."""
		self._require_room(room_id)
		canvas = self._whiteboard.get_canvas_state(room_id) or {}
		summary = self._whiteboard.read_canvas_summary(room_id) or {
			"shape_count": 0,
			"shapes": [],
			"text_elements": [],
			"connections": [],
		}

		ideas: List[Dict[str, Any]] = []
		themes: List[Dict[str, Any]] = []

		for record in canvas.values():
			if not isinstance(record, dict) or record.get("typeName") != "shape":
				continue
			meta = record.get("meta", {}) or {}
			props = record.get("props", {}) or {}
			shape_type = record.get("type")

			if shape_type == "note":
				ideas.append(
					{
						"id": record.get("id"),
						"text": props.get("text", ""),
						"category": meta.get("category"),
						"created_by": meta.get("created_by"),
						"color": props.get("color"),
					}
				)
			elif shape_type == "frame":
				themes.append(
					{
						"id": record.get("id"),
						"theme": props.get("name") or props.get("text") or "",
						"connected_ideas": meta.get("connected_ideas", []),
					}
				)

		return {
			"room_id": room_id,
			"shape_count": summary.get("shape_count", 0),
			"ideas": ideas,
			"themes": themes,
			"connections": summary.get("connections", []),
			"text_elements": summary.get("text_elements", []),
			"summary": summary,
		}

	def close_session(
		self,
		room_id: str,
		*,
		export_format: str = "json",
	) -> Dict[str, Any]:
		"""Export the board snapshot, persist it, clear canvas, and close the room."""
		room = self._require_room(room_id)

		fmt = SnapshotFormat(export_format)
		export_resp = self._whiteboard.export_snapshot(
			SnapshotExportRequest(room_id=room_id, format=fmt)
		)
		if export_resp is None:
			raise ValueError(f"Whiteboard room {room_id} not found")

		brainstorm_summary = self.summarize_board(room_id)

		persisted = WhiteboardSnapshot(
			room_id=room_id,
			session_id=room.session_id,
			title=room.title,
			format=fmt,
			data=export_resp.data,
			canvas_elements=room.canvas_state,
			created_by=room.created_by,
			exported_at=export_resp.exported_at,
			metadata={
				**(room.metadata or {}),
				"idea_count": len(brainstorm_summary.get("ideas", [])),
				"theme_count": len(brainstorm_summary.get("themes", [])),
				"shape_count": brainstorm_summary.get("shape_count", 0),
			},
		)
		self._whiteboard.persist_snapshot(persisted)

		self._whiteboard.close_room(room_id)
		self._whiteboard.clear_canvas_state(room_id)

		return {
			"room_id": room_id,
			"snapshot_id": persisted.id,
			"snapshot_format": fmt.value,
			"snapshot_data": export_resp.data,
			"exported_at": export_resp.exported_at.isoformat(),
			"room_status": "closed",
		}

	def _find_active_room_for_session(self, session_id: str) -> Optional[WhiteboardRoom]:
		"""Return the active brainstorm room for a session when one exists."""
		rooms = self._whiteboard.list_rooms(session_id=session_id, limit=100, offset=0)
		for room in rooms:
			if room.status != RoomStatus.ACTIVE:
				continue
			metadata = room.metadata or {}
			if metadata.get("room_kind") == "brainstorm" or metadata.get("source") == "brainstorm_bridge":
				return room
		return None

	def _default_session_id(self, created_by: str, topic: str) -> str:
		slug = "-".join((topic or "brainstorm").lower().split())[:48]
		return f"brainstorm-{created_by or 'agent'}-{slug or 'session'}"

	def _room_payload(self, room: WhiteboardRoom, *, reused: bool) -> Dict[str, Any]:
		payload: Dict[str, Any] = {
			"room_id": room.id,
			"room_url": f"{self._console_base_url}/whiteboard/{quote(room.id)}",
			"title": room.title,
			"session_id": room.session_id,
			"status": room.status.value if hasattr(room.status, "value") else str(room.status),
			"participant_ids": list(room.participant_ids),
			"metadata": dict(room.metadata or {}),
			"reused": reused,
		}
		if self._sync_base_url:
			payload["sync_url"] = f"{self._sync_base_url}/{quote(room.id)}"
		return payload

	def _require_room(self, room_id: str) -> WhiteboardRoom:
		room = self._whiteboard.get_room(room_id)
		if room is None:
			raise ValueError(f"Whiteboard room {room_id} not found")
		return room

	def _category_position(self, room: WhiteboardRoom, category: Optional[str]) -> tuple[float, float]:
		"""Choose a stable clustered position for a category."""
		normalized = (category or "uncategorized").strip().lower()
		bucket = sum(ord(ch) for ch in normalized) % max(1, len(_CATEGORY_COLORS))
		existing = 0

		for record in (room.canvas_state or {}).values():
			if not isinstance(record, dict) or record.get("typeName") != "shape":
				continue
			meta = record.get("meta", {}) or {}
			if meta.get("idea_type") != "idea":
				continue
			if (meta.get("category") or "uncategorized").strip().lower() == normalized:
				existing += 1

		x = _CATEGORY_ORIGIN_X + (bucket * _CATEGORY_COLUMN_WIDTH)
		y = _CATEGORY_ORIGIN_Y + (existing * _CATEGORY_ROW_HEIGHT)
		return float(x), float(y)

	def _next_theme_position(self, room: WhiteboardRoom) -> tuple[float, float]:
		"""Place themes beneath the current brainstorm clusters."""
		theme_count = 0
		for record in (room.canvas_state or {}).values():
			if not isinstance(record, dict) or record.get("typeName") != "shape":
				continue
			if record.get("type") == "frame":
				theme_count += 1
		return float(120 + (theme_count * 80)), float(760 + (theme_count * 40))

	def _category_color(self, category: Optional[str]) -> str:
		normalized = (category or "uncategorized").strip().lower()
		bucket = sum(ord(ch) for ch in normalized) % max(1, len(_CATEGORY_COLORS))
		return _CATEGORY_COLORS[bucket]
