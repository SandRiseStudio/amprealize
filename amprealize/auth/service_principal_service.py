"""
Service Principal service for agent/service API authentication.

Handles CRUD operations for service principals, which provide
client_credentials OAuth flow for agents and services.
"""

import uuid
import secrets
import bcrypt
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from amprealize.storage.postgres_pool import PostgresPool
from amprealize.utils.dsn import resolve_postgres_dsn

logger = logging.getLogger(__name__)

_AUTH_PG_DSN_ENV = "AMPREALIZE_AUTH_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"


@dataclass
class ServicePrincipal:
    """Service principal for agent/service API authentication."""

    id: str
    name: str
    client_id: str
    client_secret_hash: str
    allowed_scopes: List[str]
    rate_limit: int
    role: str  # STRATEGIST | TEACHER | STUDENT | ADMIN | OBSERVER
    is_active: bool
    created_by: Optional[str]  # User ID who created this
    created_at: datetime
    updated_at: datetime
    org_id: Optional[str] = None  # Optional - service principals can exist without an org
    description: Optional[str] = None
    last_used_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_secret: bool = False) -> Dict[str, Any]:
        """Convert to dictionary (safe for serialization)."""
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "client_id": self.client_id,
            "org_id": self.org_id,  # Optional - may be None
            "allowed_scopes": self.allowed_scopes,
            "rate_limit": self.rate_limit,
            "role": self.role,
            "is_active": self.is_active,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "metadata": self.metadata,
        }
        if include_secret:
            result["client_secret_hash"] = self.client_secret_hash
        return result


@dataclass
class CreateServicePrincipalRequest:
    """Request to create a service principal."""
    name: str
    description: Optional[str] = None
    allowed_scopes: List[str] = field(default_factory=lambda: ["read", "write"])
    rate_limit: int = 100
    role: str = "STUDENT"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CreateServicePrincipalResponse:
    """Response from creating a service principal (includes secret once)."""
    service_principal: ServicePrincipal
    client_secret: str  # Plain text secret, only returned on creation


