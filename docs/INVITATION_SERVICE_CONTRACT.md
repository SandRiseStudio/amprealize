# Invitation Service Contract

> **Epic**: 13.2.4 User Management (invite flow, role assignment)
> **Version**: 1.0.0
> **Status**: Draft
> **Date**: 2025-12-05

## Overview

The Invitation Service manages the complete lifecycle of organization invitations, from creation through acceptance or revocation. It integrates with the Notify package for multi-channel delivery and maintains a complete audit trail of all invitation events.

## Design Principles

1. **Security-First**: Cryptographically secure tokens, expiration enforcement, rate limiting
2. **Multi-Channel**: Support email, Slack, SMS, and copy-link delivery methods
3. **Audit Trail**: Complete history of invitation lifecycle events
4. **Graceful Degradation**: Invitation remains valid even if notification fails
5. **Idempotent Acceptance**: Re-accepting doesn't create duplicate memberships

## Data Models

### InvitationRequest

```python
@dataclass
class InvitationRequest:
    """Request to create an organization invitation."""
    org_id: str
    invitee_email: str
    role: MemberRole  # owner, admin, member, viewer, billing
    channel: NotificationChannel = NotificationChannel.EMAIL

    # Optional fields
    invitee_name: Optional[str] = None
    invitee_phone: Optional[str] = None  # For SMS
    invitee_slack_id: Optional[str] = None  # For Slack
    message: Optional[str] = None  # Custom message
    expires_days: int = 7  # Default expiration

    # Requester context
    invited_by: str  # user_id of inviter
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### Invitation

```python
@dataclass
class Invitation:
    """Organization invitation entity."""
    id: str
    org_id: str
    token: str  # Secure random token for URL

    # Invitee info
    invitee_email: str
    invitee_name: Optional[str]
    invitee_phone: Optional[str]
    invitee_slack_id: Optional[str]

    # Assignment
    role: MemberRole

    # Invitation details
    message: Optional[str]
    notification_channel: NotificationChannel
    status: InvitationStatus

    # Timing
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    # Actor tracking
    invited_by: str
    accepted_by: Optional[str]
    accepted_at: Optional[datetime]

    # Notification tracking
    notification_sent_at: Optional[datetime]
    notification_provider: Optional[str]
    notification_message_id: Optional[str]

    metadata: Dict[str, Any]
```

### InvitationStatus

```python
class InvitationStatus(Enum):
    PENDING = "pending"      # Awaiting acceptance
    ACCEPTED = "accepted"    # User accepted
    EXPIRED = "expired"      # Past expiration
    REVOKED = "revoked"      # Admin revoked
    DECLINED = "declined"    # User declined
```

### InvitationEvent

```python
@dataclass
class InvitationEvent:
    """Audit event for invitation lifecycle."""
    id: str
    invitation_id: str
    event_type: InvitationEventType

    actor_id: Optional[str]
    actor_type: str  # 'user', 'system', 'api'

    details: Dict[str, Any]

    # For notification events
    notification_channel: Optional[NotificationChannel]
    notification_provider: Optional[str]
    notification_success: Optional[bool]
    notification_error: Optional[str]

    # Request metadata
    ip_address: Optional[str]
    user_agent: Optional[str]

    created_at: datetime
```

### InvitationEventType

```python
class InvitationEventType(Enum):
    CREATED = "created"
    NOTIFICATION_SENT = "notification_sent"
    NOTIFICATION_FAILED = "notification_failed"
    VIEWED = "viewed"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    REVOKED = "revoked"
    RESENT = "resent"
