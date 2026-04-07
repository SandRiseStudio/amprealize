"""KMS-Encrypted Token Vault.

Secure storage for OAuth tokens using envelope encryption.
Supports AWS KMS, HashiCorp Vault, and local Fernet providers.

Phase 8 of MCP Auth Implementation Plan:
- Envelope encryption for OAuth access/refresh tokens
- Token rotation with configurable intervals
- Token blacklist for revocation
- Automatic cleanup of expired tokens
- Audit logging for all token operations

Behavior: behavior_lock_down_security_surface, behavior_prevent_secret_leaks
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple
import threading

from .credential_encryption import (
    AWSKMSProvider,
    EncryptionProvider,
    FernetProvider,
    HashiCorpVaultProvider,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Token Vault Enums and Data Classes
# ============================================================================

class TokenType(str, Enum):
    """Types of tokens stored in the vault."""
    ACCESS = "access"
    REFRESH = "refresh"
    API_KEY = "api_key"
    SERVICE_PRINCIPAL = "service_principal"


class TokenStatus(str, Enum):
    """Status of a stored token."""
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ROTATED = "rotated"


class TokenProvider(str, Enum):
    """OAuth providers for token storage."""
    GOOGLE = "google"
    GITHUB = "github"
    MICROSOFT = "microsoft"
    AMPREALIZE = "amprealize"  # Internal tokens
    CUSTOM = "custom"


@dataclass
class StoredToken:
    """Token stored in the vault."""
    id: str
    user_id: str
    provider: str
    token_type: TokenType
    access_token: str
    refresh_token: Optional[str] = None
    scopes: List[str] = field(default_factory=list)
    expires_at: Optional[datetime] = None
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: Optional[datetime] = None
    rotation_count: int = 0
    status: TokenStatus = TokenStatus.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if token is expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def needs_rotation(self, rotation_threshold: timedelta = timedelta(hours=12)) -> bool:
        """Check if token should be rotated based on age."""
        if self.refresh_token is None:
            return False  # Can't rotate without refresh token
        if self.expires_at is None:
            return False
        time_until_expiry = self.expires_at - datetime.now(timezone.utc)
        return time_until_expiry < rotation_threshold

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "provider": self.provider,
            "token_type": self.token_type.value,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "scopes": self.scopes,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "issued_at": self.issued_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "rotation_count": self.rotation_count,
            "status": self.status.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoredToken":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            provider=data["provider"],
            token_type=TokenType(data["token_type"]),
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            scopes=data.get("scopes", []),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            issued_at=datetime.fromisoformat(data["issued_at"]) if data.get("issued_at") else datetime.now(timezone.utc),
            last_used_at=datetime.fromisoformat(data["last_used_at"]) if data.get("last_used_at") else None,
            rotation_count=data.get("rotation_count", 0),
            status=TokenStatus(data.get("status", "active")),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TokenBlacklistEntry:
    """Entry in the token blacklist."""
    token_hash: str
    user_id: str
    provider: str
    reason: str
    revoked_at: datetime
    revoked_by: str
    expires_at: Optional[datetime] = None  # When blacklist entry can be cleaned up


@dataclass
class TokenVaultStats:
    """Statistics about the token vault."""
    total_tokens: int
    active_tokens: int
    expired_tokens: int
    revoked_tokens: int
    blacklist_size: int
    providers: Dict[str, int]  # Count per provider
    oldest_token_age_days: Optional[int] = None
    last_rotation: Optional[datetime] = None
    last_cleanup: Optional[datetime] = None


# ============================================================================
# Storage Backend Protocol
# ============================================================================

class TokenStorageBackend(Protocol):
    """Protocol for token storage backends (PostgreSQL, Redis, etc.)."""

    async def store_token(self, token: StoredToken, encrypted_data: str) -> None:
        """Store encrypted token data."""
        ...

    async def get_token(self, user_id: str, provider: str, token_type: TokenType) -> Optional[Tuple[StoredToken, str]]:
        """Retrieve token metadata and encrypted data."""
        ...

    async def update_token(self, token_id: str, updates: Dict[str, Any], encrypted_data: Optional[str] = None) -> bool:
        """Update token metadata and optionally encrypted data."""
        ...

    async def delete_token(self, token_id: str) -> bool:
        """Delete a token."""
        ...

    async def list_tokens(self, user_id: str, provider: Optional[str] = None) -> List[StoredToken]:
        """List tokens for a user (without decrypted values)."""
        ...

    async def add_to_blacklist(self, entry: TokenBlacklistEntry) -> None:
        """Add token hash to blacklist."""
        ...

    async def check_blacklist(self, token_hash: str) -> bool:
        """Check if token hash is blacklisted."""
        ...

    async def cleanup_expired(self, before: datetime) -> int:
        """Remove expired tokens and blacklist entries. Returns count deleted."""
        ...

    async def get_stats(self) -> TokenVaultStats:
        """Get vault statistics."""
        ...


# ============================================================================
# In-Memory Storage Backend (for testing)
# ============================================================================

class InMemoryTokenStorage:
    """In-memory token storage for testing."""

    def __init__(self) -> None:
        self._tokens: Dict[str, Tuple[StoredToken, str]] = {}  # id -> (token, encrypted_data)
        self._blacklist: Dict[str, TokenBlacklistEntry] = {}  # hash -> entry
        self._lock = threading.RLock()

    async def store_token(self, token: StoredToken, encrypted_data: str) -> None:
        with self._lock:
            self._tokens[token.id] = (token, encrypted_data)

    async def get_token(
        self, user_id: str, provider: str, token_type: TokenType
    ) -> Optional[Tuple[StoredToken, str]]:
        with self._lock:
            for token, encrypted_data in self._tokens.values():
                if (
                    token.user_id == user_id
                    and token.provider == provider
                    and token.token_type == token_type
                    and token.status == TokenStatus.ACTIVE
                ):
                    return (token, encrypted_data)
            return None

    async def get_token_by_id(self, token_id: str) -> Optional[Tuple[StoredToken, str]]:
        with self._lock:
            return self._tokens.get(token_id)

    async def update_token(
        self, token_id: str, updates: Dict[str, Any], encrypted_data: Optional[str] = None
    ) -> bool:
        with self._lock:
            if token_id not in self._tokens:
                return False
            token, old_encrypted = self._tokens[token_id]
            for key, value in updates.items():
                if hasattr(token, key):
                    setattr(token, key, value)
            self._tokens[token_id] = (token, encrypted_data or old_encrypted)
            return True

    async def delete_token(self, token_id: str) -> bool:
        with self._lock:
            if token_id in self._tokens:
                del self._tokens[token_id]
                return True
            return False

    async def list_tokens(self, user_id: str, provider: Optional[str] = None) -> List[StoredToken]:
        with self._lock:
            tokens = []
            for token, _ in self._tokens.values():
                if token.user_id == user_id:
                    if provider is None or token.provider == provider:
                        # Return copy without sensitive data
                        safe_token = StoredToken(
                            id=token.id,
                            user_id=token.user_id,
                            provider=token.provider,
                            token_type=token.token_type,
                            access_token="[REDACTED]",
                            refresh_token="[REDACTED]" if token.refresh_token else None,
                            scopes=token.scopes,
                            expires_at=token.expires_at,
                            issued_at=token.issued_at,
                            last_used_at=token.last_used_at,
                            rotation_count=token.rotation_count,
                            status=token.status,
                            metadata=token.metadata,
                        )
                        tokens.append(safe_token)
            return tokens

    async def add_to_blacklist(self, entry: TokenBlacklistEntry) -> None:
        with self._lock:
            self._blacklist[entry.token_hash] = entry

    async def check_blacklist(self, token_hash: str) -> bool:
        with self._lock:
            entry = self._blacklist.get(token_hash)
            if entry is None:
                return False
            # Check if blacklist entry itself expired
            if entry.expires_at and datetime.now(timezone.utc) > entry.expires_at:
                del self._blacklist[token_hash]
                return False
            return True

    async def cleanup_expired(self, before: datetime) -> int:
        with self._lock:
            deleted = 0
            # Clean up expired tokens
            expired_ids = [
                token_id
                for token_id, (token, _) in self._tokens.items()
                if token.expires_at and token.expires_at < before
            ]
            for token_id in expired_ids:
                del self._tokens[token_id]
                deleted += 1

            # Clean up expired blacklist entries
            expired_hashes = [
                token_hash
                for token_hash, entry in self._blacklist.items()
                if entry.expires_at and entry.expires_at < before
            ]
            for token_hash in expired_hashes:
                del self._blacklist[token_hash]
                deleted += 1

            return deleted

    async def get_stats(self) -> TokenVaultStats:
        with self._lock:
            active = sum(1 for t, _ in self._tokens.values() if t.status == TokenStatus.ACTIVE)
            expired = sum(1 for t, _ in self._tokens.values() if t.is_expired())
            revoked = sum(1 for t, _ in self._tokens.values() if t.status == TokenStatus.REVOKED)

            providers: Dict[str, int] = {}
            oldest_age = None
            now = datetime.now(timezone.utc)

            for token, _ in self._tokens.values():
                providers[token.provider] = providers.get(token.provider, 0) + 1
                age_days = (now - token.issued_at).days
                if oldest_age is None or age_days > oldest_age:
                    oldest_age = age_days

            return TokenVaultStats(
                total_tokens=len(self._tokens),
                active_tokens=active,
                expired_tokens=expired,
                revoked_tokens=revoked,
                blacklist_size=len(self._blacklist),
                providers=providers,
                oldest_token_age_days=oldest_age,
                last_rotation=None,  # Not tracked in memory
                last_cleanup=None,
            )

    def clear(self) -> None:
        """Clear all tokens and blacklist (for testing)."""
        with self._lock:
            self._tokens.clear()
            self._blacklist.clear()


# ============================================================================
# PostgreSQL Storage Backend
# ============================================================================

class PostgresTokenStorage:
    """PostgreSQL token storage backend."""

    def __init__(self, pool: Any) -> None:  # PostgresPool
        self._pool = pool

    async def store_token(self, token: StoredToken, encrypted_data: str) -> None:
        """Store encrypted token in PostgreSQL."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO auth.token_vault (
                    id, user_id, provider, token_type, encrypted_data,
                    scopes, expires_at, issued_at, last_used_at,
                    rotation_count, status, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (user_id, provider, token_type)
                DO UPDATE SET
                    encrypted_data = EXCLUDED.encrypted_data,
                    scopes = EXCLUDED.scopes,
                    expires_at = EXCLUDED.expires_at,
                    rotation_count = EXCLUDED.rotation_count,
                    status = EXCLUDED.status,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """,
                token.id,
                token.user_id,
                token.provider,
                token.token_type.value,
                encrypted_data,
                json.dumps(token.scopes),
                token.expires_at,
                token.issued_at,
                token.last_used_at,
                token.rotation_count,
                token.status.value,
                json.dumps(token.metadata),
            )

    async def get_token(
        self, user_id: str, provider: str, token_type: TokenType
    ) -> Optional[Tuple[StoredToken, str]]:
        """Retrieve token from PostgreSQL."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, provider, token_type, encrypted_data,
                       scopes, expires_at, issued_at, last_used_at,
                       rotation_count, status, metadata
                FROM auth.token_vault
                WHERE user_id = $1 AND provider = $2 AND token_type = $3
                  AND status = 'active'
                """,
                user_id,
                provider,
                token_type.value,
            )

            if row is None:
                return None

            token = StoredToken(
                id=str(row["id"]),
                user_id=row["user_id"],
                provider=row["provider"],
                token_type=TokenType(row["token_type"]),
                access_token="",  # Will be filled after decryption
                refresh_token=None,
                scopes=json.loads(row["scopes"]) if row["scopes"] else [],
                expires_at=row["expires_at"],
                issued_at=row["issued_at"],
                last_used_at=row["last_used_at"],
                rotation_count=row["rotation_count"],
                status=TokenStatus(row["status"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            )

            return (token, row["encrypted_data"])

    async def update_token(
        self, token_id: str, updates: Dict[str, Any], encrypted_data: Optional[str] = None
    ) -> bool:
        """Update token in PostgreSQL."""
        set_clauses = ["updated_at = now()"]
        params = [token_id]
        param_idx = 2

        for key, value in updates.items():
            if key in ("scopes", "metadata"):
                value = json.dumps(value)
            elif key == "status" and isinstance(value, TokenStatus):
                value = value.value
            elif key == "token_type" and isinstance(value, TokenType):
                value = value.value

            set_clauses.append(f"{key} = ${param_idx}")
            params.append(value)
            param_idx += 1

        if encrypted_data is not None:
            set_clauses.append(f"encrypted_data = ${param_idx}")
            params.append(encrypted_data)
            param_idx += 1

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE auth.token_vault
                SET {", ".join(set_clauses)}
                WHERE id = $1
                """,
                *params,
            )
            return result == "UPDATE 1"

    async def delete_token(self, token_id: str) -> bool:
        """Delete token from PostgreSQL."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM auth.token_vault WHERE id = $1",
                token_id,
            )
            return result == "DELETE 1"

    async def list_tokens(self, user_id: str, provider: Optional[str] = None) -> List[StoredToken]:
        """List tokens for a user (without encrypted data)."""
        query = """
            SELECT id, user_id, provider, token_type, scopes,
                   expires_at, issued_at, last_used_at,
                   rotation_count, status, metadata
            FROM auth.token_vault
            WHERE user_id = $1
        """
        params = [user_id]

        if provider:
            query += " AND provider = $2"
            params.append(provider)

        query += " ORDER BY issued_at DESC"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

            return [
                StoredToken(
                    id=str(row["id"]),
                    user_id=row["user_id"],
                    provider=row["provider"],
                    token_type=TokenType(row["token_type"]),
                    access_token="[REDACTED]",
                    refresh_token=None,
                    scopes=json.loads(row["scopes"]) if row["scopes"] else [],
                    expires_at=row["expires_at"],
                    issued_at=row["issued_at"],
                    last_used_at=row["last_used_at"],
                    rotation_count=row["rotation_count"],
                    status=TokenStatus(row["status"]),
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                )
                for row in rows
            ]

    async def add_to_blacklist(self, entry: TokenBlacklistEntry) -> None:
        """Add token hash to blacklist."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO auth.token_blacklist (
                    token_hash, user_id, provider, reason,
                    revoked_at, revoked_by, expires_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (token_hash) DO NOTHING
                """,
                entry.token_hash,
                entry.user_id,
                entry.provider,
                entry.reason,
                entry.revoked_at,
                entry.revoked_by,
                entry.expires_at,
            )

    async def check_blacklist(self, token_hash: str) -> bool:
        """Check if token hash is blacklisted."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM auth.token_blacklist
                WHERE token_hash = $1
                  AND (expires_at IS NULL OR expires_at > now())
                """,
                token_hash,
            )
            return row is not None

    async def cleanup_expired(self, before: datetime) -> int:
        """Remove expired tokens and blacklist entries."""
        deleted = 0

        async with self._pool.acquire() as conn:
            # Delete expired tokens
            result = await conn.execute(
                """
                DELETE FROM auth.token_vault
                WHERE expires_at < $1 AND status != 'active'
                """,
                before,
            )
            deleted += int(result.split()[-1]) if result else 0

            # Delete expired blacklist entries
            result = await conn.execute(
                """
                DELETE FROM auth.token_blacklist
                WHERE expires_at < $1
                """,
                before,
            )
            deleted += int(result.split()[-1]) if result else 0

        return deleted

    async def get_stats(self) -> TokenVaultStats:
        """Get vault statistics."""
        async with self._pool.acquire() as conn:
            # Get token counts
            stats_row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status = 'active') as active,
                    COUNT(*) FILTER (WHERE expires_at < now()) as expired,
                    COUNT(*) FILTER (WHERE status = 'revoked') as revoked,
                    MIN(issued_at) as oldest_issued
                FROM auth.token_vault
                """
            )

            # Get provider breakdown
            provider_rows = await conn.fetch(
                """
                SELECT provider, COUNT(*) as count
                FROM auth.token_vault
                GROUP BY provider
                """
            )

            # Get blacklist size
            blacklist_row = await conn.fetchrow(
                "SELECT COUNT(*) as count FROM auth.token_blacklist"
            )

            providers = {row["provider"]: row["count"] for row in provider_rows}
            oldest_age = None
            if stats_row["oldest_issued"]:
                oldest_age = (datetime.now(timezone.utc) - stats_row["oldest_issued"]).days

            return TokenVaultStats(
                total_tokens=stats_row["total"],
                active_tokens=stats_row["active"],
                expired_tokens=stats_row["expired"],
                revoked_tokens=stats_row["revoked"],
                blacklist_size=blacklist_row["count"],
                providers=providers,
                oldest_token_age_days=oldest_age,
            )


