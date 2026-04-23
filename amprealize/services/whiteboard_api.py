"""REST API routes for whiteboard rooms (CRUD + snapshots).

Provides endpoints for creating, listing, joining, and closing whiteboard rooms,
saving canvas state, and exporting snapshots. All operations are scoped to the
authenticated user's org/project context.

Part of GUIDEAI-950 — Add REST API endpoints for whiteboard CRUD and snapshots.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from whiteboard.models import (
    RoomCreateRequest as ServiceCreateRequest,
    RoomStatus as ServiceRoomStatus,
    SnapshotExportRequest as ServiceSnapshotRequest,
    SnapshotFormat,
    WhiteboardSnapshot,
)

logger = logging.getLogger(__name__)


def _is_ephemeral_brainstorm_room(room: Any) -> bool:
    metadata = getattr(room, "metadata", {}) or {}
    return metadata.get("source") == "brainstorm_bridge" or metadata.get("room_kind") == "brainstorm"


def _raise_if_room_url_expired(room: Any, room_id: str) -> None:
    status_value = room.status.value if hasattr(room.status, "value") else str(room.status)
    if _is_ephemeral_brainstorm_room(room) and status_value in {"closed", "archived"}:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "This brainstorm whiteboard session has ended. "
                "Its live room URL is ephemeral and is no longer available."
            ),
        )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateRoomRequest(BaseModel):
    title: str = Field(default="Untitled", min_length=1, max_length=255)
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class RoomResponse(BaseModel):
    id: str
    title: str
    status: str
    session_id: Optional[str] = None
    created_by: Optional[str] = None
    participant_ids: List[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    closed_at: Optional[str] = None


class RoomListResponse(BaseModel):
    rooms: List[RoomResponse]
    total: int


class CanvasSaveRequest(BaseModel):
    canvas_state: Dict[str, Any]


class SnapshotExportRequest(BaseModel):
    format: str = Field(default="json", pattern="^(png|svg|json)$")


class SnapshotResponse(BaseModel):
    room_id: str
    format: str
    data: str
    exported_at: Optional[str] = None


class PersistedSnapshotResponse(BaseModel):
    id: str
    room_id: str
    session_id: Optional[str] = None
    title: str
    format: str
    data: Optional[Any] = None
    canvas_elements: Optional[Dict[str, Any]] = None
    thumbnail_url: Optional[str] = None
    created_by: Optional[str] = None
    exported_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    shared_with: List[str] = Field(default_factory=list)


class SnapshotListResponse(BaseModel):
    snapshots: List[PersistedSnapshotResponse]
    total: int


class MessageResponse(BaseModel):
    success: bool
    message: str


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_whiteboard_routes(
    service: Any,
    tags: Optional[List[str]] = None,
) -> APIRouter:
    """Create FastAPI router for whiteboard room CRUD.

    Args:
        service: WhiteboardService instance.
        tags: Optional OpenAPI tags.

    Returns:
        APIRouter with whiteboard endpoints at /v1/whiteboard/*.
    """
    resolved_tags: List[Union[str, Enum]] = list(tags) if tags else ["whiteboard"]
    router = APIRouter(tags=resolved_tags)

    def _get_user_id(request: Request) -> str:
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        return str(user_id)

    def _get_org_id(request: Request) -> Optional[str]:
        return getattr(request.state, "org_id", None)

    # ----- Rooms -----------------------------------------------------------

    @router.post(
        "/v1/whiteboard/rooms",
        response_model=RoomResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create whiteboard room",
        description=(
            "Create a new whiteboard room. Rooms should be created via the "
            "brainstorm MCP flow; direct creation requires a brainstorm "
            "source marker in metadata."
        ),
    )
    async def create_room(
        request: Request,
        body: CreateRoomRequest,
    ) -> RoomResponse:
        user_id = _get_user_id(request)
        metadata = body.metadata or {}
        # Rooms must originate from a brainstorm session (MCP bridge sets
        # source=brainstorm_bridge).  Allow internal callers that set the
        # header, but reject ad-hoc creation from the web console lobby.
        is_internal = request.headers.get("x-amprealize-internal") == "1"
        is_brainstorm = metadata.get("source") == "brainstorm_bridge"
        if not is_internal and not is_brainstorm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Whiteboard rooms are created via brainstorm sessions. "
                    "Use the brainstorm.openWhiteboard MCP tool to start a session."
                ),
            )
        req = ServiceCreateRequest(
            session_id=body.session_id or "",
            title=body.title,
            created_by=user_id,
            metadata=metadata,
        )
        resp = service.create_room(req)
        room = resp.room
        return RoomResponse(
            id=room.id,
            title=room.title,
            status=room.status.value if hasattr(room.status, "value") else str(room.status),
            session_id=room.session_id,
            created_by=room.created_by,
            participant_ids=room.participant_ids,
            created_at=room.created_at.isoformat() if room.created_at else None,
            updated_at=room.updated_at.isoformat() if room.updated_at else None,
        )

    @router.get(
        "/v1/whiteboard/rooms",
        response_model=RoomListResponse,
        summary="List whiteboard rooms",
        description="List whiteboard rooms with optional status or session filter.",
    )
    async def list_rooms(
        request: Request,
        session_id: Optional[str] = Query(None, description="Filter by brainstorm session"),
        room_status: Optional[str] = Query(None, alias="status", description="Filter by status (active, closed, archived)"),
        limit: int = Query(20, ge=1, le=100, description="Max rooms to return"),
        offset: int = Query(0, ge=0, description="Pagination offset"),
    ) -> RoomListResponse:
        user_id = _get_user_id(request)
        status_enum: Optional[ServiceRoomStatus] = None
        if room_status:
            try:
                status_enum = ServiceRoomStatus(room_status)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status: {room_status}",
                )
        rooms = service.list_rooms(
            status=status_enum,
            session_id=session_id,
            visible_to_user_id=user_id,
        )
        total = len(rooms)
        page = rooms[offset : offset + limit]
        return RoomListResponse(
            rooms=[
                RoomResponse(
                    id=r.id,
                    title=r.title,
                    status=r.status.value if hasattr(r.status, "value") else str(r.status),
                    session_id=r.session_id,
                    created_by=r.created_by,
                    participant_ids=r.participant_ids,
                    created_at=r.created_at.isoformat() if r.created_at else None,
                    updated_at=r.updated_at.isoformat() if r.updated_at else None,
                    closed_at=r.closed_at.isoformat() if r.closed_at else None,
                )
                for r in page
            ],
            total=total,
        )

    @router.get(
        "/v1/whiteboard/rooms/{room_id}",
        response_model=RoomResponse,
        summary="Get whiteboard room",
        description="Get details of a specific whiteboard room.",
    )
    async def get_room(
        request: Request,
        room_id: str,
    ) -> RoomResponse:
        _get_user_id(request)  # auth check
        room = service.get_room(room_id)
        if room is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Whiteboard room {room_id} not found",
            )
        _raise_if_room_url_expired(room, room_id)
        return RoomResponse(
            id=room.id,
            title=room.title,
            status=room.status.value if hasattr(room.status, "value") else str(room.status),
            session_id=room.session_id,
            created_by=room.created_by,
            participant_ids=room.participant_ids,
            created_at=room.created_at.isoformat() if room.created_at else None,
            updated_at=room.updated_at.isoformat() if room.updated_at else None,
            closed_at=room.closed_at.isoformat() if room.closed_at else None,
        )

    @router.post(
        "/v1/whiteboard/rooms/{room_id}/join",
        response_model=RoomResponse,
        summary="Join whiteboard room",
        description="Join an existing whiteboard room as a participant.",
    )
    async def join_room(
        request: Request,
        room_id: str,
    ) -> RoomResponse:
        user_id = _get_user_id(request)
        existing_room = service.get_room(room_id)
        if existing_room is not None:
            _raise_if_room_url_expired(existing_room, room_id)
        room = service.join_room(room_id, user_id)
        if room is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Whiteboard room {room_id} not found",
            )
        return RoomResponse(
            id=room.id,
            title=room.title,
            status=room.status.value if hasattr(room.status, "value") else str(room.status),
            session_id=room.session_id,
            created_by=room.created_by,
            participant_ids=room.participant_ids,
            created_at=room.created_at.isoformat() if room.created_at else None,
            updated_at=room.updated_at.isoformat() if room.updated_at else None,
        )

    @router.post(
        "/v1/whiteboard/rooms/{room_id}/close",
        response_model=MessageResponse,
        summary="Close whiteboard room",
        description="Close a whiteboard room. Prevents further edits.",
    )
    async def close_room(
        request: Request,
        room_id: str,
    ) -> MessageResponse:
        user_id = _get_user_id(request)
        room = service.close_room(room_id)
        if room is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Whiteboard room {room_id} not found",
            )
        return MessageResponse(success=True, message=f"Room {room_id} closed")

    # ----- Canvas ----------------------------------------------------------

    MAX_CANVAS_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

    @router.put(
        "/v1/whiteboard/rooms/{room_id}/canvas",
        response_model=MessageResponse,
        summary="Save canvas state",
        description="Persist the current tldraw canvas state for a room.",
    )
    async def save_canvas(
        request: Request,
        room_id: str,
        body: CanvasSaveRequest,
    ) -> MessageResponse:
        user_id = _get_user_id(request)
        room = service.get_room(room_id)
        if room is not None:
            _raise_if_room_url_expired(room, room_id)
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_CANVAS_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Canvas state exceeds {MAX_CANVAS_SIZE_BYTES} byte limit",
            )
        updated_room = service.save_canvas_state(room_id, body.canvas_state)
        if updated_room is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Whiteboard room {room_id} not found",
            )
        return MessageResponse(success=True, message="Canvas state saved")

    @router.get(
        "/v1/whiteboard/rooms/{room_id}/canvas",
        summary="Get canvas state",
        description="Retrieve the current canvas state for a room.",
    )
    async def get_canvas(
        request: Request,
        room_id: str,
    ) -> Dict[str, Any]:
        _get_user_id(request)  # auth check
        room = service.get_room(room_id)
        if room is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Whiteboard room {room_id} not found",
            )
        _raise_if_room_url_expired(room, room_id)
        return {
            "room_id": room.id,
            "canvas_state": room.canvas_state,
            "participant_ids": room.participant_ids,
        }

    # ----- Snapshots -------------------------------------------------------

    @router.post(
        "/v1/whiteboard/rooms/{room_id}/export",
        response_model=SnapshotResponse,
        summary="Export whiteboard snapshot",
        description="Export a snapshot of the whiteboard in the specified format.",
    )
    async def export_snapshot(
        request: Request,
        room_id: str,
        body: SnapshotExportRequest,
    ) -> SnapshotResponse:
        _get_user_id(request)  # auth check
        room = service.get_room(room_id)
        if room is not None:
            _raise_if_room_url_expired(room, room_id)
        snap_req = ServiceSnapshotRequest(
            room_id=room_id,
            format=SnapshotFormat(body.format),
        )
        result = service.export_snapshot(snap_req)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Whiteboard room {room_id} not found",
            )
        return SnapshotResponse(
            room_id=result.room_id,
            format=result.format.value if hasattr(result.format, "value") else str(result.format),
            data=result.data if isinstance(result.data, str) else str(result.data) if result.data else "",
            exported_at=result.exported_at.isoformat() if result.exported_at else None,
        )

    # ----- Persisted snapshot history -------------------------------------

    def _snapshot_to_response(snap: WhiteboardSnapshot) -> PersistedSnapshotResponse:
        return PersistedSnapshotResponse(
            id=snap.id,
            room_id=snap.room_id,
            session_id=snap.session_id or None,
            title=snap.title,
            format=snap.format.value if hasattr(snap.format, "value") else str(snap.format),
            data=snap.data,
            canvas_elements=snap.canvas_elements,
            thumbnail_url=snap.thumbnail_url,
            created_by=snap.created_by or None,
            exported_at=snap.exported_at.isoformat() if snap.exported_at else None,
            metadata=snap.metadata or {},
            shared_with=snap.shared_with or [],
        )

    @router.get(
        "/v1/whiteboard/snapshots",
        response_model=SnapshotListResponse,
        summary="List persisted whiteboard snapshots",
        description=(
            "List snapshots saved when brainstorm sessions were closed. "
            "Optionally filter by room_id or session_id."
        ),
    )
    async def list_snapshots(
        request: Request,
        room_id: Optional[str] = Query(default=None),
        session_id: Optional[str] = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> SnapshotListResponse:
        user_id = _get_user_id(request)
        storage = getattr(service, "_storage", None)
        if storage is None or not hasattr(storage, "list_snapshots"):
            return SnapshotListResponse(snapshots=[], total=0)
        snaps: List[WhiteboardSnapshot] = storage.list_snapshots(
            room_id=room_id,
            session_id=session_id,
            created_by=user_id,
            limit=limit,
            offset=offset,
        )
        return SnapshotListResponse(
            snapshots=[_snapshot_to_response(s) for s in snaps],
            total=len(snaps),
        )

    @router.get(
        "/v1/whiteboard/snapshots/{snapshot_id}",
        response_model=PersistedSnapshotResponse,
        summary="Get a persisted whiteboard snapshot",
    )
    async def get_snapshot(
        request: Request,
        snapshot_id: str,
    ) -> PersistedSnapshotResponse:
        _get_user_id(request)  # auth check
        storage = getattr(service, "_storage", None)
        if storage is None or not hasattr(storage, "get_snapshot"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Snapshot not found",
            )
        snap: Optional[WhiteboardSnapshot] = storage.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Snapshot {snapshot_id} not found",
            )
        return _snapshot_to_response(snap)

    return router
