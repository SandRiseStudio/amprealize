"""Tests for device authorization flow implementation.

Validates the device flow manager, token lifecycle, approval/denial workflows,
CLI integration, and API endpoint parity per behavior_lock_down_security_surface.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest

from amprealize.auth_tokens import AuthTokenBundle, FileTokenStore, TokenStoreError
from amprealize.device_flow import (
    DeviceAuthorizationSession,
    DeviceAuthorizationStatus,
    DeviceCodeExpiredError,
    DeviceCodeNotFoundError,
    DeviceFlowError,
    DeviceFlowManager,
    RefreshTokenExpiredError,
    RefreshTokenNotFoundError,
    UserCodeNotFoundError,
)
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient


@pytest.fixture
def telemetry_sink() -> InMemoryTelemetrySink:
    """In-memory telemetry sink for event validation."""
    return InMemoryTelemetrySink()


@pytest.fixture
def device_manager(telemetry_sink: InMemoryTelemetrySink) -> DeviceFlowManager:
    """Device flow manager with short timeouts for fast tests."""
    telemetry_client = TelemetryClient(sink=telemetry_sink)
    return DeviceFlowManager(
        telemetry=telemetry_client,
        verification_uri="https://test.device.local/activate",
        device_code_ttl=300,  # 5 minutes
        poll_interval=1,  # 1 second for fast tests
        access_token_ttl=60,  # 1 minute
        refresh_token_ttl=3600,  # 1 hour
        user_code_length=8,
    )


@pytest.fixture
def token_store(tmp_path) -> Generator[FileTokenStore, None, None]:
    """Temporary file-based token store."""
    store = FileTokenStore(tmp_path / "test_tokens.json")
    yield store
    # Cleanup
    try:
        store.clear()
    except Exception:
        pass


# ============================================================================
# DeviceFlowManager Lifecycle Tests
# ============================================================================


def test_start_authorization_creates_session(device_manager: DeviceFlowManager) -> None:
    """Verify start_authorization generates valid device/user codes."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read", "behaviors.read"],
        surface="CLI",
        metadata={"platform": "test"},
    )

    assert session.device_code.startswith("") and len(session.device_code) > 20
    assert len(session.user_code) == 9  # 8 chars + 1 hyphen (ABCD-EFGH)
    assert session.client_id == "test-client"
    assert session.scopes == ["actions.read", "behaviors.read"]
    assert session.surface == "CLI"
    assert session.status == DeviceAuthorizationStatus.PENDING
    assert session.verification_uri == "https://test.device.local/activate"
    assert session.user_code in session.verification_uri_complete
    assert session.tokens is None


def test_start_authorization_requires_client_id(device_manager: DeviceFlowManager) -> None:
    """Verify client_id is required."""
    with pytest.raises(ValueError, match="client_id is required"):
        device_manager.start_authorization(
            client_id="",
            scopes=["actions.read"],
            surface="CLI",
        )


def test_start_authorization_requires_scopes(device_manager: DeviceFlowManager) -> None:
    """Verify at least one scope is required."""
    with pytest.raises(ValueError, match="scopes must contain at least one scope"):
        device_manager.start_authorization(
            client_id="test-client",
            scopes=[],
            surface="CLI",
        )


def test_start_authorization_emits_telemetry(
    device_manager: DeviceFlowManager, telemetry_sink: InMemoryTelemetrySink
) -> None:
    """Verify start_authorization emits telemetry event."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    events = [e for e in telemetry_sink.events if e.event_type == "auth_device_flow_started"]
    assert len(events) == 1
    event = events[0]
    assert event.payload["device_code"] == session.device_code
    assert event.payload["client_id"] == "test-client"
    assert event.payload["scopes"] == ["actions.read"]


# ============================================================================
# User Code Lookup and Approval Tests
# ============================================================================


def test_describe_user_code_retrieves_session(device_manager: DeviceFlowManager) -> None:
    """Verify user code lookup returns session details."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    described = device_manager.describe_user_code(session.user_code)
    assert described.device_code == session.device_code
    assert described.user_code == session.user_code
    assert described.status == DeviceAuthorizationStatus.PENDING


