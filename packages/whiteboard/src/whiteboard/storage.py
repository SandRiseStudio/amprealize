"""Storage backends for whiteboard room persistence."""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from typing import Dict, List, Optional

from whiteboard.models import RoomStatus, WhiteboardRoom, WhiteboardSnapshot


class StorageBackend(abc.ABC):
    """Abstract storage interface for whiteboard rooms and snapshots."""

    @abc.abstractmethod
    def save_room(self, room: WhiteboardRoom) -> None:
        """Persist a room record."""

    @abc.abstractmethod
    def get_room(self, room_id: str) -> Optional[WhiteboardRoom]:
        """Retrieve a room by ID."""

    @abc.abstractmethod
    def list_rooms(
        self,
        session_id: Optional[str] = None,
        status: Optional[RoomStatus] = None,
        created_by: Optional[str] = None,
        visible_to_user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardRoom]:
        """List rooms, optionally filtered by session, status, or user visibility."""

    @abc.abstractmethod
    def update_room(self, room: WhiteboardRoom) -> None:
        """Update an existing room record."""

    @abc.abstractmethod
    def delete_room(self, room_id: str) -> bool:
        """Delete a room. Returns True if found and deleted."""

    # -- Snapshot persistence (optional for lightweight backends) ---------------

    def save_snapshot(self, snapshot: WhiteboardSnapshot) -> None:
        """Persist a snapshot record. Override in backends with snapshot support."""

    def get_snapshot(self, snapshot_id: str) -> Optional[WhiteboardSnapshot]:
        """Retrieve a snapshot by ID."""
        return None

    def list_snapshots(
        self,
        room_id: Optional[str] = None,
        session_id: Optional[str] = None,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardSnapshot]:
        """List snapshots with optional filters."""
        return []


class InMemoryStorage(StorageBackend):
    """In-memory storage for tests and local development."""

    def __init__(self) -> None:
        self._rooms: Dict[str, WhiteboardRoom] = {}
        self._snapshots: Dict[str, WhiteboardSnapshot] = {}

    def save_room(self, room: WhiteboardRoom) -> None:
        self._rooms[room.id] = room

    def get_room(self, room_id: str) -> Optional[WhiteboardRoom]:
        return self._rooms.get(room_id)

    def list_rooms(
        self,
        session_id: Optional[str] = None,
        status: Optional[RoomStatus] = None,
        created_by: Optional[str] = None,
        visible_to_user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardRoom]:
        results = list(self._rooms.values())
        if session_id:
            results = [r for r in results if r.session_id == session_id]
        if status:
            results = [r for r in results if r.status == status]
        if created_by:
            results = [r for r in results if r.created_by == created_by]
        if visible_to_user_id:
            results = [
                r for r in results
                if r.created_by == visible_to_user_id
                or visible_to_user_id in r.participant_ids
            ]
        return results[offset : offset + limit]

    def update_room(self, room: WhiteboardRoom) -> None:
        if room.id in self._rooms:
            room.updated_at = datetime.now(timezone.utc)
            self._rooms[room.id] = room

    def delete_room(self, room_id: str) -> bool:
        return self._rooms.pop(room_id, None) is not None

    # -- Snapshot persistence --------------------------------------------------

    def save_snapshot(self, snapshot: WhiteboardSnapshot) -> None:
        self._snapshots[snapshot.id] = snapshot

    def get_snapshot(self, snapshot_id: str) -> Optional[WhiteboardSnapshot]:
        return self._snapshots.get(snapshot_id)

    def list_snapshots(
        self,
        room_id: Optional[str] = None,
        session_id: Optional[str] = None,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardSnapshot]:
        results = sorted(
            self._snapshots.values(),
            key=lambda s: s.exported_at,
            reverse=True,
        )
        if room_id:
            results = [s for s in results if s.room_id == room_id]
        if session_id:
            results = [s for s in results if s.session_id == session_id]
        if created_by:
            results = [s for s in results if s.created_by == created_by]
        return results[offset : offset + limit]
