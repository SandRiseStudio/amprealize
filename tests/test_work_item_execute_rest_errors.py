"""REST :execute maps domain errors to HTTP status codes (not opaque 500)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.boards.contracts import InvalidResearchWorkItemMetadataError
from amprealize.services.board_service import WorkItemNotFoundError
from amprealize.services.work_item_execution_api import create_work_item_execution_routes
from amprealize.work_item_execution_contracts import ExecuteWorkItemRequest

pytestmark = pytest.mark.unit


class _StubExecuteService:
    """Minimal async execute implementation for router error-mapping tests."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def execute(self, request: ExecuteWorkItemRequest):  # noqa: ARG002
        raise self._exc


@pytest.mark.parametrize(
    ("exc", "expected_status", "error_key"),
    [
        (WorkItemNotFoundError("Work item missing"), 404, "work_item_not_found"),
        (
            InvalidResearchWorkItemMetadataError("Research work items require metadata.research_url"),
            400,
            "invalid_research_metadata",
        ),
    ],
)
def test_execute_maps_errors_to_http_status(
    exc: BaseException,
    expected_status: int,
    error_key: str,
) -> None:
    app = FastAPI()
    app.include_router(create_work_item_execution_routes(_StubExecuteService(exc)))
    client = TestClient(app)
    resp = client.post("/v1/work-items/wi-test:execute?project_id=proj-1", json={})
    assert resp.status_code == expected_status
    body = resp.json()
    assert body["detail"]["error"] == error_key
