"""GitHub App Installation Repository.

Manages GitHub App installations with encrypted token caching.
Allows multiple projects/orgs to share a single GitHub App installation.

Behavior: behavior_align_storage_layers

Following the pattern from github_credential_repository.py for consistency.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from ..storage.postgres_pool import PostgresPool
from ..utils.dsn import resolve_postgres_dsn
from .credential_encryption import CredentialEncryptionService
from .github_credential_repository import CredentialScopeType


logger = logging.getLogger(__name__)

# DSN resolution constants (same as other auth services)
_AUTH_PG_DSN_ENV = "AMPREALIZE_AUTH_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class GitHubAppInstallation:
    """Represents a GitHub App installation."""

    id: str
    installation_id: int
    app_id: Optional[int]
    account_type: str  # 'User' or 'Organization'
    account_login: str
    account_id: int
    account_avatar_url: Optional[str]
    scope_type: CredentialScopeType
    scope_id: str
    repository_selection: Optional[str]  # 'all' or 'selected'
    selected_repository_ids: List[int]
    permissions: Dict[str, str]
    events: List[str]
    is_active: bool = True
    suspended_at: Optional[datetime] = None
    suspended_reason: Optional[str] = None
    installed_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Token cache (populated when requested)
    _cached_token: Optional[str] = field(default=None, repr=False)
    _cached_token_expires_at: Optional[datetime] = field(default=None, repr=False)

    @property
    def has_required_permissions(self) -> bool:
        """Check if installation has required permissions for PR operations.

        Required: contents:write, pull_requests:write
        """
        return (
            self.permissions.get("contents") == "write"
            and self.permissions.get("pull_requests") == "write"
        )

    @property
    def permission_warning(self) -> Optional[str]:
        """Return warning if permissions are insufficient."""
        if self.has_required_permissions:
            return None

        missing = []
        if self.permissions.get("contents") != "write":
            missing.append("contents:write")
        if self.permissions.get("pull_requests") != "write":
            missing.append("pull_requests:write")

        return f"Missing permissions: {', '.join(missing)}. Configure in GitHub App settings."

    def can_access_repo(self, repo_id: int) -> bool:
        """Check if installation has access to a specific repository."""
        if self.repository_selection == "all":
            return True
        return repo_id in self.selected_repository_ids

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "installation_id": self.installation_id,
            "app_id": self.app_id,
            "account_type": self.account_type,
            "account_login": self.account_login,
            "account_id": self.account_id,
            "account_avatar_url": self.account_avatar_url,
            "scope_type": self.scope_type.value if isinstance(self.scope_type, Enum) else self.scope_type,
            "scope_id": self.scope_id,
            "repository_selection": self.repository_selection,
            "selected_repository_ids": self.selected_repository_ids,
            "permissions": self.permissions,
            "events": self.events,
            "has_required_permissions": self.has_required_permissions,
            "permission_warning": self.permission_warning,
            "is_active": self.is_active,
            "suspended_at": self.suspended_at.isoformat() if self.suspended_at else None,
            "suspended_reason": self.suspended_reason,
            "installed_by": self.installed_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata,
        }


@dataclass
class GitHubAppInstallationLink:
    """Link between an Amprealize scope and a GitHub App installation."""

    id: str
    installation_id: int
    scope_type: CredentialScopeType
    scope_id: str
    linked_by: Optional[str]
    created_at: Optional[datetime]


@dataclass
class CachedInstallationToken:
    """Cached installation access token."""

    token: str
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        """Check if token is expired (with 5 minute buffer)."""
        return datetime.now(timezone.utc) >= self.expires_at - timedelta(minutes=5)


# ==============================================================================
# Repository
# ==============================================================================


class GitHubAppInstallationRepository:
    """Repository for GitHub App installation CRUD operations.

    Behavior: behavior_align_storage_layers
    """

    def __init__(
        self,
        pool: Optional[PostgresPool] = None,
        encryption_service: Optional[CredentialEncryptionService] = None,
        dsn: Optional[str] = None,
    ) -> None:
        self._pool: PostgresPool
        if pool:
            self._pool = pool
        else:
            resolved_dsn = resolve_postgres_dsn(
                service="AUTH",
                explicit_dsn=dsn,
                env_var=_AUTH_PG_DSN_ENV,
                default_dsn=_DEFAULT_PG_DSN,
            )
            self._pool = PostgresPool(resolved_dsn)
        self._encryption = encryption_service or CredentialEncryptionService()

    # --------------------------------------------------------------------------
    # Installation CRUD
    # --------------------------------------------------------------------------

    def create_or_update_installation(
        self,
        installation_id: int,
        account_type: str,
        account_login: str,
        account_id: int,
        scope_type: CredentialScopeType,
        scope_id: str,
        app_id: Optional[int] = None,
        account_avatar_url: Optional[str] = None,
        repository_selection: Optional[str] = None,
        selected_repository_ids: Optional[List[int]] = None,
        permissions: Optional[Dict[str, str]] = None,
        events: Optional[List[str]] = None,
        installed_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GitHubAppInstallation:
        """Create or update a GitHub App installation record.

        If an installation with the same installation_id already exists,
        updates it. Otherwise, creates a new record.
        """
        import json

        with self._pool.connection() as conn:
            cursor = conn.cursor()

            # Check if installation exists
            cursor.execute(
                """
                SELECT id FROM auth.github_app_installations
                WHERE installation_id = %s
                LIMIT 1
                """,
                (installation_id,),
            )
            existing = cursor.fetchone()

            now = datetime.now(timezone.utc)

            if existing:
                # Update existing installation
                record_id = existing[0]
                cursor.execute(
                    """
                    UPDATE auth.github_app_installations SET
                        account_type = %s,
                        account_login = %s,
                        account_id = %s,
                        app_id = %s,
                        account_avatar_url = %s,
                        repository_selection = %s,
                        selected_repository_ids = %s,
                        permissions = %s,
                        events = %s,
                        is_active = true,
                        suspended_at = NULL,
                        suspended_reason = NULL,
                        updated_at = %s,
                        metadata = COALESCE(%s, metadata)
                    WHERE id = %s
                    """,
                    (
                        account_type,
                        account_login,
                        account_id,
                        app_id,
                        account_avatar_url,
                        repository_selection,
                        json.dumps(selected_repository_ids or []),
                        json.dumps(permissions or {}),
                        json.dumps(events or []),
                        now,
                        json.dumps(metadata) if metadata else None,
                        record_id,
                    ),
                )
                logger.info(
                    f"Updated GitHub App installation {installation_id} "
                    f"for {account_login}"
                )
            else:
                # Create new installation
                record_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO auth.github_app_installations (
                        id, installation_id, app_id, account_type, account_login,
                        account_id, account_avatar_url, scope_type, scope_id,
                        repository_selection, selected_repository_ids,
                        permissions, events, is_active, installed_by,
                        created_at, updated_at, metadata
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record_id,
                        installation_id,
                        app_id,
                        account_type,
                        account_login,
                        account_id,
                        account_avatar_url,
                        scope_type.value if isinstance(scope_type, Enum) else scope_type,
                        scope_id,
                        repository_selection,
                        json.dumps(selected_repository_ids or []),
                        json.dumps(permissions or {}),
                        json.dumps(events or []),
                        True,
                        installed_by,
                        now,
                        now,
                        json.dumps(metadata or {}),
                    ),
                )
                logger.info(
                    f"Created GitHub App installation {installation_id} "
                    f"for {account_login} linked to {scope_type}:{scope_id}"
                )

            conn.commit()

            return GitHubAppInstallation(
                id=record_id,
                installation_id=installation_id,
                app_id=app_id,
                account_type=account_type,
                account_login=account_login,
                account_id=account_id,
                account_avatar_url=account_avatar_url,
                scope_type=CredentialScopeType(scope_type) if isinstance(scope_type, str) else scope_type,
                scope_id=scope_id,
                repository_selection=repository_selection,
                selected_repository_ids=selected_repository_ids or [],
                permissions=permissions or {},
                events=events or [],
                is_active=True,
                installed_by=installed_by,
                created_at=now,
                updated_at=now,
                metadata=metadata or {},
            )

    def get_installation_by_id(
        self,
        installation_id: int,
    ) -> Optional[GitHubAppInstallation]:
        """Get a GitHub App installation by its GitHub installation ID."""
        with self._pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    id, installation_id, app_id, account_type, account_login,
                    account_id, account_avatar_url, scope_type, scope_id,
                    repository_selection, selected_repository_ids, permissions,
                    events, is_active, suspended_at, suspended_reason,
                    installed_by, created_at, updated_at, metadata,
                    cached_token_encrypted, cached_token_expires_at
                FROM auth.github_app_installations
                WHERE installation_id = %s
                LIMIT 1
                """,
                (installation_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            return self._row_to_installation(row)

    def get_installation_for_scope(
        self,
        scope_type: CredentialScopeType,
        scope_id: str,
    ) -> Optional[GitHubAppInstallation]:
        """Get the active GitHub App installation for a scope.

        First checks the links table, then falls back to direct scope match.
        """
        with self._pool.connection() as conn:
            cursor = conn.cursor()

            # First, check links table
            cursor.execute(
                """
                SELECT i.id, i.installation_id, i.app_id, i.account_type, i.account_login,
                       i.account_id, i.account_avatar_url, i.scope_type, i.scope_id,
                       i.repository_selection, i.selected_repository_ids, i.permissions,
                       i.events, i.is_active, i.suspended_at, i.suspended_reason,
                       i.installed_by, i.created_at, i.updated_at, i.metadata,
                       i.cached_token_encrypted, i.cached_token_expires_at
                FROM auth.github_app_installations i
                JOIN auth.github_app_installation_links l ON l.installation_id = i.installation_id
                WHERE l.scope_type = %s AND l.scope_id = %s AND i.is_active = true
                LIMIT 1
                """,
                (
                    scope_type.value if isinstance(scope_type, Enum) else scope_type,
                    scope_id,
                ),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_installation(row)

            # Fall back to direct scope match (for primary scope)
            cursor.execute(
                """
                SELECT
                    id, installation_id, app_id, account_type, account_login,
                    account_id, account_avatar_url, scope_type, scope_id,
                    repository_selection, selected_repository_ids, permissions,
                    events, is_active, suspended_at, suspended_reason,
                    installed_by, created_at, updated_at, metadata,
                    cached_token_encrypted, cached_token_expires_at
                FROM auth.github_app_installations
                WHERE scope_type = %s AND scope_id = %s AND is_active = true
                LIMIT 1
                """,
                (
                    scope_type.value if isinstance(scope_type, Enum) else scope_type,
                    scope_id,
                ),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_installation(row)

            return None

    def list_installations_for_account(
        self,
        account_login: str,
    ) -> List[GitHubAppInstallation]:
        """List all installations for a GitHub account (user or org)."""
        with self._pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    id, installation_id, app_id, account_type, account_login,
                    account_id, account_avatar_url, scope_type, scope_id,
                    repository_selection, selected_repository_ids, permissions,
                    events, is_active, suspended_at, suspended_reason,
                    installed_by, created_at, updated_at, metadata,
                    cached_token_encrypted, cached_token_expires_at
                FROM auth.github_app_installations
                WHERE account_login = %s
                ORDER BY created_at DESC
                """,
                (account_login,),
            )
            return [self._row_to_installation(row) for row in cursor.fetchall()]

    def deactivate_installation(
        self,
        installation_id: int,
        reason: Optional[str] = None,
    ) -> bool:
        """Mark an installation as inactive (e.g., on uninstall)."""
        with self._pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE auth.github_app_installations
                SET is_active = false,
                    suspended_at = %s,
                    suspended_reason = %s,
                    updated_at = %s
                WHERE installation_id = %s
                """,
                (
                    datetime.now(timezone.utc),
                    reason or "Uninstalled",
                    datetime.now(timezone.utc),
                    installation_id,
                ),
            )
            affected = cursor.rowcount
            conn.commit()
            logger.info(f"Deactivated GitHub App installation {installation_id}: {reason}")
            return affected > 0

    # --------------------------------------------------------------------------
    # Installation Links (multi-project support)
    # --------------------------------------------------------------------------

    def link_installation_to_scope(
        self,
        installation_id: int,
        scope_type: CredentialScopeType,
        scope_id: str,
        linked_by: Optional[str] = None,
    ) -> GitHubAppInstallationLink:
        """Link an existing installation to an additional scope.

        This allows multiple projects to share the same GitHub App installation.
        """
        with self._pool.connection() as conn:
            cursor = conn.cursor()

            # Check if link already exists
            cursor.execute(
                """
                SELECT id FROM auth.github_app_installation_links
                WHERE scope_type = %s AND scope_id = %s
                """,
                (
                    scope_type.value if isinstance(scope_type, Enum) else scope_type,
                    scope_id,
                ),
            )
            existing = cursor.fetchone()

            link_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            if existing:
                # Update existing link to new installation
                link_id = existing[0]
                cursor.execute(
                    """
                    UPDATE auth.github_app_installation_links
                    SET installation_id = %s, linked_by = %s
                    WHERE id = %s
                    """,
                    (installation_id, linked_by, link_id),
                )
                logger.info(
                    f"Updated link for {scope_type}:{scope_id} to installation {installation_id}"
                )
            else:
                # Create new link
                cursor.execute(
                    """
                    INSERT INTO auth.github_app_installation_links (
                        id, installation_id, scope_type, scope_id, linked_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        link_id,
                        installation_id,
                        scope_type.value if isinstance(scope_type, Enum) else scope_type,
                        scope_id,
                        linked_by,
                        now,
                    ),
                )
                logger.info(
                    f"Linked {scope_type}:{scope_id} to installation {installation_id}"
                )

            conn.commit()

            return GitHubAppInstallationLink(
                id=link_id,
                installation_id=installation_id,
                scope_type=CredentialScopeType(scope_type) if isinstance(scope_type, str) else scope_type,
                scope_id=scope_id,
                linked_by=linked_by,
                created_at=now,
            )

    def unlink_installation_from_scope(
        self,
        scope_type: CredentialScopeType,
        scope_id: str,
    ) -> bool:
        """Remove the link between a scope and its GitHub App installation.

        Note: This does NOT uninstall the app from GitHub, just removes the link.
        """
        with self._pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM auth.github_app_installation_links
                WHERE scope_type = %s AND scope_id = %s
                """,
                (
                    scope_type.value if isinstance(scope_type, Enum) else scope_type,
                    scope_id,
                ),
            )
            affected = cursor.rowcount
            conn.commit()
            logger.info(f"Unlinked {scope_type}:{scope_id} from GitHub App installation")
            return affected > 0

    # --------------------------------------------------------------------------
    # Token Caching
    # --------------------------------------------------------------------------

    def cache_installation_token(
        self,
        installation_id: int,
        token: str,
        expires_at: datetime,
    ) -> None:
        """Cache an encrypted installation access token."""
        encrypted = self._encryption.encrypt(token)

        with self._pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE auth.github_app_installations
                SET cached_token_encrypted = %s,
                    cached_token_expires_at = %s,
                    updated_at = %s
                WHERE installation_id = %s
                """,
                (encrypted, expires_at, datetime.now(timezone.utc), installation_id),
            )
            conn.commit()
            logger.debug(f"Cached token for installation {installation_id}")

    def get_cached_token(
        self,
        installation_id: int,
    ) -> Optional[CachedInstallationToken]:
        """Get cached installation token if still valid."""
        with self._pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT cached_token_encrypted, cached_token_expires_at
                FROM auth.github_app_installations
                WHERE installation_id = %s AND cached_token_encrypted IS NOT NULL
                """,
                (installation_id,),
            )
            row = cursor.fetchone()
            if not row or not row[0] or not row[1]:
                return None

            expires_at = row[1]
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))

            # Check if expired (with 5 minute buffer)
            if datetime.now(timezone.utc) >= expires_at - timedelta(minutes=5):
                return None

            token = self._encryption.decrypt(row[0])
            return CachedInstallationToken(token=token, expires_at=expires_at)

    def clear_cached_token(self, installation_id: int) -> None:
        """Clear the cached token for an installation."""
        with self._pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE auth.github_app_installations
                SET cached_token_encrypted = NULL,
                    cached_token_expires_at = NULL,
                    updated_at = %s
                WHERE installation_id = %s
                """,
                (datetime.now(timezone.utc), installation_id),
            )
            conn.commit()

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _row_to_installation(self, row: tuple) -> GitHubAppInstallation:
        """Convert a database row to a GitHubAppInstallation object."""
        return GitHubAppInstallation(
            id=row[0],
            installation_id=row[1],
            app_id=row[2],
            account_type=row[3],
            account_login=row[4],
            account_id=row[5],
            account_avatar_url=row[6],
            scope_type=CredentialScopeType(row[7]) if row[7] else CredentialScopeType.PROJECT,
            scope_id=row[8],
            repository_selection=row[9],
            selected_repository_ids=row[10] if isinstance(row[10], list) else [],
            permissions=row[11] if isinstance(row[11], dict) else {},
            events=row[12] if isinstance(row[12], list) else [],
            is_active=row[13],
            suspended_at=row[14],
            suspended_reason=row[15],
            installed_by=row[16],
            created_at=row[17],
            updated_at=row[18],
            metadata=row[19] if isinstance(row[19], dict) else {},
        )