# ============================================================================
# Token Vault Main Class
# ============================================================================

class TokenVault:
    """
    KMS-Encrypted Token Vault.

    Provides secure storage for OAuth tokens with:
    - Envelope encryption (data key encrypted by KMS, data encrypted locally)
    - Token rotation with configurable thresholds
    - Token blacklist for revocation
    - Automatic cleanup of expired tokens
    - Audit logging for compliance

    Usage:
        # Create vault with Fernet (local development)
        vault = TokenVault.create_fernet(storage, encryption_key)

        # Create vault with AWS KMS (production)
        vault = TokenVault.create_aws_kms(storage, kms_key_id)

        # Create vault with HashiCorp Vault (enterprise)
        vault = TokenVault.create_hashicorp_vault(storage, vault_addr, transit_key)

        # Store token
        await vault.store_token(user_id, provider, access_token, refresh_token, scopes, expires_at)

        # Get token (auto-rotates if needed)
        token = await vault.get_token(user_id, provider)

        # Revoke token
        await vault.revoke_token(user_id, provider, reason="User logged out")
    """

    def __init__(
        self,
        storage: TokenStorageBackend,
        encryption_provider: EncryptionProvider,
        rotation_threshold: timedelta = timedelta(hours=12),
        blacklist_retention: timedelta = timedelta(days=30),
    ) -> None:
        """
        Initialize token vault.

        Args:
            storage: Storage backend for token persistence
            encryption_provider: Encryption provider (Fernet, KMS, Vault)
            rotation_threshold: Time before expiry to trigger rotation
            blacklist_retention: How long to keep revoked tokens in blacklist
        """
        self._storage = storage
        self._encryption = encryption_provider
        self._rotation_threshold = rotation_threshold
        self._blacklist_retention = blacklist_retention
        self._lock = threading.RLock()

        logger.info(
            "TokenVault initialized",
            extra={
                "rotation_threshold_hours": rotation_threshold.total_seconds() / 3600,
                "blacklist_retention_days": blacklist_retention.days,
            },
        )

    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    def create_fernet(
        cls,
        storage: TokenStorageBackend,
        encryption_key: Optional[str] = None,
        **kwargs,
    ) -> "TokenVault":
        """
        Create vault with Fernet encryption (local development).

        Args:
            storage: Storage backend
            encryption_key: Base64-encoded 32-byte key, or use AMPREALIZE_TOKEN_VAULT_KEY env var
            **kwargs: Additional arguments for TokenVault
        """
        key = encryption_key or os.getenv("AMPREALIZE_TOKEN_VAULT_KEY")
        if not key:
            raise ValueError(
                "Encryption key required. Set AMPREALIZE_TOKEN_VAULT_KEY env var "
                "or generate with: TokenVault.generate_fernet_key()"
            )
        provider = FernetProvider(key)
        return cls(storage, provider, **kwargs)

    @classmethod
    def create_aws_kms(
        cls,
        storage: TokenStorageBackend,
        kms_key_id: Optional[str] = None,
        region: Optional[str] = None,
        **kwargs,
    ) -> "TokenVault":
        """
        Create vault with AWS KMS encryption (production).

        Args:
            storage: Storage backend
            kms_key_id: KMS key ID or ARN, or use AMPREALIZE_KMS_KEY_ID env var
            region: AWS region, or use AWS_DEFAULT_REGION env var
            **kwargs: Additional arguments for TokenVault
        """
        key_id = kms_key_id or os.getenv("AMPREALIZE_KMS_KEY_ID")
        if not key_id:
            raise ValueError("KMS key ID required. Set AMPREALIZE_KMS_KEY_ID env var.")
        provider = AWSKMSProvider(key_id, region)
        return cls(storage, provider, **kwargs)

    @classmethod
    def create_hashicorp_vault(
        cls,
        storage: TokenStorageBackend,
        vault_addr: Optional[str] = None,
        transit_key: Optional[str] = None,
        vault_token: Optional[str] = None,
        **kwargs,
    ) -> "TokenVault":
        """
        Create vault with HashiCorp Vault encryption (enterprise).

        Args:
            storage: Storage backend
            vault_addr: Vault server address, or use VAULT_ADDR env var
            transit_key: Transit secrets engine key name, or use AMPREALIZE_VAULT_TRANSIT_KEY
            vault_token: Vault token, or use VAULT_TOKEN env var
            **kwargs: Additional arguments for TokenVault
        """
        addr = vault_addr or os.getenv("VAULT_ADDR")
        key = transit_key or os.getenv("AMPREALIZE_VAULT_TRANSIT_KEY", "amprealize-token-vault")
        if not addr:
            raise ValueError("Vault address required. Set VAULT_ADDR env var.")
        provider = HashiCorpVaultProvider(addr, key, vault_token)
        return cls(storage, provider, **kwargs)

    @staticmethod
    def generate_fernet_key() -> str:
        """Generate a new Fernet encryption key."""
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()

    # -------------------------------------------------------------------------
    # Token Operations
    # -------------------------------------------------------------------------

    async def store_token(
        self,
        user_id: str,
        provider: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
        token_type: TokenType = TokenType.ACCESS,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StoredToken:
        """
        Store a token in the vault.

        Args:
            user_id: User ID the token belongs to
            provider: OAuth provider (google, github, etc.)
            access_token: The access token to store
            refresh_token: Optional refresh token
            scopes: List of granted scopes
            expires_at: Token expiration time
            token_type: Type of token (access, refresh, api_key)
            metadata: Additional metadata

        Returns:
            StoredToken with ID for future reference
        """
        token = StoredToken(
            id=secrets.token_urlsafe(16),
            user_id=user_id,
            provider=provider,
            token_type=token_type,
            access_token=access_token,
            refresh_token=refresh_token,
            scopes=scopes or [],
            expires_at=expires_at,
            issued_at=datetime.now(timezone.utc),
            status=TokenStatus.ACTIVE,
            metadata=metadata or {},
        )

        # Encrypt token data
        encrypted_data = self._encrypt_token_data(token)

        # Store in backend
        await self._storage.store_token(token, encrypted_data)

        logger.info(
            "Token stored",
            extra={
                "user_id": user_id,
                "provider": provider,
                "token_type": token_type.value,
                "has_refresh": refresh_token is not None,
                "scopes_count": len(scopes or []),
            },
        )

        return token

    async def get_token(
        self,
        user_id: str,
        provider: str,
        token_type: TokenType = TokenType.ACCESS,
        auto_rotate: bool = True,
    ) -> Optional[StoredToken]:
        """
        Retrieve a token from the vault.

        Args:
            user_id: User ID
            provider: OAuth provider
            token_type: Type of token to retrieve
            auto_rotate: Whether to auto-rotate if near expiry

        Returns:
            StoredToken with decrypted access/refresh tokens, or None if not found
        """
        result = await self._storage.get_token(user_id, provider, token_type)
        if result is None:
            return None

        token, encrypted_data = result

        # Decrypt token data FIRST to get actual token values
        decrypted_token = self._decrypt_token_data(token, encrypted_data)

        # Check blacklist with ACTUAL decrypted token
        token_hash = self._hash_token(decrypted_token.access_token)
        if await self._storage.check_blacklist(token_hash):
            logger.warning(
                "Attempted to access blacklisted token",
                extra={"user_id": user_id, "provider": provider},
            )
            return None

        # Check if expired
        if decrypted_token.is_expired():
            logger.info(
                "Token expired",
                extra={"user_id": user_id, "provider": provider},
            )
            await self._storage.update_token(token.id, {"status": TokenStatus.EXPIRED})
            return None

        # Update last used and set on returned token
        now = datetime.now(timezone.utc)
        await self._storage.update_token(
            token.id,
            {"last_used_at": now},
        )
        decrypted_token.last_used_at = now  # Set on returned token too

        # Auto-rotate if needed
        if auto_rotate and decrypted_token.needs_rotation(self._rotation_threshold):
            logger.info(
                "Token needs rotation",
                extra={
                    "user_id": user_id,
                    "provider": provider,
                    "expires_at": decrypted_token.expires_at.isoformat() if decrypted_token.expires_at else None,
                },
            )
            # Note: Actual rotation requires OAuth refresh flow, which is provider-specific
            # The caller should handle rotation using decrypted_token.refresh_token

        return decrypted_token

    async def revoke_token(
        self,
        user_id: str,
        provider: str,
        reason: str,
        revoked_by: str,
        token_type: TokenType = TokenType.ACCESS,
    ) -> bool:
        """
        Revoke a token and add to blacklist.

        Args:
            user_id: User ID
            provider: OAuth provider
            reason: Reason for revocation
            revoked_by: ID of user/system performing revocation
            token_type: Type of token to revoke

        Returns:
            True if token was revoked, False if not found
        """
        result = await self._storage.get_token(user_id, provider, token_type)
        if result is None:
            return False

        token, encrypted_data = result

        # Decrypt to get the actual token for blacklisting
        decrypted = self._decrypt_token_data(token, encrypted_data)

        # Add to blacklist
        token_hash = self._hash_token(decrypted.access_token)
        blacklist_entry = TokenBlacklistEntry(
            token_hash=token_hash,
            user_id=user_id,
            provider=provider,
            reason=reason,
            revoked_at=datetime.now(timezone.utc),
            revoked_by=revoked_by,
            expires_at=datetime.now(timezone.utc) + self._blacklist_retention,
        )
        await self._storage.add_to_blacklist(blacklist_entry)

        # If there's a refresh token, blacklist it too
        if decrypted.refresh_token:
            refresh_hash = self._hash_token(decrypted.refresh_token)
            refresh_entry = TokenBlacklistEntry(
                token_hash=refresh_hash,
                user_id=user_id,
                provider=provider,
                reason=f"{reason} (refresh token)",
                revoked_at=datetime.now(timezone.utc),
                revoked_by=revoked_by,
                expires_at=datetime.now(timezone.utc) + self._blacklist_retention,
            )
            await self._storage.add_to_blacklist(refresh_entry)

        # Update token status
        await self._storage.update_token(token.id, {"status": TokenStatus.REVOKED})

        logger.info(
            "Token revoked",
            extra={
                "user_id": user_id,
                "provider": provider,
                "reason": reason,
                "revoked_by": revoked_by,
            },
        )

        return True

    async def rotate_token(
        self,
        user_id: str,
        provider: str,
        new_access_token: str,
        new_refresh_token: Optional[str] = None,
        new_expires_at: Optional[datetime] = None,
        token_type: TokenType = TokenType.ACCESS,
    ) -> Optional[StoredToken]:
        """
        Rotate a token with new values.

        This should be called after a successful OAuth token refresh.

        Args:
            user_id: User ID
            provider: OAuth provider
            new_access_token: New access token
            new_refresh_token: New refresh token (if provided by OAuth)
            new_expires_at: New expiration time
            token_type: Type of token to rotate

        Returns:
            Updated StoredToken, or None if original not found
        """
        result = await self._storage.get_token(user_id, provider, token_type)
        if result is None:
            return None

        old_token, _ = result

        # Blacklist old token
        decrypted = self._decrypt_token_data(old_token, _)
        old_hash = self._hash_token(decrypted.access_token)
        await self._storage.add_to_blacklist(
            TokenBlacklistEntry(
                token_hash=old_hash,
                user_id=user_id,
                provider=provider,
                reason="Token rotated",
                revoked_at=datetime.now(timezone.utc),
                revoked_by="system:rotation",
                expires_at=datetime.now(timezone.utc) + self._blacklist_retention,
            )
        )

        # Create new token
        new_token = StoredToken(
            id=old_token.id,  # Keep same ID for continuity
            user_id=user_id,
            provider=provider,
            token_type=token_type,
            access_token=new_access_token,
            refresh_token=new_refresh_token or decrypted.refresh_token,
            scopes=old_token.scopes,
            expires_at=new_expires_at,
            issued_at=datetime.now(timezone.utc),
            rotation_count=old_token.rotation_count + 1,
            status=TokenStatus.ACTIVE,
            metadata=old_token.metadata,
        )

        # Encrypt and update
        encrypted_data = self._encrypt_token_data(new_token)
        await self._storage.update_token(
            old_token.id,
            {
                "rotation_count": new_token.rotation_count,
                "expires_at": new_expires_at,
                "issued_at": new_token.issued_at,
                "status": TokenStatus.ACTIVE,
            },
            encrypted_data,
        )

        logger.info(
            "Token rotated",
            extra={
                "user_id": user_id,
                "provider": provider,
                "rotation_count": new_token.rotation_count,
            },
        )

        return new_token

    async def list_tokens(
        self,
        user_id: str,
        provider: Optional[str] = None,
    ) -> List[StoredToken]:
        """
        List tokens for a user (without sensitive data).

        Args:
            user_id: User ID
            provider: Optional provider filter

        Returns:
            List of StoredToken with redacted access/refresh tokens
        """
        return await self._storage.list_tokens(user_id, provider)

    async def check_blacklist(self, token: str) -> bool:
        """
        Check if a token is blacklisted.

        Args:
            token: Raw token value

        Returns:
            True if blacklisted
        """
        token_hash = self._hash_token(token)
        return await self._storage.check_blacklist(token_hash)

    async def cleanup_expired(self) -> int:
        """
        Remove expired tokens and blacklist entries.

        Returns:
            Number of entries deleted
        """
        before = datetime.now(timezone.utc)
        deleted = await self._storage.cleanup_expired(before)

        if deleted > 0:
            logger.info("Token cleanup completed", extra={"deleted_count": deleted})

        return deleted

    async def get_stats(self) -> TokenVaultStats:
        """Get vault statistics."""
        return await self._storage.get_stats()

    # -------------------------------------------------------------------------
    # Private Methods
    # -------------------------------------------------------------------------

    def _encrypt_token_data(self, token: StoredToken) -> str:
        """Encrypt sensitive token data."""
        # Only encrypt the actual token values
        sensitive_data = {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
        }
        plaintext = json.dumps(sensitive_data)
        return self._encryption.encrypt(plaintext)

    def _decrypt_token_data(self, token: StoredToken, encrypted_data: str) -> StoredToken:
        """Decrypt and populate token with sensitive data."""
        plaintext = self._encryption.decrypt(encrypted_data)
        sensitive_data = json.loads(plaintext)

        return StoredToken(
            id=token.id,
            user_id=token.user_id,
            provider=token.provider,
            token_type=token.token_type,
            access_token=sensitive_data["access_token"],
            refresh_token=sensitive_data.get("refresh_token"),
            scopes=token.scopes,
            expires_at=token.expires_at,
            issued_at=token.issued_at,
            last_used_at=token.last_used_at,
            rotation_count=token.rotation_count,
            status=token.status,
            metadata=token.metadata,
        )

    def _hash_token(self, token: str) -> str:
        """Create SHA-256 hash of token for blacklist."""
        return hashlib.sha256(token.encode()).hexdigest()


# ============================================================================
# Singleton and Factory Functions
# ============================================================================

_token_vault_instance: Optional[TokenVault] = None
_vault_lock = threading.Lock()


def get_token_vault(
    storage: Optional[TokenStorageBackend] = None,
    encryption_key: Optional[str] = None,
) -> TokenVault:
    """
    Get or create singleton TokenVault instance.

    Args:
        storage: Storage backend (required on first call)
        encryption_key: Fernet key for local development

    Returns:
        TokenVault singleton instance
    """
    global _token_vault_instance

    if _token_vault_instance is None:
        with _vault_lock:
            if _token_vault_instance is None:
                if storage is None:
                    storage = InMemoryTokenStorage()

                # Determine encryption provider from environment
                kms_key = os.getenv("AMPREALIZE_KMS_KEY_ID")
                vault_addr = os.getenv("VAULT_ADDR")
                fernet_key = encryption_key or os.getenv("AMPREALIZE_TOKEN_VAULT_KEY")

                if kms_key:
                    _token_vault_instance = TokenVault.create_aws_kms(storage, kms_key)
                elif vault_addr:
                    _token_vault_instance = TokenVault.create_hashicorp_vault(storage, vault_addr)
                elif fernet_key:
                    _token_vault_instance = TokenVault.create_fernet(storage, fernet_key)
                else:
                    # Generate temporary key for development
                    temp_key = TokenVault.generate_fernet_key()
                    logger.warning(
                        "No encryption key configured, using temporary key. "
                        "Set AMPREALIZE_TOKEN_VAULT_KEY for persistent encryption."
                    )
                    _token_vault_instance = TokenVault.create_fernet(storage, temp_key)

    return _token_vault_instance


def reset_token_vault() -> None:
    """Reset the singleton instance (for testing)."""
    global _token_vault_instance
    with _vault_lock:
        _token_vault_instance = None


# ============================================================================
# CLI Helpers
# ============================================================================

def main():
    """CLI entry point for token vault management."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Token Vault Management")
    parser.add_argument("--generate-key", action="store_true", help="Generate new Fernet key")
    parser.add_argument("--stats", action="store_true", help="Show vault statistics")
    parser.add_argument("--cleanup", action="store_true", help="Clean up expired tokens")

    args = parser.parse_args()

    if args.generate_key:
        key = TokenVault.generate_fernet_key()
        print(f"Generated Fernet key: {key}")
        print("\nAdd to your environment:")
        print(f"export AMPREALIZE_TOKEN_VAULT_KEY='{key}'")
        return

    async def run_command():
        vault = get_token_vault()

        if args.stats:
            stats = await vault.get_stats()
            print(f"Total tokens: {stats.total_tokens}")
            print(f"Active tokens: {stats.active_tokens}")
            print(f"Expired tokens: {stats.expired_tokens}")
            print(f"Revoked tokens: {stats.revoked_tokens}")
            print(f"Blacklist size: {stats.blacklist_size}")
            print(f"Providers: {stats.providers}")
            if stats.oldest_token_age_days:
                print(f"Oldest token age: {stats.oldest_token_age_days} days")

        if args.cleanup:
            deleted = await vault.cleanup_expired()
            print(f"Cleaned up {deleted} expired entries")

    asyncio.run(run_command())


if __name__ == "__main__":
    main()
