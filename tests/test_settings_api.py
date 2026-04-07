"""Tests for Organization and Project Settings API endpoints.

Tests the REST API layer for settings management including:
- Organization settings CRUD
- Branding, notifications, security, integrations, workflow settings
- Project settings with inheritance
- Webhook management
- Feature flags

Following behavior_design_test_strategy (Student):
- Unit tests with mocked services
- Tests for authorization requirements
- Tests for error handling
"""

from __future__ import annotations

import pytest

from amprealize.multi_tenant.settings import SettingsService

# Mark all tests as unit; skip if enterprise not installed
pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(SettingsService is None, reason="SettingsService requires amprealize-enterprise"),
]
from datetime import datetime
from unittest.mock import MagicMock, patch
from typing import Dict, Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.multi_tenant.settings_api import create_settings_routes
from amprealize.multi_tenant.settings import (
    SettingsService,
    OrgSettings,
    ProjectSettings,
    BrandingSettings,
    NotificationSettings,
    SecuritySettings,
    IntegrationSettings,
    WorkflowSettings,
    AgentSettings,
)
from amprealize.multi_tenant.contracts import MemberRole, ProjectRole


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_settings_service():
    """Create mock SettingsService."""
    service = MagicMock(spec=SettingsService)
    return service


@pytest.fixture
def sample_org_settings() -> OrgSettings:
    """Sample organization settings for testing."""
    return OrgSettings(
        org_id="org-test123",
        branding=BrandingSettings(
            logo_url="https://example.com/logo.png",
            primary_color="#007bff",
            display_name="Test Org",
        ),
        notifications=NotificationSettings(
            email_enabled=True,
            slack_enabled=False,
        ),
        security=SecuritySettings(
            require_mfa=False,
            sso_enabled=False,
        ),
        integrations=IntegrationSettings(
            github_enabled=True,
            github_org="test-org",
        ),
        workflow=WorkflowSettings(
            default_behaviors=["behavior_1"],
            max_concurrent_runs=10,
        ),
        agents=AgentSettings(
            default_model="claude-sonnet-4-20250514",
        ),
        default_project_visibility="private",
        default_member_role="member",
        features={"feature_a": True},
        custom={"custom_key": "value"},
    )


@pytest.fixture
def sample_project_settings() -> ProjectSettings:
    """Sample project settings for testing."""
    return ProjectSettings(
        project_id="proj-test123",
        inherit_org_settings=True,
        workflow=WorkflowSettings(
            default_behaviors=["behavior_a"],
            max_concurrent_runs=5,
        ),
        agents=AgentSettings(
            default_model="gpt-4o",
        ),
        repository_url="https://github.com/test/repo",
        default_branch="main",
        protected_branches=["main", "develop"],
        environments=["dev", "staging", "prod"],
        active_environment="dev",
        features={"project_feature": True},
        custom={"project_custom": "data"},
    )


