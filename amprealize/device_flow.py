"""Device flow manager implementing OAuth-style device authorization for stubs.

This module provides an in-memory implementation of the device authorization
flow (RFC 8628) tailored for the amprealize prototypes. It supports issuing device
codes, approving/denying them via a verification URI, and polling for tokens.
The implementation emphasises parity across CLI, REST, and IDE surfaces while
remaining lightweight for unit tests.
"""

from __future__ import annotations

import os
import secrets
import string
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from .auth.providers import (
    GitHubOAuthProvider,
    OAuthProvider,
    AuthorizationPendingError,
    SlowDownError,
    ExpiredTokenError,
    AccessDeniedError,
    UserInfo,
)
from .telemetry import TelemetryClient


def _now() -> datetime:
    """Return current UTC time."""

    return datetime.now(timezone.utc)


def _isoformat(dt: datetime) -> str:
    """Return ISO 8601 representation."""

    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class DeviceAuthorizationStatus(str, Enum):
    """Lifecycle states for a device authorization request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


@dataclass
class DeviceTokens:
    """Issued tokens for a device authorization."""

    access_token: str
    refresh_token: str
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime
    token_type: str = "Bearer"

    def access_expires_in(self, *, as_of: Optional[datetime] = None) -> int:
        """Seconds until the access token expires."""

        reference = as_of or _now()
        remaining = int((self.access_token_expires_at - reference).total_seconds())
        return max(0, remaining)

    def refresh_expires_in(self, *, as_of: Optional[datetime] = None) -> int:
        """Seconds until the refresh token expires."""

        reference = as_of or _now()
        remaining = int((self.refresh_token_expires_at - reference).total_seconds())
        return max(0, remaining)


@dataclass
class DeviceAuthorizationSession:
    """Internal representation of a device authorization request."""

    device_code: str
    user_code: str
    client_id: str
    scopes: List[str]
    surface: str
    verification_uri: str
    verification_uri_complete: str
    created_at: datetime
    expires_at: datetime
    poll_interval: int
    metadata: Dict[str, str] = field(default_factory=dict)
    status: DeviceAuthorizationStatus = DeviceAuthorizationStatus.PENDING
    tokens: Optional[DeviceTokens] = None
    approver: Optional[str] = None
    approved_at: Optional[datetime] = None
    denied_at: Optional[datetime] = None
    denied_reason: Optional[str] = None
    last_poll_at: Optional[datetime] = None
    oauth_user_info: Optional[UserInfo] = None

    def expires_in(self, *, as_of: Optional[datetime] = None) -> int:
        """Seconds until the device code expires."""

        reference = as_of or _now()
        remaining = int((self.expires_at - reference).total_seconds())
        return max(0, remaining)


@dataclass
class DevicePollResult:
    """Result returned when polling a device code."""

    status: DeviceAuthorizationStatus
    retry_after: Optional[int] = None
    expires_in: Optional[int] = None
    tokens: Optional[DeviceTokens] = None
    denied_reason: Optional[str] = None
    scopes: Optional[List[str]] = None
    client_id: Optional[str] = None


class DeviceFlowError(Exception):
    """Base exception for device flow operations."""


class DeviceCodeNotFoundError(DeviceFlowError):
    """Raised when a device code is unknown."""


class UserCodeNotFoundError(DeviceFlowError):
    """Raised when a user code cannot be resolved."""


class DeviceCodeExpiredError(DeviceFlowError):
    """Raised when attempting to interact with an expired device code."""


class RefreshTokenNotFoundError(DeviceFlowError):
    """Raised when a refresh token cannot be mapped to a session."""


class RefreshTokenExpiredError(DeviceFlowError):
    """Raised when a refresh token has exceeded its lifetime."""


class DeviceFlowManager:
    """Manage device authorization lifecycle for prototype services."""

    _DEFAULT_USER_CODE_ALPHABET = string.ascii_uppercase + string.digits

    def __init__(
        self,
        *,
        telemetry: Optional[TelemetryClient] = None,
        verification_uri: Optional[str] = None,
        device_code_ttl: Optional[int] = None,
        poll_interval: Optional[int] = None,
        access_token_ttl: Optional[int] = None,
        refresh_token_ttl: Optional[int] = None,
        user_code_length: Optional[int] = None,
        provider: Optional[OAuthProvider] = None,
        use_real_oauth: bool = False,
    ) -> None:
        self._telemetry = telemetry or TelemetryClient.noop()
        self._verification_uri = (
            verification_uri
            or os.getenv("AMPREALIZE_DEVICE_VERIFICATION_URI", "https://device.amprealize.dev/activate")
        )
        self._device_code_ttl = device_code_ttl or int(
            os.getenv("AMPREALIZE_DEVICE_CODE_TTL_SECONDS", "600")
        )
        self._poll_interval = poll_interval or int(
            os.getenv("AMPREALIZE_DEVICE_POLL_INTERVAL_SECONDS", "5")
        )
        self._access_token_ttl = access_token_ttl or int(
            os.getenv("AMPREALIZE_ACCESS_TOKEN_TTL_SECONDS", "3600")
        )
        self._refresh_token_ttl = refresh_token_ttl or int(
            os.getenv("AMPREALIZE_REFRESH_TOKEN_TTL_SECONDS", str(7 * 24 * 3600))
        )
        self._user_code_length = user_code_length or int(
            os.getenv("AMPREALIZE_DEVICE_USER_CODE_LENGTH", "8")
        )

        # OAuth provider support
        self._use_real_oauth = use_real_oauth or os.getenv("AMPREALIZE_USE_REAL_OAUTH", "").lower() in ("1", "true", "yes")
        self._provider = provider
        if self._use_real_oauth and not self._provider:
            # Default to GitHub provider if real OAuth enabled but no provider specified
            client_id = os.getenv("OAUTH_CLIENT_ID")
            client_secret = os.getenv("OAUTH_CLIENT_SECRET")
            if client_id and client_secret:
                self._provider = GitHubOAuthProvider(client_id=client_id, client_secret=client_secret)

        self._sessions: Dict[str, DeviceAuthorizationSession] = {}
        self._user_code_index: Dict[str, str] = {}
        self._refresh_token_index: Dict[str, str] = {}
        self._access_token_index: Dict[str, str] = {}  # access_token -> device_code
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    async def start_authorization_real_oauth(
        self,
        *,
        scopes: List[str],
        surface: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> DeviceAuthorizationSession:
        """Create a new device authorization request using real OAuth provider."""

        if not self._provider:
            raise DeviceFlowError("No OAuth provider configured. Set OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET.")

        # Start device flow with the OAuth provider
        device_flow_response = await self._provider.start_device_flow(scopes)

        # Create session with OAuth provider's response
        created_at = _now()
        expires_at = created_at + timedelta(seconds=device_flow_response.expires_in)

        session = DeviceAuthorizationSession(
            device_code=device_flow_response.device_code,
            user_code=device_flow_response.user_code,
            client_id="oauth_provider",  # OAuth provider manages client_id
            scopes=list(scopes),
            surface=surface,
            verification_uri=device_flow_response.verification_uri,
            verification_uri_complete=device_flow_response.verification_uri,
            created_at=created_at,
            expires_at=expires_at,
            poll_interval=device_flow_response.interval,
            metadata=dict(metadata or {}),
        )

        with self._lock:
            self._prune_expired_locked()
            self._sessions[device_flow_response.device_code] = session
            self._user_code_index[device_flow_response.user_code] = device_flow_response.device_code

        self._emit_event(
            "auth_device_flow_started",
            session,
            extra={
                "client_id": "oauth_provider",
                "scopes": scopes,
                "surface": surface,
                "expires_at": _isoformat(expires_at),
                "provider": "real_oauth",
            },
        )
        return session

    async def start_authorization_internal(
        self,
        *,
        username: str,
        password: str,
        surface: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> DeviceTokens:
        """
        [DEPRECATED] Internal auth (username/password) has been removed.

        Use OAuth authentication instead via --provider=github or --provider=google.

        Raises:
            DeviceFlowError: Always - this method is deprecated
        """
        raise DeviceFlowError(
            "Internal authentication (username/password) has been deprecated. "
            "Please use OAuth authentication via --provider=github or --provider=google"
        )

    async def register_internal_user(
        self,
        *,
        username: str,
        password: str,
        email: Optional[str] = None,
        surface: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> DeviceTokens:
        """
        [DEPRECATED] Internal user registration has been removed.

        Use OAuth authentication instead via --provider=github or --provider=google.

        Raises:
            DeviceFlowError: Always - this method is deprecated
        """
        raise DeviceFlowError(
            "Internal user registration has been deprecated. "
            "Please use OAuth authentication via --provider=github or --provider=google"
        )

    def start_authorization(
        self,
        *,
        client_id: str,
        scopes: List[str],
        surface: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> DeviceAuthorizationSession:
        """Create a new device authorization request."""

        if not client_id:
            raise ValueError("client_id is required")
        if not scopes:
            raise ValueError("scopes must contain at least one scope")

        device_code = secrets.token_urlsafe(32)
        user_code = self._generate_user_code()
        created_at = _now()
        expires_at = created_at + timedelta(seconds=self._device_code_ttl)
        verification_uri_complete = f"{self._verification_uri}?user_code={user_code}"
        session = DeviceAuthorizationSession(
            device_code=device_code,
            user_code=user_code,
            client_id=client_id,
            scopes=list(scopes),
            surface=surface,
            verification_uri=self._verification_uri,
            verification_uri_complete=verification_uri_complete,
            created_at=created_at,
            expires_at=expires_at,
            poll_interval=self._poll_interval,
            metadata=dict(metadata or {}),
        )

        with self._lock:
            self._prune_expired_locked()
            self._sessions[device_code] = session
            self._user_code_index[user_code] = device_code

        self._emit_event(
            "auth_device_flow_started",
            session,
            extra={
                "client_id": client_id,
                "scopes": scopes,
                "surface": surface,
                "expires_at": _isoformat(expires_at),
            },
        )
        return session

    def describe_user_code(self, user_code: str) -> DeviceAuthorizationSession:
        """Retrieve a session by user code for verification UI."""

        with self._lock:
            session = self._get_session_by_user_code_locked(user_code)
            self._update_status_for_expiry(session)
            return session

    def approve_user_code(
        self,
        user_code: str,
        approver: str,
        *,
        approver_surface: str,
        roles: Optional[List[str]] = None,
        mfa_verified: bool = False,
    ) -> DeviceAuthorizationSession:
        """Approve a pending device authorization."""

        roles = roles or []
        with self._lock:
            session = self._get_session_by_user_code_locked(user_code)
            self._update_status_for_expiry(session)
            if session.status is DeviceAuthorizationStatus.EXPIRED:
                raise DeviceCodeExpiredError(f"User code {user_code} expired")
            if session.status is DeviceAuthorizationStatus.DENIED:
                raise DeviceFlowError("Device code already denied")
            if session.status is DeviceAuthorizationStatus.APPROVED:
                return session

            session.status = DeviceAuthorizationStatus.APPROVED
            session.approver = approver
            session.approved_at = _now()
            session.tokens = self._issue_tokens()
            self._register_tokens_locked(session)

        self._emit_event(
            "auth_device_flow_approved",
            session,
            extra={
                "approver": approver,
                "approver_surface": approver_surface,
                "roles": roles,
                "mfa_verified": mfa_verified,
            },
        )
        return session

    def deny_user_code(
        self,
        user_code: str,
        approver: str,
        *,
        approver_surface: str,
        reason: Optional[str] = None,
    ) -> DeviceAuthorizationSession:
        """Deny a pending device authorization."""

        with self._lock:
            session = self._get_session_by_user_code_locked(user_code)
            self._update_status_for_expiry(session)
            if session.status is DeviceAuthorizationStatus.EXPIRED:
                raise DeviceCodeExpiredError(f"User code {user_code} expired")
            if session.status is DeviceAuthorizationStatus.APPROVED:
                raise DeviceFlowError("Device code already approved")
            if session.status is DeviceAuthorizationStatus.DENIED:
                return session

            session.status = DeviceAuthorizationStatus.DENIED
            session.denied_at = _now()
            session.denied_reason = reason or "User denied access"
            self._unregister_tokens_locked(session)

        self._emit_event(
            "auth_device_flow_denied",
            session,
            extra={
                "approver": approver,
                "approver_surface": approver_surface,
                "reason": session.denied_reason,
            },
        )
        return session

    async def poll_device_code_real_oauth(self, device_code: str) -> DevicePollResult:
        """Poll a device code using real OAuth provider."""

        if not self._provider:
            raise DeviceFlowError("No OAuth provider configured")

        with self._lock:
            session = self._sessions.get(device_code)
            if session is None:
                raise DeviceCodeNotFoundError(f"Device code {device_code} not found")
            self._update_status_for_expiry(session)

            if session.status is DeviceAuthorizationStatus.EXPIRED:
                return DevicePollResult(
                    status=DeviceAuthorizationStatus.EXPIRED,
                    expires_in=0,
                )

            if session.status is DeviceAuthorizationStatus.APPROVED:
                # Already approved, return tokens
                return DevicePollResult(
                    status=DeviceAuthorizationStatus.APPROVED,
                    tokens=session.tokens,
                    scopes=session.scopes,
                    client_id=session.client_id,
                )

            if session.status is DeviceAuthorizationStatus.DENIED:
                return DevicePollResult(
                    status=DeviceAuthorizationStatus.DENIED,
                    denied_reason=session.denied_reason,
                )

        # Poll OAuth provider
        try:
            token_response = await self._provider.poll_token(device_code)

            # Authorization approved! Store tokens
            with self._lock:
                session.status = DeviceAuthorizationStatus.APPROVED
                session.approved_at = _now()
                session.tokens = DeviceTokens(
                    access_token=token_response.access_token,
                    refresh_token=token_response.refresh_token or "",
                    access_token_expires_at=_now() + timedelta(seconds=token_response.expires_in),
                    refresh_token_expires_at=_now() + timedelta(days=90),  # Default 90 days
                    token_type=token_response.token_type,
                )
                self._register_tokens_locked(session)

            self._emit_event(
                "auth_device_flow_approved",
                session,
                extra={
                    "approver": "oauth_provider",
                    "approver_surface": "oauth",
                    "provider": "real_oauth",
                },
            )

            return DevicePollResult(
                status=DeviceAuthorizationStatus.APPROVED,
                tokens=session.tokens,
                scopes=session.scopes,
                client_id=session.client_id,
            )

        except AuthorizationPendingError:
            # Still pending
            session.last_poll_at = _now()
            return DevicePollResult(
                status=DeviceAuthorizationStatus.PENDING,
                retry_after=session.poll_interval,
                expires_in=session.expires_in(),
            )

        except SlowDownError:
            # Provider wants us to slow down
            session.last_poll_at = _now()
            return DevicePollResult(
                status=DeviceAuthorizationStatus.PENDING,
                retry_after=session.poll_interval + 5,  # Add 5 seconds
                expires_in=session.expires_in(),
            )

        except ExpiredTokenError:
            # Device code expired
            with self._lock:
                session.status = DeviceAuthorizationStatus.EXPIRED
            return DevicePollResult(
                status=DeviceAuthorizationStatus.EXPIRED,
                expires_in=0,
            )

        except AccessDeniedError:
            # User denied authorization
            with self._lock:
                session.status = DeviceAuthorizationStatus.DENIED
                session.denied_at = _now()
                session.denied_reason = "User denied access"

            self._emit_event(
                "auth_device_flow_denied",
                session,
                extra={
                    "approver": "oauth_provider",
                    "approver_surface": "oauth",
                    "reason": "User denied access",
                },
            )

            return DevicePollResult(
                status=DeviceAuthorizationStatus.DENIED,
                denied_reason=session.denied_reason,
            )

    def poll_device_code(self, device_code: str) -> DevicePollResult:
        """Poll a device code for completion."""

        with self._lock:
            session = self._sessions.get(device_code)
            if session is None:
                raise DeviceCodeNotFoundError(f"Device code {device_code} not found")
            self._update_status_for_expiry(session)

            now = _now()
            if session.status is DeviceAuthorizationStatus.EXPIRED:
                return DevicePollResult(
                    status=DeviceAuthorizationStatus.EXPIRED,
                    expires_in=0,
                )

            if session.status is DeviceAuthorizationStatus.PENDING:
                if session.last_poll_at is not None:
                    delta = (now - session.last_poll_at).total_seconds()
                    if delta < session.poll_interval:
                        retry_after = max(1, int(session.poll_interval - delta))
                        return DevicePollResult(
                            status=DeviceAuthorizationStatus.PENDING,
                            retry_after=retry_after,
                            expires_in=session.expires_in(as_of=now),
                            scopes=list(session.scopes),
                            client_id=session.client_id,
                        )
                session.last_poll_at = now
                return DevicePollResult(
                    status=DeviceAuthorizationStatus.PENDING,
                    retry_after=session.poll_interval,
                    expires_in=session.expires_in(as_of=now),
                    scopes=list(session.scopes),
                    client_id=session.client_id,
                )

            if session.status is DeviceAuthorizationStatus.DENIED:
                return DevicePollResult(
                    status=DeviceAuthorizationStatus.DENIED,
                    denied_reason=session.denied_reason,
                    expires_in=session.expires_in(as_of=now),
                    scopes=list(session.scopes),
                    client_id=session.client_id,
                )

            # APPROVED
            assert session.tokens is not None, "approved session must carry tokens"
            tokens = session.tokens
            if tokens.access_expires_in(as_of=now) <= 0 and tokens.refresh_expires_in(as_of=now) > 0:
                # Rotate access token while refresh token is valid.
                session.tokens = self._issue_tokens(
                    existing_refresh=tokens.refresh_token,
                    refresh_expires_at=tokens.refresh_token_expires_at,
                )
                self._register_tokens_locked(session)
                tokens = session.tokens
            return DevicePollResult(
                status=DeviceAuthorizationStatus.APPROVED,
                tokens=tokens,
                expires_in=session.expires_in(as_of=now),
                scopes=list(session.scopes),
                client_id=session.client_id,
            )

    def cleanup_expired(self) -> None:
        """Remove expired sessions from memory."""

        with self._lock:
            self._prune_expired_locked()

    def refresh_access_token(self, refresh_token: str) -> DeviceAuthorizationSession:
        """Issue a new access token when provided a valid refresh token."""

        if not refresh_token:
            raise ValueError("refresh_token is required")

        with self._lock:
            device_code = self._refresh_token_index.get(refresh_token)
            if device_code is None:
                raise RefreshTokenNotFoundError("Refresh token not recognized")

            session = self._sessions.get(device_code)
            if session is None:
                raise DeviceCodeNotFoundError(
                    f"Device code for refresh token {refresh_token} not found"
                )

            self._update_status_for_expiry(session)
            if session.status is DeviceAuthorizationStatus.EXPIRED:
                self._unregister_tokens_locked(session)
                raise DeviceCodeExpiredError("Device authorization expired")
            if session.tokens is None:
                raise DeviceFlowError("Device authorization not yet approved")

            tokens = session.tokens
            if tokens.refresh_token != refresh_token:
                raise DeviceFlowError("Refresh token mismatch")
            if tokens.refresh_expires_in(as_of=_now()) <= 0:
                session.status = DeviceAuthorizationStatus.EXPIRED
                self._unregister_tokens_locked(session)
                raise RefreshTokenExpiredError("Refresh token expired")

            session.tokens = self._issue_tokens(
                existing_refresh=refresh_token,
                refresh_expires_at=tokens.refresh_token_expires_at,
            )
            self._register_tokens_locked(session)
            new_tokens = session.tokens

        self._emit_event(
            "auth_device_flow_refreshed",
            session,
            extra={"refresh_expires_at": _isoformat(new_tokens.refresh_token_expires_at)},
        )
        return session

    def get_user_info_from_access_token(self, access_token: str) -> Optional[Dict[str, Any]]:
        """Retrieve user info associated with a valid access token.

        Returns a dictionary with user info if the access token is valid,
        or None if the token is invalid, expired, or not found.
        """
        if not access_token:
            return None

        with self._lock:
            device_code = self._access_token_index.get(access_token)
            if device_code is None:
                return None

            session = self._sessions.get(device_code)
            if session is None:
                return None

            self._update_status_for_expiry(session)
            if session.status is DeviceAuthorizationStatus.EXPIRED:
                self._unregister_tokens_locked(session)
                return None

            if session.tokens is None:
                return None

            tokens = session.tokens
            if tokens.access_token != access_token:
                return None
            if tokens.access_expires_in(as_of=_now()) <= 0:
                return None

            # Build user info from session data
            # Priority: oauth_user_info > approver > device_code
            user_info: Dict[str, Any] = {
                "sub": session.approver or session.device_code,  # Use approver if set
                "scopes": session.scopes,
            }

            # Include OAuth user info if available (UserInfo has: user_id, username, email, display_name, avatar_url)
            if session.oauth_user_info:
                user_info["sub"] = session.oauth_user_info.user_id
                user_info["name"] = session.oauth_user_info.display_name or session.oauth_user_info.username
                user_info["email"] = session.oauth_user_info.email
                user_info["picture"] = session.oauth_user_info.avatar_url
                user_info["username"] = session.oauth_user_info.username
                user_info["provider"] = session.oauth_user_info.provider

            return user_info

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _generate_user_code(self) -> str:
        alphabet = self._DEFAULT_USER_CODE_ALPHABET
        code = "".join(secrets.choice(alphabet) for _ in range(self._user_code_length))
        # Insert hyphen for readability (e.g., ABCD-EFGH) when length permits.
        if len(code) >= 8:
            midpoint = len(code) // 2
            code = f"{code[:midpoint]}-{code[midpoint:]}"
        return code

    def _prune_expired_locked(self) -> None:
        now = _now()
        expired_device_codes: List[str] = []
        for device_code, session in self._sessions.items():
            if session.status in {DeviceAuthorizationStatus.APPROVED, DeviceAuthorizationStatus.DENIED}:
                continue
            if session.expires_at <= now:
                session.status = DeviceAuthorizationStatus.EXPIRED
                self._unregister_tokens_locked(session)
                expired_device_codes.append(device_code)

        if expired_device_codes:
            self._emit_event(
                "auth_device_flow_expired",
                None,
                extra={"device_codes": expired_device_codes},
            )

    def _get_session_by_user_code_locked(self, user_code: str) -> DeviceAuthorizationSession:
        device_code = self._user_code_index.get(user_code)
        if device_code is None:
            raise UserCodeNotFoundError(f"User code {user_code} not found")
        session = self._sessions[device_code]
        return session

    def _update_status_for_expiry(self, session: DeviceAuthorizationSession) -> None:
        if session.status in {
            DeviceAuthorizationStatus.APPROVED,
            DeviceAuthorizationStatus.DENIED,
            DeviceAuthorizationStatus.EXPIRED,
        }:
            return
        if session.expires_at <= _now():
            session.status = DeviceAuthorizationStatus.EXPIRED
            self._unregister_tokens_locked(session)

    def _issue_tokens(
        self,
        *,
        existing_refresh: Optional[str] = None,
        refresh_expires_at: Optional[datetime] = None,
    ) -> DeviceTokens:
        now = _now()
        access_token = f"ga_{uuid.uuid4()}"
        refresh_token = existing_refresh or f"gr_{uuid.uuid4()}"
        refresh_expiry = (
            refresh_expires_at.astimezone(timezone.utc)
            if (refresh_expires_at is not None and existing_refresh is not None)
            else now + timedelta(seconds=self._refresh_token_ttl)
        )
        return DeviceTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_at=now + timedelta(seconds=self._access_token_ttl),
            refresh_token_expires_at=refresh_expiry,
        )

    def _register_tokens_locked(self, session: DeviceAuthorizationSession) -> None:
        if session.tokens is None:
            return
        self._refresh_token_index[session.tokens.refresh_token] = session.device_code
        self._access_token_index[session.tokens.access_token] = session.device_code

    def _unregister_tokens_locked(self, session: DeviceAuthorizationSession) -> None:
        if session.tokens is None:
            return
        self._refresh_token_index.pop(session.tokens.refresh_token, None)
        self._access_token_index.pop(session.tokens.access_token, None)

    def _emit_event(
        self,
        event_type: str,
        session: Optional[DeviceAuthorizationSession],
        extra: Optional[Dict[str, object]] = None,
    ) -> None:
        payload: Dict[str, object] = dict(extra or {})
        if session is not None:
            payload.update(
                {
                    "device_code": session.device_code,
                    "user_code": session.user_code,
                    "client_id": session.client_id,
                    "surface": session.surface,
                    "status": session.status.value,
                    "scopes": session.scopes,
                }
            )
        self._telemetry.emit_event(
            event_type=event_type,
            payload=payload,
            actor={"id": "agentauth", "role": "SYSTEM", "surface": "api"},
        )

    def create_session_from_oauth(
        self,
        *,
        provider: str,
        user_id: str,
        email: str,
        name: Optional[str] = None,
        picture: Optional[str] = None,
        provider_access_token: Optional[str] = None,
        provider_refresh_token: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> DeviceTokens:
        """
        Create an Amprealize session from OAuth credentials.

        This bridges OAuth login (Google, GitHub) to the device flow session system,
        enabling token refresh via the standard device flow refresh endpoints.

        Args:
            provider: OAuth provider name (e.g., "google", "github")
            user_id: User ID from the OAuth provider
            email: User's email address
            name: User's display name (optional)
            picture: User's avatar URL (optional)
            provider_access_token: Access token from OAuth provider (stored for API calls)
            provider_refresh_token: Refresh token from OAuth provider (stored for re-auth)
            scopes: Scopes granted by the OAuth provider

        Returns:
            DeviceTokens with Amprealize access and refresh tokens that work with
            the standard device flow refresh endpoints.
        """
        now = _now()
        device_code = secrets.token_urlsafe(32)
        user_code = self._generate_user_code()

        # Create OAuth user info to store in session
        oauth_user_info = UserInfo(
            provider=provider,
            user_id=user_id,
            username=email,  # Use email as username for OAuth users
            email=email,
            display_name=name,
            avatar_url=picture,
        )

        # Create session
        # Store OAuth provider info in metadata field (provider tokens for potential re-auth)
        metadata = {
            "oauth_provider": provider,
        }
        if provider_access_token:
            metadata["oauth_access_token"] = provider_access_token
        if provider_refresh_token:
            metadata["oauth_refresh_token"] = provider_refresh_token

        session = DeviceAuthorizationSession(
            device_code=device_code,
            user_code=user_code,
            client_id=f"oauth-{provider}",
            scopes=scopes or ["openid", "profile", "email"],
            surface="WEB",
            verification_uri="",
            verification_uri_complete="",
            created_at=now,
            expires_at=now + timedelta(days=30),  # Long expiry for OAuth sessions
            poll_interval=self._poll_interval,
            status=DeviceAuthorizationStatus.APPROVED,
            approver=email,
            approved_at=now,
            oauth_user_info=oauth_user_info,
            metadata=metadata,
        )

        # Issue Amprealize tokens
        session.tokens = self._issue_tokens()

        # Register session and tokens
        with self._lock:
            self._sessions[device_code] = session
            self._user_code_index[user_code] = device_code
            self._register_tokens_locked(session)

        self._emit_event(
            "auth_oauth_session_created",
            session,
            extra={"provider": provider, "email": email},
        )

        assert session.tokens is not None
        return session.tokens


__all__ = [
    "DeviceAuthorizationStatus",
    "DeviceFlowManager",
    "DeviceTokens",
    "DeviceAuthorizationSession",
    "DevicePollResult",
    "DeviceFlowError",
    "DeviceCodeNotFoundError",
    "UserCodeNotFoundError",
    "DeviceCodeExpiredError",
    "RefreshTokenNotFoundError",
    "RefreshTokenExpiredError",
]
