from datetime import datetime, timezone
from typing import Any, Optional, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.multi_tenant.board_contracts import Board, BoardSettings
from amprealize.services.board_api_v2 import create_board_routes
from amprealize.services.board_service import BoardService


pytestmark = pytest.mark.unit


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeBoardService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_boards(
        self,
        *,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Board]:
        self.calls.append(
            (
                "list_boards",
                {
                    "project_id": project_id,
                    "org_id": org_id,
                    "limit": limit,
                    "offset": offset,
                },
            )
        )
        timestamp = _now()
        return [
            Board(
                board_id="brd-0123456789ab",
                project_id=project_id or "proj-unknown",
                name="Main Board",
                description=None,
                settings=BoardSettings(),
                created_at=timestamp,
                updated_at=timestamp,
                created_by="tester",
                is_default=True,
                org_id=org_id,
            ),
            Board(
                board_id="brd-abcdef012345",
                project_id=project_id or "proj-unknown",
                name="Sprint Board",
                description="Sprint-focused view",
                settings=BoardSettings(),
                created_at=timestamp,
                updated_at=timestamp,
                created_by="tester",
                is_default=False,
                org_id=org_id,
            ),
        ]


def _make_rest_client(fake_service: FakeBoardService) -> TestClient:
    app = FastAPI()
    app.include_router(create_board_routes(cast(BoardService, fake_service)))
    return TestClient(app)


def test_rest_list_boards_calls_service_and_returns_shape() -> None:
    service = FakeBoardService()
    client = _make_rest_client(service)

    resp = client.get("/v1/boards?project_id=proj-123&limit=50&offset=10")
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["total"] == 2
    assert len(payload["boards"]) == 2
    assert payload["boards"][0]["project_id"] == "proj-123"

    method, call = service.calls[-1]
    assert method == "list_boards"
    assert call["project_id"] == "proj-123"
    assert call["limit"] == 50
    assert call["offset"] == 10
