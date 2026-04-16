import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from amprealize.projects_api import create_project_routes
from amprealize.projects.contracts import Project, ProjectVisibility


pytestmark = pytest.mark.unit


def _make_client(org_service: MagicMock) -> TestClient:
    app = FastAPI()

    def get_user_id(_: Request) -> str:
        return "user-123"

    app.include_router(create_project_routes(org_service=org_service, get_user_id=get_user_id))
    return TestClient(app)


def _make_project(*, id: str = "proj-aaa", name: str = "My Project", owner_id: str = "user-123", org_id=None, slug="my-project", description="hello") -> Project:
    return Project(
        id=id, name=name, slug=slug, description=description,
        visibility=ProjectVisibility.PRIVATE, settings={},
        org_id=org_id, owner_id=owner_id,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def test_create_project_and_list() -> None:
    svc = MagicMock()
    proj = _make_project()
    svc.create_project.return_value = proj
    svc.list_projects.return_value = [proj]

    client = _make_client(svc)

    resp = client.post(
        "/v1/projects",
        json={"name": "My Project", "description": "hello", "visibility": "private"},
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["id"] == "proj-aaa"
    assert created["name"] == "My Project"
    assert created["owner_id"] == "user-123"
    assert created["org_id"] is None

    svc.create_project.assert_called_once()

    list_resp = client.get("/v1/projects")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert "items" in payload
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "proj-aaa"


def test_create_project_with_org_id_still_single_resource_type() -> None:
    svc = MagicMock()
    proj = _make_project(org_id="org-abc")
    svc.create_project.return_value = proj
    svc.list_projects.return_value = [proj]

    client = _make_client(svc)

    resp = client.post("/v1/projects", json={"name": "My Project", "org_id": "org-abc"})
    assert resp.status_code == 201
    created = resp.json()
    assert created["org_id"] == "org-abc"
    assert created["owner_id"] == "user-123"

    # Filtering works
    list_resp = client.get("/v1/projects?org_id=org-abc")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "proj-aaa"


def test_list_project_participants() -> None:
    svc = MagicMock()
    proj = _make_project()
    svc.get_project.return_value = proj
    svc.list_project_participants.return_value = [
        {
            "id": "user-123",
            "kind": "human",
            "user_id": "user-123",
            "display_name": "Nick Sanders",
            "role": "owner",
            "membership_source": "owner",
        },
        {
            "id": "agent-123",
            "kind": "agent",
            "agent_id": "agent-123",
            "display_name": "Architect Agent",
            "role": "primary",
            "assignment_status": "active",
            "presence": "available",
        },
    ]

    client = _make_client(svc)

    resp = client.get("/v1/projects/proj-aaa/participants")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["totals"] == {"total": 2, "humans": 1, "agents": 1}
    assert payload["items"][0]["kind"] == "human"
    assert payload["items"][1]["kind"] == "agent"