```

## Service Interface

### InvitationService

```python
class InvitationService:
    """Service for managing organization invitations."""

    async def create_invitation(
        self,
        request: InvitationRequest,
        send_notification: bool = True,
    ) -> InvitationResult:
        """Create and optionally send an invitation.

        Args:
            request: Invitation details.
            send_notification: Whether to send notification immediately.

        Returns:
            InvitationResult with invitation and notification status.

        Raises:
            InvitationLimitExceeded: Org has reached invitation limit.
            DuplicateInvitationError: Pending invitation already exists.
            InvalidRoleError: Requested role not allowed.
        """

    async def get_invitation(
        self,
        invitation_id: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Optional[Invitation]:
        """Get invitation by ID or token.

        Args:
            invitation_id: Invitation UUID.
            token: Invitation URL token.

        Returns:
            Invitation if found, None otherwise.
        """

    async def get_invitation_by_token(
        self,
        token: str,
        include_org_details: bool = True,
    ) -> Optional[InvitationWithOrg]:
        """Get invitation by URL token with org details.

        Used by acceptance flow to display invitation page.
        Does NOT require authentication.

        Args:
            token: Invitation URL token.
            include_org_details: Whether to include org name/logo.

        Returns:
            InvitationWithOrg if valid, None if not found or expired.
        """

    async def list_invitations(
        self,
        org_id: str,
        status: Optional[InvitationStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ListInvitationsResult:
        """List invitations for an organization.

        Args:
            org_id: Organization ID.
            status: Filter by status (default: all).
            limit: Max results.
            offset: Pagination offset.

        Returns:
            ListInvitationsResult with invitations and total count.
        """

    async def accept_invitation(
        self,
        token: str,
        user_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AcceptInvitationResult:
        """Accept an invitation and join the organization.

        Args:
            token: Invitation URL token.
            user_id: ID of user accepting (must be authenticated).
            ip_address: Request IP for audit.
            user_agent: Request user agent for audit.

        Returns:
            AcceptInvitationResult with membership and org details.

        Raises:
            InvitationNotFound: Token doesn't match any invitation.
            InvitationExpired: Invitation has expired.
            InvitationAlreadyUsed: Not pending status.
            UserAlreadyMember: User is already in the org.
        """

    async def decline_invitation(
        self,
        token: str,
        user_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Decline an invitation.

        Args:
            token: Invitation URL token.
            user_id: ID of user declining.
            reason: Optional decline reason.

        Returns:
            True if declined, False if not found/already processed.
        """

    async def revoke_invitation(
        self,
        invitation_id: str,
        revoked_by: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Revoke a pending invitation (admin action).

        Args:
            invitation_id: Invitation UUID.
            revoked_by: User ID of admin revoking.
            reason: Optional revocation reason.

        Returns:
            True if revoked, False if not found/already processed.
        """

    async def resend_invitation(
        self,
        invitation_id: str,
        requested_by: str,
        channel: Optional[NotificationChannel] = None,
    ) -> NotificationResult:
        """Resend invitation notification.

        Args:
            invitation_id: Invitation UUID.
            requested_by: User ID requesting resend.
            channel: Override channel (default: use original).

        Returns:
            NotificationResult from delivery attempt.

        Raises:
            InvitationNotFound: Invitation doesn't exist.
            InvitationNotPending: Can only resend pending invitations.
            ResendLimitExceeded: Too many resends.
        """

    async def get_invitation_events(
        self,
        invitation_id: str,
        limit: int = 50,
    ) -> List[InvitationEvent]:
        """Get audit events for an invitation.

        Args:
            invitation_id: Invitation UUID.
            limit: Max events to return.

        Returns:
            List of events, most recent first.
        """

    async def expire_invitations(self) -> int:
        """Mark expired invitations (batch job).

        Called by scheduled task to update status of
        invitations past their expiration date.

        Returns:
            Count of invitations marked expired.
        """
```

## Result Types

### InvitationResult

```python
@dataclass
class InvitationResult:
    """Result of creating an invitation."""
    invitation: Invitation
    notification_sent: bool
    notification_result: Optional[NotificationResult]
    invitation_url: str  # Full URL for acceptance
```

### AcceptInvitationResult

```python
@dataclass
class AcceptInvitationResult:
    """Result of accepting an invitation."""
    success: bool
    membership_id: Optional[str]
    org_id: Optional[str]
    org_name: Optional[str]
    role: Optional[MemberRole]
    error_message: Optional[str]
```

### InvitationWithOrg

```python
@dataclass
class InvitationWithOrg:
    """Invitation with organization details for display."""
    invitation: Invitation
    org_name: str
    org_slug: str
    org_logo_url: Optional[str]
    inviter_name: Optional[str]
    inviter_email: Optional[str]
    is_expired: bool
    hours_until_expiry: Optional[float]
```

## API Endpoints

### Create Invitation

```
POST /api/v1/orgs/{org_id}/invitations
Authorization: Bearer <token>
Content-Type: application/json

{
  "invitee_email": "newuser@example.com",
  "invitee_name": "New User",
  "role": "member",
  "channel": "email",
  "message": "Welcome to our team!",
  "expires_days": 7
}

Response 201:
{
  "invitation": {
    "id": "inv_abc123",
    "token": "aBcDeFgH...",
    "status": "pending",
    "invitee_email": "newuser@example.com",
    "role": "member",
    "expires_at": "2025-12-12T00:00:00Z",
    "invitation_url": "https://app.amprealize.dev/invitations/aBcDeFgH.../accept"
  },
  "notification_sent": true,
  "notification_result": {
    "success": true,
    "channel": "email",
    "provider": "sendgrid"
  }
}
```

### Get Invitation (Public)

```
GET /api/v1/invitations/{token}

Response 200:
{
  "invitation": {
    "id": "inv_abc123",
    "status": "pending",
    "invitee_email": "newuser@example.com",
    "role": "member",
    "message": "Welcome to our team!",
    "expires_at": "2025-12-12T00:00:00Z"
  },
  "org_name": "Acme Corp",
  "org_slug": "acme-corp",
  "org_logo_url": "https://...",
  "inviter_name": "Alice Admin",
  "is_expired": false,
  "hours_until_expiry": 168.5
}

Response 404:
{
  "error": "invitation_not_found",
  "message": "Invitation not found or expired"
}
```

### Accept Invitation

```
POST /api/v1/invitations/{token}/accept
Authorization: Bearer <token>

Response 200:
{
  "success": true,
  "membership_id": "mem_xyz789",
  "org_id": "org_abc123",
  "org_name": "Acme Corp",
  "role": "member"
}

Response 400:
{
  "error": "invitation_expired",
  "message": "This invitation has expired"
}

Response 409:
{
  "error": "already_member",
  "message": "You are already a member of this organization"
}
```

### List Invitations

```
GET /api/v1/orgs/{org_id}/invitations?status=pending&limit=20
Authorization: Bearer <token>

Response 200:
{
  "invitations": [...],
  "total_count": 5,
  "limit": 20,
  "offset": 0
}
```

### Revoke Invitation

```
DELETE /api/v1/invitations/{invitation_id}
Authorization: Bearer <token>
Content-Type: application/json

{
  "reason": "User no longer joining team"
}

Response 204: (no content)

Response 404:
{
  "error": "invitation_not_found"
}
```

### Resend Invitation

```
POST /api/v1/invitations/{invitation_id}/resend
Authorization: Bearer <token>
Content-Type: application/json

{
  "channel": "slack"  // Optional: override channel
}

Response 200:
{
  "notification_sent": true,
  "channel": "slack",
  "provider": "slack_webhook"
}

Response 429:
{
  "error": "resend_limit_exceeded",
  "message": "Maximum 3 resends per invitation"
}
```

## MCP Tools

### invitations.create

```json
{
  "name": "invitations.create",
  "description": "Create an organization invitation",
  "inputSchema": {
    "type": "object",
    "properties": {
      "org_id": { "type": "string", "description": "Organization ID" },
      "invitee_email": { "type": "string", "format": "email" },
      "role": { "type": "string", "enum": ["owner", "admin", "member", "viewer", "billing"] },
      "channel": { "type": "string", "enum": ["email", "slack", "sms", "copy_link"] },
      "invitee_name": { "type": "string" },
      "message": { "type": "string" },
      "expires_days": { "type": "integer", "minimum": 1, "maximum": 30 },
      "send_notification": { "type": "boolean", "default": true }
    },
    "required": ["org_id", "invitee_email", "role"]
  }
}
```

### invitations.list

```json
{
  "name": "invitations.list",
  "description": "List invitations for an organization",
  "inputSchema": {
    "type": "object",
    "properties": {
      "org_id": { "type": "string" },
      "status": { "type": "string", "enum": ["pending", "accepted", "expired", "revoked", "declined"] },
      "limit": { "type": "integer", "default": 50 },
      "offset": { "type": "integer", "default": 0 }
    },
    "required": ["org_id"]
  }
}
```

### invitations.get

```json
{
  "name": "invitations.get",
  "description": "Get invitation details by ID or token",
  "inputSchema": {
    "type": "object",
    "properties": {
      "invitation_id": { "type": "string" },
      "token": { "type": "string" }
    }
  }
}
```

### invitations.revoke

```json
{
  "name": "invitations.revoke",
  "description": "Revoke a pending invitation",
  "inputSchema": {
    "type": "object",
    "properties": {
      "invitation_id": { "type": "string" },
      "reason": { "type": "string" }
    },
    "required": ["invitation_id"]
  }
}
```

### invitations.resend

```json
{
  "name": "invitations.resend",
  "description": "Resend invitation notification",
  "inputSchema": {
    "type": "object",
    "properties": {
      "invitation_id": { "type": "string" },
      "channel": { "type": "string", "enum": ["email", "slack", "sms"] }
    },
    "required": ["invitation_id"]
  }
}
```

## Security Considerations

### Token Generation

- 32 bytes of cryptographically secure random data
- Base64url encoded (URL-safe)
- Single-use: tokens are invalidated after acceptance
- Not guessable: ~10^77 possible values

### Rate Limiting

| Action | Limit | Window |
|--------|-------|--------|
| Create invitation | 10/org | 1 hour |
| Resend invitation | 3/invitation | 24 hours |
| Accept attempts | 5/token | 15 minutes |
| View invitation page | 20/IP | 1 minute |

### Permission Requirements

| Action | Required Role |
|--------|---------------|
| Create invitation | admin, owner |
| List invitations | admin, owner |
| Revoke invitation | admin, owner |
| Resend invitation | admin, owner |
| Accept invitation | authenticated user |
| View invitation | none (public) |

### Audit Requirements

All invitation actions must be recorded with:
- Actor ID and type
- Timestamp
- IP address (when available)
- User agent (when available)
- Action-specific details

## Notification Templates

The service uses the Notify package with these templates:

### org_invitation (Email)

```
Subject: You've been invited to join {{ org_name }} on Amprealize

{{ inviter_name }} has invited you to join {{ org_name }} as a {{ role }}.

{% if message %}
Personal message:
"{{ message }}"
{% endif %}

Accept your invitation: {{ invitation_url }}

This invitation expires {{ expires_at | humanize_time }}.

If you didn't expect this invitation, you can safely ignore this email.
```

### org_invitation (Slack)

```
🎉 *Organization Invitation*

{{ inviter_name }} has invited you to join *{{ org_name }}* as a *{{ role }}*.

{% if message %}
> {{ message }}
{% endif %}

<{{ invitation_url }}|Accept Invitation>

_This invitation expires {{ expires_at | humanize_time }}._
```

## Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `invitation_not_found` | 404 | Token/ID doesn't match any invitation |
| `invitation_expired` | 400 | Invitation past expiration date |
| `invitation_revoked` | 400 | Invitation was revoked by admin |
| `invitation_already_used` | 400 | Invitation already accepted/declined |
| `already_member` | 409 | User already in organization |
| `duplicate_invitation` | 409 | Pending invitation exists for email |
| `invitation_limit_exceeded` | 429 | Org hit invitation rate limit |
| `resend_limit_exceeded` | 429 | Max resends for this invitation |
| `invalid_role` | 400 | Requested role not allowed |
| `insufficient_permissions` | 403 | User can't create/manage invitations |

## Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `invitations.created` | Counter | Total invitations created |
| `invitations.accepted` | Counter | Total invitations accepted |
| `invitations.expired` | Counter | Total invitations expired |
| `invitations.revoked` | Counter | Total invitations revoked |
| `invitations.declined` | Counter | Total invitations declined |
| `invitations.notification_sent` | Counter | Notifications sent by channel |
| `invitations.notification_failed` | Counter | Notification failures by channel |
| `invitations.acceptance_time_seconds` | Histogram | Time from create to accept |

## Related Documents

- [Organization Service Contract](./ORGANIZATION_SERVICE_CONTRACT.md)
- [Notify Package](./packages/notify/README.md)
- [Migration 026](./schema/migrations/026_user_management_invitations.sql)
- [MCP Server Design](./MCP_SERVER_DESIGN.md)
