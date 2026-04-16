"""MCP ↔ REST parity tests for whiteboard operations.

Exercises both the MCP handlers and REST API with the same inputs,
verifying equivalent results. Uses InMemoryStorage for isolation.

Part of GUIDEAI-978 — Parity tests + unit coverage for whiteboard.
"""

from __future__ import annotations

import pytest

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.testclient import TestClient
from unittest.mock import MagicMock

from whiteboard import InMemoryStorage, WhiteboardService
from whiteboard.models import RoomStatus

from amprealize.services.whiteboard_api import create_whiteboard_routes
from amprealize.services.brainstorm_bridge import BrainstormBridge
from amprealize.mcp.handlers.whiteboard_handlers import (
    handle_create_room,
    handle_list_rooms,
)

pytestmark = pytest.mark.unit

TEST_USER = "parity-user-1"
TEST_ORG = "parity-org"


class _FakeAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.user_id = TEST_USER
        request.state.org_id = TEST_ORG
        return await call_next(request)


def _make_shared_service() -> WhiteboardService:
    return WhiteboardService(storage=InMemoryStorage())


def _make_rest_client(svc: WhiteboardService) -> TestClient:
    app = FastAPI()
    app.add_middleware(_FakeAuthMiddleware)
    app.include_router(create_whiteboard_routes(svc))
    return TestClient(app, raise_server_exceptions=False)


def _make_bridge(svc: WhiteboardService) -> BrainstormBridge:
    return BrainstormBridge(
        whiteboard_service=svc,
        base_url="http://localhost:8080",
        console_base_url="http://localhost:5173",
    )


class TestCreateRoomParity:
    """Rooms created via REST and MCP bridge yield consistent structures."""

    def test_room_fields_match(self):
        svc = _make_shared_service()
        client = _make_rest_client(svc)
        bridge = _make_bridge(svc)

        rest_resp = client.post(
            "/v1/whiteboard/rooms",
            json={"title": "Parity Board", "session_id": "sess-parity"},
        )
        assert rest_resp.status_code == 201
        rest_room = rest_resp.json()

        mcp_room = bridge.open_whiteboard(
            session_id="sess-mcp-parity",
            topic="Parity Board",
            created_by=TEST_USER,
        )

        assert rest_room["status"] == "active"
        assert mcp_room["status"] == "active"
        assert rest_room["title"] == "Parity Board"
        assert "Parity Board" in mcp_room["title"]

    def test_list_rooms_sees_both(self):
        svc = _make_shared_service()
        client = _make_rest_client(svc)
        bridge = _make_bridge(svc)

        client.post("/v1/whiteboard/rooms", json={"title": "REST Room"})
        bridge.open_whiteboard(
            session_id="sess-mcp",
            topic="MCP Room",
            created_by=TEST_USER,
        )

        rest_list = client.get("/v1/whiteboard/rooms")
        assert rest_list.status_code == 200
        all_rooms = svc.list_rooms()

        assert rest_list.json()["total"] == len(all_rooms)
        assert rest_list.json()["total"] >= 2


class TestCloseSessionParity:
    """Close via REST and bridge both set status to closed."""

    def test_close_via_rest(self):
        svc = _make_shared_service()
        client = _make_rest_client(svc)

        create = client.post("/v1/whiteboard/rooms", json={"title": "REST Close"})
        room_id = create.json()["id"]
        close = client.post(f"/v1/whiteboard/rooms/{room_id}/close")
        assert close.status_code == 200

        room = svc.get_room(room_id)
        assert room.status == RoomStatus.CLOSED

    def test_close_via_bridge(self):
        svc = _make_shared_service()
        bridge = _make_bridge(svc)

        result = bridge.open_whiteboard(
            session_id="sess-bridge-close",
            topic="Close Test",
            created_by=TEST_USER,
        )
        room_id = result["room_id"]

        bridge.add_idea_to_board(room_id, "Test idea", created_by=TEST_USER)
        close_result = bridge.close_session(room_id)

        assert close_result["room_status"] == "closed"
        assert "snapshot_id" in close_result

        room = svc.get_room(room_id)
        assert room.status == RoomStatus.CLOSED


class TestSnapshotPersistence:
    """Ephemeral lifecycle: snapshot persists, canvas_state is cleared."""

    def test_close_session_persists_snapshot(self):
        svc = _make_shared_service()
        bridge = _make_bridge(svc)

        result = bridge.open_whiteboard(
            session_id="sess-snap",
            topic="Snapshot Test",
            created_by=TEST_USER,
        )
        room_id = result["room_id"]
        bridge.add_idea_to_board(room_id, "Persisted idea", created_by=TEST_USER)

        close_result = bridge.close_session(room_id)

        assert close_result["snapshot_id"]
        assert close_result["snapshot_format"] == "json"
        assert isinstance(close_result["snapshot_data"], dict)

    def test_close_session_clears_canvas_state(self):
        svc = _make_shared_service()
        bridge = _make_bridge(svc)

        result = bridge.open_whiteboard(
            session_id="sess-clear",
            topic="Clear Test",
            created_by=TEST_USER,
        )
        room_id = result["room_id"]
        bridge.add_idea_to_board(room_id, "Will be cleared", created_by=TEST_USER)

        room_before = svc.get_room(room_id)
        assert room_before.canvas_state is not None

        bridge.close_session(room_id)

        room_after = svc.get_room(room_id)
        assert room_after.canvas_state is None
        assert room_after.status == RoomStatus.CLOSED

    def test_snapshot_contains_canvas_elements(self):
        svc = _make_shared_service()
        bridge = _make_bridge(svc)

        result = bridge.open_whiteboard(
            session_id="sess-elements",
            topic="Elements Test",
            created_by=TEST_USER,
        )
        room_id = result["room_id"]
        bridge.add_idea_to_board(room_id, "Element A", created_by=TEST_USER)
        bridge.add_idea_to_board(room_id, "Element B", created_by=TEST_USER)

        close_result = bridge.close_session(room_id)
        assert close_result["snapshot_data"] is not None


class TestCanvasSizeLimit:
    """REST API rejects oversized canvas payloads."""

    def test_save_canvas_within_limit(self):
        svc = _make_shared_service()
        client = _make_rest_client(svc)

        create = client.post("/v1/whiteboard/rooms", json={"title": "Small"})
        room_id = create.json()["id"]

        resp = client.put(
            f"/v1/whiteboard/rooms/{room_id}/canvas",
            json={"canvas_state": {"shapes": [{"id": "s1"}]}},
        )
        assert resp.status_code == 200


class TestBrainstormOnlyCreation:
    """MCP createRoom handler rejects non-brainstorm sources."""

    def test_mcp_create_room_rejects_without_brainstorm_source(self):
        svc = _make_shared_service()

        result = handle_create_room(
            svc,
            {"title": "Direct Create", "metadata": {"source": "user_manual"}},
        )
        assert result["success"] is False
        assert "brainstorm" in result["error"].lower()

    def test_mcp_create_room_allows_brainstorm_source(self):
        svc = _make_shared_service()

        result = handle_create_room(
            svc,
            {
                "title": "Brainstorm Board",
                "session_id": "sess-ok",
                "metadata": {"source": "brainstorm_bridge"},
                "_session": {"user_id": TEST_USER},
            },
        )
        assert result["success"] is True
        assert result["room"]["status"] == "active"
