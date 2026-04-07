"""PostgreSQL-backed device flow storage.

This module provides a PostgreSQL storage backend for device authorization sessions,
enabling shared state between MCP server, REST API, and CLI surfaces.

Key features:
- All surfaces share the same pending device codes
- Tokens are stored persistently for session recovery
- Automatic cleanup of expired sessions

Following behavior_align_storage_layers (Student).
"""

from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from amprealize.storage.postgres_pool import PostgresPool

logger = logging.getLogger(__name__)


@dataclass
class DeviceSession:
    """Represents a device authorization session."""

    device_code: str
    user_code: str
    client_id: str
    scopes: List[str]
    status: str  # PENDING, APPROVED, DENIED, EXPIRED
    surface: str
    poll_interval: int
    created_at: datetime
    expires_at: datetime

    # Set on approval
    approver: Optional[str] = None
    approver_surface: Optional[str] = None
    approved_at: Optional[datetime] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    access_token_expires_at: Optional[datetime] = None
    refresh_token_expires_at: Optional[datetime] = None

    # Set on denial
    denial_reason: Optional[str] = None

    # OAuth provider info (for real OAuth flows)
    oauth_user_id: Optional[str] = None
    oauth_username: Optional[str] = None
    oauth_email: Optional[str] = None
    oauth_display_name: Optional[str] = None
    oauth_avatar_url: Optional[str] = None
    oauth_provider: Optional[str] = None

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "device_code": self.device_code,
            "user_code": self.user_code,
            "client_id": self.client_id,
            "scopes": self.scopes,
            "status": self.status,
            "surface": self.surface,
            "poll_interval": self.poll_interval,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "approver": self.approver,
            "approver_surface": self.approver_surface,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_token_expires_at": self.access_token_expires_at.isoformat() if self.access_token_expires_at else None,
            "refresh_token_expires_at": self.refresh_token_expires_at.isoformat() if self.refresh_token_expires_at else None,
            "denial_reason": self.denial_reason,
            "oauth_user_id": self.oauth_user_id,
            "oauth_username": self.oauth_username,
            "oauth_email": self.oauth_email,
            "oauth_display_name": self.oauth_display_name,
            "oauth_avatar_url": self.oauth_avatar_url,
            "oauth_provider": self.oauth_provider,
            "metadata": self.metadata,
        }


