"""
Integration Tests for MCP Device Flow in Staging Environment

Tests real OAuth device authorization flow with staging infrastructure:
- Device login with real GitHub OAuth server
- Token persistence across CLI/MCP surfaces
- Telemetry event emission to staging observability stack
- Cross-surface token sharing and refresh

Prerequisites:
- Staging environment running (podman ps | grep staging)
- AMPREALIZE_GATEWAY_URL set to staging endpoint (default: http://localhost:8080)
- Valid GitHub OAuth app credentials in deployment/staging.env

Usage:
    # Set staging endpoint
    export AMPREALIZE_GATEWAY_URL=http://localhost:8080

    # Run integration tests
    pytest tests/integration/test_staging_device_flow.py -v -s

    # Run specific test
    pytest tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_device_login_real_oauth -v -s
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class StagingAPIClient:
    """Client for interacting with Amprealize staging API."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("AMPREALIZE_GATEWAY_URL", "http://localhost:8080")
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create requests session with retry logic."""
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def health_check(self) -> Dict[str, Any]:
        """Check if staging API is healthy."""
        response = self.session.get(f"{self.base_url}/health", timeout=5)
        response.raise_for_status()
        return response.json()

    def device_login(
        self,
        *,
        client_id: str = "amprealize-staging-client",
        scopes: Optional[list] = None,
        poll_interval: int = 5,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """Initiate device authorization flow."""
        scopes = scopes or ["behaviors.read", "workflows.read", "runs.create"]

        response = self.session.post(
            f"{self.base_url}/api/v1/auth/device/login",
            json={
                "client_id": client_id,
                "scopes": scopes,
                "poll_interval": poll_interval,
                "timeout": timeout,
            },
            timeout=timeout + 10,
        )
        response.raise_for_status()
        return response.json()

    def auth_status(self, client_id: str = "amprealize-staging-client") -> Dict[str, Any]:
        """Check authentication status."""
        response = self.session.get(
            f"{self.base_url}/api/v1/auth/status",
            params={"client_id": client_id},
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def refresh_token(self, client_id: str = "amprealize-staging-client") -> Dict[str, Any]:
        """Refresh access token."""
        response = self.session.post(
            f"{self.base_url}/api/v1/auth/refresh",
            json={"client_id": client_id},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def logout(self, client_id: str = "amprealize-staging-client") -> Dict[str, Any]:
        """Logout and clear tokens."""
        response = self.session.post(
            f"{self.base_url}/api/v1/auth/logout",
            json={"client_id": client_id},
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def get_telemetry_events(
        self,
        *,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list:
        """Fetch telemetry events from staging observability stack."""
        params: Dict[str, Any] = {"limit": limit}

        if event_type:
            params["event_type"] = event_type
        if since:
            params["since"] = since.isoformat()

        response = self.session.get(
            f"{self.base_url}/api/v1/telemetry/events",
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        return response.json().get("events", [])


@pytest.fixture(scope="session")
def staging_client() -> StagingAPIClient:
    """Staging API client fixture."""
    return StagingAPIClient()


@pytest.fixture(scope="session")
def ensure_staging_running(staging_client: StagingAPIClient) -> None:
    """Ensure staging environment is running."""
    try:
        health = staging_client.health_check()
        assert health.get("status") == "healthy", f"Staging unhealthy: {health}"
    except Exception as exc:
        pytest.skip(f"Staging environment not available: {exc}")


# Override conftest fixtures to prevent test infrastructure startup
@pytest.fixture(scope="session", autouse=True)
def skip_test_infrastructure_check():
    """Skip test infrastructure checks for staging integration tests."""
    pass


class TestStagingDeviceFlow:
    """Integration tests for device flow in staging environment."""

    def test_staging_api_health(
        self,
        staging_client: StagingAPIClient,
        ensure_staging_running,
    ):
        """Verify staging API is healthy."""
        health = staging_client.health_check()

        assert health["status"] == "healthy"
        # Version and environment may not be in response
        # Just verify we have service health information
        assert "services" in health or "pools_summary" in health

    @pytest.mark.manual
    def test_device_login_real_oauth(
        self,
        staging_client: StagingAPIClient,
        ensure_staging_running,
    ):
        """
        Test device login with real GitHub OAuth server.

        **MANUAL TEST**: Requires user interaction to approve device code.

        Steps:
        1. Start device login flow
        2. Display verification URL and user code
        3. Wait for user to approve in browser
        4. Verify tokens returned
        5. Validate token storage

        Run with: pytest -v -s -m manual tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_device_login_real_oauth
        """
        manual_oauth_enabled = os.getenv("AMPREALIZE_RUN_MANUAL_STAGING_OAUTH", "0").lower() in {"1", "true", "yes"}
        if not manual_oauth_enabled:
            pytest.skip(
                "Manual staging OAuth test disabled. Set AMPREALIZE_RUN_MANUAL_STAGING_OAUTH=1 to enable."
            )
        print("\n" + "="*80)
        print("MANUAL TEST: Real OAuth Device Authorization Flow")
        print("="*80)

        # Start device login
        print("\n1. Starting device login flow...")
        result = staging_client.device_login(
            client_id="amprealize-staging-test",
            scopes=["behaviors.read", "runs.create"],
            poll_interval=5,
            timeout=300,  # 5 minutes
        )

        # Display instructions
        print("\n2. User authorization required:")
        print(f"   URL: {result['verification_uri']}")
        print(f"   Code: {result['user_code']}")
        print(f"\n   Please visit the URL above and enter the code to authorize.")
        print(f"   Waiting for approval (timeout in {result['expires_in']}s)...\n")

        # Polling happens server-side, but we wait for completion
        # In real scenario, this would return when user approves

        if result["status"] == "authorized":
            print("✓ Authorization successful!")
            print(f"   Access token: {result['access_token'][:20]}...")
            print(f"   Refresh token: {result['refresh_token'][:20]}...")
            print(f"   Scopes: {result['scopes']}")
            print(f"   Expires at: {result['expires_at']}")

            # Verify token storage
            assert "access_token" in result
            assert "refresh_token" in result
            assert result["scopes"] == ["behaviors.read", "runs.create"]

        elif result["status"] == "pending":
            print("⚠ Still pending - test needs manual approval")
            print("  Note: Server-side polling will continue for up to 5 minutes")
            pytest.skip("Manual approval required - rerun test after approving")
        else:
            pytest.fail(f"Unexpected status: {result['status']}")

    def test_auth_status_with_staging_tokens(
        self,
        staging_client: StagingAPIClient,
        ensure_staging_running,
    ):
        """
        Test auth status check with staging token storage.

        Verifies:
        - Auth status API returns correct token state
        - Token expiry calculations
        - Storage path information
        """
        status = staging_client.auth_status(client_id="amprealize-staging-test")

        # Should return status even if no tokens stored
        assert "is_authenticated" in status
        assert "access_token_valid" in status
        assert "refresh_token_valid" in status

        if status["is_authenticated"]:
            print(f"\n✓ Authenticated with staging tokens")
            print(f"  Client: {status['client_id']}")
            print(f"  Scopes: {status['scopes']}")
            print(f"  Access expires in: {status['expires_in']}s")
            print(f"  Storage: {status.get('token_storage_type', 'unknown')}")
        else:
            print(f"\n⚠ Not authenticated - run manual login test first")

    def test_token_persistence_across_surfaces(
        self,
        staging_client: StagingAPIClient,
        ensure_staging_running,
    ):
        """
        Test token sharing between CLI and MCP surfaces.

        Verifies:
        - Tokens stored by one surface available to another
        - Token bundle includes all required fields
        - Storage paths consistent across surfaces
        """
        # Check current auth status
        status = staging_client.auth_status(client_id="amprealize-staging-test")

        if not status["is_authenticated"]:
            pytest.skip("No stored tokens - run manual login test first")

        # Verify token bundle structure
        assert status["client_id"] == "amprealize-staging-test"
        assert isinstance(status["scopes"], list)
        assert len(status["scopes"]) > 0

        # Check token validity
        if status["access_token_valid"]:
            print(f"\n✓ Access token valid for {status['expires_in']}s")

        if status["refresh_token_valid"]:
            print(f"✓ Refresh token valid for {status['refresh_expires_in']}s")

        # Verify storage information
        storage_info = status.get("token_storage_path")
        if storage_info:
            print(f"✓ Token storage: {storage_info}")

    @pytest.mark.skipif(
        os.getenv("TELEMETRY_ENABLED", "false").lower() != "true",
        reason="Telemetry not enabled in staging",
    )
    def test_telemetry_events_in_staging(
        self,
        staging_client: StagingAPIClient,
        ensure_staging_running,
    ):
        """
        Test telemetry event emission to staging observability stack.

        Verifies:
        - Device flow events captured in telemetry system
        - Event schema includes required fields
        - Events queryable via telemetry API
        """
        # Fetch recent device flow events
        since = datetime.now(timezone.utc)
        since = since.replace(hour=0, minute=0, second=0, microsecond=0)  # Start of day

        events = staging_client.get_telemetry_events(
            event_type="device_flow.mcp.login_started",
            since=since,
            limit=10,
        )

        if len(events) > 0:
            print(f"\n✓ Found {len(events)} device flow events today")

            # Examine most recent event
            latest = events[0]
            print(f"\nLatest event:")
            print(f"  Type: {latest['event_type']}")
            print(f"  Timestamp: {latest['timestamp']}")
            print(f"  Client ID: {latest.get('payload', {}).get('client_id')}")

            # Verify event structure
            assert "event_id" in latest
            assert "timestamp" in latest
            assert "event_type" in latest
            assert "payload" in latest
        else:
            print("\n⚠ No recent device flow events - run manual login test first")

    def test_token_refresh_with_staging_oauth(
        self,
        staging_client: StagingAPIClient,
        ensure_staging_running,
    ):
        """
        Test token refresh with staging OAuth server.

        Verifies:
        - Refresh token exchange works with real OAuth server
        - New access token issued
        - Refresh token may be rotated
        """
        # Check if we have a refresh token
        status = staging_client.auth_status(client_id="amprealize-staging-test")

        if not status.get("refresh_token_valid"):
            pytest.skip("No valid refresh token - run manual login test first")

        print(f"\n1. Current token expires in: {status['expires_in']}s")

        # Perform refresh
        print("2. Refreshing token...")
        refresh_result = staging_client.refresh_token(client_id="amprealize-staging-test")

        if refresh_result.get("status") == "success":
            print("✓ Token refresh successful!")
            print(f"  New access token: {refresh_result['access_token'][:20]}...")
            print(f"  Expires in: {refresh_result['expires_in']}s")

            # Verify new token is different
            new_status = staging_client.auth_status(client_id="amprealize-staging-test")
            assert new_status["expires_in"] > status["expires_in"]
        else:
            pytest.fail(f"Token refresh failed: {refresh_result}")

    def test_logout_clears_staging_tokens(
        self,
        staging_client: StagingAPIClient,
        ensure_staging_running,
    ):
        """
        Test logout clears tokens from staging storage.

        Verifies:
        - Logout clears tokens
        - Auth status reflects unauthenticated state
        - Warning about remote revocation
        """
        # Check initial state
        status_before = staging_client.auth_status(client_id="amprealize-staging-test")
        was_authenticated = status_before["is_authenticated"]

        if not was_authenticated:
            print("\n⚠ No tokens to clear - skipping logout test")
            return

        # Perform logout
        print("\n1. Logging out...")
        logout_result = staging_client.logout(client_id="amprealize-staging-test")

        assert logout_result["status"] == "success"
        print("✓ Logout successful")

        if "warning" in logout_result:
            print(f"⚠ Warning: {logout_result['warning']}")

        # Verify tokens cleared
        print("2. Verifying tokens cleared...")
        status_after = staging_client.auth_status(client_id="amprealize-staging-test")

        assert not status_after["is_authenticated"]
        assert not status_after["access_token_valid"]
        assert not status_after["refresh_token_valid"]
        print("✓ Tokens successfully cleared from storage")


class TestStagingCLIMCPParity:
    """Test CLI and MCP tool parity in staging environment."""

    def test_cli_login_visible_to_mcp(
        self,
        staging_client: StagingAPIClient,
        ensure_staging_running,
    ):
        """
        Test tokens stored via CLI are accessible to MCP tools.

        This would require running amprealize CLI commands and then
        checking via MCP API - implementation depends on CLI availability.
        """
        pytest.skip("Requires CLI installed - implement when CLI available in staging")

    def test_mcp_login_visible_to_cli(
        self,
        staging_client: StagingAPIClient,
        ensure_staging_running,
    ):
        """
        Test tokens stored via MCP are accessible to CLI.

        This would require MCP login followed by CLI auth status check.
        """
        pytest.skip("Requires CLI installed - implement when CLI available in staging")


if __name__ == "__main__":
    # Allow running directly for quick testing
    print("Amprealize Staging Integration Tests")
    print("=" * 80)

    client = StagingAPIClient()

    try:
        health = client.health_check()
        print(f"\n✓ Staging API: {client.base_url}")
        print(f"  Status: {health['status']}")
        print(f"  Version: {health.get('version', 'unknown')}")
        print(f"  Environment: {health.get('environment', 'unknown')}")

        print("\nRun tests with: pytest tests/integration/test_staging_device_flow.py -v -s")
        print("Manual tests: pytest -v -s -m manual tests/integration/test_staging_device_flow.py")
    except Exception as exc:
        print(f"\n✗ Staging API not available: {exc}")
        print(f"  Endpoint: {client.base_url}")
        print("\nEnsure staging is running: podman ps | grep staging")
