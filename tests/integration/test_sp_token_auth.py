"""
Integration Tests for Service Principal Token Authentication (GT2.1.3)

Tests that SP tokens obtained via /api/v1/auth/service-principals/authenticate
can be used to create and access projects, boards, and work items.

Also tests that device flow approval correctly populates oauth_user_id
so tokens resolve to a real user identity.

Prerequisites:
- API server running (uvicorn amprealize.api:app) with PostgreSQL
- A service principal must exist (created via API or DB seed)

Usage:
    pytest tests/integration/test_sp_token_auth.py -v -s

    # Run specific test
    pytest tests/integration/test_sp_token_auth.py::TestSPTokenAuth -v
"""

import os
import time
import uuid
from typing import Any, Dict, Optional

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = os.getenv("AMPREALIZE_GATEWAY_URL", "http://localhost:8080")


class AmprealizeTestClient:
    """Test client for Amprealize API with retry logic."""

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.3, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def health_check(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/health", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def request(
        self,
        method: str,
        path: str,
        json: Optional[Dict] = None,
        token: Optional[str] = None,
        **kwargs,
    ) -> requests.Response:
        headers = kwargs.pop("headers", {})
        headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.session.request(
            method,
            f"{self.base_url}{path}",
            json=json,
            headers=headers,
            timeout=10,
            **kwargs,
        )


@pytest.fixture(scope="module")
def client() -> AmprealizeTestClient:
    c = AmprealizeTestClient()
    if not c.health_check():
        pytest.skip("API server not available")
    return c


