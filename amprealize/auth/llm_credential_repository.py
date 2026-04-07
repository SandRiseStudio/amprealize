"""LLM Credential Repository.

Manages BYOK credentials with encrypted storage, failure tracking,
and audit logging.

Behavior: behavior_align_storage_layers
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from ..storage.postgres_pool import PostgresPool
from ..utils.dsn import resolve_postgres_dsn
from .credential_encryption import CredentialEncryptionService


logger = logging.getLogger(__name__)


class CredentialScopeType(str, Enum):
    """Scope type for credentials."""
    ORG = "org"
    PROJECT = "project"


class CredentialAction(str, Enum):
    """Actions for audit logging."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    USED = "used"
    FAILED = "failed"
    DISABLED = "disabled"
    RE_ENABLED = "re-enabled"


class ActorType(str, Enum):
    """Actor types for audit logging."""
    USER = "user"
    SERVICE = "service"
    SYSTEM = "system"


@dataclass
class LLMCredential:
    """Represents an LLM provider credential."""

    id: str
    scope_type: CredentialScopeType
    scope_id: str
    provider: str
    name: str
    key_prefix: str
    is_valid: bool = True
    failure_count: int = 0
    last_used_at: Optional[datetime] = None
    last_validated_at: Optional[datetime] = None
    created_by: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Only populated when decryption is requested
    _decrypted_key: Optional[str] = field(default=None, repr=False)

    @property
    def decrypted_key(self) -> Optional[str]:
        """Return decrypted API key if available."""
        return self._decrypted_key

    @property
    def masked_key(self) -> str:
        """Return masked key for display."""
        return f"{self.key_prefix}****"

    def to_dict(self, include_key: bool = False) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        result = {
            "id": self.id,
            "scope_type": self.scope_type.value if isinstance(self.scope_type, CredentialScopeType) else self.scope_type,
            "scope_id": self.scope_id,
            "provider": self.provider,
            "name": self.name,
            "key_prefix": self.key_prefix,
            "masked_key": self.masked_key,
            "is_valid": self.is_valid,
            "failure_count": self.failure_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "last_validated_at": self.last_validated_at.isoformat() if self.last_validated_at else None,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata,
        }
        if include_key and self._decrypted_key:
            result["api_key"] = self._decrypted_key
        return result


@dataclass
class CreateCredentialRequest:
    """Request to create a new credential."""

    scope_type: CredentialScopeType
    scope_id: str
    provider: str
    name: str
    api_key: str
    created_by: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CredentialAuditEntry:
    """Audit log entry for credential operations."""

    id: str
    credential_id: str
    action: CredentialAction
    actor_id: Optional[str]
    actor_type: ActorType
    details: Dict[str, Any]
    created_at: datetime


