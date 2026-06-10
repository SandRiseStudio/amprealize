"""Unit tests for GET /v1/console/dashboard-bootstrap."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from amprealize.console_dashboard_api import create_console_dashboard_routes
from amprealize.projects.contracts import Project, ProjectVisibility

pytestmark = pytest.mark.unit


def _make_project(*, id: str = "proj-aaa") -> Project:
    return Project(
        id=id,
        name="My Project",
        slug="my-project",
        description="hello",
        visibility=ProjectVisibility.PRIVATE,
        settings={},
        org_id=None,
        owner_id="user-123",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def test_dashboard_bootstrap_returns_projects_and_boards_map() -> None:
    org_service = MagicMock()
    board_service = MagicMock()
    proj = _make_project()
    org_service.list_projects.return_value = [proj]
    board_service.list_boards_for_projects.return_value = {"proj-aaa": []}

    app = FastAPI()

    def get_user_id(_: Request) -> str:
        return "user-123"

    app.include_router(
        create_console_dashboard_routes(
            org_service=org_service,
            board_service=board_service,
            get_user_id=get_user_id,
        )
    )
    client = TestClient(app)

    resp = client.get("/v1/console/dashboard-bootstrap")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["projects"]) == 1
    assert body["projects"][0]["id"] == "proj-aaa"
    assert body["boards_by_project"]["proj-aaa"] == []

    org_service.list_projects.assert_called_once_with(owner_id="user-123", org_id=None)
    board_service.list_boards_for_projects.assert_called_once_with(["proj-aaa"], org_id=None)


def test_dashboard_bootstrap_passes_org_filter() -> None:
    org_service = MagicMock()
    board_service = MagicMock()
    proj = _make_project()
    org_service.list_projects.return_value = [proj]
    board_service.list_boards_for_projects.return_value = {"proj-aaa": []}

    app = FastAPI()

    def get_user_id(_: Request) -> str:
        return "user-123"

    app.include_router(
        create_console_dashboard_routes(
            org_service=org_service,
            board_service=board_service,
            get_user_id=get_user_id,
        )
    )
    client = TestClient(app)

    resp = client.get("/v1/console/dashboard-bootstrap?org_id=org-xyz")
    assert resp.status_code == 200

    org_service.list_projects.assert_called_once_with(owner_id="user-123", org_id="org-xyz")
    board_service.list_boards_for_projects.assert_called_once_with(["proj-aaa"], org_id="org-xyz")