def test_describe_user_code_raises_for_invalid_code(device_manager: DeviceFlowManager) -> None:
    """Verify invalid user code raises UserCodeNotFoundError."""
    with pytest.raises(UserCodeNotFoundError, match="INVALID-CODE not found"):
        device_manager.describe_user_code("INVALID-CODE")


def test_approve_user_code_issues_tokens(device_manager: DeviceFlowManager) -> None:
    """Verify approving user code transitions to APPROVED and issues tokens."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    approved = device_manager.approve_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
        roles=["STRATEGIST"],
        mfa_verified=True,
    )

    assert approved.status == DeviceAuthorizationStatus.APPROVED
    assert approved.approver == "test-user"
    assert approved.approved_at is not None
    assert approved.tokens is not None
    assert approved.tokens.access_token.startswith("ga_")
    assert approved.tokens.refresh_token.startswith("gr_")
    assert approved.tokens.access_expires_in() > 0
    assert approved.tokens.refresh_expires_in() > 0


def test_approve_user_code_emits_telemetry(
    device_manager: DeviceFlowManager, telemetry_sink: InMemoryTelemetrySink
) -> None:
    """Verify approval emits telemetry with approver context."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    device_manager.approve_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
        roles=["STRATEGIST"],
        mfa_verified=True,
    )

    events = [e for e in telemetry_sink.events if e.event_type == "auth_device_flow_approved"]
    assert len(events) == 1
    event = events[0]
    assert event.payload["approver"] == "test-user"
    assert event.payload["approver_surface"] == "WEB"
    assert event.payload["roles"] == ["STRATEGIST"]
    assert event.payload["mfa_verified"] is True


def test_approve_already_approved_returns_existing(device_manager: DeviceFlowManager) -> None:
    """Verify approving an already-approved code returns existing session."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    first = device_manager.approve_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
    )

    second = device_manager.approve_user_code(
        user_code=session.user_code,
        approver="different-user",
        approver_surface="CLI",
    )

    assert first.device_code == second.device_code
    assert second.approver == "test-user"  # Original approver preserved


def test_deny_user_code_transitions_to_denied(device_manager: DeviceFlowManager) -> None:
    """Verify denying user code transitions to DENIED."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    denied = device_manager.deny_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
        reason="User rejected scope request",
    )

    assert denied.status == DeviceAuthorizationStatus.DENIED
    assert denied.denied_at is not None
    assert denied.denied_reason == "User rejected scope request"
    assert denied.tokens is None


def test_deny_already_denied_returns_existing(device_manager: DeviceFlowManager) -> None:
    """Verify denying an already-denied code returns existing session."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    first = device_manager.deny_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
        reason="First denial",
    )

    second = device_manager.deny_user_code(
        user_code=session.user_code,
        approver="different-user",
        approver_surface="CLI",
        reason="Second denial",
    )

    assert first.device_code == second.device_code
    assert second.denied_reason == "First denial"  # Original reason preserved


def test_approve_denied_code_raises_error(device_manager: DeviceFlowManager) -> None:
    """Verify approving a denied code raises DeviceFlowError."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    device_manager.deny_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
    )

    with pytest.raises(DeviceFlowError, match="already denied"):
        device_manager.approve_user_code(
            user_code=session.user_code,
            approver="test-user",
            approver_surface="WEB",
        )


# ============================================================================
# Device Code Polling Tests
# ============================================================================


def test_poll_pending_device_code_returns_pending(device_manager: DeviceFlowManager) -> None:
    """Verify polling pending code returns PENDING with retry interval."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    result = device_manager.poll_device_code(session.device_code)
    assert result.status == DeviceAuthorizationStatus.PENDING
    assert result.retry_after == 1  # poll_interval configured to 1 second
    assert result.expires_in > 0
    assert result.tokens is None


def test_poll_approved_device_code_returns_tokens(device_manager: DeviceFlowManager) -> None:
    """Verify polling approved code returns tokens."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    device_manager.approve_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
    )

    result = device_manager.poll_device_code(session.device_code)
    assert result.status == DeviceAuthorizationStatus.APPROVED
    assert result.tokens is not None
    assert result.tokens.access_token.startswith("ga_")
    assert result.tokens.refresh_token.startswith("gr_")