@pytest.fixture(scope="module")
def device_flow_token(client: AmprealizeTestClient) -> str:
    """Get a device flow token for setup operations."""
    # Initiate device flow
    r = client.request("POST", "/api/v1/auth/device/authorize", json={
        "client_id": "test-sp-integration",
        "scopes": ["read", "write"],
    })
    assert r.status_code == 200, f"Device flow init failed: {r.text}"
    data = r.json()

    # Approve
    r = client.request("POST", "/api/v1/auth/device/approve", json={
        "user_code": data["user_code"],
        "approver": "test-integration-runner",
    })
    assert r.status_code == 200, f"Device approve failed: {r.text}"

    # Exchange for token
    r = client.request("POST", "/api/v1/auth/device/token", json={
        "device_code": data["device_code"],
        "client_id": "test-sp-integration",
    })
    assert r.status_code == 200, f"Device token exchange failed: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def service_principal(client: AmprealizeTestClient, device_flow_token: str) -> Dict[str, Any]:
    """Create a service principal for testing."""
    sp_name = f"test-sp-{uuid.uuid4().hex[:8]}"
    r = client.request(
        "POST",
        "/api/v1/auth/service-principals",
        json={
            "name": sp_name,
            "description": "Integration test service principal",
            "allowed_scopes": ["read", "write"],
            "role": "STUDENT",
        },
        token=device_flow_token,
    )
    if r.status_code == 404:
        pytest.skip("Service principal endpoint not available")
    assert r.status_code in (200, 201), f"SP creation failed: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def sp_token(client: AmprealizeTestClient, service_principal: Dict[str, Any]) -> str:
    """Authenticate as a service principal and get an access token."""
    sp_data = service_principal
    # Extract client_id and client_secret from creation response
    client_id = sp_data.get("client_id") or sp_data.get("service_principal", {}).get("client_id")
    client_secret = sp_data.get("client_secret")

    if not client_id or not client_secret:
        pytest.skip(f"Could not extract SP credentials from response: {sp_data}")

    r = client.request(
        "POST",
        "/api/v1/auth/service-principals/authenticate",
        json={
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    assert r.status_code == 200, f"SP authentication failed: {r.status_code} {r.text}"
    data = r.json()
    token = data["access_token"]

    # Verify the token has the ga_ prefix (stored and validatable)
    assert token.startswith("ga_"), (
        f"SP token should have ga_ prefix but got: {token[:20]}... "
        "This means the token is not stored and won't be validatable."
    )
    return token


class TestSPTokenAuth:
    """Tests that SP tokens work across all API endpoints (GT2.1.3)."""

    def test_sp_token_has_ga_prefix(self, sp_token: str):
        """SP tokens must have ga_ prefix to be validated by auth middleware."""
        assert sp_token.startswith("ga_")

    def test_sp_token_list_projects(self, client: AmprealizeTestClient, sp_token: str):
        """SP token can list projects (was returning 401 before fix)."""
        r = client.request("GET", "/api/v1/projects", token=sp_token)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        # Should return a valid response (may be empty list)
        assert "items" in data or isinstance(data, list), f"Unexpected response: {data}"

    def test_sp_token_create_project(self, client: AmprealizeTestClient, sp_token: str):
        """SP token can create a project."""
        project_name = f"sp-test-project-{uuid.uuid4().hex[:8]}"
        r = client.request(
            "POST",
            "/api/v1/projects",
            json={
                "name": project_name,
                "slug": project_name,
                "description": "Created by SP token integration test",
                "visibility": "private",
            },
            token=sp_token,
        )
        assert r.status_code in (200, 201), f"Expected 200/201, got {r.status_code}: {r.text}"
        data = r.json()
        project_id = data.get("id") or data.get("project_id")
        assert project_id, f"No project ID in response: {data}"

    def test_sp_token_list_boards(self, client: AmprealizeTestClient, sp_token: str):
        """SP token can list boards."""
        r = client.request("GET", "/api/v1/boards", token=sp_token)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_sp_token_list_work_items(self, client: AmprealizeTestClient, sp_token: str):
        """SP token can list work items."""
        r = client.request(
            "GET",
            "/api/v1/work-items?limit=5",
            token=sp_token,
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_sp_token_create_board_and_work_item(
        self, client: AmprealizeTestClient, sp_token: str
    ):
        """SP token can create a board and work item (full workflow)."""
        # Create a project first
        project_name = f"sp-workflow-{uuid.uuid4().hex[:8]}"
        r = client.request(
            "POST",
            "/api/v1/projects",
            json={
                "name": project_name,
                "slug": project_name,
                "description": "SP workflow test",
                "visibility": "private",
            },
            token=sp_token,
        )
        assert r.status_code in (200, 201), f"Project creation failed: {r.text}"
        project_id = r.json().get("id") or r.json().get("project_id")

        # Create a board
        r = client.request(
            "POST",
            "/api/v1/boards",
            json={
                "project_id": project_id,
                "name": f"SP Test Board {uuid.uuid4().hex[:6]}",
                "create_default_columns": True,
            },
            token=sp_token,
        )
        assert r.status_code in (200, 201), f"Board creation failed: {r.text}"
        board_data = r.json().get("board", r.json())
        board_id = board_data.get("board_id") or board_data.get("id")
        assert board_id, f"No board ID: {r.json()}"

        # Create a work item
        r = client.request(
            "POST",
            "/api/v1/work-items",
            json={
                "item_type": "task",
                "project_id": project_id,
                "board_id": board_id,
                "title": "SP integration test task",
                "description": "Created by service principal token",
                "priority": "medium",
            },
            token=sp_token,
        )
        assert r.status_code in (200, 201), f"Work item creation failed: {r.text}"
        item_data = r.json().get("item", r.json())
        item_id = item_data.get("item_id") or item_data.get("id")
        assert item_id, f"No item ID: {r.json()}"

        # Read the work item back
        r = client.request("GET", f"/api/v1/work-items/{item_id}", token=sp_token)
        assert r.status_code == 200, f"Work item read failed: {r.text}"


class TestDeviceFlowIdentity:
    """Tests that device flow approval populates oauth_user_id correctly."""

    def test_device_flow_token_resolves_known_user(
        self, client: AmprealizeTestClient
    ):
        """When approver matches an auth.users entry, token should resolve to that user."""
        # Initiate device flow
        r = client.request("POST", "/api/v1/auth/device/authorize", json={
            "client_id": "test-identity-resolution",
            "scopes": ["read", "write"],
        })
        assert r.status_code == 200
        data = r.json()

        # Approve using a known user identity (system user exists in auth.users)
        r = client.request("POST", "/api/v1/auth/device/approve", json={
            "user_code": data["user_code"],
            "approver": "system",
        })
        assert r.status_code == 200

        # Exchange for token
        r = client.request("POST", "/api/v1/auth/device/token", json={
            "device_code": data["device_code"],
            "client_id": "test-identity-resolution",
        })
        assert r.status_code == 200
        token = r.json()["access_token"]

        # Token should work for listing projects (was failing due to null user_id)
        r = client.request("GET", "/api/v1/projects", token=token)
        assert r.status_code == 200, (
            f"Expected 200 but got {r.status_code}: {r.text}. "
            "This suggests the token didn't resolve to a user identity."
        )

    def test_device_flow_with_unknown_approver_still_works(
        self, client: AmprealizeTestClient
    ):
        """When approver is not in auth.users, token should still work with approver as sub."""
        r = client.request("POST", "/api/v1/auth/device/authorize", json={
            "client_id": "test-unknown-approver",
            "scopes": ["read", "write"],
        })
        assert r.status_code == 200
        data = r.json()

        # Approve with a string that's NOT in auth.users
        r = client.request("POST", "/api/v1/auth/device/approve", json={
            "user_code": data["user_code"],
            "approver": f"unknown-test-user-{uuid.uuid4().hex[:8]}",
        })
        assert r.status_code == 200

        # Exchange for token — should still work
        r = client.request("POST", "/api/v1/auth/device/token", json={
            "device_code": data["device_code"],
            "client_id": "test-unknown-approver",
        })
        assert r.status_code == 200
        token = r.json()["access_token"]
        assert token.startswith("ga_")

        # Token should work (approver string used as sub)
        r = client.request("GET", "/api/v1/projects", token=token)
        assert r.status_code == 200
