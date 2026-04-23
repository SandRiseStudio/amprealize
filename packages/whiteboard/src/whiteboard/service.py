"""WhiteboardService — room lifecycle and canvas persistence."""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from whiteboard.canvas_ops import (
    add_shape as canvas_add_shape,
    add_sticky_note as canvas_add_sticky_note,
    add_text_annotation as canvas_add_text_annotation,
    read_canvas_summary as canvas_read_summary,
)
from whiteboard.hooks import WhiteboardHooks
from whiteboard.models import (
    RoomCreateRequest,
    RoomCreateResponse,
    RoomState,
    RoomStatus,
    SnapshotExportRequest,
    SnapshotExportResponse,
    SnapshotFormat,
    WhiteboardRoom,
    WhiteboardSnapshot,
)
from whiteboard.storage import InMemoryStorage, StorageBackend, create_storage_from_env

logger = logging.getLogger(__name__)


class WhiteboardService:
    """Core service managing whiteboard room lifecycle.

    Follows the standalone-package pattern: zero amprealize core deps,
    with hook points for external integration.
    """

    def __init__(
        self,
        storage: Optional[StorageBackend] = None,
        hooks: Optional[WhiteboardHooks] = None,
    ) -> None:
        self._storage = storage if storage is not None else create_storage_from_env()
        self._hooks = hooks or WhiteboardHooks()

    # -- Room lifecycle ------------------------------------------------------

    def create_room(self, request: RoomCreateRequest) -> RoomCreateResponse:
        """Create a new whiteboard room."""
        room = WhiteboardRoom(
            session_id=request.session_id,
            title=request.title,
            created_by=request.created_by,
            status=RoomStatus.ACTIVE,
            metadata=request.metadata,
        )
        if request.created_by:
            room.participant_ids.append(request.created_by)

        self._storage.save_room(room)
        self._hooks.on_room_created(room)
        logger.info("Room created: %s (session=%s)", room.id, room.session_id)
        return RoomCreateResponse(room=room)

    def get_room(self, room_id: str) -> Optional[WhiteboardRoom]:
        """Retrieve a room by ID."""
        return self._storage.get_room(room_id)

    def list_rooms(
        self,
        session_id: Optional[str] = None,
        status: Optional[RoomStatus] = None,
        created_by: Optional[str] = None,
        visible_to_user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardRoom]:
        """List rooms with optional filters."""
        return self._storage.list_rooms(
            session_id=session_id,
            status=status,
            created_by=created_by,
            visible_to_user_id=visible_to_user_id,
            limit=limit,
            offset=offset,
        )

    def close_room(self, room_id: str) -> Optional[WhiteboardRoom]:
        """Transition a room to closed status."""
        room = self._storage.get_room(room_id)
        if room is None:
            return None
        if room.status == RoomStatus.CLOSED:
            return room

        room.status = RoomStatus.CLOSED
        room.closed_at = datetime.now(timezone.utc)
        self._storage.update_room(room)
        self._hooks.on_room_closed(room)
        logger.info("Room closed: %s", room_id)
        return room

    def archive_room(self, room_id: str) -> Optional[WhiteboardRoom]:
        """Archive a closed room."""
        room = self._storage.get_room(room_id)
        if room is None:
            return None
        if room.status not in (RoomStatus.CLOSED, RoomStatus.ACTIVE):
            return room

        if room.status == RoomStatus.ACTIVE:
            room.closed_at = datetime.now(timezone.utc)
        room.status = RoomStatus.ARCHIVED
        self._storage.update_room(room)
        self._hooks.on_room_archived(room)
        logger.info("Room archived: %s", room_id)
        return room

    def get_room_state(self, room_id: str) -> Optional[RoomState]:
        """Get lightweight room state."""
        room = self._storage.get_room(room_id)
        if room is None:
            return None
        return RoomState(
            room_id=room.id,
            status=room.status,
            participant_count=len(room.participant_ids),
            last_activity=room.updated_at,
        )

    # -- Participant management ----------------------------------------------

    def join_room(self, room_id: str, user_id: str) -> Optional[WhiteboardRoom]:
        """Add a participant to a room."""
        room = self._storage.get_room(room_id)
        if room is None or room.status != RoomStatus.ACTIVE:
            return None

        if user_id not in room.participant_ids:
            room.participant_ids.append(user_id)
            self._storage.update_room(room)
            self._hooks.on_participant_joined(room_id, user_id)
        return room

    def leave_room(self, room_id: str, user_id: str) -> Optional[WhiteboardRoom]:
        """Remove a participant from a room."""
        room = self._storage.get_room(room_id)
        if room is None:
            return None

        if user_id in room.participant_ids:
            room.participant_ids.remove(user_id)
            self._storage.update_room(room)
            self._hooks.on_participant_left(room_id, user_id)
        return room

    # -- Canvas persistence --------------------------------------------------

    def save_canvas_state(
        self,
        room_id: str,
        state: Dict[str, Any],
    ) -> Optional[WhiteboardRoom]:
        """Persist the current canvas state for a room."""
        room = self._storage.get_room(room_id)
        if room is None:
            return None

        room.canvas_state = state
        self._storage.update_room(room)
        self._hooks.on_canvas_updated(room_id, state)
        return room

    def get_canvas_state(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Return a defensive copy of the current canvas state for a room."""
        room = self._storage.get_room(room_id)
        if room is None:
            return None
        if room.canvas_state is None:
            return None
        return copy.deepcopy(room.canvas_state)

    def add_shape(
        self,
        room_id: str,
        shape_data: Dict[str, Any],
        *,
        created_by: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[tuple[WhiteboardRoom, str]]:
        """Append an arbitrary tldraw shape record to a room canvas."""
        room = self._storage.get_room(room_id)
        if room is None:
            return None

        canvas = copy.deepcopy(room.canvas_state) if room.canvas_state else {}
        canvas, shape_id = canvas_add_shape(
            canvas,
            shape_data,
            created_by=created_by,
            meta=meta,
        )
        updated_room = self.save_canvas_state(room_id, canvas)
        if updated_room is None:
            return None
        return updated_room, shape_id

    def add_sticky_note(
        self,
        room_id: str,
        text: str,
        *,
        x: Optional[float] = None,
        y: Optional[float] = None,
        color: str = "yellow",
        created_by: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[tuple[WhiteboardRoom, str]]:
        """Add a sticky note to a room canvas."""
        room = self._storage.get_room(room_id)
        if room is None:
            return None

        canvas = copy.deepcopy(room.canvas_state) if room.canvas_state else {}
        canvas, shape_id = canvas_add_sticky_note(
            canvas,
            text,
            x=x,
            y=y,
            color=color,
            created_by=created_by,
            meta=meta,
        )
        updated_room = self.save_canvas_state(room_id, canvas)
        if updated_room is None:
            return None
        return updated_room, shape_id

    def add_text_annotation(
        self,
        room_id: str,
        text: str,
        *,
        x: Optional[float] = None,
        y: Optional[float] = None,
        color: str = "black",
        created_by: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[tuple[WhiteboardRoom, str]]:
        """Add a text annotation to a room canvas."""
        room = self._storage.get_room(room_id)
        if room is None:
            return None

        canvas = copy.deepcopy(room.canvas_state) if room.canvas_state else {}
        canvas, shape_id = canvas_add_text_annotation(
            canvas,
            text,
            x=x,
            y=y,
            color=color,
            created_by=created_by,
            meta=meta,
        )
        updated_room = self.save_canvas_state(room_id, canvas)
        if updated_room is None:
            return None
        return updated_room, shape_id

    def read_canvas_summary(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Read an LLM-friendly summary of the room canvas."""
        room = self._storage.get_room(room_id)
        if room is None:
            return None
        canvas = copy.deepcopy(room.canvas_state) if room.canvas_state else {}
        return canvas_read_summary(canvas)

    # -- Snapshot export -----------------------------------------------------

    def export_snapshot(
        self,
        request: SnapshotExportRequest,
    ) -> Optional[SnapshotExportResponse]:
        """Export a canvas snapshot in the requested format."""
        room = self._storage.get_room(request.room_id)
        if room is None:
            return None

        if request.format == SnapshotFormat.JSON:
            data = room.canvas_state or {}
        else:
            # PNG/SVG export requires tldraw headless renderer — stubbed for now
            data = None

        response = SnapshotExportResponse(
            room_id=request.room_id,
            format=request.format,
            data=data,
        )
        self._hooks.on_snapshot_exported(
            request.room_id,
            request.format.value,
            {"exported_at": response.exported_at.isoformat()},
        )
        return response

    def persist_snapshot(self, snapshot: WhiteboardSnapshot) -> None:
        """Save a snapshot to durable storage for the session archive."""
        self._storage.save_snapshot(snapshot)
        logger.info(
            "Snapshot persisted: %s (room=%s)", snapshot.id, snapshot.room_id
        )

    def clear_canvas_state(self, room_id: str) -> Optional[WhiteboardRoom]:
        """Null out the canvas_state on a room, turning it into a lightweight tombstone."""
        room = self._storage.get_room(room_id)
        if room is None:
            return None
        room.canvas_state = None
        self._storage.update_room(room)
        logger.info("Canvas state cleared: %s", room_id)
        return room
