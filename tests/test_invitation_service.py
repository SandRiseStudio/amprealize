"""Unit tests for InvitationService CRUD operations.

Tests invitation creation, acceptance, revocation, and listing.

Following behavior_design_test_strategy (Student):
- Unit tests with mocks for database layer
- Tests for happy path and error cases
- 70% unit coverage target
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call
from typing import List, Dict, Any, Optional

from amprealize.multi_tenant.invitation_service import InvitationService

# Mark all tests in this module as unit tests; skip entirely if enterprise not installed
pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(InvitationService is None, reason="InvitationService requires amprealize-enterprise"),
]

# Import contracts
from amprealize.multi_tenant.contracts import (
    Invitation,
    InvitationStatus,
    InvitationChannel,
    InvitationEvent,
    InvitationWithOrg,
    InvitationListResponse,
    CreateInvitationRequest,
    OrgMembership,
    MemberRole,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_pool():
    """Create mock PostgreSQL connection pool with proper context manager."""
    pool = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()

    # Setup cursor() to return the mock cursor
    connection.cursor.return_value = cursor

    # Setup pool.connection() context manager
    connection_ctx = MagicMock()
    connection_ctx.__enter__ = MagicMock(return_value=connection)
    connection_ctx.__exit__ = MagicMock(return_value=False)
    pool.connection.return_value = connection_ctx

    return pool, connection, cursor


@pytest.fixture
def invite_service(mock_pool):
    """Create InvitationService with mocked pool."""
    pool, connection, cursor = mock_pool

    from amprealize.multi_tenant.invitation_service import InvitationService

    # Create service with mock pool directly
    service = InvitationService(pool=pool)

    return service, cursor


@pytest.fixture
def sample_invitation_row() -> tuple:
    """Sample invitation data as returned by database (tuple format).

    Column order matches: id, org_id, email, role, status, token, channel,
    invited_by, expires_at, accepted_at, accepted_by, message, metadata,
    created_at, updated_at
    """
    return (
        "inv-abc123",                                            # id
        "org-xyz789",                                            # org_id
        "user@example.com",                                      # email
        "member",                                                # role
        "pending",                                               # status
        "token123abc",                                           # token
        "email",                                                 # channel
        "user-inviter",                                          # invited_by
        datetime(2024, 1, 15, tzinfo=timezone.utc),             # expires_at
        None,                                                    # accepted_at
        None,                                                    # accepted_by
        "Welcome to the team!",                                  # message
        {},                                                      # metadata
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # created_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # updated_at
    )


# =============================================================================
# Creation Tests
# =============================================================================

class TestCreateInvitation:
    """Tests for invitation creation."""

    def test_create_invitation_success(self, invite_service, sample_invitation_row):
        """Test successful invitation creation."""
        service, cursor = invite_service

        # Setup: No existing member, no pending invitation
        cursor.fetchone.side_effect = [
            None,  # No existing member
            None,  # No pending invitation
        ]

        request = CreateInvitationRequest(
            email="newuser@example.com",
            role=MemberRole.MEMBER,
            channel=InvitationChannel.EMAIL,
            message="Welcome!",
        )

        # Execute
        invitation = service.create_invitation(
            org_id="org-123",
            request=request,
            invited_by="user-456",
            send=False,  # Don't try to send
        )

        # Verify
        assert invitation.org_id == "org-123"
        assert invitation.email == "newuser@example.com"
        assert invitation.role == MemberRole.MEMBER
        assert invitation.status == InvitationStatus.PENDING
        assert invitation.channel == InvitationChannel.EMAIL
        assert invitation.invited_by == "user-456"
        assert invitation.message == "Welcome!"
        assert invitation.token is not None
        assert len(invitation.token) > 20  # Token should be substantial

    def test_create_invitation_already_member(self, invite_service):
        """Test creating invitation for existing member raises error."""
        service, cursor = invite_service

        # Setup: User is already a member
        cursor.fetchone.return_value = (1,)  # Member exists

        request = CreateInvitationRequest(
            email="existing@example.com",
            role=MemberRole.MEMBER,
        )

        # Execute and verify
        with pytest.raises(ValueError, match="already a member"):
            service.create_invitation(
                org_id="org-123",
                request=request,
                invited_by="user-456",
                send=False,
            )

    def test_create_invitation_pending_exists(self, invite_service):
        """Test creating invitation when pending one already exists."""
        service, cursor = invite_service

        # Setup: Not a member, but pending invitation exists
        cursor.fetchone.side_effect = [
            None,  # Not a member
            ("inv-existing",),  # Pending invitation exists
        ]

        request = CreateInvitationRequest(
            email="pending@example.com",
            role=MemberRole.MEMBER,
        )

        # Execute and verify
        with pytest.raises(ValueError, match="Pending invitation already exists"):
            service.create_invitation(
                org_id="org-123",
                request=request,
                invited_by="user-456",
                send=False,
            )

    def test_create_invitation_custom_expiration(self, invite_service):
        """Test invitation with custom expiration days."""
        service, cursor = invite_service

        # Setup: No existing member or pending invitation
        cursor.fetchone.side_effect = [None, None]

        request = CreateInvitationRequest(
            email="newuser@example.com",
            role=MemberRole.ADMIN,
            expires_in_days=14,
        )

        # Execute
        invitation = service.create_invitation(
            org_id="org-123",
            request=request,
            invited_by="user-456",
            send=False,
        )

        # Verify expiration is approximately 14 days from now
        expected_expiry = datetime.now(timezone.utc) + timedelta(days=14)
        assert abs((invitation.expires_at - expected_expiry).total_seconds()) < 5


# =============================================================================
# Get/List Tests
# =============================================================================

class TestGetInvitation:
    """Tests for retrieving invitations."""

    def test_get_invitation_by_id(self, invite_service, sample_invitation_row):
        """Test getting invitation by ID."""
        service, cursor = invite_service

        cursor.fetchone.return_value = sample_invitation_row

        invitation = service.get_invitation("inv-abc123")

        assert invitation is not None
        assert invitation.id == "inv-abc123"
        assert invitation.email == "user@example.com"
        assert invitation.status == InvitationStatus.PENDING

    def test_get_invitation_not_found(self, invite_service):
        """Test getting non-existent invitation."""
        service, cursor = invite_service

        cursor.fetchone.return_value = None

        invitation = service.get_invitation("inv-nonexistent")

        assert invitation is None

    def test_get_invitation_by_token(self, invite_service, sample_invitation_row):
        """Test getting invitation by token with org details."""
        service, cursor = invite_service

        # Add org details to the row
        row_with_org = sample_invitation_row + (
            "Acme Corp",       # org name
            "acme",           # org slug
            "John Doe",       # inviter name
        )
        cursor.fetchone.return_value = row_with_org

        result = service.get_invitation_by_token("token123abc")

        assert result is not None
        assert result.invitation.token == "token123abc"
        assert result.org_name == "Acme Corp"
        assert result.org_slug == "acme"
        assert result.inviter_name == "John Doe"


class TestListInvitations:
    """Tests for listing invitations."""

    def test_list_org_invitations(self, invite_service, sample_invitation_row):
        """Test listing all invitations for an org."""
        service, cursor = invite_service

        # Setup: Total count, pending count, then rows
        cursor.fetchone.side_effect = [
            (5,),  # Total count
            (3,),  # Pending count
        ]
        cursor.fetchall.return_value = [
            sample_invitation_row,
            sample_invitation_row,  # Two invitations
        ]

        result = service.list_org_invitations(org_id="org-123")

        assert result.total == 5
        assert result.pending_count == 3
        assert len(result.invitations) == 2

    def test_list_org_invitations_with_status_filter(self, invite_service, sample_invitation_row):
        """Test listing invitations filtered by status."""
        service, cursor = invite_service

        cursor.fetchone.side_effect = [
            (2,),  # Total count
            (0,),  # Pending count (0 since we're filtering by accepted)
        ]
        cursor.fetchall.return_value = []

        result = service.list_org_invitations(
            org_id="org-123",
            status=InvitationStatus.ACCEPTED,
        )

        assert result.total == 2


# =============================================================================
# Acceptance Tests
# =============================================================================

class TestAcceptInvitation:
    """Tests for invitation acceptance."""

    def test_accept_invitation_success(self, invite_service):
        """Test successful invitation acceptance."""
        service, cursor = invite_service

        # Future expiration
        future_expiry = datetime.now(timezone.utc) + timedelta(days=5)

        # Setup: Get invitation, get user email, no existing membership
        cursor.fetchone.side_effect = [
            ("inv-abc", "org-123", "user@example.com", "member", "pending", future_expiry),  # Invitation
            ("user@example.com",),  # User email matches
            None,  # Not already a member
        ]

        membership = service.accept_invitation(
            token="token123",
            user_id="user-789",
        )

        assert membership is not None
        assert membership.org_id == "org-123"
        assert membership.user_id == "user-789"
        assert membership.role == MemberRole.MEMBER

    def test_accept_invitation_invalid_token(self, invite_service):
        """Test accepting with invalid token."""
        service, cursor = invite_service

        cursor.fetchone.return_value = None

        with pytest.raises(ValueError, match="Invalid invitation token"):
            service.accept_invitation(
                token="invalid-token",
                user_id="user-789",
            )

    def test_accept_invitation_expired(self, invite_service):
        """Test accepting expired invitation."""
        service, cursor = invite_service

        # Past expiration
        past_expiry = datetime.now(timezone.utc) - timedelta(days=1)

        cursor.fetchone.side_effect = [
            ("inv-abc", "org-123", "user@example.com", "member", "pending", past_expiry),
            None,  # For UPDATE returning
        ]

        with pytest.raises(ValueError, match="expired"):
            service.accept_invitation(
                token="token123",
                user_id="user-789",
            )

    def test_accept_invitation_email_mismatch(self, invite_service):
        """Test accepting when user email doesn't match."""
        service, cursor = invite_service

        future_expiry = datetime.now(timezone.utc) + timedelta(days=5)

        cursor.fetchone.side_effect = [
            ("inv-abc", "org-123", "invited@example.com", "member", "pending", future_expiry),
            ("different@example.com",),  # User has different email
        ]

        with pytest.raises(ValueError, match="does not match"):
            service.accept_invitation(
                token="token123",
                user_id="user-789",
            )

    def test_accept_invitation_already_member(self, invite_service):
        """Test accepting when user is already a member."""
        service, cursor = invite_service

        future_expiry = datetime.now(timezone.utc) + timedelta(days=5)

        cursor.fetchone.side_effect = [
            ("inv-abc", "org-123", "user@example.com", "member", "pending", future_expiry),
            ("user@example.com",),  # Email matches
            (1,),  # Already a member
        ]

        with pytest.raises(ValueError, match="already a member"):
            service.accept_invitation(
                token="token123",
                user_id="user-789",
            )