def test_poll_denied_device_code_returns_denied(device_manager: DeviceFlowManager) -> None:
    """Verify polling denied code returns DENIED with reason."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    device_manager.deny_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
        reason="Test denial",
    )

    result = device_manager.poll_device_code(session.device_code)
    assert result.status == DeviceAuthorizationStatus.DENIED
    assert result.denied_reason == "Test denial"
    assert result.tokens is None


def test_poll_invalid_device_code_raises_error(device_manager: DeviceFlowManager) -> None:
    """Verify polling invalid device code raises DeviceCodeNotFoundError."""
    with pytest.raises(DeviceCodeNotFoundError, match="invalid-device-code not found"):
        device_manager.poll_device_code("invalid-device-code")


def test_poll_respects_rate_limiting(device_manager: DeviceFlowManager) -> None:
    """Verify rapid polling enforces retry_after backoff."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    # First poll succeeds
    result1 = device_manager.poll_device_code(session.device_code)
    assert result1.status == DeviceAuthorizationStatus.PENDING
    assert result1.retry_after == 1

    # Immediate second poll returns higher retry_after
    result2 = device_manager.poll_device_code(session.device_code)
    assert result2.retry_after == 1  # Still 1s since delta < poll_interval


# ============================================================================
# Refresh Token Tests
# ============================================================================


def test_refresh_access_token_issues_new_access_token(device_manager: DeviceFlowManager) -> None:
    """Verify refresh token can obtain new access token."""
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    device_manager.approve_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
    )

    result = device_manager.poll_device_code(session.device_code)
    original_access = result.tokens.access_token
    refresh_token = result.tokens.refresh_token

    # Refresh tokens
    refreshed = device_manager.refresh_access_token(refresh_token)
    assert refreshed.tokens is not None
    assert refreshed.tokens.access_token != original_access  # New access token
    assert refreshed.tokens.refresh_token == refresh_token  # Same refresh token


def test_refresh_invalid_token_raises_error(device_manager: DeviceFlowManager) -> None:
    """Verify refreshing invalid token raises RefreshTokenNotFoundError."""
    with pytest.raises(RefreshTokenNotFoundError, match="not recognized"):
        device_manager.refresh_access_token("invalid-refresh-token")


def test_refresh_expired_session_raises_error(device_manager: DeviceFlowManager) -> None:
    """Verify refreshing expired session raises DeviceCodeExpiredError."""
    # Create manager with 1-second TTL
    short_manager = DeviceFlowManager(
        device_code_ttl=1,
        access_token_ttl=1,
        refresh_token_ttl=1,
    )

    session = short_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    short_manager.approve_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
    )

    result = short_manager.poll_device_code(session.device_code)
    refresh_token = result.tokens.refresh_token

    # Wait for expiry
    time.sleep(2)

    with pytest.raises(RefreshTokenExpiredError, match="expired"):
        short_manager.refresh_access_token(refresh_token)


# ============================================================================
# Expiry and Cleanup Tests
# ============================================================================


def test_expired_device_code_transitions_to_expired(device_manager: DeviceFlowManager) -> None:
    """Verify expired device codes transition to EXPIRED status."""
    # Create manager with 1-second TTL
    short_manager = DeviceFlowManager(device_code_ttl=1)

    session = short_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    # Wait for expiry
    time.sleep(2)

    described = short_manager.describe_user_code(session.user_code)
    assert described.status == DeviceAuthorizationStatus.EXPIRED


def test_cleanup_expired_removes_sessions(device_manager: DeviceFlowManager) -> None:
    """Verify cleanup_expired prunes expired sessions."""
    short_manager = DeviceFlowManager(device_code_ttl=1)

    session = short_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    # Wait for expiry
    time.sleep(2)

    # Cleanup should prune the session
    short_manager.cleanup_expired()

    # Subsequent describe should still work (session marked expired but not removed)
    described = short_manager.describe_user_code(session.user_code)
    assert described.status == DeviceAuthorizationStatus.EXPIRED


# ============================================================================
# TokenStore Integration Tests
# ============================================================================


