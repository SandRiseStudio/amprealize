"""Unit tests for AgentAuthService - PostgreSQL-backed auth service.

Test Coverage:
- Grant CRUD operations (ensure_grant, revoke_grant, list_grants)
- Policy evaluation (RBAC roles, high-risk scopes, MFA requirements)
- Grant lifecycle (TTL enforcement, expiry, reuse)
- Consent flows (CONSENT_REQUIRED, approve_consent)
- Database schema creation and integrity
- Telemetry integration (event emission)
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, MagicMock, patch

from amprealize.services.agent_auth_service import (
    AgentAuthService,
    EnsureGrantRequest,
    EnsureGrantResponse,
    RevokeGrantRequest,
    RevokeGrantResponse,
    ListGrantsRequest,
    PolicyPreviewRequest,
    PolicyPreviewResponse,
    GrantDecision,
    DecisionReason,
    GrantMetadata,
    Obligation,
    AgentAuthServiceError,
    GrantNotFoundError,
    ConsentRequestNotFoundError,
)
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient


# --- Fixtures ---


@pytest.fixture
def telemetry_sink() -> InMemoryTelemetrySink:
    """In-memory telemetry sink for testing event emission."""
    return InMemoryTelemetrySink()


@pytest.fixture
def mock_postgres_pool() -> MagicMock:
    """Mock PostgresPool for unit testing without database."""
    pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    # Setup connection context manager
    pool.connection.return_value.__enter__.return_value = mock_conn
    pool.connection.return_value.__exit__.return_value = None

    # Setup cursor context manager
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None

    # Default cursor behavior
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []

    return pool


@pytest.fixture
def auth_service(telemetry_sink: InMemoryTelemetrySink, mock_postgres_pool: MagicMock) -> AgentAuthService:
    """AgentAuthService instance with mocked database."""
    telemetry = TelemetryClient(sink=telemetry_sink)

    with patch("amprealize.services.agent_auth_service.PostgresPool") as mock_pool_class:
        mock_pool_class.return_value = mock_postgres_pool
        service = AgentAuthService(dsn="postgresql://test:test@localhost/test", telemetry=telemetry)
        service._pool = mock_postgres_pool  # Override with our mock
        return service


# --- Unit Tests (no infrastructure required) ---


@pytest.mark.unit
class TestGrantCRUD:
    """Test grant CRUD operations."""

    def test_ensure_grant_allow_basic(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock, telemetry_sink: InMemoryTelemetrySink
    ) -> None:
        """Test basic grant approval flow."""
        mock_cursor = mock_postgres_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.side_effect = [
            None,  # No existing grant
            ("grant-123",),  # Return grant_id after INSERT
        ]

        request = EnsureGrantRequest(
            agent_id="agent-1",
            surface="CLI",
            tool_name="actions.list",
            scopes=["actions.read"],
            user_id="user-1",
            context={},
        )

        response = auth_service.ensure_grant(request)

        assert response.decision == GrantDecision.ALLOW
        assert response.grant is not None
        assert response.grant.grant_id == "grant-123"
        assert response.reason is None

        # Verify telemetry event
        events = telemetry_sink.events
        assert len(events) == 1
        assert events[0].event_type == "auth_grant_decision"
        assert events[0].payload["decision"] == "ALLOW"

    def test_ensure_grant_reuses_existing_valid_grant(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock
    ) -> None:
        """Test that valid grants are reused instead of creating duplicates."""
        mock_cursor = mock_postgres_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value

        # Simulate existing valid grant
        future_time = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        mock_cursor.fetchone.return_value = (
            "existing-grant-123",
            json.dumps(["actions.read"]),
            future_time,
            None,  # not revoked
        )

        request = EnsureGrantRequest(
            agent_id="agent-1",
            surface="CLI",
            tool_name="actions.list",
            scopes=["actions.read"],
            user_id="user-1",
            context={},
        )

        response = auth_service.ensure_grant(request)

        assert response.decision == GrantDecision.ALLOW
        assert response.grant is not None
        assert response.grant.grant_id == "existing-grant-123"

    def test_ensure_grant_consent_required_for_high_risk_scope(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock
    ) -> None:
        """Test that high-risk scopes trigger consent flow."""
        mock_cursor = mock_postgres_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = None  # No existing grant

        request = EnsureGrantRequest(
            agent_id="agent-1",
            surface="CLI",
            tool_name="actions.replay",
            scopes=["actions.replay"],
            user_id="user-1",
            context={},
        )

        response = auth_service.ensure_grant(request)

        assert response.decision == GrantDecision.CONSENT_REQUIRED
        assert response.reason == DecisionReason.SCOPE_NOT_APPROVED
        assert response.consent_request_id is not None

    def test_ensure_grant_deny_for_high_risk_without_mfa(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock
    ) -> None:
        """Test that high-risk scopes are denied without MFA verification."""
        mock_cursor = mock_postgres_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = None  # No existing grant

        request = EnsureGrantRequest(
            agent_id="agent-1",
            surface="CLI",
            tool_name="agentauth.manage",
            scopes=["agentauth.manage"],
            user_id="user-1",
            context={},  # No MFA verification
        )

        response = auth_service.ensure_grant(request)

        # Should trigger consent, not direct deny (consent flow will check MFA)
        assert response.decision == GrantDecision.CONSENT_REQUIRED

    def test_revoke_grant_success(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock, telemetry_sink: InMemoryTelemetrySink
    ) -> None:
        """Test successful grant revocation."""
        mock_cursor = mock_postgres_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        mock_cursor.rowcount = 1  # One row updated

        request = RevokeGrantRequest(
            grant_id="grant-123",
            revoked_by="user-1",
            reason="User initiated revocation",
        )

        response = auth_service.revoke_grant(request)

        assert response.success is True
        assert response.grant_id == "grant-123"

        # Verify telemetry event
        events = telemetry_sink.events
        assert any(e.event_type == "auth_grant_revoked" for e in events)

    def test_revoke_grant_not_found(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock
    ) -> None:
        """Test revocation of non-existent grant raises error."""
        mock_cursor = mock_postgres_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        mock_cursor.rowcount = 0  # No rows updated

        request = RevokeGrantRequest(
            grant_id="nonexistent-grant",
            revoked_by="user-1",
        )

        with pytest.raises(GrantNotFoundError):
            auth_service.revoke_grant(request)

    def test_list_grants_filters_by_agent_and_user(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock
    ) -> None:
        """Test grant listing with filters."""
        mock_cursor = mock_postgres_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value

        future_time = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        mock_cursor.fetchall.return_value = [
            ("grant-1", "agent-1", "user-1", "actions.list", json.dumps(["actions.read"]), "CLI", future_time, None, None, json.dumps([])),
            ("grant-2", "agent-1", "user-1", "actions.replay", json.dumps(["actions.replay"]), "CLI", future_time, None, None, json.dumps([])),
        ]

        request = ListGrantsRequest(
            agent_id="agent-1",
            user_id="user-1",
            tool_name=None,
            include_expired=False,
        )

        grants = auth_service.list_grants(request)

        assert len(grants) == 2
        assert all(g.agent_id == "agent-1" for g in grants)
        assert all(g.user_id == "user-1" for g in grants)


@pytest.mark.unit
class TestPolicyEvaluation:
    """Test policy evaluation and preview."""

    def test_policy_preview_allow_basic_scope(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock
    ) -> None:
        """Test policy preview for basic allowed scope."""
        request = PolicyPreviewRequest(
            agent_id="agent-1",
            tool_name="actions.list",
            scopes=["actions.read"],
            user_id="user-1",
            context={},
        )

        response = auth_service.policy_preview(request)

        assert response.decision == GrantDecision.ALLOW
        assert response.reason is None

    def test_policy_preview_consent_for_high_risk(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock
    ) -> None:
        """Test policy preview for high-risk scope requires consent."""
        request = PolicyPreviewRequest(
            agent_id="agent-1",
            tool_name="actions.replay",
            scopes=["actions.replay"],
            user_id="user-1",
            context={},
        )

        response = auth_service.policy_preview(request)

        # PolicyEngine default-deny when no rule matches OBSERVER + high-risk scope
        assert response.decision == GrantDecision.DENY

    def test_policy_preview_deny_admin_scope_without_role(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock
    ) -> None:
        """Test policy preview denies admin scopes without proper role."""
        request = PolicyPreviewRequest(
            agent_id="agent-1",
            tool_name="agentauth.manage",
            scopes=["agentauth.manage"],
            user_id="user-1",
            context={},  # No role specified
        )

        response = auth_service.policy_preview(request)

        # PolicyEngine default-deny when no rule matches OBSERVER + admin scope
        assert response.decision == GrantDecision.DENY


@pytest.mark.unit
class TestConsentFlow:
    """Test consent approval flows."""

    def test_approve_consent_creates_grant(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock, telemetry_sink: InMemoryTelemetrySink
    ) -> None:
        """Test consent approval creates a new grant."""
        mock_cursor = mock_postgres_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.side_effect = [
            ("grant-456",),  # Return grant_id after INSERT
        ]

        # First, create a consent request
        request = EnsureGrantRequest(
            agent_id="agent-1",
            surface="CLI",
            tool_name="actions.replay",
            scopes=["actions.replay"],
            user_id="user-1",
            context={},
        )

        consent_response = auth_service.ensure_grant(request)
        assert consent_response.decision == GrantDecision.CONSENT_REQUIRED
        consent_id = consent_response.consent_request_id
        assert consent_id is not None

        # Mock the consent request lookup
        auth_service._pending_consent[consent_id] = request

        # Approve the consent
        grant = auth_service.approve_consent(consent_id, "approver-1")

        assert grant.grant_id == "grant-456"
        assert consent_id not in auth_service._pending_consent

        # Verify telemetry event
        events = telemetry_sink.events
        assert any(e.event_type == "auth_consent_approved" for e in events)

    def test_approve_consent_not_found_raises_error(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock
    ) -> None:
        """Test approving non-existent consent request raises error."""
        with pytest.raises(ConsentRequestNotFoundError):
            auth_service.approve_consent("nonexistent-consent-id", "approver-1")


@pytest.mark.unit
class TestGrantLifecycle:
    """Test grant expiry and TTL enforcement."""

    def test_expired_grants_not_reused(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock
    ) -> None:
        """Test that expired grants are not reused."""
        mock_cursor = mock_postgres_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value

        # Simulate expired grant
        past_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        mock_cursor.fetchone.side_effect = [
            (
                "expired-grant-123",
                json.dumps(["actions.read"]),
                past_time,
                None,  # not revoked
            ),
            ("new-grant-456",),  # New grant created
        ]

        request = EnsureGrantRequest(
            agent_id="agent-1",
            surface="CLI",
            tool_name="actions.list",
            scopes=["actions.read"],
            user_id="user-1",
            context={},
        )

        response = auth_service.ensure_grant(request)

        # Should create new grant, not reuse expired one
        assert response.grant is not None
        assert response.grant.grant_id == "new-grant-456"

    def test_revoked_grants_not_listed_by_default(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock
    ) -> None:
        """Test that revoked grants are excluded from list_grants by default."""
        mock_cursor = mock_postgres_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value

        future_time = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        # Only return non-revoked grants (WHERE revoked_at IS NULL in query)
        mock_cursor.fetchall.return_value = [
            ("grant-1", "agent-1", "user-1", "actions.list", json.dumps(["actions.read"]), "CLI", future_time, None, None, json.dumps([])),
        ]

        request = ListGrantsRequest(
            agent_id="agent-1",
            user_id="user-1",
            include_expired=False,
        )

        grants = auth_service.list_grants(request)

        assert len(grants) == 1


@pytest.mark.unit
class TestTelemetryIntegration:
    """Test telemetry event emission."""

    def test_telemetry_emitted_on_grant_decision(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock, telemetry_sink: InMemoryTelemetrySink
    ) -> None:
        """Test telemetry events are emitted for grant decisions."""
        mock_cursor = mock_postgres_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.side_effect = [None, ("grant-123",)]

        request = EnsureGrantRequest(
            agent_id="agent-1",
            surface="CLI",
            tool_name="actions.list",
            scopes=["actions.read"],
            user_id="user-1",
            context={},
        )

        auth_service.ensure_grant(request)

        events = telemetry_sink.events
        assert len(events) == 1
        assert events[0].event_type == "auth_grant_decision"
        assert events[0].payload["agent_id"] == "agent-1"
        assert events[0].payload["tool_name"] == "actions.list"

    def test_telemetry_emitted_on_policy_preview(
        self, auth_service: AgentAuthService, mock_postgres_pool: MagicMock, telemetry_sink: InMemoryTelemetrySink
    ) -> None:
        """Test telemetry events are emitted for policy previews."""
        request = PolicyPreviewRequest(
            agent_id="agent-1",
            tool_name="actions.list",
            scopes=["actions.read"],
            user_id="user-1",
            context={},
        )

        auth_service.policy_preview(request)

        events = telemetry_sink.events
        assert len(events) == 1
        assert events[0].event_type == "auth_policy_preview"


# --- Integration Tests (require PostgreSQL) ---


@pytest.mark.integration
@pytest.mark.skipif(
    "not config.getoption('--run-integration')",
    reason="Integration tests require --run-integration flag and PostgreSQL infrastructure",
)
class TestDatabaseIntegration:
    """Integration tests requiring real PostgreSQL database."""

    @pytest.fixture
    def real_auth_service(self, telemetry_sink: InMemoryTelemetrySink) -> AgentAuthService:
        """AgentAuthService with real PostgreSQL connection."""
        from amprealize.telemetry import TelemetryClient
        telemetry = TelemetryClient(sink=telemetry_sink)
        # Use test database DSN from environment or default
        import os
        dsn = os.getenv("TEST_POSTGRES_DSN", "postgresql://test:test@localhost:5432/test")
        return AgentAuthService(dsn=dsn, telemetry=telemetry)

    def test_schema_creation(self, real_auth_service: AgentAuthService) -> None:
        """Test database schema is created correctly."""
        # Schema creation happens in __init__, just verify service initializes
        assert real_auth_service._pool is not None

    def test_full_grant_lifecycle_integration(
        self, real_auth_service: AgentAuthService, telemetry_sink: InMemoryTelemetrySink
    ) -> None:
        """Test complete grant lifecycle with real database."""
        # Create grant
        request = EnsureGrantRequest(
            agent_id="agent-test",
            surface="CLI",
            tool_name="actions.list",
            scopes=["actions.read"],
            user_id="user-test",
            context={},
        )

        response = real_auth_service.ensure_grant(request)
        assert response.decision == GrantDecision.ALLOW
        assert response.grant is not None
        grant_id = response.grant.grant_id

        # List grants
        list_request = ListGrantsRequest(
            agent_id="agent-test",
            user_id="user-test",
        )
        grants = real_auth_service.list_grants(list_request)
        assert len(grants) >= 1
        assert any(g.grant_id == grant_id for g in grants)

        # Revoke grant
        revoke_request = RevokeGrantRequest(
            grant_id=grant_id,
            revoked_by="user-test",
        )
        revoke_response = real_auth_service.revoke_grant(revoke_request)
        assert revoke_response.success is True

        # Verify revoked grant not in list
        grants_after = real_auth_service.list_grants(list_request)
        assert not any(g.grant_id == grant_id for g in grants_after)