# =============================================================================
# Management Tests
# =============================================================================

class TestRevokeInvitation:
    """Tests for invitation revocation."""

    def test_revoke_invitation_success(self, invite_service):
        """Test successful revocation."""
        service, cursor = invite_service

        cursor.fetchone.return_value = ("inv-abc",)  # Revoked successfully

        result = service.revoke_invitation(
            invitation_id="inv-abc",
            revoked_by="user-admin",
        )

        assert result is True

    def test_revoke_invitation_not_found(self, invite_service):
        """Test revoking non-existent invitation."""
        service, cursor = invite_service

        cursor.fetchone.return_value = None

        result = service.revoke_invitation(
            invitation_id="inv-nonexistent",
            revoked_by="user-admin",
        )

        assert result is False


class TestExpireInvitations:
    """Tests for automatic expiration."""

    def test_expire_invitations(self, invite_service):
        """Test batch expiration of past-due invitations."""
        service, cursor = invite_service

        cursor.fetchall.return_value = [
            ("inv-1",),
            ("inv-2",),
            ("inv-3",),
        ]

        count = service.expire_invitations()

        assert count == 3


class TestGetInvitationLink:
    """Tests for getting invitation links."""

    def test_get_invitation_link_success(self, invite_service):
        """Test getting link for valid invitation."""
        service, cursor = invite_service

        cursor.fetchone.return_value = ("token123abc",)

        link = service.get_invitation_link("inv-abc")

        assert link is not None
        assert "token123abc" in link
        assert "/accept" in link

    def test_get_invitation_link_not_found(self, invite_service):
        """Test getting link for non-existent invitation."""
        service, cursor = invite_service

        cursor.fetchone.return_value = None

        link = service.get_invitation_link("inv-nonexistent")

        assert link is None