@pytest.fixture
def app_with_admin_context(mock_settings_service, sample_org_settings, sample_project_settings):
    """Create FastAPI app with admin user context."""
    app = FastAPI()

    # Configure mock service
    mock_settings_service.get_org_settings.return_value = sample_org_settings
    mock_settings_service.get_project_settings.return_value = sample_project_settings
    mock_settings_service.update_org_settings.return_value = sample_org_settings
    mock_settings_service.update_project_settings.return_value = sample_project_settings
    mock_settings_service.update_org_branding.return_value = sample_org_settings.branding
    mock_settings_service.update_org_notifications.return_value = sample_org_settings.notifications
    mock_settings_service.update_org_security.return_value = sample_org_settings.security
    mock_settings_service.update_org_integrations.return_value = sample_org_settings.integrations
    mock_settings_service.update_org_workflow.return_value = sample_org_settings.workflow
    mock_settings_service.update_project_workflow.return_value = sample_project_settings.workflow
    mock_settings_service.set_org_feature_flag.return_value = {"feature_a": True, "new_feature": True}
    mock_settings_service.set_project_feature_flag.return_value = {"project_feature": True, "new_feature": True}
    mock_settings_service.set_project_repository.return_value = sample_project_settings
    mock_settings_service.add_org_webhook.return_value = {
        "id": "wh-test123",
        "url": "https://example.com/webhook",
        "events": ["run.complete", "run.failed"],
        "enabled": True,
        "created_at": datetime.utcnow().isoformat(),
    }
    mock_settings_service.remove_org_webhook.return_value = True

    router = create_settings_routes(mock_settings_service)
    app.include_router(router)

    @app.middleware("http")
    async def add_admin_context(request, call_next):
        # Simulate authenticated admin user with org and project context
        request.state.user_id = "user-admin"
        request.state.org_context = MagicMock()
        request.state.org_context.org_id = "org-test123"
        request.state.org_context.role = MemberRole.ADMIN
        request.state.project_context = MagicMock()
        request.state.project_context.project_id = "proj-test123"
        request.state.project_context.role = ProjectRole.MAINTAINER
        return await call_next(request)

    return app, mock_settings_service


@pytest.fixture
def app_with_viewer_context(mock_settings_service, sample_org_settings, sample_project_settings):
    """Create FastAPI app with viewer-only context."""
    app = FastAPI()

    mock_settings_service.get_org_settings.return_value = sample_org_settings
    mock_settings_service.get_project_settings.return_value = sample_project_settings

    router = create_settings_routes(mock_settings_service)
    app.include_router(router)

    @app.middleware("http")
    async def add_viewer_context(request, call_next):
        request.state.user_id = "user-viewer"
        request.state.org_context = MagicMock()
        request.state.org_context.org_id = "org-test123"
        request.state.org_context.role = MemberRole.VIEWER
        request.state.project_context = MagicMock()
        request.state.project_context.project_id = "proj-test123"
        request.state.project_context.role = ProjectRole.VIEWER
        return await call_next(request)

    return app, mock_settings_service


@pytest.fixture
def admin_client(app_with_admin_context):
    """Test client with admin privileges."""
    app, _ = app_with_admin_context
    return TestClient(app)


@pytest.fixture
def viewer_client(app_with_viewer_context):
    """Test client with viewer-only privileges."""
    app, _ = app_with_viewer_context
    return TestClient(app)


# =============================================================================
# Organization Settings Tests
# =============================================================================

