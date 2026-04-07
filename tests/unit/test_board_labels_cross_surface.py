import json
import logging
from datetime import datetime, timezone
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.multi_tenant.board_contracts import (
    CreateLabelRequest,
    DeleteResult,
    Label,
    LabelColor,
    LabelListResponse,
    UpdateLabelRequest,
)
from amprealize.services.board_api_v2 import create_board_routes
from amprealize.services.board_service import BoardService


pytestmark = pytest.mark.unit


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeBoardService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def create_label(self, project_id: str, request: CreateLabelRequest, actor, *, org_id=None) -> Label:
        self.calls.append(
            (
                "create_label",
                {"project_id": project_id, "request": request, "actor": actor, "org_id": org_id},
            )
        )
        return Label(
            label_id="lbl-0123456789ab",
            project_id=project_id,
            name=request.name,
            color=request.color,
            description=request.description,
            created_at=_now(),
            updated_at=_now(),
            created_by=getattr(actor, "id", None),
        )

    def list_labels(self, project_id: str, *, org_id=None, limit: int = 100, offset: int = 0) -> LabelListResponse:
        self.calls.append(("list_labels", {"project_id": project_id, "org_id": org_id, "limit": limit, "offset": offset}))
        label = Label(
            label_id="lbl-0123456789ab",
            project_id=project_id,
            name="Bug",
            color=LabelColor.RED,
            description=None,
            created_at=_now(),
            updated_at=_now(),
            created_by="tester",
        )
        # total intentionally != len(labels) to catch shape mismatches
        return LabelListResponse(labels=[label], total=99)

    def get_label(self, label_id: str, *, org_id=None) -> Label:
        self.calls.append(("get_label", {"label_id": label_id, "org_id": org_id}))
        return Label(
            label_id=label_id,
            project_id="proj-123",
            name="Bug",
            color=LabelColor.RED,
            description=None,
            created_at=_now(),
            updated_at=_now(),
            created_by="tester",
        )

    def update_label(self, label_id: str, request: UpdateLabelRequest, actor, *, org_id=None) -> Label:
        self.calls.append(
            (
                "update_label",
                {"label_id": label_id, "request": request, "actor": actor, "org_id": org_id},
            )
        )
        return Label(
            label_id=label_id,
            project_id="proj-123",
            name=request.name or "Bug",
            color=request.color or LabelColor.RED,
            description=request.description,
            created_at=_now(),
            updated_at=_now(),
            created_by="tester",
        )

    def delete_label(self, label_id: str, actor, *, org_id=None) -> DeleteResult:
        self.calls.append(("delete_label", {"label_id": label_id, "actor": actor, "org_id": org_id}))
        return DeleteResult(deleted_id=label_id, deleted_type="label")


def _make_rest_client(fake_service: FakeBoardService) -> TestClient:
    app = FastAPI()
    app.include_router(create_board_routes(cast(BoardService, fake_service)))
    return TestClient(app)


def test_rest_create_label_contract() -> None:
    service = FakeBoardService()
    client = _make_rest_client(service)

    resp = client.post("/v1/projects/proj-123/labels", json={"name": "Bug", "color": "red"})
    assert resp.status_code == 201

    payload = resp.json()
    assert payload["label"]["project_id"] == "proj-123"
    assert payload["label"]["name"] == "Bug"
    assert payload["label"]["color"] == "red"

    method, call = service.calls[-1]
    assert method == "create_label"
    assert call["project_id"] == "proj-123"
    assert call["request"].name == "Bug"


def test_rest_list_labels_uses_service_total() -> None:
    service = FakeBoardService()
    client = _make_rest_client(service)

    resp = client.get("/v1/projects/proj-123/labels")
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["total"] == 99
    assert len(payload["labels"]) == 1


@pytest.mark.asyncio
async def test_mcp_list_labels_and_delete_shapes(monkeypatch) -> None:
    import amprealize.mcp_server as mcp_server_mod
    from amprealize.services import board_service as board_service_mod

    class FakeBoardServiceForMCP:
        def __init__(self) -> None:
            pass

        def list_labels(self, project_id: str, *, org_id=None, limit: int = 100, offset: int = 0) -> LabelListResponse:
            label = Label(
                label_id="lbl-0123456789ab",
                project_id=project_id,
                name="Bug",
                color=LabelColor.RED,
                description=None,
                created_at=_now(),
                updated_at=_now(),
                created_by="tester",
            )
            return LabelListResponse(labels=[label], total=1)

        def delete_label(self, label_id: str, actor, *, org_id=None) -> DeleteResult:
            return DeleteResult(deleted_id=label_id, deleted_type="label")

        def create_label(self, project_id: str, request: CreateLabelRequest, actor, *, org_id=None) -> Label:
            return Label(
                label_id="lbl-0123456789ab",
                project_id=project_id,
                name=request.name,
                color=request.color,
                description=request.description,
                created_at=_now(),
                updated_at=_now(),
                created_by=getattr(actor, "id", None),
            )

        def update_label(self, label_id: str, request: UpdateLabelRequest, actor, *, org_id=None) -> Label:
            return Label(
                label_id=label_id,
                project_id="proj-123",
                name=request.name or "Bug",
                color=request.color or LabelColor.RED,
                description=request.description,
                created_at=_now(),
                updated_at=_now(),
                created_by="tester",
            )

        def list_work_items(self, **kwargs):
            return []

    monkeypatch.setattr(board_service_mod, "BoardService", FakeBoardServiceForMCP)

    server = mcp_server_mod.MCPServer.__new__(mcp_server_mod.MCPServer)
    server._logger = logging.getLogger("test.mcp")

    list_resp_raw = await server._dispatch_tool_call(
        request_id="1",
        tool_name="board.listLabels",
        tool_params={"project_id": "proj-123", "actor": {"id": "u1", "type": "user"}},
    )
    list_resp = json.loads(list_resp_raw)
    inner = json.loads(list_resp["result"]["content"][0]["text"])
    assert inner["total"] == 1
    assert inner["labels"][0]["project_id"] == "proj-123"

    del_resp_raw = await server._dispatch_tool_call(
        request_id="2",
        tool_name="board.deleteLabel",
        tool_params={"label_id": "lbl-0123456789ab", "actor": {"id": "u1", "type": "user"}},
    )
    del_resp = json.loads(del_resp_raw)
    inner_del = json.loads(del_resp["result"]["content"][0]["text"])
    assert inner_del == {"success": True, "deleted_id": "lbl-0123456789ab"}