class LLMCredentialRepository:
    """Repository for BYOK credential CRUD with encryption and audit logging."""

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
        self._pool = pool or PostgresPool(dsn or resolve_postgres_dsn())
        self._encryption = encryption_service or CredentialEncryptionService()

    # -------------------------------------------------------------------------
    # CRUD Operations
    # -------------------------------------------------------------------------

    def create(self, request: CreateCredentialRequest) -> LLMCredential:
        """Create a new credential.

        If a credential already exists for the same scope/provider, it will be
        replaced (upsert behavior for key rotation).
        """
        credential_id = f"cred-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        # Encrypt the API key
        key_prefix = self._encryption.get_key_prefix(request.api_key)
        key_encrypted = self._encryption.encrypt(request.api_key)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Upsert: replace existing credential for same scope/provider
                cur.execute(
                    """
                        INSERT INTO credentials.llm_credentials (
                            id, scope_type, scope_id, provider, name,
                            key_prefix, key_encrypted, is_valid, failure_count,
                            created_by, created_at, updated_at, metadata
                        ) VALUES (
                            %(id)s, %(scope_type)s, %(scope_id)s, %(provider)s, %(name)s,
                            %(key_prefix)s, %(key_encrypted)s, true, 0,
                            %(created_by)s, %(created_at)s, %(updated_at)s, %(metadata)s::jsonb
                        )
                        ON CONFLICT (scope_type, scope_id, provider)
                        DO UPDATE SET
                            name = EXCLUDED.name,
                            key_prefix = EXCLUDED.key_prefix,
                            key_encrypted = EXCLUDED.key_encrypted,
                            is_valid = true,
                            failure_count = 0,
                            updated_at = EXCLUDED.updated_at,
                            metadata = EXCLUDED.metadata
                        RETURNING id, created_at
                    """,
                    {
                        "id": credential_id,
                        "scope_type": request.scope_type.value,
                        "scope_id": request.scope_id,
                        "provider": request.provider,
                        "name": request.name,
                        "key_prefix": key_prefix,
                        "key_encrypted": key_encrypted,
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
                    action=CredentialAction.CREATED,
                    actor_id=request.created_by,
                    actor_type=ActorType.USER,
                    details={"provider": request.provider, "scope_type": request.scope_type.value},
                )

            conn.commit()

        return LLMCredential(
            id=returned_id,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
            provider=request.provider,
            name=request.name,
            key_prefix=key_prefix,
            is_valid=True,
            failure_count=0,
            created_by=request.created_by,
            created_at=now,
            updated_at=now,
            metadata=request.metadata or {},
        )

    def get_by_id(
        self,
        credential_id: str,
        decrypt: bool = False,
    ) -> Optional[LLMCredential]:
        """Get credential by ID."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id, scope_type, scope_id, provider, name,
                        key_prefix, key_encrypted, is_valid, failure_count,
                        last_used_at, last_validated_at, created_by,
                        created_at, updated_at, metadata
                    FROM credentials.llm_credentials
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
        provider: Optional[str] = None,
        include_invalid: bool = False,
        decrypt: bool = False,
    ) -> List[LLMCredential]:
        """Get credentials for a scope (org or project)."""
        with self._pool.connection() as conn:
            query = """
                SELECT
                    id, scope_type, scope_id, provider, name,
                    key_prefix, key_encrypted, is_valid, failure_count,
                    last_used_at, last_validated_at, created_by,
                    created_at, updated_at, metadata
                FROM credentials.llm_credentials
                WHERE scope_type = %(scope_type)s AND scope_id = %(scope_id)s
            """
            params: Dict[str, Any] = {
                "scope_type": scope_type.value,
                "scope_id": scope_id,
            }

            if provider:
                query += " AND provider = %(provider)s"
                params["provider"] = provider

            if not include_invalid:
                query += " AND is_valid = true"

            query += " ORDER BY provider, created_at DESC"

            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [self._row_to_credential(row, decrypt=decrypt) for row in rows]

    def get_for_provider(
        self,
        provider: str,
        scope_type: CredentialScopeType,
        scope_id: str,
        decrypt: bool = False,
    ) -> Optional[LLMCredential]:
        """Get the active credential for a specific provider and scope."""
        credentials = self.get_for_scope(
            scope_type=scope_type,
            scope_id=scope_id,
            provider=provider,
            include_invalid=False,
            decrypt=decrypt,
        )
        return credentials[0] if credentials else None

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
                    "SELECT provider, scope_type, scope_id FROM credentials.llm_credentials WHERE id = %(id)s",
                    {"id": credential_id},
                )
                row = cur.fetchone()
                if not row:
                    return False

                provider, scope_type, scope_id = row

                # Delete the credential
                cur.execute(
                    "DELETE FROM credentials.llm_credentials WHERE id = %(id)s",
                    {"id": credential_id},
                )

                # Log audit entry
                self._log_audit(
                    cur,
                    credential_id=credential_id,
                    action=CredentialAction.DELETED,
                    actor_id=actor_id,
                    actor_type=actor_type,
                    details={"provider": provider, "scope_type": scope_type, "scope_id": scope_id},
                )

            conn.commit()
            return True

    # -------------------------------------------------------------------------
    # Failure Tracking
    # -------------------------------------------------------------------------

    def record_success(
        self,
        credential_id: str,
        run_id: Optional[str] = None,
    ) -> None:
        """Record successful use of a credential (resets failure count)."""
        now = datetime.now(timezone.utc)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE credentials.llm_credentials
                    SET
                        failure_count = 0,
                        last_used_at = %(now)s,
                        last_validated_at = %(now)s,
                        updated_at = %(now)s
                    WHERE id = %(id)s
                    """,
                    {"id": credential_id, "now": now},
                )

                self._log_audit(
                    cur,
                    credential_id=credential_id,
                    action=CredentialAction.USED,
                    actor_id=None,
                    actor_type=ActorType.SYSTEM,
                    details={"run_id": run_id} if run_id else {},
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
                    UPDATE credentials.llm_credentials
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
                            UPDATE credentials.llm_credentials
                            SET is_valid = false
                            WHERE id = %(id)s
                            """,
                            {"id": credential_id},
                        )
                        disabled = True

                        self._log_audit(
                            cur,
                            credential_id=credential_id,
                            action=CredentialAction.DISABLED,
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
                        action=CredentialAction.FAILED,
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
        actor_id: str,
    ) -> bool:
        """Re-enable a disabled credential after user provides new key."""
        now = datetime.now(timezone.utc)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE credentials.llm_credentials
                    SET
                        is_valid = true,
                        failure_count = 0,
                        updated_at = %(now)s
                    WHERE id = %(id)s AND is_valid = false
                    RETURNING id
                    """,
                    {"id": credential_id, "now": now},
                )

                if cur.fetchone():
                    self._log_audit(
                        cur,
                        credential_id=credential_id,
                        action=CredentialAction.RE_ENABLED,
                        actor_id=actor_id,
                        actor_type=ActorType.USER,
                        details={},
                    )
                    conn.commit()
                    return True

            return False

    # -------------------------------------------------------------------------
    # Audit Log
    # -------------------------------------------------------------------------

    def get_audit_log(
        self,
        credential_id: str,
        limit: int = 50,
    ) -> List[CredentialAuditEntry]:
        """Get audit log entries for a credential."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, credential_id, action, actor_id, actor_type, details, created_at
                    FROM credentials.llm_credential_audit_log
                    WHERE credential_id = %(credential_id)s
                    ORDER BY created_at DESC
                    LIMIT %(limit)s
                    """,
                    {"credential_id": credential_id, "limit": limit},
                )

                return [
                    CredentialAuditEntry(
                        id=row[0],
                        credential_id=row[1],
                        action=CredentialAction(row[2]),
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
        action: CredentialAction,
        actor_id: Optional[str],
        actor_type: ActorType,
        details: Dict[str, Any],
    ) -> None:
        """Log an audit entry (within existing transaction).

        Args:
            cur: psycopg2 cursor from the current transaction
        """
        audit_id = f"audit-{uuid.uuid4().hex[:12]}"

        cur.execute(
            """
            INSERT INTO credentials.llm_credential_audit_log (
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

    def _row_to_credential(self, row, decrypt: bool = False) -> LLMCredential:
        """Convert database row to LLMCredential."""
        (
            id_, scope_type, scope_id, provider, name,
            key_prefix, key_encrypted, is_valid, failure_count,
            last_used_at, last_validated_at, created_by,
            created_at, updated_at, metadata
        ) = row

        credential = LLMCredential(
            id=id_,
            scope_type=CredentialScopeType(scope_type),
            scope_id=scope_id,
            provider=provider,
            name=name,
            key_prefix=key_prefix,
            is_valid=is_valid,
            failure_count=failure_count,
            last_used_at=last_used_at,
            last_validated_at=last_validated_at,
            created_by=created_by,
            created_at=created_at,
            updated_at=updated_at,
            metadata=metadata or {},
        )

        if decrypt:
            try:
                credential._decrypted_key = self._encryption.decrypt(key_encrypted)
            except ValueError as e:
                logger.error(f"Failed to decrypt credential {id_}: {e}")

        return credential