class ServicePrincipalService:
    """Service for managing service principals (agent/service API credentials).

    Uses PostgreSQL for persistence in the auth schema.
    """

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        pool: Optional[PostgresPool] = None,
    ) -> None:
        """Initialize service principal service.

        Args:
            dsn: PostgreSQL DSN. If not provided, resolved from environment.
            pool: Optional existing PostgresPool to reuse.
        """
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

    def _hash_secret(self, secret: str) -> str:
        """Hash a client secret using bcrypt."""
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(secret.encode("utf-8"), salt)
        return hashed.decode("utf-8")

    def _verify_secret(self, secret: str, hashed: str) -> bool:
        """Verify a client secret against its hash."""
        try:
            return bcrypt.checkpw(secret.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False

    def _generate_client_id(self) -> str:
        """Generate a unique client ID."""
        return f"sp_{uuid.uuid4().hex[:24]}"

    def _generate_client_secret(self) -> str:
        """Generate a secure client secret."""
        return secrets.token_urlsafe(32)

    def _row_to_service_principal(self, row: Dict[str, Any]) -> ServicePrincipal:
        """Convert database row to ServicePrincipal object."""
        import json

        allowed_scopes = row.get("allowed_scopes", [])
        if isinstance(allowed_scopes, str):
            allowed_scopes = json.loads(allowed_scopes)

        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        return ServicePrincipal(
            id=row["id"],
            name=row["name"],
            description=row.get("description"),
            client_id=row["client_id"],
            client_secret_hash=row["client_secret_hash"],
            allowed_scopes=allowed_scopes,
            rate_limit=row["rate_limit"],
            role=row["role"],
            is_active=row["is_active"],
            created_by=row.get("created_by"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_used_at=row.get("last_used_at"),
            metadata=metadata,
        )

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def create(
        self,
        request: CreateServicePrincipalRequest,
        created_by: Optional[str] = None,
    ) -> CreateServicePrincipalResponse:
        """Create a new service principal.

        Args:
            request: Creation request with name, scopes, etc.
            created_by: User ID of the creator (optional).

        Returns:
            Response containing the service principal and plain text secret.
        """
        import json

        sp_id = str(uuid.uuid4())
        client_id = self._generate_client_id()
        client_secret = self._generate_client_secret()
        client_secret_hash = self._hash_secret(client_secret)
        now = datetime.now(timezone.utc)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth.service_principals (
                        id, name, description, client_id, client_secret_hash,
                        allowed_scopes, rate_limit, role, is_active,
                        created_by, created_at, updated_at, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        sp_id,
                        request.name,
                        request.description,
                        client_id,
                        client_secret_hash,
                        json.dumps(request.allowed_scopes),
                        request.rate_limit,
                        request.role,
                        True,
                        created_by,
                        now,
                        now,
                        json.dumps(request.metadata),
                    ),
                )
                row = cur.fetchone()
                columns = [desc[0] for desc in cur.description]
                row_dict = dict(zip(columns, row))
                conn.commit()

        sp = self._row_to_service_principal(row_dict)
        logger.info(f"Created service principal: {sp.id} ({sp.name})")

        return CreateServicePrincipalResponse(
            service_principal=sp,
            client_secret=client_secret,
        )

    def get_by_id(self, sp_id: str) -> Optional[ServicePrincipal]:
        """Get a service principal by ID."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM auth.service_principals WHERE id = %s",
                    (sp_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                columns = [desc[0] for desc in cur.description]
                return self._row_to_service_principal(dict(zip(columns, row)))

    def get_by_client_id(self, client_id: str) -> Optional[ServicePrincipal]:
        """Get a service principal by client_id."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM auth.service_principals WHERE client_id = %s",
                    (client_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                columns = [desc[0] for desc in cur.description]
                return self._row_to_service_principal(dict(zip(columns, row)))

    def authenticate(
        self,
        client_id: str,
        client_secret: str,
    ) -> Optional[ServicePrincipal]:
        """Authenticate a service principal with client credentials.

        Args:
            client_id: The client ID.
            client_secret: The plain text client secret.

        Returns:
            ServicePrincipal if authentication succeeds, None otherwise.
        """
        sp = self.get_by_client_id(client_id)
        if not sp:
            logger.warning(f"Authentication failed: unknown client_id {client_id}")
            return None

        if not sp.is_active:
            logger.warning(f"Authentication failed: inactive service principal {sp.id}")
            return None

        if not self._verify_secret(client_secret, sp.client_secret_hash):
            logger.warning(f"Authentication failed: invalid secret for {client_id}")
            return None

        # Update last_used_at
        self._update_last_used(sp.id)

        logger.info(f"Service principal authenticated: {sp.id} ({sp.name})")
        return sp

    def _update_last_used(self, sp_id: str) -> None:
        """Update the last_used_at timestamp."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth.service_principals
                    SET last_used_at = NOW()
                    WHERE id = %s
                    """,
                    (sp_id,),
                )
                conn.commit()

    def list_all(
        self,
        *,
        created_by: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ServicePrincipal]:
        """List service principals with optional filters.

        Args:
            created_by: Filter by creator user ID.
            is_active: Filter by active status.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of ServicePrincipal objects.
        """
        query = "SELECT * FROM auth.service_principals WHERE 1=1"
        params: List[Any] = []

        if created_by is not None:
            query += " AND created_by = %s"
            params.append(created_by)

        if is_active is not None:
            query += " AND is_active = %s"
            params.append(is_active)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                return [
                    self._row_to_service_principal(dict(zip(columns, row)))
                    for row in rows
                ]

    def update(
        self,
        sp_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        allowed_scopes: Optional[List[str]] = None,
        rate_limit: Optional[int] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[ServicePrincipal]:
        """Update a service principal.

        Args:
            sp_id: Service principal ID.
            **kwargs: Fields to update.

        Returns:
            Updated ServicePrincipal or None if not found.
        """
        import json

        updates = []
        params: List[Any] = []

        if name is not None:
            updates.append("name = %s")
            params.append(name)

        if description is not None:
            updates.append("description = %s")
            params.append(description)

        if allowed_scopes is not None:
            updates.append("allowed_scopes = %s")
            params.append(json.dumps(allowed_scopes))

        if rate_limit is not None:
            updates.append("rate_limit = %s")
            params.append(rate_limit)

        if role is not None:
            updates.append("role = %s")
            params.append(role)

        if is_active is not None:
            updates.append("is_active = %s")
            params.append(is_active)

        if metadata is not None:
            updates.append("metadata = %s")
            params.append(json.dumps(metadata))

        if not updates:
            return self.get_by_id(sp_id)

        updates.append("updated_at = NOW()")
        params.append(sp_id)

        query = f"""
            UPDATE auth.service_principals
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *
        """

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                if not row:
                    return None
                columns = [desc[0] for desc in cur.description]
                conn.commit()
                return self._row_to_service_principal(dict(zip(columns, row)))

    def rotate_secret(self, sp_id: str) -> Optional[str]:
        """Rotate the client secret for a service principal.

        Args:
            sp_id: Service principal ID.

        Returns:
            New plain text client secret, or None if not found.
        """
        new_secret = self._generate_client_secret()
        new_hash = self._hash_secret(new_secret)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth.service_principals
                    SET client_secret_hash = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id
                    """,
                    (new_hash, sp_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                conn.commit()

        logger.info(f"Rotated secret for service principal: {sp_id}")
        return new_secret

    def delete(self, sp_id: str) -> bool:
        """Delete a service principal.

        Args:
            sp_id: Service principal ID.

        Returns:
            True if deleted, False if not found.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM auth.service_principals WHERE id = %s RETURNING id",
                    (sp_id,),
                )
                row = cur.fetchone()
                conn.commit()
                if row:
                    logger.info(f"Deleted service principal: {sp_id}")
                    return True
                return False

    def deactivate(self, sp_id: str) -> Optional[ServicePrincipal]:
        """Deactivate a service principal (soft delete).

        Args:
            sp_id: Service principal ID.

        Returns:
            Updated ServicePrincipal or None if not found.
        """
        return self.update(sp_id, is_active=False)
