from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

os.environ.setdefault("AMPREALIZE_EXECUTION_ENABLED", "false")

from amprealize import api as api_module


pytestmark = pytest.mark.unit


def _route_paths(app) -> set[str]:
    return {route.path for route in app.routes}


def _minimal_router(path: str):
    router = APIRouter()

    @router.get(path)
    def _handler():
        return {"ok": True}

    return router


def test_oss_org_dsn_mounts_projects_and_participants_without_org_routes(monkeypatch) -> None:
    monkeypatch.setenv("AMPREALIZE_EXECUTION_ENABLED", "false")
    monkeypatch.setenv("AMPREALIZE_ORG_PG_DSN", "postgresql://amprealize:test@localhost:5432/amprealize")
    monkeypatch.setattr(api_module, "ORG_ROUTES_AVAILABLE", False)
    monkeypatch.setattr(api_module, "SETTINGS_ROUTES_AVAILABLE", False)
    monkeypatch.setattr(api_module, "OSSProjectService", lambda dsn: MagicMock(name="oss_project_service"))

    app = api_module.create_app(enable_auth_middleware=False)
    paths = _route_paths(app)

    assert "/api/v1/projects" in paths
    assert "/api/v1/projects/{project_id}/participants" in paths
    assert "/api/v1/orgs" not in paths

    client = TestClient(app)
    capabilities = client.get("/api/v1/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["routes"] == {
        "projects": True,
        "participants": True,
        "orgs": False,
        "settings": False,
        "executions": False,
    }


def test_enterprise_capable_mounts_org_and_settings_routes(monkeypatch) -> None:
    monkeypatch.setenv("AMPREALIZE_EXECUTION_ENABLED", "false")
    monkeypatch.setenv("AMPREALIZE_ORG_PG_DSN", "postgresql://amprealize:test@localhost:5432/amprealize")
    monkeypatch.setattr(api_module, "MULTI_TENANT_AVAILABLE", True)
    monkeypatch.setattr(api_module, "ORG_ROUTES_AVAILABLE", True)
    monkeypatch.setattr(api_module, "SETTINGS_ROUTES_AVAILABLE", True)
    monkeypatch.setattr(api_module, "OrganizationService", lambda dsn, board_service: MagicMock(name="org_service"))
    monkeypatch.setattr(api_module, "InvitationService", lambda dsn, base_url: MagicMock(name="invitation_service"))
    monkeypatch.setattr(api_module, "SettingsService", lambda dsn: MagicMock(name="settings_service"))
    monkeypatch.setattr(api_module, "create_org_routes", lambda **_: _minimal_router("/v1/orgs"))
    monkeypatch.setattr(api_module, "create_settings_routes", lambda **_: _minimal_router("/v1/settings-probe"))

    app = api_module.create_app(enable_auth_middleware=False)
    paths = _route_paths(app)

    assert "/api/v1/orgs" in paths
    assert "/api/v1/settings-probe" in paths
    assert "/api/v1/projects/{project_id}/participants" in paths

    client = TestClient(app)
    capabilities = client.get("/api/v1/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["routes"]["orgs"] is True
    assert capabilities.json()["routes"]["settings"] is True


def test_execution_enabled_fails_fast_when_wiring_breaks(monkeypatch) -> None:
    """When execution wiring fails, the app should gracefully disable executions."""
    monkeypatch.setenv("AMPREALIZE_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("AMPREALIZE_EXECUTION_PG_DSN", "postgresql://amprealize:test@localhost:5432/amprealize")
    monkeypatch.setattr(api_module, "WORK_ITEM_EXECUTION_AVAILABLE", True)

    def _raise_execution_wiring(**_kwargs):
        raise RuntimeError("simulated wiring failure")

    monkeypatch.setattr(api_module, "wire_execution_service", _raise_execution_wiring)

    app = api_module.create_app(enable_auth_middleware=False)
    client = TestClient(app)
    capabilities = client.get("/api/v1/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["routes"]["executions"] is False
    assert capabilities.json()["services"]["execution_enabled"] is False


def test_execution_disabled_skips_execution_routes(monkeypatch) -> None:
    monkeypatch.setenv("AMPREALIZE_EXECUTION_ENABLED", "false")

    def _unexpected_execution_wiring(**_kwargs):
        raise AssertionError("execution wiring should not run when disabled")

    monkeypatch.setattr(api_module, "wire_execution_service", _unexpected_execution_wiring)

    app = api_module.create_app(enable_auth_middleware=False)
    paths = _route_paths(app)

    assert not any(path.startswith("/api/v1/executions") for path in paths)

    client = TestClient(app)
    capabilities = client.get("/api/v1/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["routes"]["executions"] is False
    assert capabilities.json()["services"]["execution_enabled"] is False
