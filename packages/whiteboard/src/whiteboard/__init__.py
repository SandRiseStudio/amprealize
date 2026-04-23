"""Whiteboard — real-time collaborative canvas service.

Provides room lifecycle management, canvas persistence, and snapshot export
for tldraw-based brainstorm whiteboards.
"""

from whiteboard.models import (
    RoomCreateRequest,
    RoomCreateResponse,
    RoomState,
    RoomStatus,
    SnapshotExportRequest,
    SnapshotExportResponse,
    SnapshotFormat,
    WhiteboardRoom,
)
from whiteboard.canvas_ops import (
    add_shape,
    add_sticky_note,
    add_text_annotation,
    read_canvas_summary,
)
from whiteboard.hooks import WhiteboardHooks
from whiteboard.service import WhiteboardService
from whiteboard.storage import StorageBackend, InMemoryStorage, SqliteStorageBackend, PostgresStorageBackend, create_storage_from_env

__version__ = "0.1.0"
__all__ = [
    "WhiteboardService",
    "WhiteboardHooks",
    "WhiteboardRoom",
    "RoomStatus",
    "RoomState",
    "RoomCreateRequest",
    "RoomCreateResponse",
    "SnapshotExportRequest",
    "SnapshotExportResponse",
    "SnapshotFormat",
    "StorageBackend",
    "InMemoryStorage",
    "SqliteStorageBackend",
    "PostgresStorageBackend",
    "create_storage_from_env",
    "add_shape",
    "add_sticky_note",
    "add_text_annotation",
    "read_canvas_summary",
]