class TestGetOrgSettings:
    """Tests for GET /v1/orgs/{org_id}/settings."""

    def test_get_org_settings_success(self, admin_client):
        """Admin can get complete org settings."""
        response = admin_client.get("/v1/orgs/org-test123/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["org_id"] == "org-test123"
        assert data["branding"]["logo_url"] == "https://example.com/logo.png"
        assert data["branding"]["primary_color"] == "#007bff"
        assert data["notifications"]["email_enabled"] is True
        assert data["security"]["require_mfa"] is False
        assert data["integrations"]["github_enabled"] is True
        assert data["workflow"]["max_concurrent_runs"] == 10
        assert data["features"]["feature_a"] is True

    def test_get_org_settings_viewer_allowed(self, viewer_client):
        """Viewer can read org settings."""
        response = viewer_client.get("/v1/orgs/org-test123/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["org_id"] == "org-test123"

    def test_get_org_settings_not_found(self, app_with_admin_context):
        """Returns 404 when service raises ValueError."""
        app, mock_service = app_with_admin_context
        mock_service.get_org_settings.side_effect = ValueError("Organization not found")

        client = TestClient(app)
        response = client.get("/v1/orgs/org-test123/settings")

        # ValueError from service is caught and returns 404
        assert response.status_code == 404


class TestUpdateOrgSettings:
    """Tests for PATCH /v1/orgs/{org_id}/settings."""

    def test_update_org_settings_success(self, admin_client):
        """Admin can update org settings."""
        response = admin_client.patch(
            "/v1/orgs/org-test123/settings",
            json={
                "branding": {"primary_color": "#ff0000"},
                "features": {"new_feature": True},
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["org_id"] == "org-test123"

    def test_update_org_settings_viewer_forbidden(self, viewer_client):
        """Viewer cannot update org settings."""
        response = viewer_client.patch(
            "/v1/orgs/org-test123/settings",
            json={"branding": {"primary_color": "#ff0000"}}
        )

        assert response.status_code == 403


# =============================================================================
# Individual Settings Section Tests
# =============================================================================

class TestBrandingSettings:
    """Tests for branding settings endpoints."""

    def test_get_branding(self, admin_client):
        """Get branding settings."""
        response = admin_client.get("/v1/orgs/org-test123/settings/branding")

        assert response.status_code == 200
        data = response.json()
        assert data["logo_url"] == "https://example.com/logo.png"
        assert data["primary_color"] == "#007bff"

    def test_update_branding(self, admin_client):
        """Update branding settings."""
        response = admin_client.patch(
            "/v1/orgs/org-test123/settings/branding",
            json={
                "logo_url": "https://new.example.com/logo.png",
                "tagline": "New tagline",
            }
        )

        assert response.status_code == 200


class TestNotificationSettings:
    """Tests for notification settings endpoints."""

    def test_get_notifications(self, admin_client):
        """Get notification settings."""
        response = admin_client.get("/v1/orgs/org-test123/settings/notifications")

        assert response.status_code == 200
        data = response.json()
        assert data["email_enabled"] is True

    def test_update_notifications(self, admin_client):
        """Update notification settings."""
        response = admin_client.patch(
            "/v1/orgs/org-test123/settings/notifications",
            json={
                "slack_enabled": True,
                "slack_webhook_url": "https://hooks.slack.com/xxx",
            }
        )

        assert response.status_code == 200


class TestSecuritySettings:
    """Tests for security settings endpoints."""

    def test_get_security(self, admin_client):
        """Get security settings."""
        response = admin_client.get("/v1/orgs/org-test123/settings/security")

        assert response.status_code == 200
        data = response.json()
        assert data["require_mfa"] is False

    def test_update_security(self, admin_client):
        """Update security settings."""
        response = admin_client.patch(
            "/v1/orgs/org-test123/settings/security",
            json={
                "require_mfa": True,
                "session_timeout_hours": 4,
            }
        )

        assert response.status_code == 200


class TestIntegrationSettings:
    """Tests for integration settings endpoints."""

    def test_get_integrations(self, admin_client):
        """Get integration settings."""
        response = admin_client.get("/v1/orgs/org-test123/settings/integrations")

        assert response.status_code == 200
        data = response.json()
        assert data["github_enabled"] is True
        assert data["github_org"] == "test-org"

    def test_update_integrations(self, admin_client):
        """Update integration settings."""
        response = admin_client.patch(
            "/v1/orgs/org-test123/settings/integrations",
            json={
                "gitlab_enabled": True,
                "gitlab_url": "https://gitlab.example.com",
            }
        )

        assert response.status_code == 200


class TestWorkflowSettings:
    """Tests for workflow settings endpoints."""

    def test_get_workflow(self, admin_client):
        """Get workflow settings."""
        response = admin_client.get("/v1/orgs/org-test123/settings/workflow")

        assert response.status_code == 200
        data = response.json()
        assert data["max_concurrent_runs"] == 10

    def test_update_workflow(self, admin_client):
        """Update workflow settings."""
        response = admin_client.patch(
            "/v1/orgs/org-test123/settings/workflow",
            json={
                "max_concurrent_runs": 20,
                "default_token_budget": 50000,
            }
        )

        assert response.status_code == 200


# =============================================================================
# Webhook Tests
# =============================================================================

class TestWebhooks:
    """Tests for webhook management endpoints."""

    def test_add_webhook(self, admin_client):
        """Add a webhook to organization."""
        response = admin_client.post(
            "/v1/orgs/org-test123/settings/webhooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["run.complete", "run.failed"],
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "wh-test123"
        assert data["url"] == "https://example.com/webhook"
        assert data["enabled"] is True

    def test_remove_webhook(self, admin_client):
        """Remove a webhook from organization."""
        response = admin_client.delete(
            "/v1/orgs/org-test123/settings/webhooks/wh-test123"
        )

        assert response.status_code == 204

    def test_remove_nonexistent_webhook(self, app_with_admin_context):
        """Returns 404 for non-existent webhook."""
        app, mock_service = app_with_admin_context
        mock_service.remove_org_webhook.return_value = False

        client = TestClient(app)
        response = client.delete(
            "/v1/orgs/org-test123/settings/webhooks/wh-nonexistent"
        )

        assert response.status_code == 404


# =============================================================================
# Feature Flag Tests
# =============================================================================

class TestFeatureFlags:
    """Tests for feature flag endpoints."""

    def test_set_org_feature_flag(self, admin_client):
        """Set organization feature flag."""
        response = admin_client.put(
            "/v1/orgs/org-test123/settings/features/new_feature",
            json={"enabled": True}
        )

        assert response.status_code == 200
        data = response.json()
        assert "new_feature" in data

    def test_set_project_feature_flag(self, admin_client):
        """Set project feature flag."""
        response = admin_client.put(
            "/v1/projects/proj-test123/settings/features/new_feature",
            json={"enabled": True}
        )

        assert response.status_code == 200


# =============================================================================
# Project Settings Tests
# =============================================================================

class TestProjectSettings:
    """Tests for project settings endpoints."""

    def test_get_project_settings(self, admin_client):
        """Get complete project settings."""
        response = admin_client.get("/v1/projects/proj-test123/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == "proj-test123"
        assert data["inherit_org_settings"] is True
        assert data["repository_url"] == "https://github.com/test/repo"
        assert data["default_branch"] == "main"

    def test_update_project_settings(self, admin_client):
        """Update project settings."""
        response = admin_client.patch(
            "/v1/projects/proj-test123/settings",
            json={
                "inherit_org_settings": False,
                "default_branch": "develop",
            }
        )

        assert response.status_code == 200

    def test_get_project_workflow(self, admin_client):
        """Get project workflow settings."""
        response = admin_client.get("/v1/projects/proj-test123/settings/workflow")

        assert response.status_code == 200
        data = response.json()
        assert data["max_concurrent_runs"] == 5

    def test_update_project_workflow(self, admin_client):
        """Update project workflow settings."""
        response = admin_client.patch(
            "/v1/projects/proj-test123/settings/workflow",
            json={"max_concurrent_runs": 15}
        )

        assert response.status_code == 200

    def test_set_repository(self, admin_client):
        """Set project repository configuration."""
        response = admin_client.put(
            "/v1/projects/proj-test123/settings/repository",
            json={
                "repository_url": "https://github.com/new/repo",
                "default_branch": "main",
            }
        )

        assert response.status_code == 200


# =============================================================================
# Authorization Tests
# =============================================================================

class TestAuthorization:
    """Tests for authorization requirements."""

    def test_viewer_cannot_update_branding(self, viewer_client):
        """Viewer cannot update branding."""
        response = viewer_client.patch(
            "/v1/orgs/org-test123/settings/branding",
            json={"primary_color": "#ff0000"}
        )

        assert response.status_code == 403

    def test_viewer_cannot_add_webhook(self, viewer_client):
        """Viewer cannot add webhooks."""
        response = viewer_client.post(
            "/v1/orgs/org-test123/settings/webhooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["run.complete"],
            }
        )

        assert response.status_code == 403

    def test_viewer_cannot_set_feature_flag(self, viewer_client):
        """Viewer cannot set feature flags."""
        response = viewer_client.put(
            "/v1/orgs/org-test123/settings/features/new_feature",
            json={"enabled": True}
        )

        assert response.status_code == 403