class DeviceFlowStore(Protocol):
    """Protocol for device flow storage backends."""

    def create_session(
        self,
        *,
        client_id: str,
        scopes: List[str],
        surface: str,
        metadata: Optional[Dict[str, Any]] = None,
        device_code_ttl: int = 600,
        poll_interval: int = 5,
    ) -> DeviceSession:
        """Create a new device authorization session."""
        ...

    def get_by_device_code(self, device_code: str) -> Optional[DeviceSession]:
        """Get session by device code."""
        ...

    def get_by_user_code(self, user_code: str) -> Optional[DeviceSession]:
        """Get session by user code."""
        ...

    def get_by_access_token(self, access_token: str) -> Optional[DeviceSession]:
        """Get session by access token."""
        ...

    def approve(
        self,
        device_code: str,
        *,
        approver: str,
        approver_surface: str,
        access_token_ttl: int = 3600,
        refresh_token_ttl: int = 604800,
    ) -> Optional[DeviceSession]:
        """Approve a pending session and generate tokens."""
        ...

    def deny(
        self,
        device_code: str,
        *,
        approver: str,
        approver_surface: str,
        reason: Optional[str] = None,
    ) -> Optional[DeviceSession]:
        """Deny a pending session."""
        ...

    def cleanup_expired(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        ...


class PostgresDeviceFlowStore:
    """PostgreSQL-backed device flow storage.

    Stores device authorization sessions in auth.device_sessions table,
    enabling shared state across MCP, REST API, and CLI surfaces.
    """

    USER_CODE_ALPHABET = string.ascii_uppercase + string.digits
    USER_CODE_LENGTH = 8  # Format: XXXX-XXXX

    def __init__(self, pool: "PostgresPool") -> None:
        self._pool = pool

    def _generate_device_code(self) -> str:
        """Generate a cryptographically secure device code."""
        return secrets.token_urlsafe(32)

    def _generate_user_code(self) -> str:
        """Generate a human-readable user code (e.g., ABCD-EFGH)."""
        code = "".join(secrets.choice(self.USER_CODE_ALPHABET) for _ in range(self.USER_CODE_LENGTH))
        # Insert hyphen for readability
        return f"{code[:4]}-{code[4:]}"

    def _generate_token(self, prefix: str) -> str:
        """Generate a token with prefix (ga_ for access, gr_ for refresh)."""
        import uuid
        return f"{prefix}{uuid.uuid4()}"

    def create_session(
        self,
        *,
        client_id: str,
        scopes: List[str],
        surface: str,
        metadata: Optional[Dict[str, Any]] = None,
        device_code_ttl: int = 600,
        poll_interval: int = 5,
    ) -> DeviceSession:
        """Create a new device authorization session in PostgreSQL."""
        import json

        device_code = self._generate_device_code()
        user_code = self._generate_user_code()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=device_code_ttl)

        session = DeviceSession(
            device_code=device_code,
            user_code=user_code,
            client_id=client_id,
            scopes=scopes,
            status="PENDING",
            surface=surface,
            poll_interval=poll_interval,
            created_at=now,
            expires_at=expires_at,
            metadata=metadata or {},
        )

        def _execute(conn) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth.device_sessions (
                        device_code, user_code, client_id, scopes, status,
                        surface, poll_interval, metadata, created_at, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        device_code,
                        user_code,
                        client_id,
                        json.dumps(scopes),
                        "PENDING",
                        surface,
                        poll_interval,
                        json.dumps(metadata or {}),
                        now,
                        expires_at,
                    ),
                )

        self._pool.run_transaction(
            operation="device_session.create",
            service_prefix="auth",
            actor=None,
            metadata={"client_id": client_id, "surface": surface},
            executor=_execute,
            telemetry=None,
        )

        logger.info(f"Created device session: user_code={user_code}, client_id={client_id}, surface={surface}")
        return session

    def get_by_device_code(self, device_code: str) -> Optional[DeviceSession]:
        """Get session by device code from PostgreSQL."""
        return self._get_session("device_code", device_code)

    def get_by_user_code(self, user_code: str) -> Optional[DeviceSession]:
        """Get session by user code from PostgreSQL."""
        # Normalize user code (remove hyphen, uppercase)
        normalized = user_code.replace("-", "").upper()
        if len(normalized) == 8:
            normalized = f"{normalized[:4]}-{normalized[4:]}"
        return self._get_session("user_code", normalized)

    def get_by_access_token(self, access_token: str) -> Optional[DeviceSession]:
        """Get session by access token from PostgreSQL."""
        return self._get_session("access_token", access_token)

    def get_by_refresh_token(self, refresh_token: str) -> Optional[DeviceSession]:
        """Get session by refresh token from PostgreSQL."""
        return self._get_session("refresh_token", refresh_token)

    def _get_session(self, field: str, value: str) -> Optional[DeviceSession]:
        """Generic session lookup by field."""
        import json

        result: Optional[DeviceSession] = None

        def _execute(conn) -> None:
            nonlocal result
            with conn.cursor() as cur:
                # Use parameterized field name via format (safe since field is internal)
                cur.execute(
                    f"""
                    SELECT device_code, user_code, client_id, scopes, status,
                           surface, poll_interval, metadata, created_at, expires_at,
                           approver, approver_surface, approved_at,
                           access_token, refresh_token,
                           access_token_expires_at, refresh_token_expires_at,
                           denial_reason,
                           oauth_user_id, oauth_username, oauth_email,
                           oauth_display_name, oauth_avatar_url, oauth_provider
                    FROM auth.device_sessions
                    WHERE {field} = %s
                    """,
                    (value,),
                )
                row = cur.fetchone()
                if row:
                    scopes = row[3] if isinstance(row[3], list) else json.loads(row[3] or "[]")
                    metadata = row[7] if isinstance(row[7], dict) else json.loads(row[7] or "{}")

                    result = DeviceSession(
                        device_code=row[0],
                        user_code=row[1],
                        client_id=row[2],
                        scopes=scopes,
                        status=row[4],
                        surface=row[5],
                        poll_interval=row[6],
                        metadata=metadata,
                        created_at=row[8],
                        expires_at=row[9],
                        approver=row[10],
                        approver_surface=row[11],
                        approved_at=row[12],
                        access_token=row[13],
                        refresh_token=row[14],
                        access_token_expires_at=row[15],
                        refresh_token_expires_at=row[16],
                        denial_reason=row[17],
                        oauth_user_id=row[18],
                        oauth_username=row[19],
                        oauth_email=row[20],
                        oauth_display_name=row[21],
                        oauth_avatar_url=row[22],
                        oauth_provider=row[23],
                    )

                    # Update status if expired
                    if result.status == "PENDING" and result.is_expired:
                        result.status = "EXPIRED"

        try:
            self._pool.run_transaction(
                operation="device_session.get",
                service_prefix="auth",
                actor=None,
                metadata={field: value},
                executor=_execute,
                telemetry=None,
            )
        except Exception as e:
            logger.warning(f"Failed to get device session by {field}: {e}")
            return None

        return result

    def approve(
        self,
        device_code: str,
        *,
        approver: str,
        approver_surface: str,
        access_token_ttl: int = 3600,
        refresh_token_ttl: int = 604800,
    ) -> Optional[DeviceSession]:
        """Approve a pending session and generate tokens."""
        session = self.get_by_device_code(device_code)
        if not session:
            return None

        if session.status != "PENDING":
            logger.warning(f"Cannot approve session in status {session.status}")
            return None

        if session.is_expired:
            logger.warning(f"Cannot approve expired session")
            return None

        now = datetime.now(timezone.utc)
        access_token = self._generate_token("ga_")
        refresh_token = self._generate_token("gr_")
        access_expires = now + timedelta(seconds=access_token_ttl)
        refresh_expires = now + timedelta(seconds=refresh_token_ttl)

        def _execute(conn) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth.device_sessions
                    SET status = 'APPROVED',
                        approver = %s,
                        approver_surface = %s,
                        approved_at = %s,
                        access_token = %s,
                        refresh_token = %s,
                        access_token_expires_at = %s,
                        refresh_token_expires_at = %s,
                        oauth_email = COALESCE(oauth_email, %s),
                        oauth_user_id = COALESCE(oauth_user_id, %s)
                    WHERE device_code = %s AND status = 'PENDING'
                    """,
                    (
                        approver,
                        approver_surface,
                        now,
                        access_token,
                        refresh_token,
                        access_expires,
                        refresh_expires,
                        approver,
                        approver,
                        device_code,
                    ),
                )

        self._pool.run_transaction(
            operation="device_session.approve",
            service_prefix="auth",
            actor=approver,
            metadata={"device_code": device_code},
            executor=_execute,
            telemetry=None,
        )

        # Update session object
        session.status = "APPROVED"
        session.approver = approver
        session.approver_surface = approver_surface
        session.approved_at = now
        session.access_token = access_token
        session.refresh_token = refresh_token
        session.access_token_expires_at = access_expires
        session.refresh_token_expires_at = refresh_expires
        if not session.oauth_email:
            session.oauth_email = approver
        if not session.oauth_user_id:
            session.oauth_user_id = approver

        logger.info(f"Approved device session: user_code={session.user_code}, approver={approver}")
        return session

    def approve_by_user_code(
        self,
        user_code: str,
        *,
        approver: str,
        approver_surface: str,
        access_token_ttl: int = 3600,
        refresh_token_ttl: int = 604800,
    ) -> Optional[DeviceSession]:
        """Approve a session by user code."""
        session = self.get_by_user_code(user_code)
        if not session:
            return None
        return self.approve(
            session.device_code,
            approver=approver,
            approver_surface=approver_surface,
            access_token_ttl=access_token_ttl,
            refresh_token_ttl=refresh_token_ttl,
        )

    def deny(
        self,
        device_code: str,
        *,
        approver: str,
        approver_surface: str,
        reason: Optional[str] = None,
    ) -> Optional[DeviceSession]:
        """Deny a pending session."""
        session = self.get_by_device_code(device_code)
        if not session:
            return None

        if session.status != "PENDING":
            return None

        def _execute(conn) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth.device_sessions
                    SET status = 'DENIED',
                        approver = %s,
                        approver_surface = %s,
                        denial_reason = %s
                    WHERE device_code = %s AND status = 'PENDING'
                    """,
                    (approver, approver_surface, reason, device_code),
                )

        self._pool.run_transaction(
            operation="device_session.deny",
            service_prefix="auth",
            actor=approver,
            metadata={"device_code": device_code},
            executor=_execute,
            telemetry=None,
        )

        session.status = "DENIED"
        session.approver = approver
        session.approver_surface = approver_surface
        session.denial_reason = reason

        logger.info(f"Denied device session: user_code={session.user_code}, approver={approver}")
        return session

    def deny_by_user_code(
        self,
        user_code: str,
        *,
        approver: str,
        approver_surface: str,
        reason: Optional[str] = None,
    ) -> Optional[DeviceSession]:
        """Deny a session by user code."""
        session = self.get_by_user_code(user_code)
        if not session:
            return None
        return self.deny(
            session.device_code,
            approver=approver,
            approver_surface=approver_surface,
            reason=reason,
        )

    def update_oauth_identity(
        self,
        device_code: str,
        *,
        oauth_user_id: Optional[str] = None,
        oauth_username: Optional[str] = None,
        oauth_email: Optional[str] = None,
        oauth_display_name: Optional[str] = None,
        oauth_avatar_url: Optional[str] = None,
        oauth_provider: Optional[str] = None,
    ) -> Optional[DeviceSession]:
        """Update OAuth identity fields on an approved session.

        Used to populate user identity after approval, e.g. for service
        principals or when the approver's identity is resolved from
        auth.users.
        """
        session = self.get_by_device_code(device_code)
        if not session:
            return None

        def _execute(conn) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth.device_sessions
                    SET oauth_user_id = COALESCE(%s, oauth_user_id),
                        oauth_username = COALESCE(%s, oauth_username),
                        oauth_email = COALESCE(%s, oauth_email),
                        oauth_display_name = COALESCE(%s, oauth_display_name),
                        oauth_avatar_url = COALESCE(%s, oauth_avatar_url),
                        oauth_provider = COALESCE(%s, oauth_provider)
                    WHERE device_code = %s
                    """,
                    (
                        oauth_user_id,
                        oauth_username,
                        oauth_email,
                        oauth_display_name,
                        oauth_avatar_url,
                        oauth_provider,
                        device_code,
                    ),
                )

        self._pool.run_transaction(
            operation="device_session.update_oauth_identity",
            service_prefix="auth",
            actor=oauth_user_id,
            metadata={"device_code": device_code},
            executor=_execute,
            telemetry=None,
        )

        # Update session object
        if oauth_user_id:
            session.oauth_user_id = oauth_user_id
        if oauth_username:
            session.oauth_username = oauth_username
        if oauth_email:
            session.oauth_email = oauth_email
        if oauth_display_name:
            session.oauth_display_name = oauth_display_name
        if oauth_avatar_url:
            session.oauth_avatar_url = oauth_avatar_url
        if oauth_provider:
            session.oauth_provider = oauth_provider

        logger.info(f"Updated OAuth identity for device session: device_code={device_code}, oauth_user_id={oauth_user_id}")
        return session

    def cleanup_expired(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        count = 0
        now = datetime.now(timezone.utc)

        def _execute(conn) -> None:
            nonlocal count
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM auth.device_sessions
                    WHERE expires_at < %s
                    RETURNING device_code
                    """,
                    (now,),
                )
                count = cur.rowcount

        self._pool.run_transaction(
            operation="device_session.cleanup",
            service_prefix="auth",
            actor=None,
            metadata={},
            executor=_execute,
            telemetry=None,
        )

        if count > 0:
            logger.info(f"Cleaned up {count} expired device sessions")

        return count

    def refresh_access_token(
        self,
        refresh_token: str,
        *,
        access_token_ttl: int = 3600,
    ) -> Optional[DeviceSession]:
        """Refresh an access token using a valid refresh token.

        Generates a new access token while keeping the same refresh token.
        Returns the updated session with new tokens, or None if refresh token
        is invalid or expired.

        Args:
            refresh_token: The refresh token to use
            access_token_ttl: TTL for the new access token in seconds (default: 1 hour)

        Returns:
            Updated DeviceSession with new access token, or None if invalid/expired
        """
        session = self.get_by_refresh_token(refresh_token)
        if not session:
            logger.warning(f"Refresh token not found in database")
            return None

        if session.status != "APPROVED":
            logger.warning(f"Cannot refresh token for session in status {session.status}")
            return None

        now = datetime.now(timezone.utc)

        # Check refresh token expiry
        if session.refresh_token_expires_at and now > session.refresh_token_expires_at:
            logger.warning(f"Refresh token expired")
            return None

        # Generate new access token
        new_access_token = self._generate_token("ga_")
        new_access_expires = now + timedelta(seconds=access_token_ttl)

        def _execute(conn) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth.device_sessions
                    SET access_token = %s,
                        access_token_expires_at = %s
                    WHERE refresh_token = %s AND status = 'APPROVED'
                    """,
                    (new_access_token, new_access_expires, refresh_token),
                )

        self._pool.run_transaction(
            operation="device_session.refresh",
            service_prefix="auth",
            actor=session.oauth_user_id or session.approver,
            metadata={"device_code": session.device_code},
            executor=_execute,
            telemetry=None,
        )

        # Update session object
        session.access_token = new_access_token
        session.access_token_expires_at = new_access_expires

        logger.info(f"Refreshed access token for session: device_code={session.device_code}")
        return session

    def get_user_info_from_access_token(self, access_token: str) -> Optional[Dict[str, Any]]:
        """Get user info from a valid access token.

        Returns dict with 'sub' (user_id), 'scopes', and optional OAuth fields.
        """
        session = self.get_by_access_token(access_token)
        if not session:
            return None

        if session.status != "APPROVED":
            return None

        # Check token expiry
        if session.access_token_expires_at and datetime.now(timezone.utc) > session.access_token_expires_at:
            return None

        # Build user info - priority: oauth_user_id > approver
        user_info: Dict[str, Any] = {
            "sub": session.oauth_user_id or session.approver,
            "scopes": session.scopes,
        }

        # Include OAuth info if available
        if session.oauth_user_id:
            user_info["sub"] = session.oauth_user_id
            if session.oauth_display_name:
                user_info["name"] = session.oauth_display_name
            if session.oauth_username:
                user_info["username"] = session.oauth_username
            if session.oauth_email:
                user_info["email"] = session.oauth_email
            if session.oauth_avatar_url:
                user_info["picture"] = session.oauth_avatar_url
            if session.oauth_provider:
                user_info["provider"] = session.oauth_provider

        return user_info
