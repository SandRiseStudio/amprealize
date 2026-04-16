"""REST API parity tests for whiteboard endpoints.

Tests all 8 endpoints in whiteboard_api.py against a real WhiteboardService
backed by InMemoryStorage. Uses starlette TestClient (synchronous).

Part of GUIDEAI-978 — Add parity tests and unit coverage for WhiteboardService.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.testclient import TestClient

from whiteboard.models import RoomStatus
from whiteboard.service import WhiteboardService
from whiteboard.storage import InMemoryStorage

from amprealize.services.whiteboard_api import create_whiteboard_routes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_USER = "user-test-123"


class _FakeAuthMiddleware(BaseHTTPMiddleware):
    """Injects request.state.user_id for test auth."""

    async def dispatch(self, request: Request, call_next):
        request.state.user_id = TEST_USER
        request.state.org_id = "org-test"
        return await call_next(request)


class _NoAuthMiddleware(BaseHTTPMiddleware):
    """Leaves request.state.user_id unset — simulates unauthenticated."""

    async def dispatch(self, request: Request, call_next):
        return await call_next(request)


def _make_client(
    service: WhiteboardService | None = None,
    authenticated: bool = True,
) -> tuple[TestClient, WhiteboardService]:
    """Build a TestClient wired to a real WhiteboardService."""
    storage = InMemoryStorage()
    svc = service or WhiteboardService(storage=storage)
    app = FastAPI()
    if authenticated:
        app.add_middleware(_FakeAuthMiddleware)
    else:
        app.add_middleware(_NoAuthMiddleware)
    app.include_router(create_whiteboard_routes(svc))
    return TestClient(app, raise_server_exceptions=False), svc


# ---------------------------------------------------------------------------
# POST /v1/whiteboard/rooms — Create room
# ---------------------------------------------------------------------------


class TestCreateRoom:
    def test_create_room_defaults(self):
        client, _ = _make_client()
        resp = client.post("/v1/whiteboard/rooms", json={})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Untitled"
        assert data["status"] == "active"
        assert data["created_by"] == TEST_USER
        assert TEST_USER in data["participant_ids"]
        assert data["id"]

    def test_create_room_with_title(self):
        client, _ = _make_client()
        resp = client.post(
            "/v1/whiteboard/rooms",
            json={"title": "Sprint Retro Board", "session_id": "sess-42"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Sprint Retro Board"
        assert data["session_id"] == "sess-42"

    def test_create_room_unauthenticated(self):
        client, _ = _make_client(authenticated=False)
        resp = client.post("/v1/whiteboard/rooms", json={})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/whiteboard/rooms — List rooms
# ---------------------------------------------------------------------------


class TestListRooms:
    def test_list_rooms_empty(self):
        client, _ = _make_client()
        resp = client.get("/v1/whiteboard/rooms")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rooms"] == []
        assert data["total"] == 0

    def test_list_rooms_returns_created(self):
        client, _ = _make_client()
        client.post("/v1/whiteboard/rooms", json={"title": "Room A"})
        client.post("/v1/whiteboard/rooms", json={"title": "Room B"})

        resp = client.get("/v1/whiteboard/rooms")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        titles = {r["title"] for r in data["rooms"]}
        assert titles == {"Room A", "Room B"}

    def test_list_rooms_filter_by_status(self):
        client, svc = _make_client()
        r1 = client.post("/v1/whiteboard/rooms", json={"title": "Active"})
        r2 = client.post("/v1/whiteboard/rooms", json={"title": "ToBeClosed"})
        room_id = r2.json()["id"]
        svc.close_room(room_id)

        resp = client.get("/v1/whiteboard/rooms", params={"status": "active"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["rooms"][0]["title"] == "Active"

    def test_list_rooms_filter_by_session(self):
        client, _ = _make_client()
        client.post("/v1/whiteboard/rooms", json={"title": "A", "session_id": "s1"})
        client.post("/v1/whiteboard/rooms", json={"title": "B", "session_id": "s2"})

        resp = client.get("/v1/whiteboard/rooms", params={"session_id": "s1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["rooms"][0]["session_id"] == "s1"

    def test_list_rooms_invalid_status(self):
        client, _ = _make_client()
        resp = client.get("/v1/whiteboard/rooms", params={"status": "bogus"})
        assert resp.status_code == 400

    def test_list_rooms_pagination(self):
        client, _ = _make_client()
        for i in range(5):
            client.post("/v1/whiteboard/rooms", json={"title": f"Room {i}"})

        resp = client.get("/v1/whiteboard/rooms", params={"limit": 2, "offset": 0})
        data = resp.json()
        assert data["total"] == 5
        assert len(data["rooms"]) == 2

        resp2 = client.get("/v1/whiteboard/rooms", params={"limit": 2, "offset": 2})
        data2 = resp2.json()
        assert len(data2["rooms"]) == 2

    def test_list_rooms_unauthenticated(self):
        client, _ = _make_client(authenticated=False)
        resp = client.get("/v1/whiteboard/rooms")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/whiteboard/rooms/{room_id} — Get room
# ---------------------------------------------------------------------------


class TestGetRoom:
    def test_get_room_exists(self):
        client, _ = _make_client()
        create_resp = client.post(
            "/v1/whiteboard/rooms", json={"title": "My Room"}
        )
        room_id = create_resp.json()["id"]

        resp = client.get(f"/v1/whiteboard/rooms/{room_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == room_id
        assert data["title"] == "My Room"

    def test_get_room_not_found(self):
        client, _ = _make_client()
        resp = client.get("/v1/whiteboard/rooms/nonexistent-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/whiteboard/rooms/{room_id}/join — Join room
# ---------------------------------------------------------------------------


class TestJoinRoom:
    def test_join_room_success(self):
        client, _ = _make_client()
        create_resp = client.post(
            "/v1/whiteboard/rooms", json={"title": "Collab Board"}
        )
        room_id = create_resp.json()["id"]

        resp = client.post(f"/v1/whiteboard/rooms/{room_id}/join")
        assert resp.status_code == 200
        data = resp.json()
        assert TEST_USER in data["participant_ids"]

    def test_join_room_not_found(self):
        client, _ = _make_client()
        resp = client.post("/v1/whiteboard/rooms/bad-id/join")
        assert resp.status_code == 404

    def test_join_room_idempotent(self):
        client, _ = _make_client()
        create_resp = client.post(
            "/v1/whiteboard/rooms", json={"title": "Board"}
        )
        room_id = create_resp.json()["id"]

        client.post(f"/v1/whiteboard/rooms/{room_id}/join")
        resp = client.post(f"/v1/whiteboard/rooms/{room_id}/join")
        assert resp.status_code == 200
        # User should appear only once
        assert resp.json()["participant_ids"].count(TEST_USER) == 1


# ---------------------------------------------------------------------------
# POST /v1/whiteboard/rooms/{room_id}/close — Close room
# ---------------------------------------------------------------------------


class TestCloseRoom:
    def test_close_room_success(self):
        client, _ = _make_client()
        create_resp = client.post(
            "/v1/whiteboard/rooms", json={"title": "Board"}
        )
        room_id = create_resp.json()["id"]

        resp = client.post(f"/v1/whiteboard/rooms/{room_id}/close")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert room_id in data["message"]

        # Verify room is now closed
        get_resp = client.get(f"/v1/whiteboard/rooms/{room_id}")
        assert get_resp.json()["status"] == "closed"

    def test_close_room_not_found(self):
        client, _ = _make_client()
        resp = client.post("/v1/whiteboard/rooms/nonexistent/close")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /v1/whiteboard/rooms/{room_id}/canvas — Save canvas
# ---------------------------------------------------------------------------


class TestSaveCanvas:
    def test_save_canvas_success(self):
        client, _ = _make_client()
        create_resp = client.post(
            "/v1/whiteboard/rooms", json={"title": "Board"}
        )
        room_id = create_resp.json()["id"]

        canvas = {"shapes": [{"type": "rect", "x": 10, "y": 20}]}
        resp = client.put(
            f"/v1/whiteboard/rooms/{room_id}/canvas",
            json={"canvas_state": canvas},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_save_canvas_not_found(self):
        client, _ = _make_client()
        resp = client.put(
            "/v1/whiteboard/rooms/nope/canvas",
            json={"canvas_state": {}},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /v1/whiteboard/rooms/{room_id}/canvas — Get canvas
# ---------------------------------------------------------------------------


class TestGetCanvas:
    def test_get_canvas_empty(self):
        client, _ = _make_client()
        create_resp = client.post(
            "/v1/whiteboard/rooms", json={"title": "Board"}
        )
        room_id = create_resp.json()["id"]

        resp = client.get(f"/v1/whiteboard/rooms/{room_id}/canvas")
        assert resp.status_code == 200
        data = resp.json()
        assert data["room_id"] == room_id
        assert data["canvas_state"] is None  # no canvas saved yet

    def test_get_canvas_after_save(self):
        client, _ = _make_client()
        create_resp = client.post(
            "/v1/whiteboard/rooms", json={"title": "Board"}
        )
        room_id = create_resp.json()["id"]

        canvas = {"shapes": [{"id": "s1"}], "bindings": []}
        client.put(
            f"/v1/whiteboard/rooms/{room_id}/canvas",
            json={"canvas_state": canvas},
        )

        resp = client.get(f"/v1/whiteboard/rooms/{room_id}/canvas")
        assert resp.status_code == 200
        data = resp.json()
        assert data["canvas_state"] == canvas
        assert data["participant_ids"] == [TEST_USER]

    def test_get_canvas_not_found(self):
        client, _ = _make_client()
        resp = client.get("/v1/whiteboard/rooms/bad/canvas")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/whiteboard/rooms/{room_id}/export — Export snapshot
# ---------------------------------------------------------------------------


class TestExportSnapshot:
    def test_export_json_snapshot(self):
        client, _ = _make_client()
        create_resp = client.post(
            "/v1/whiteboard/rooms", json={"title": "Board"}
        )
        room_id = create_resp.json()["id"]

        canvas = {"shapes": [{"id": "rect-1"}]}
        client.put(
            f"/v1/whiteboard/rooms/{room_id}/canvas",
            json={"canvas_state": canvas},
        )

        resp = client.post(
            f"/v1/whiteboard/rooms/{room_id}/export",
            json={"format": "json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["room_id"] == room_id
        assert data["format"] == "json"
        assert data["exported_at"]

    def test_export_not_found(self):
        client, _ = _make_client()
        resp = client.post(
            "/v1/whiteboard/rooms/nope/export",
            json={"format": "json"},
        )
        assert resp.status_code == 404

    def test_export_png_stub(self):
        """PNG export is stubbed — still returns a response."""
        client, _ = _make_client()
        create_resp = client.post(
            "/v1/whiteboard/rooms", json={"title": "Board"}
        )
        room_id = create_resp.json()["id"]

        resp = client.post(
            f"/v1/whiteboard/rooms/{room_id}/export",
            json={"format": "png"},
        )
        assert resp.status_code == 200
        assert resp.json()["format"] == "png"


# ---------------------------------------------------------------------------
# Cross-cutting: auth required on all endpoints
# ---------------------------------------------------------------------------


class TestAuthRequired:
    """Verify every endpoint returns 401 without auth middleware."""

    @pytest.fixture()
    def unauth_client(self):
        client, _ = _make_client(authenticated=False)
        return client

    def test_create_room_401(self, unauth_client):
        assert unauth_client.post("/v1/whiteboard/rooms", json={}).status_code == 401

    def test_list_rooms_401(self, unauth_client):
        assert unauth_client.get("/v1/whiteboard/rooms").status_code == 401

    def test_get_room_401(self, unauth_client):
        assert unauth_client.get("/v1/whiteboard/rooms/x").status_code == 401

    def test_join_room_401(self, unauth_client):
        assert unauth_client.post("/v1/whiteboard/rooms/x/join").status_code == 401

    def test_close_room_401(self, unauth_client):
        assert unauth_client.post("/v1/whiteboard/rooms/x/close").status_code == 401

    def test_save_canvas_401(self, unauth_client):
        assert unauth_client.put(
            "/v1/whiteboard/rooms/x/canvas", json={"canvas_state": {}}
        ).status_code == 401

    def test_get_canvas_401(self, unauth_client):
        assert unauth_client.get("/v1/whiteboard/rooms/x/canvas").status_code == 401

    def test_export_401(self, unauth_client):
        assert unauth_client.post(
            "/v1/whiteboard/rooms/x/export", json={"format": "json"}
        ).status_code == 401