# =============================================================================
# Event Tracking Tests
# =============================================================================

class TestInvitationEvents:
    """Tests for invitation event tracking."""

    def test_get_invitation_events(self, invite_service):
        """Test retrieving invitation events."""
        service, cursor = invite_service

        cursor.fetchall.return_value = [
            ("iev-1", "inv-abc", "created", "user-123", {}, datetime(2024, 1, 1, tzinfo=timezone.utc)),
            ("iev-2", "inv-abc", "sent", "user-123", {"channel": "email"}, datetime(2024, 1, 1, 0, 0, 1, tzinfo=timezone.utc)),
        ]

        events = service.get_invitation_events("inv-abc")

        assert len(events) == 2
        assert events[0].event_type == "created"
        assert events[1].event_type == "sent"


# =============================================================================
# Token Generation Tests
# =============================================================================

class TestTokenGeneration:
    """Tests for secure token generation."""

    def test_token_uniqueness(self, invite_service):
        """Test that generated tokens are unique."""
        service, _ = invite_service

        tokens = {service._generate_token() for _ in range(100)}

        # All 100 tokens should be unique
        assert len(tokens) == 100

    def test_token_length(self, invite_service):
        """Test that tokens are sufficiently long."""
        service, _ = invite_service

        token = service._generate_token()

        # URL-safe base64 of 48 bytes = 64 characters
        assert len(token) >= 60

    def test_accept_url_format(self, invite_service):
        """Test accept URL generation."""
        service, _ = invite_service

        url = service._get_accept_url("test-token-123")

        assert url == "https://amprealize.dev/invitations/test-token-123/accept"
