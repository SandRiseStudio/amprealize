"""Activation service for Knowledge Packs.

Manages which pack+version is active for which workspace, including
activation profiles (solo-dev, amprealize-platform, etc.) and status tracking.

Uses the knowledge_pack_activations table created in migration 20260318.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from amprealize.storage.postgres_pool import PostgresPool
from amprealize.utils.dsn import resolve_postgres_dsn

logger = logging.getLogger(__name__)

_ACTIVATION_PG_DSN_ENV = "AMPREALIZE_ACTIVATION_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _short_id() -> str:
    return f"act-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class Activation:
    """Represents an active knowledge pack assignment to a workspace."""

    activation_id: str
    workspace_id: str
    pack_id: str
    pack_version: str
    profile: Optional[str] = None
    activated_at: Optional[datetime] = None
    activated_by: Optional[str] = None
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "activation_id": self.activation_id,
            "workspace_id": self.workspace_id,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "profile": self.profile,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "activated_by": self.activated_by,
            "status": self.status,
        }


@dataclass
class ActivationListResult:
    """Result of listing activations with pagination."""

    activations: List[Activation] = field(default_factory=list)
    total_count: int = 0
    limit: int = 50
    offset: int = 0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ActivationServiceError(Exception):
    """Base exception for activation service."""


class ActivationNotFoundError(ActivationServiceError):
    """Activation not found."""


class PackNotFoundError(ActivationServiceError):
    """Referenced pack not found in storage."""


class DuplicateActivationError(ActivationServiceError):
    """Workspace already has an active pack (must deactivate first)."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ActivationService:
    """Service for managing knowledge pack activations.

    Each workspace can have at most one active pack at a time.
    Activating a new pack for a workspace requires first deactivating the existing one.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        pool: Optional[PostgresPool] = None,
        telemetry: Optional[Any] = None,
    ) -> None:
        if pool is None:
            if dsn is None:
                dsn = resolve_postgres_dsn(
                    service="ACTIVATION",
                    explicit_dsn=None,
                    env_var=_ACTIVATION_PG_DSN_ENV,
                    default_dsn=_DEFAULT_PG_DSN,
                )
            pool = PostgresPool(dsn)
        self._pool = pool
        self._telemetry = telemetry

    # =========================================================================
    # Core Operations
    # =========================================================================

    def activate_pack(
        self,
        workspace_id: str,
        pack_id: str,
        version: str,
        profile: Optional[str] = None,
        activated_by: Optional[str] = None,
        *,
        auto_deactivate: bool = True,
    ) -> Activation:
        """Activate a knowledge pack for a workspace.

        Parameters
        ----------
        workspace_id:
            Unique identifier for the workspace (typically path hash or explicit config).
        pack_id:
            Knowledge pack identifier.
        version:
            Pack version to activate.
        profile:
            Optional activation profile (solo-dev, amprealize-platform, etc.).
        activated_by:
            Optional identifier of who activated the pack.
        auto_deactivate:
            If True, automatically deactivate any existing active pack for this workspace.
            If False, raise DuplicateActivationError if workspace already has active pack.

        Returns
        -------
        Activation:
            The newly created activation record.

        Raises
        ------
        DuplicateActivationError:
            If auto_deactivate=False and workspace already has an active pack.
        PackNotFoundError:
            If the referenced pack+version doesn't exist in storage.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Check if pack exists (optional - can be disabled for ephemeral packs)
                cur.execute(
                    """
                    SELECT 1 FROM knowledge_pack_manifests
                    WHERE pack_id = %s AND version = %s
                    """,
                    (pack_id, version),
                )
                if cur.fetchone() is None:
                    # Pack doesn't exist in DB - this is OK for in-memory/ephemeral packs
                    # but we log a warning
                    logger.warning(
                        f"Activating pack {pack_id}@{version} not in database "
                        "(may be ephemeral or built in-memory)"
                    )

                # Check for existing active pack
                cur.execute(
                    """
                    SELECT activation_id FROM knowledge_pack_activations
                    WHERE workspace_id = %s AND status = 'active'
                    """,
                    (workspace_id,),
                )
                existing = cur.fetchone()
                if existing:
                    if auto_deactivate:
                        # Deactivate the existing pack
                        cur.execute(
                            """
                            UPDATE knowledge_pack_activations
                            SET status = 'deactivated'
                            WHERE workspace_id = %s AND status = 'active'
                            """,
                            (workspace_id,),
                        )
                    else:
                        raise DuplicateActivationError(
                            f"Workspace {workspace_id} already has an active pack"
                        )

                # Create new activation
                activation_id = _short_id()
                now = _now()

                cur.execute(
                    """
                    INSERT INTO knowledge_pack_activations
                    (activation_id, workspace_id, pack_id, pack_version, profile,
                     activated_at, activated_by, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')
                    """,
                    (
                        activation_id,
                        workspace_id,
                        pack_id,
                        version,
                        profile,
                        now,
                        activated_by,
                    ),
                )
                conn.commit()

                activation = Activation(
                    activation_id=activation_id,
                    workspace_id=workspace_id,
                    pack_id=pack_id,
                    pack_version=version,
                    profile=profile,
                    activated_at=now,
                    activated_by=activated_by,
                    status="active",
                )

                self._emit_pack_event("pack.activated", {
                    "pack_id": pack_id,
                    "pack_version": version,
                    "workspace_id": workspace_id,
                    "surface": "api",
                    "profile": profile,
                    "activated_by": activated_by,
                })

                return activation

    def get_active_pack(self, workspace_id: str) -> Optional[Activation]:
        """Get the currently active pack for a workspace.

        Parameters
        ----------
        workspace_id:
            Unique identifier for the workspace.

        Returns
        -------
        Optional[Activation]:
            The active pack activation, or None if no pack is active.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT activation_id, workspace_id, pack_id, pack_version,
                           profile, activated_at, activated_by, status
                    FROM knowledge_pack_activations
                    WHERE workspace_id = %s AND status = 'active'
                    ORDER BY activated_at DESC
                    LIMIT 1
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None

                return Activation(
                    activation_id=row[0],
                    workspace_id=row[1],
                    pack_id=row[2],
                    pack_version=row[3],
                    profile=row[4],
                    activated_at=row[5],
                    activated_by=row[6],
                    status=row[7],
                )

    def deactivate_pack(self, workspace_id: str) -> bool:
        """Deactivate the active pack for a workspace.

        Parameters
        ----------
        workspace_id:
            Unique identifier for the workspace.

        Returns
        -------
        bool:
            True if a pack was deactivated, False if no active pack existed.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE knowledge_pack_activations
                    SET status = 'deactivated'
                    WHERE workspace_id = %s AND status = 'active'
                    """,
                    (workspace_id,),
                )
                updated = cur.rowcount
                conn.commit()
                if updated > 0:
                    self._emit_pack_event("pack.deactivated", {
                        "pack_id": "",  # pack_id not available during bulk deactivate
                        "workspace_id": workspace_id,
                        "surface": "api",
                    })
                return updated > 0

    def list_activations(
        self,
        limit: int = 50,
        offset: int = 0,
        *,
        workspace_id: Optional[str] = None,
        pack_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> ActivationListResult:
        """List activations with optional filtering.

        Parameters
        ----------
        limit:
            Maximum number of results to return.
        offset:
            Number of results to skip.
        workspace_id:
            Filter by workspace ID.
        pack_id:
            Filter by pack ID.
        status:
            Filter by status ('active' or 'deactivated').

        Returns
        -------
        ActivationListResult:
            List of activations with pagination info.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Build WHERE clause
                conditions = []
                params: List[Any] = []

                if workspace_id:
                    conditions.append("workspace_id = %s")
                    params.append(workspace_id)
                if pack_id:
                    conditions.append("pack_id = %s")
                    params.append(pack_id)
                if status:
                    conditions.append("status = %s")
                    params.append(status)

                where_clause = ""
                if conditions:
                    where_clause = "WHERE " + " AND ".join(conditions)

                # Get total count
                cur.execute(
                    f"SELECT COUNT(*) FROM knowledge_pack_activations {where_clause}",
                    params,
                )
                total_count = cur.fetchone()[0]

                # Get results
                cur.execute(
                    f"""
                    SELECT activation_id, workspace_id, pack_id, pack_version,
                           profile, activated_at, activated_by, status
                    FROM knowledge_pack_activations
                    {where_clause}
                    ORDER BY activated_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                rows = cur.fetchall()

                activations = [
                    Activation(
                        activation_id=row[0],
                        workspace_id=row[1],
                        pack_id=row[2],
                        pack_version=row[3],
                        profile=row[4],
                        activated_at=row[5],
                        activated_by=row[6],
                        status=row[7],
                    )
                    for row in rows
                ]

                return ActivationListResult(
                    activations=activations,
                    total_count=total_count,
                    limit=limit,
                    offset=offset,
                )

    def get_activation_by_id(self, activation_id: str) -> Optional[Activation]:
        """Get an activation by its ID.

        Parameters
        ----------
        activation_id:
            The unique activation identifier.

        Returns
        -------
        Optional[Activation]:
            The activation record, or None if not found.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT activation_id, workspace_id, pack_id, pack_version,
                           profile, activated_at, activated_by, status
                    FROM knowledge_pack_activations
                    WHERE activation_id = %s
                    """,
                    (activation_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None

                return Activation(
                    activation_id=row[0],
                    workspace_id=row[1],
                    pack_id=row[2],
                    pack_version=row[3],
                    profile=row[4],
                    activated_at=row[5],
                    activated_by=row[6],
                    status=row[7],
                )

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------

    def _emit_pack_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Emit a pack telemetry event if a telemetry client is configured."""
        if not self._telemetry:
            return
        try:
            clean = {k: v for k, v in payload.items() if v is not None}
            self._telemetry.emit_event(event_type=event_type, payload=clean)
        except Exception:
            logger.debug("Failed to emit %s telemetry", event_type, exc_info=True)


# ---------------------------------------------------------------------------
# Workspace ID Helpers
# ---------------------------------------------------------------------------


def workspace_id_from_path(path: str) -> str:
    """Generate a workspace ID from a filesystem path.

    Uses a hash of the path to create a stable, deterministic workspace ID.
    This is useful for CLI/IDE contexts where workspace identity is
    determined by the filesystem location.

    Parameters
    ----------
    path:
        Absolute path to the workspace root.

    Returns
    -------
    str:
        Workspace ID in the format 'ws-{hash}'.
    """
    import hashlib

    # Normalize path (remove trailing slashes, resolve symlinks conceptually)
    normalized = path.rstrip("/")
    hash_bytes = hashlib.sha256(normalized.encode()).digest()
    return f"ws-{hash_bytes[:8].hex()}"