def test_token_store_saves_and_loads_bundle(token_store: FileTokenStore) -> None:
    """Verify token store persists and retrieves bundles."""
    now = datetime.now(timezone.utc)
    bundle = AuthTokenBundle(
        access_token="ga_test_access",
        refresh_token="gr_test_refresh",
        token_type="Bearer",
        scopes=["actions.read", "behaviors.read"],
        client_id="test-client",
        issued_at=now,
        expires_at=now + timedelta(seconds=3600),
        refresh_expires_at=now + timedelta(days=7),
    )

    token_store.save(bundle)
    loaded = token_store.load()

    assert loaded is not None
    assert loaded.access_token == "ga_test_access"
    assert loaded.refresh_token == "gr_test_refresh"
    assert loaded.scopes == ["actions.read", "behaviors.read"]
    assert loaded.client_id == "test-client"


def test_token_store_clears_bundle(token_store: FileTokenStore) -> None:
    """Verify token store clear removes persisted tokens."""
    now = datetime.now(timezone.utc)
    bundle = AuthTokenBundle(
        access_token="ga_test",
        refresh_token="gr_test",
        token_type="Bearer",
        scopes=["actions.read"],
        client_id="test-client",
        issued_at=now,
        expires_at=now + timedelta(seconds=3600),
        refresh_expires_at=now + timedelta(days=7),
    )

    token_store.save(bundle)
    token_store.clear()
    loaded = token_store.load()

    assert loaded is None


def test_token_store_handles_missing_file(token_store: FileTokenStore) -> None:
    """Verify loading from non-existent file returns None."""
    loaded = token_store.load()
    assert loaded is None


# ============================================================================
# End-to-End Flow Tests
# ============================================================================


def test_complete_device_flow_with_token_storage(
    device_manager: DeviceFlowManager, token_store: FileTokenStore
) -> None:
    """Verify complete device flow from start to token storage."""
    # 1. Start authorization
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read", "behaviors.read"],
        surface="CLI",
    )

    # 2. User approves via web
    device_manager.approve_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
        roles=["STRATEGIST"],
    )

    # 3. CLI polls for completion
    result = device_manager.poll_device_code(session.device_code)
    assert result.status == DeviceAuthorizationStatus.APPROVED
    assert result.tokens is not None

    # 4. CLI stores tokens
    now = datetime.now(timezone.utc)
    bundle = AuthTokenBundle(
        access_token=result.tokens.access_token,
        refresh_token=result.tokens.refresh_token,
        token_type=result.tokens.token_type,
        scopes=result.scopes,
        client_id=result.client_id,
        issued_at=now,
        expires_at=result.tokens.access_token_expires_at,
        refresh_expires_at=result.tokens.refresh_token_expires_at,
    )
    token_store.save(bundle)

    # 5. Verify stored tokens can be retrieved
    loaded = token_store.load()
    assert loaded is not None
    assert loaded.access_token == result.tokens.access_token
    assert loaded.is_access_valid()


def test_complete_device_flow_with_denial(device_manager: DeviceFlowManager) -> None:
    """Verify complete denial flow."""
    # 1. Start authorization
    session = device_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.write", "behaviors.delete"],
        surface="CLI",
    )

    # 2. User denies via web
    device_manager.deny_user_code(
        user_code=session.user_code,
        approver="test-user",
        approver_surface="WEB",
        reason="Excessive scope request",
    )

    # 3. CLI polls and receives denial
    result = device_manager.poll_device_code(session.device_code)
    assert result.status == DeviceAuthorizationStatus.DENIED
    assert result.denied_reason == "Excessive scope request"
    assert result.tokens is None


def test_complete_device_flow_with_timeout(device_manager: DeviceFlowManager) -> None:
    """Verify timeout behavior when user never approves."""
    # Create manager with 2-second TTL
    short_manager = DeviceFlowManager(device_code_ttl=2, poll_interval=1)

    session = short_manager.start_authorization(
        client_id="test-client",
        scopes=["actions.read"],
        surface="CLI",
    )

    # Poll once (pending)
    result1 = short_manager.poll_device_code(session.device_code)
    assert result1.status == DeviceAuthorizationStatus.PENDING

    # Wait for expiry
    time.sleep(3)

    # Poll again (expired)
    result2 = short_manager.poll_device_code(session.device_code)
    assert result2.status == DeviceAuthorizationStatus.EXPIRED
    assert result2.expires_in == 0
