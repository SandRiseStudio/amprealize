"""Data models for the Whiteboard service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RoomStatus(str, Enum):
    """Lifecycle status of a whiteboard room."""

    CREATING = "creating"
    ACTIVE = "active"
    CLOSED = "closed"
    ARCHIVED = "archived"


class SnapshotFormat(str, Enum):
    """Supported snapshot export formats."""

    PNG = "png"
    JSON = "json"
    SVG = "svg"


class WhiteboardRoom(BaseModel):
    """A whiteboard room record."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    title: str = "Untitled Whiteboard"
    status: RoomStatus = RoomStatus.CREATING
    created_by: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    participant_ids: List[str] = Field(default_factory=list)
    canvas_state: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RoomState(BaseModel):
    """Lightweight view of room state for status queries."""

    room_id: str
    status: RoomStatus
    active_connections: int = 0
    participant_count: int = 0
    last_activity: Optional[datetime] = None


class RoomCreateRequest(BaseModel):
    """Request to create a new whiteboard room."""

    session_id: str
    title: str = "Untitled Whiteboard"
    created_by: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RoomCreateResponse(BaseModel):
    """Response after creating a whiteboard room."""

    room: WhiteboardRoom
    websocket_url: Optional[str] = None


class WhiteboardSnapshot(BaseModel):
    """A persisted snapshot from a closed whiteboard session.

    Stores both the rendered export (``data``) and the raw structured
    canvas elements so individual shapes, notes, and frames can be
    queried or reused as building blocks in future features.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    room_id: str
    session_id: str = ""
    title: str = "Untitled"
    format: SnapshotFormat = SnapshotFormat.JSON
    data: Optional[Any] = None
    canvas_elements: Optional[Dict[str, Any]] = None
    thumbnail_url: Optional[str] = None
    created_by: str = ""
    exported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)
    shared_with: List[str] = Field(default_factory=list)


class SnapshotExportRequest(BaseModel):
    """Request to export a canvas snapshot."""

    room_id: str
    format: SnapshotFormat = SnapshotFormat.JSON


class SnapshotExportResponse(BaseModel):
    """Response containing an exported snapshot."""

    room_id: str
    format: SnapshotFormat
    data: Any = None
    url: Optional[str] = None
    exported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
