"""Source Registry Service for Knowledge Packs.

Manages the lifecycle of registered pack sources — files and services
that feed into knowledge pack generation.

Implements T1.2.1 (AMPREALIZE-298) of the Knowledge Pack Foundations epic.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from amprealize.storage.postgres_pool import PostgresPool
from amprealize.utils.dsn import resolve_postgres_dsn

logger = logging.getLogger(__name__)

_KP_PG_DSN_ENV = "AMPREALIZE_KP_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceRecord:
    """A registered source in the knowledge pack system."""

    source_id: str
    source_type: str  # "file" | "service"
    ref: str
    scope: str  # "canonical" | "operational" | "surface" | "runtime"
    owner: Optional[str]
    version_hash: Optional[str]
    generation_eligible: bool
    created_at: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "ref": self.ref,
            "scope": self.scope,
            "owner": self.owner,
            "version_hash": self.version_hash,
            "generation_eligible": self.generation_eligible,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class RegisterSourceRequest:
    """Request to register a new knowledge pack source."""

    source_type: str  # "file" | "service"
    ref: str
    scope: str = "canonical"
    owner: Optional[str] = None
    generation_eligible: bool = True


@dataclass(frozen=True)
class DriftResult:
    """Result of a source drift check."""

    source_id: str
    ref: str
    stored_hash: Optional[str]
    current_hash: Optional[str]
    has_drift: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "ref": self.ref,
            "stored_hash": self.stored_hash,
            "current_hash": self.current_hash,
            "has_drift": self.has_drift,
        }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SourceRegistryError(Exception):
    """Base error for source registry operations."""


class SourceNotFoundError(SourceRegistryError):
    """Raised when a source_id is not found."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SourceRegistryService:
    """PostgreSQL-backed source registry for knowledge packs."""

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        pool: Optional[PostgresPool] = None,
    ) -> None:
        if pool is not None:
            self._pool = pool
        else:
            self._dsn = resolve_postgres_dsn(
                service="KP",
                explicit_dsn=dsn,
                env_var=_KP_PG_DSN_ENV,
                default_dsn=_DEFAULT_PG_DSN,
            )
            self._pool = PostgresPool(self._dsn)

    # ------------------------------------------------------------------ CRUD

    def register_source(self, request: RegisterSourceRequest) -> SourceRecord:
        """Register a new source and compute its initial hash."""
        source_id = f"src-{uuid.uuid4().hex[:12]}"
        version_hash = self._compute_hash(request.source_type, request.ref)
        now = datetime.now(timezone.utc).isoformat()

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO knowledge_pack_sources
                        (source_id, source_type, ref, scope, owner,
                         version_hash, generation_eligible, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        source_id,
                        request.source_type,
                        request.ref,
                        request.scope,
                        request.owner,
                        version_hash,
                        request.generation_eligible,
                        now,
                        now,
                    ),
                )
            conn.commit()

        return SourceRecord(
            source_id=source_id,
            source_type=request.source_type,
            ref=request.ref,
            scope=request.scope,
            owner=request.owner,
            version_hash=version_hash,
            generation_eligible=request.generation_eligible,
            created_at=now,
            updated_at=now,
        )

    def list_sources(
        self,
        *,
        scope: Optional[str] = None,
        eligible_for_generation: bool = False,
    ) -> List[SourceRecord]:
        """List registered sources, optionally filtered."""
        clauses: List[str] = []
        params: List[Any] = []

        if scope is not None:
            clauses.append("scope = %s")
            params.append(scope)
        if eligible_for_generation:
            clauses.append("generation_eligible = true")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM knowledge_pack_sources {where} ORDER BY created_at",
                    params,
                )
                rows = cur.fetchall()
                desc = cur.description

        return [self._row_to_record(row, desc) for row in rows]

    def get_source(self, source_id: str) -> SourceRecord:
        """Retrieve a single source by ID."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM knowledge_pack_sources WHERE source_id = %s",
                    (source_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise SourceNotFoundError(
                        f"Source not found: {source_id}"
                    )
                return self._row_to_record(row, cur.description)

    def update_source_hash(
        self, source_id: str, new_hash: str
    ) -> SourceRecord:
        """Update the stored version hash for a source."""
        now = datetime.now(timezone.utc).isoformat()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE knowledge_pack_sources
                    SET version_hash = %s, updated_at = %s
                    WHERE source_id = %s
                    """,
                    (new_hash, now, source_id),
                )
                if cur.rowcount == 0:
                    raise SourceNotFoundError(
                        f"Source not found: {source_id}"
                    )
            conn.commit()
        return self.get_source(source_id)

    def check_drift(self, source_id: str) -> DriftResult:
        """Compare stored hash against current file content hash."""
        record = self.get_source(source_id)
        current_hash = self._compute_hash(record.source_type, record.ref)
        has_drift = record.version_hash != current_hash
        return DriftResult(
            source_id=source_id,
            ref=record.ref,
            stored_hash=record.version_hash,
            current_hash=current_hash,
            has_drift=has_drift,
        )

    # ---------------------------------------------------------- Hash helpers

    @staticmethod
    def _compute_hash(source_type: str, ref: str) -> Optional[str]:
        """Compute SHA-256 of source content. Returns None if unavailable."""
        if source_type == "file":
            path = Path(ref)
            if path.is_file():
                content = path.read_bytes()
                return hashlib.sha256(content).hexdigest()
            return None
        # Service sources don't have a local file hash
        return None

    # --------------------------------------------------------- Row mapping

    @staticmethod
    def _row_to_record(row: tuple, description: Any) -> SourceRecord:
        cols = [d[0] for d in description]
        data = dict(zip(cols, row))
        return SourceRecord(
            source_id=data["source_id"],
            source_type=data["source_type"],
            ref=data["ref"],
            scope=data["scope"],
            owner=data.get("owner"),
            version_hash=data.get("version_hash"),
            generation_eligible=data.get("generation_eligible", True),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )
