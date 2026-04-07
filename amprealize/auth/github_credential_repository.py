"""GitHub Credential Repository.

Manages BYOK GitHub PAT credentials with encrypted storage, validation,
failure tracking, and audit logging.

Behavior: behavior_align_storage_layers

Parallel implementation to LLMCredentialRepository for GitHub tokens.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..storage.postgres_pool import PostgresPool
from ..utils.dsn import resolve_postgres_dsn
from .credential_encryption import CredentialEncryptionService


logger = logging.getLogger(__name__)


# ==============================================================================
# Enums
# ==============================================================================


class CredentialScopeType(str, Enum):
    """Scope type for credentials."""
    ORG = "org"
    PROJECT = "project"
    USER = "user"  # Personal credentials owned by a specific user


class GitHubTokenType(str, Enum):
    """GitHub token types based on prefix."""
    CLASSIC = "classic"  # ghp_* prefix
    FINE_GRAINED = "fine_grained"  # github_pat_* prefix
    APP = "app"  # ghs_* (GitHub App installation token)
    UNKNOWN = "unknown"  # Unknown prefix


class GitHubCredentialAction(str, Enum):
    """Actions for audit logging."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    USED = "used"
    FAILED = "failed"
    DISABLED = "disabled"
    RE_ENABLED = "re-enabled"
    VALIDATED = "validated"


class ActorType(str, Enum):
    """Actor types for audit logging."""
    USER = "user"
    SERVICE = "service"
    SYSTEM = "system"


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class GitHubCredential:
    """Represents a GitHub PAT credential."""

    id: str
    scope_type: CredentialScopeType
    scope_id: str
    token_type: GitHubTokenType
    name: str
    token_prefix: str
    is_valid: bool = True
    failure_count: int = 0
    scopes: Optional[List[str]] = None
    rate_limit: Optional[int] = None
    rate_limit_remaining: Optional[int] = None
    rate_limit_reset: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    last_validated_at: Optional[datetime] = None
    github_username: Optional[str] = None
    github_user_id: Optional[int] = None
    created_by: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Only populated when decryption is requested
    _decrypted_token: Optional[str] = field(default=None, repr=False)

    @property
    def decrypted_token(self) -> Optional[str]:
        """Return decrypted GitHub token if available."""
        return self._decrypted_token

    @property
    def masked_token(self) -> str:
        """Return masked token for display."""
        return f"{self.token_prefix}****"

    @property
    def has_required_scopes(self) -> bool:
        """Check if token has required scopes for PR operations.

        Required scopes depend on token type:
        - Classic PAT: 'repo' scope covers everything
        - Fine-grained PAT: 'contents:write' and 'pull_requests:write'
        """
        if not self.scopes:
            return False

        if self.token_type == GitHubTokenType.CLASSIC:
            # Classic tokens: 'repo' grants full access
            return "repo" in self.scopes
        elif self.token_type == GitHubTokenType.FINE_GRAINED:
            # Fine-grained tokens: need specific permissions
            # Note: Fine-grained permissions show differently, check common variants
            required = {"contents:write", "pull_requests:write"}
            return required.issubset(set(self.scopes))
        elif self.token_type == GitHubTokenType.APP:
            # App tokens: typically have permissions in metadata
            return True  # Assume app tokens are configured correctly

        return False

    @property
    def scope_warning(self) -> Optional[str]:
        """Return warning message if scopes are insufficient."""
        if self.has_required_scopes:
            return None

        if not self.scopes:
            return "Token scopes could not be determined. Verify token has repo access."

        if self.token_type == GitHubTokenType.CLASSIC:
            return "Token missing 'repo' scope. PR creation may fail."
        elif self.token_type == GitHubTokenType.FINE_GRAINED:
            return "Token may be missing 'Contents: Read and write' or 'Pull requests: Read and write' permissions."

        return "Token scopes may be insufficient for PR operations."

    def to_dict(self, include_token: bool = False) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        result = {
            "id": self.id,
            "scope_type": self.scope_type.value if isinstance(self.scope_type, CredentialScopeType) else self.scope_type,
            "scope_id": self.scope_id,
            "token_type": self.token_type.value if isinstance(self.token_type, GitHubTokenType) else self.token_type,
            "name": self.name,
            "token_prefix": self.token_prefix,
            "masked_token": self.masked_token,
            "is_valid": self.is_valid,
            "failure_count": self.failure_count,
            "scopes": self.scopes,
            "has_required_scopes": self.has_required_scopes,
            "scope_warning": self.scope_warning,
            "rate_limit": self.rate_limit,
            "rate_limit_remaining": self.rate_limit_remaining,
            "rate_limit_reset": self.rate_limit_reset.isoformat() if self.rate_limit_reset else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "last_validated_at": self.last_validated_at.isoformat() if self.last_validated_at else None,
            "github_username": self.github_username,
            "github_user_id": self.github_user_id,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata,
        }
        if include_token and self._decrypted_token:
            result["token"] = self._decrypted_token
        return result


@dataclass
class CreateGitHubCredentialRequest:
    """Request to create a new GitHub credential."""

    scope_type: CredentialScopeType
    scope_id: str
    token: str
    name: Optional[str] = None
    created_by: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GitHubCredentialAuditEntry:
    """Audit log entry for GitHub credential operations."""

    id: str
    credential_id: str
    action: GitHubCredentialAction
    actor_id: Optional[str]
    actor_type: ActorType
    details: Dict[str, Any]
    created_at: datetime


@dataclass
class GitHubTokenValidationResult:
    """Result of validating a GitHub token against the API."""

    is_valid: bool
    token_type: GitHubTokenType
    username: Optional[str] = None
    user_id: Optional[int] = None
    scopes: Optional[List[str]] = None
    rate_limit: Optional[int] = None
    rate_limit_remaining: Optional[int] = None
    rate_limit_reset: Optional[datetime] = None
    error: Optional[str] = None
    error_code: Optional[int] = None


# ==============================================================================
# Token Type Detection
# ==============================================================================


def detect_token_type(token: str) -> GitHubTokenType:
    """Detect GitHub token type from prefix.

    Token prefixes:
    - ghp_: Classic Personal Access Token
    - github_pat_: Fine-grained Personal Access Token
    - ghs_: GitHub App installation token
    - gho_: OAuth access token
    - ghu_: GitHub App user-to-server token
    """
    if token.startswith("ghp_"):
        return GitHubTokenType.CLASSIC
    elif token.startswith("github_pat_"):
        return GitHubTokenType.FINE_GRAINED
    elif token.startswith("ghs_"):
        return GitHubTokenType.APP
    else:
        # Could be an older token format or OAuth token
        return GitHubTokenType.UNKNOWN


def get_token_prefix(token: str, length: int = 12) -> str:
    """Get display prefix for token.

    For classic tokens (ghp_): shows "ghp_xxxx" (8 chars)
    For fine-grained (github_pat_): shows "github_pat_xxxx" (15 chars)
    For app tokens (ghs_): shows "ghs_xxxx" (8 chars)
    """
    token_type = detect_token_type(token)

    if token_type == GitHubTokenType.CLASSIC:
        # ghp_ + 4 chars = 8 total
        return token[:8] if len(token) >= 8 else token
    elif token_type == GitHubTokenType.FINE_GRAINED:
        # github_pat_ + 4 chars = 15 total
        return token[:15] if len(token) >= 15 else token
    elif token_type == GitHubTokenType.APP:
        # ghs_ + 4 chars = 8 total
        return token[:8] if len(token) >= 8 else token
    else:
        # Unknown: show first 8 chars
        return token[:8] if len(token) >= 8 else token


# ==============================================================================
# Token Validation
# ==============================================================================


def validate_github_token(token: str, timeout: float = 10.0) -> GitHubTokenValidationResult:
    """Validate a GitHub token by calling the API.

    Makes a GET /user request to:
    1. Verify the token is valid (not expired, not revoked)
    2. Extract the scopes from X-OAuth-Scopes header
    3. Get rate limit info from X-RateLimit-* headers
    4. Get user info for audit purposes

    Args:
        token: The GitHub token to validate
        timeout: Request timeout in seconds

    Returns:
        GitHubTokenValidationResult with validation details
    """
    token_type = detect_token_type(token)

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

            # Parse rate limit headers
            rate_limit = None
            rate_limit_remaining = None
            rate_limit_reset = None

            if "X-RateLimit-Limit" in response.headers:
                try:
                    rate_limit = int(response.headers["X-RateLimit-Limit"])
                except ValueError:
                    pass

            if "X-RateLimit-Remaining" in response.headers:
                try:
                    rate_limit_remaining = int(response.headers["X-RateLimit-Remaining"])
                except ValueError:
                    pass

            if "X-RateLimit-Reset" in response.headers:
                try:
                    reset_timestamp = int(response.headers["X-RateLimit-Reset"])
                    rate_limit_reset = datetime.fromtimestamp(reset_timestamp, tz=timezone.utc)
                except ValueError:
                    pass

            # Parse scopes header
            scopes: Optional[List[str]] = None
            if "X-OAuth-Scopes" in response.headers:
                scope_str = response.headers["X-OAuth-Scopes"]
                if scope_str:
                    scopes = [s.strip() for s in scope_str.split(",")]

            # Check response status
            if response.status_code == 200:
                user_data = response.json()
                return GitHubTokenValidationResult(
                    is_valid=True,
                    token_type=token_type,
                    username=user_data.get("login"),
                    user_id=user_data.get("id"),
                    scopes=scopes,
                    rate_limit=rate_limit,
                    rate_limit_remaining=rate_limit_remaining,
                    rate_limit_reset=rate_limit_reset,
                )
            elif response.status_code == 401:
                return GitHubTokenValidationResult(
                    is_valid=False,
                    token_type=token_type,
                    error="Token is invalid, expired, or revoked",
                    error_code=401,
                    rate_limit=rate_limit,
                    rate_limit_remaining=rate_limit_remaining,
                    rate_limit_reset=rate_limit_reset,
                )
            elif response.status_code == 403:
                return GitHubTokenValidationResult(
                    is_valid=False,
                    token_type=token_type,
                    error="Token does not have required permissions",
                    error_code=403,
                    rate_limit=rate_limit,
                    rate_limit_remaining=rate_limit_remaining,
                    rate_limit_reset=rate_limit_reset,
                )
            else:
                return GitHubTokenValidationResult(
                    is_valid=False,
                    token_type=token_type,
                    error=f"Unexpected response: {response.status_code}",
                    error_code=response.status_code,
                    rate_limit=rate_limit,
                    rate_limit_remaining=rate_limit_remaining,
                    rate_limit_reset=rate_limit_reset,
                )

    except httpx.TimeoutException:
        return GitHubTokenValidationResult(
            is_valid=False,
            token_type=token_type,
            error="GitHub API request timed out",
        )
    except httpx.RequestError as e:
        return GitHubTokenValidationResult(
            is_valid=False,
            token_type=token_type,
            error=f"Network error: {str(e)}",
        )


# ==============================================================================
# Repository
# ==============================================================================


class GitHubCredentialRepository:
    """Repository for BYOK GitHub credential CRUD with encryption and audit logging.

    Parallel implementation to LLMCredentialRepository for GitHub PAT storage.
    Key differences:
    - Only one credential per scope (not per provider like LLM)
    - Stores GitHub-specific metadata (scopes, rate limits, user info)
    - Validates token against GitHub API on save
    """

    # Threshold for auto-disabling credentials after consecutive failures
    FAILURE_LOCKOUT_THRESHOLD = 3

    def __init__(
        self,
        pool: Optional[PostgresPool] = None,
        encryption_service: Optional[CredentialEncryptionService] = None,
        dsn: Optional[str] = None,
    ) -> None:
        """
        Initialize repository.

        Args:
            pool: PostgreSQL connection pool
            encryption_service: Service for encrypting/decrypting credentials
            dsn: Database connection string (used if pool not provided)
        """
        self._pool = pool or PostgresPool(dsn or resolve_postgres_dsn(
            service="github_credentials",
            explicit_dsn=None,
            env_var="AMPREALIZE_GITHUB_CREDENTIALS_PG_DSN",
            default_dsn="postgresql://localhost:5432/amprealize",
        ))
        self._encryption = encryption_service or CredentialEncryptionService()

    # -------------------------------------------------------------------------
    # CRUD Operations
    # -------------------------------------------------------------------------

    def create(
        self,
        request: CreateGitHubCredentialRequest,
        skip_validation: bool = False,
    ) -> Tuple[GitHubCredential, Optional[str]]:
        """Create a new GitHub credential.

        If a credential already exists for the same scope, it will be
        replaced (upsert behavior for token rotation).

        Args:
            request: Credential creation request
            skip_validation: Skip GitHub API validation (for testing)

        Returns:
            Tuple of (credential, warning_message)
            Warning message is set if token scopes are insufficient

        Raises:
            ValueError: If token validation fails
        """
        credential_id = f"ghcred-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        # Detect token type
        token_type = detect_token_type(request.token)
        token_prefix = get_token_prefix(request.token)

        # Validate token against GitHub API
        validation: Optional[GitHubTokenValidationResult] = None
        if not skip_validation:
            validation = validate_github_token(request.token)
            if not validation.is_valid:
                raise ValueError(f"GitHub token validation failed: {validation.error}")

        # Encrypt the token
        token_encrypted = self._encryption.encrypt(request.token)

        # Default name if not provided
        name = request.name
        if not name:
            if validation and validation.username:
                name = f"GitHub PAT ({validation.username})"
            else:
                name = f"GitHub {token_type.value.replace('_', ' ').title()} Token"

        # Prepare scope data
        scopes = validation.scopes if validation else None
        rate_limit = validation.rate_limit if validation else None
        rate_limit_remaining = validation.rate_limit_remaining if validation else None
        rate_limit_reset = validation.rate_limit_reset if validation else None
        github_username = validation.username if validation else None
        github_user_id = validation.user_id if validation else None

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Upsert: replace existing credential for same scope
                cur.execute(
                    """
                    INSERT INTO credentials.github_credentials (
                        id, scope_type, scope_id, token_type, name,
                        token_prefix, token_encrypted, is_valid, failure_count,
                        scopes, rate_limit, rate_limit_remaining, rate_limit_reset,
                        last_validated_at, github_username, github_user_id,
                        created_by, created_at, updated_at, metadata
                    ) VALUES (
                        %(id)s, %(scope_type)s, %(scope_id)s, %(token_type)s, %(name)s,
                        %(token_prefix)s, %(token_encrypted)s, true, 0,
                        %(scopes)s, %(rate_limit)s, %(rate_limit_remaining)s, %(rate_limit_reset)s,
                        %(last_validated_at)s, %(github_username)s, %(github_user_id)s,
                        %(created_by)s, %(created_at)s, %(updated_at)s, %(metadata)s::jsonb
                    )
                    ON CONFLICT (scope_type, scope_id)
                    DO UPDATE SET
                        token_type = EXCLUDED.token_type,
                        name = EXCLUDED.name,
                        token_prefix = EXCLUDED.token_prefix,
                        token_encrypted = EXCLUDED.token_encrypted,
                        is_valid = true,
                        failure_count = 0,
                        scopes = EXCLUDED.scopes,
                        rate_limit = EXCLUDED.rate_limit,
                        rate_limit_remaining = EXCLUDED.rate_limit_remaining,
                        rate_limit_reset = EXCLUDED.rate_limit_reset,
                        last_validated_at = EXCLUDED.last_validated_at,
                        github_username = EXCLUDED.github_username,
                        github_user_id = EXCLUDED.github_user_id,
                        updated_at = EXCLUDED.updated_at,
                        metadata = EXCLUDED.metadata
                    RETURNING id, created_at
                    """,
                    {
                        "id": credential_id,
                        "scope_type": request.scope_type.value,
                        "scope_id": request.scope_id,
                        "token_type": token_type.value,
                        "name": name,
                        "token_prefix": token_prefix,
                        "token_encrypted": token_encrypted,
                        "scopes": scopes,
                        "rate_limit": rate_limit,
                        "rate_limit_remaining": rate_limit_remaining,
                        "rate_limit_reset": rate_limit_reset,
                        "last_validated_at": now if validation else None,
                        "github_username": github_username,
                        "github_user_id": github_user_id,
                        "created_by": request.created_by,
                        "created_at": now,
                        "updated_at": now,
                        "metadata": json.dumps(request.metadata or {}),
                    },
                )
                row = cur.fetchone()
                returned_id = row[0] if row else credential_id

                # Log audit entry
                self._log_audit(
                    cur,
                    credential_id=returned_id,
                    action=GitHubCredentialAction.CREATED,
                    actor_id=request.created_by,
                    actor_type=ActorType.USER,
                    details={
                        "token_type": token_type.value,
                        "scope_type": request.scope_type.value,
                        "scopes": scopes,
                        "github_username": github_username,
                    },
                )

            conn.commit()

        credential = GitHubCredential(
            id=returned_id,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
            token_type=token_type,
            name=name,
            token_prefix=token_prefix,
            is_valid=True,
            failure_count=0,
            scopes=scopes,
            rate_limit=rate_limit,
            rate_limit_remaining=rate_limit_remaining,
            rate_limit_reset=rate_limit_reset,
            last_validated_at=now if validation else None,
            github_username=github_username,
            github_user_id=github_user_id,
            created_by=request.created_by,
            created_at=now,
            updated_at=now,
            metadata=request.metadata or {},
        )

        # Return warning if scopes are insufficient
        warning = credential.scope_warning

        return credential, warning

    def get_by_id(
        self,
        credential_id: str,
        decrypt: bool = False,
    ) -> Optional[GitHubCredential]:
        """Get credential by ID."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id, scope_type, scope_id, token_type, name,
                        token_prefix, token_encrypted, is_valid, failure_count,
                        scopes, rate_limit, rate_limit_remaining, rate_limit_reset,
                        last_used_at, last_validated_at, github_username, github_user_id,
                        created_by, created_at, updated_at, metadata
                    FROM credentials.github_credentials
                    WHERE id = %(id)s
                    """,
                    {"id": credential_id},
                )
                row = cur.fetchone()

            if not row:
                return None

            return self._row_to_credential(row, decrypt=decrypt)

    def get_for_scope(
        self,
        scope_type: CredentialScopeType,
        scope_id: str,
        decrypt: bool = False,
    ) -> Optional[GitHubCredential]:
        """Get the GitHub credential for a scope (org or project).

        Unlike LLM credentials, there's only ONE GitHub credential per scope.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id, scope_type, scope_id, token_type, name,
                        token_prefix, token_encrypted, is_valid, failure_count,
                        scopes, rate_limit, rate_limit_remaining, rate_limit_reset,
                        last_used_at, last_validated_at, github_username, github_user_id,
                        created_by, created_at, updated_at, metadata
                    FROM credentials.github_credentials
                    WHERE scope_type = %(scope_type)s AND scope_id = %(scope_id)s
                    """,
                    {
                        "scope_type": scope_type.value,
                        "scope_id": scope_id,
                    },
                )
                row = cur.fetchone()

            if not row:
                return None

            return self._row_to_credential(row, decrypt=decrypt)

    def list_by_creator(
        self,
        created_by: str,
        include_invalid: bool = False,
    ) -> List[GitHubCredential]:
        """List all credentials created by a specific user.

        Args:
            created_by: The user ID who created the credentials
            include_invalid: Whether to include disabled/invalid credentials

        Returns:
            List of GitHubCredential objects (without decrypted tokens)
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT
                        id, scope_type, scope_id, token_type, name,
                        token_prefix, token_encrypted, is_valid, failure_count,
                        scopes, rate_limit, rate_limit_remaining, rate_limit_reset,
                        last_used_at, last_validated_at, github_username, github_user_id,
                        created_by, created_at, updated_at, metadata
                    FROM credentials.github_credentials
                    WHERE created_by = %(created_by)s
                """
                if not include_invalid:
                    query += " AND is_valid = true"
                query += " ORDER BY created_at DESC"

                cur.execute(query, {"created_by": created_by})
                rows = cur.fetchall()

        return [self._row_to_credential(row, decrypt=False) for row in rows]

    def delete(
        self,
        credential_id: str,
        actor_id: str,
        actor_type: ActorType = ActorType.USER,
    ) -> bool:
        """Delete a credential."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Get credential info for audit before delete
                cur.execute(
                    "SELECT token_type, scope_type, scope_id, github_username FROM credentials.github_credentials WHERE id = %(id)s",
                    {"id": credential_id},
                )
                row = cur.fetchone()
                if not row:
                    return False

                token_type, scope_type, scope_id, github_username = row

                # Delete the credential
                cur.execute(
                    "DELETE FROM credentials.github_credentials WHERE id = %(id)s",
                    {"id": credential_id},
                )

                # Log audit entry
                self._log_audit(
                    cur,
                    credential_id=credential_id,
                    action=GitHubCredentialAction.DELETED,
                    actor_id=actor_id,
                    actor_type=actor_type,
                    details={
                        "token_type": token_type,
                        "scope_type": scope_type,
                        "scope_id": scope_id,
                        "github_username": github_username,
                    },
                )

            conn.commit()
            return True

    # -------------------------------------------------------------------------
    # Usage Tracking & Failure Handling
    # -------------------------------------------------------------------------

    def record_success(
        self,
        credential_id: str,
        rate_limit: Optional[int] = None,
        rate_limit_remaining: Optional[int] = None,
        rate_limit_reset: Optional[datetime] = None,
        run_id: Optional[str] = None,
    ) -> None:
        """Record successful use of a credential (resets failure count)."""
        now = datetime.now(timezone.utc)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE credentials.github_credentials
                    SET
                        failure_count = 0,
                        last_used_at = %(now)s,
                        rate_limit = COALESCE(%(rate_limit)s, rate_limit),
                        rate_limit_remaining = COALESCE(%(rate_limit_remaining)s, rate_limit_remaining),
                        rate_limit_reset = COALESCE(%(rate_limit_reset)s, rate_limit_reset),
                        updated_at = %(now)s
                    WHERE id = %(id)s
                    """,
                    {
                        "id": credential_id,
                        "now": now,
                        "rate_limit": rate_limit,
                        "rate_limit_remaining": rate_limit_remaining,
                        "rate_limit_reset": rate_limit_reset,
                    },
                )

                self._log_audit(
                    cur,
                    credential_id=credential_id,
                    action=GitHubCredentialAction.USED,
                    actor_id=None,
                    actor_type=ActorType.SYSTEM,
                    details={
                        "run_id": run_id,
                        "rate_limit_remaining": rate_limit_remaining,
                    } if run_id or rate_limit_remaining else {},
                )

            conn.commit()

    def record_failure(
        self,
        credential_id: str,
        error_code: int,
        error_message: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> bool:
        """Record authentication failure for a credential.

        Returns:
            True if credential was auto-disabled due to reaching threshold
        """
        now = datetime.now(timezone.utc)
        disabled = False

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Increment failure count
                cur.execute(
                    """
                    UPDATE credentials.github_credentials
                    SET
                        failure_count = failure_count + 1,
                        last_used_at = %(now)s,
                        updated_at = %(now)s
                    WHERE id = %(id)s
                    RETURNING failure_count
                    """,
                    {"id": credential_id, "now": now},
                )
                row = cur.fetchone()

                if row:
                    new_count = row[0]

                    # Check if we need to disable
                    if new_count >= self.FAILURE_LOCKOUT_THRESHOLD:
                        cur.execute(
                            """
                            UPDATE credentials.github_credentials
                            SET is_valid = false
                            WHERE id = %(id)s
                            """,
                            {"id": credential_id},
                        )
                        disabled = True

                        self._log_audit(
                            cur,
                            credential_id=credential_id,
                            action=GitHubCredentialAction.DISABLED,
                            actor_id=None,
                            actor_type=ActorType.SYSTEM,
                            details={
                                "reason": "consecutive_failures",
                                "failure_count": new_count,
                            },
                        )

                    # Log the failure
                    self._log_audit(
                        cur,
                        credential_id=credential_id,
                        action=GitHubCredentialAction.FAILED,
                        actor_id=None,
                        actor_type=ActorType.SYSTEM,
                        details={
                            "error_code": error_code,
                            "error_message": error_message,
                            "run_id": run_id,
                            "failure_count": new_count,
                        },
                    )

            conn.commit()

        return disabled

    def re_enable(
        self,
        credential_id: str,
        new_token: str,
        actor_id: str,
    ) -> Optional[GitHubCredential]:
        """Re-enable a disabled credential with a new token.

        Validates the new token before re-enabling.

        Returns:
            Updated credential if successful, None if credential not found

        Raises:
            ValueError: If new token validation fails
        """
        # Validate the new token
        validation = validate_github_token(new_token)
        if not validation.is_valid:
            raise ValueError(f"GitHub token validation failed: {validation.error}")

        now = datetime.now(timezone.utc)
        token_type = detect_token_type(new_token)
        token_prefix = get_token_prefix(new_token)
        token_encrypted = self._encryption.encrypt(new_token)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE credentials.github_credentials
                    SET
                        is_valid = true,
                        failure_count = 0,
                        token_type = %(token_type)s,
                        token_prefix = %(token_prefix)s,
                        token_encrypted = %(token_encrypted)s,
                        scopes = %(scopes)s,
                        rate_limit = %(rate_limit)s,
                        rate_limit_remaining = %(rate_limit_remaining)s,
                        rate_limit_reset = %(rate_limit_reset)s,
                        last_validated_at = %(now)s,
                        github_username = %(github_username)s,
                        github_user_id = %(github_user_id)s,
                        updated_at = %(now)s
                    WHERE id = %(id)s
                    RETURNING id
                    """,
                    {
                        "id": credential_id,
                        "token_type": token_type.value,
                        "token_prefix": token_prefix,
                        "token_encrypted": token_encrypted,
                        "scopes": validation.scopes,
                        "rate_limit": validation.rate_limit,
                        "rate_limit_remaining": validation.rate_limit_remaining,
                        "rate_limit_reset": validation.rate_limit_reset,
                        "now": now,
                        "github_username": validation.username,
                        "github_user_id": validation.user_id,
                    },
                )

                if cur.fetchone():
                    self._log_audit(
                        cur,
                        credential_id=credential_id,
                        action=GitHubCredentialAction.RE_ENABLED,
                        actor_id=actor_id,
                        actor_type=ActorType.USER,
                        details={
                            "token_type": token_type.value,
                            "github_username": validation.username,
                        },
                    )
                    conn.commit()
                    return self.get_by_id(credential_id)

            return None

    # -------------------------------------------------------------------------
    # Audit Log
    # -------------------------------------------------------------------------

    def get_audit_log(
        self,
        credential_id: str,
        limit: int = 50,
    ) -> List[GitHubCredentialAuditEntry]:
        """Get audit log entries for a credential."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, credential_id, action, actor_id, actor_type, details, created_at
                    FROM credentials.github_credential_audit_log
                    WHERE credential_id = %(credential_id)s
                    ORDER BY created_at DESC
                    LIMIT %(limit)s
                    """,
                    {"credential_id": credential_id, "limit": limit},
                )

                return [
                    GitHubCredentialAuditEntry(
                        id=row[0],
                        credential_id=row[1],
                        action=GitHubCredentialAction(row[2]),
                        actor_id=row[3],
                        actor_type=ActorType(row[4]),
                        details=row[5] or {},
                        created_at=row[6],
                    )
                    for row in cur.fetchall()
                ]

    def _log_audit(
        self,
        cur,
        credential_id: str,
        action: GitHubCredentialAction,
        actor_id: Optional[str],
        actor_type: ActorType,
        details: Dict[str, Any],
    ) -> None:
        """Log an audit entry (within existing transaction)."""
        audit_id = f"ghaudit-{uuid.uuid4().hex[:12]}"

        cur.execute(
            """
            INSERT INTO credentials.github_credential_audit_log (
                id, credential_id, action, actor_id, actor_type, details
            ) VALUES (
                %(id)s, %(credential_id)s, %(action)s, %(actor_id)s, %(actor_type)s, %(details)s
            )
            """,
            {
                "id": audit_id,
                "credential_id": credential_id,
                "action": action.value,
                "actor_id": actor_id,
                "actor_type": actor_type.value,
                "details": json.dumps(details),
            },
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _row_to_credential(self, row, decrypt: bool = False) -> GitHubCredential:
        """Convert database row to GitHubCredential."""
        (
            id_, scope_type, scope_id, token_type, name,
            token_prefix, token_encrypted, is_valid, failure_count,
            scopes, rate_limit, rate_limit_remaining, rate_limit_reset,
            last_used_at, last_validated_at, github_username, github_user_id,
            created_by, created_at, updated_at, metadata
        ) = row

        credential = GitHubCredential(
            id=id_,
            scope_type=CredentialScopeType(scope_type),
            scope_id=scope_id,
            token_type=GitHubTokenType(token_type),
            name=name,
            token_prefix=token_prefix,
            is_valid=is_valid,
            failure_count=failure_count,
            scopes=scopes,
            rate_limit=rate_limit,
            rate_limit_remaining=rate_limit_remaining,
            rate_limit_reset=rate_limit_reset,
            last_used_at=last_used_at,
            last_validated_at=last_validated_at,
            github_username=github_username,
            github_user_id=github_user_id,
            created_by=created_by,
            created_at=created_at,
            updated_at=updated_at,
            metadata=metadata or {},
        )

        if decrypt:
            try:
                credential._decrypted_token = self._encryption.decrypt(token_encrypted)
            except ValueError as e:
                logger.error(f"Failed to decrypt credential {id_}: {e}")

        return credential
