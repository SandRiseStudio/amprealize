"""Knowledge Pack Storage — persistence layer for pack manifests, overlays, and artifacts.

Provides a unified storage interface that works with both PostgresPool and
SQLitePool via the shared ``connection()`` context-manager protocol.

Uses the tables created by:
- Postgres: ``migrations/versions/20260318_add_knowledge_pack_tables.py``
- SQLite:   ``storage/sqlite_migrations/m002_knowledge_pack_tables.py``

Following ``behavior_align_storage_layers`` (Student): normalised signatures,
tested across both backends.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

from amprealize.knowledge_pack.schema import (
    KnowledgePackManifest,
    OverlayFragment,
)
from amprealize.storage.postgres_pool import PostgresPool
from amprealize.utils.dsn import resolve_postgres_dsn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQLite placeholder adapters
# ---------------------------------------------------------------------------
# PostgresPool uses psycopg2's ``%s`` placeholders; SQLitePool uses ``?``.
# Rather than duplicating every query, we transparently translate at the
# cursor level when running against SQLite.


class _SQLiteCursorAdapter:
    """Cursor wrapper that translates ``%s`` → ``?`` in SQL strings."""

    __slots__ = ("_cur",)

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        sql = sql.replace("%s", "?")
        if params is not None:
            return self._cur.execute(sql, params)
        return self._cur.execute(sql)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def close(self):
        self._cur.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _SQLiteConnectionAdapter:
    """Wraps a SQLite connection so psycopg2-style SQL works unchanged."""

    __slots__ = ("_conn",)

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return _SQLiteCursorAdapter(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def __getattr__(self, name):
        return getattr(self._conn, name)


# ---------------------------------------------------------------------------
# SQLite placeholder adapters
# ---------------------------------------------------------------------------
# PostgresPool uses psycopg2's ``%s`` placeholders; SQLitePool uses ``?``.
# Rather than duplicating every query, we transparently translate at the
# cursor level when running against SQLite.


class _SQLiteCursorAdapter:
    """Cursor wrapper that translates ``%s`` → ``?`` in SQL strings."""

    __slots__ = ("_cur",)

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        sql = sql.replace("%s", "?")
        if params is not None:
            return self._cur.execute(sql, params)
        return self._cur.execute(sql)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def close(self):
        self._cur.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _SQLiteConnectionAdapter:
    """Wraps a SQLite connection so psycopg2-style SQL works unchanged."""

    __slots__ = ("_conn",)

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return _SQLiteCursorAdapter(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def __getattr__(self, name):
        return getattr(self._conn, name)

_T = TypeVar("_T")

_KP_PG_DSN_ENV = "AMPREALIZE_KP_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PackStorageError(Exception):
    """Base exception for pack storage operations."""


class PackNotFoundError(PackStorageError):
    """Pack manifest not found in storage."""


class PackVersionExistsError(PackStorageError):
    """Tried to save a manifest with a pack_id+version that already exists."""


# ---------------------------------------------------------------------------
# Storage service
# ---------------------------------------------------------------------------


class KnowledgePackStorage:
    """Persistence layer for knowledge pack manifests, overlays, and primer text.

    Works identically on PostgresPool (local/cloud Postgres) and SQLitePool
    (OSS single-user mode).  The pool is injected via constructor; if not
    provided, a PostgresPool is lazily created from DSN resolution.

    Design notes:
    - ``primer_text`` is stored inside ``manifest_json`` under key
      ``"_primer_text"`` so we avoid a new Alembic migration column.
    - Latest-version resolution uses ``ORDER BY created_at DESC LIMIT 1``
      rather than semver parsing for simplicity across both backends.
    - Deletion requires deactivation first (activation rows are audit trail).
    """

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        pool: Optional[Any] = None,
        telemetry: Optional[Any] = None,
    ) -> None:
        self._explicit_dsn = dsn
        self._pool = pool
        self._pool_lock = Lock()
        self._telemetry = telemetry

    # ------------------------------------------------------------------
    # Pool management (lazy init, thread-safe)
    # ------------------------------------------------------------------

    def _get_pool(self) -> Any:
        """Return the storage pool, lazily creating a PostgresPool if needed."""
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is None:
                dsn = resolve_postgres_dsn(
                    service="KP",
                    explicit_dsn=self._explicit_dsn,
                    env_var=_KP_PG_DSN_ENV,
                    default_dsn=_DEFAULT_PG_DSN,
                )
                self._pool = PostgresPool(dsn, service_name="knowledge_pack")
            return self._pool

    @contextmanager
    def _connection(self, *, autocommit: bool = True):
        """Acquire a connection from the pool.

        When the pool is SQLite-backed, the yielded connection
        automatically translates ``%s`` placeholders to ``?``.
        """
        pool = self._get_pool()
        is_sqlite = type(pool).__name__ == "SQLitePool"
        with pool.connection(autocommit=autocommit) as conn:
            yield _SQLiteConnectionAdapter(conn) if is_sqlite else conn

    # ==================================================================
    # Manifest CRUD
    # ==================================================================

    def save_manifest(
        self,
        manifest: KnowledgePackManifest,
        *,
        primer_text: Optional[str] = None,
        status: str = "draft",
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a pack manifest (and optional primer text).

        Parameters
        ----------
        manifest:
            The validated manifest to store.
        primer_text:
            Optional primer text to embed in the stored JSON blob.
        status:
            Initial status — ``draft``, ``published``, ``archived``.
        created_by:
            Who created this version.

        Returns
        -------
        dict with ``pack_id``, ``version``, ``status``, ``created_at``.

        Raises
        ------
        PackVersionExistsError:
            If pack_id+version already exists.
        """
        manifest_dict = manifest.to_dict()
        if primer_text is not None:
            manifest_dict["_primer_text"] = primer_text

        manifest_json = json.dumps(manifest_dict)
        now = _now()
        cb = created_by or manifest.created_by

        with self._connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                # Check for duplicate
                cur.execute(
                    "SELECT 1 FROM knowledge_pack_manifests WHERE pack_id = %s AND version = %s",
                    (manifest.pack_id, manifest.version),
                )
                if cur.fetchone() is not None:
                    raise PackVersionExistsError(
                        f"Pack {manifest.pack_id}@{manifest.version} already exists"
                    )

                cur.execute(
                    """
                    INSERT INTO knowledge_pack_manifests
                        (pack_id, version, manifest_json, status, created_by, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (manifest.pack_id, manifest.version, manifest_json, status, cb, now),
                )
            conn.commit()

        logger.info("Saved manifest %s@%s (status=%s)", manifest.pack_id, manifest.version, status)
        return {
            "pack_id": manifest.pack_id,
            "version": manifest.version,
            "status": status,
            "created_at": now.isoformat(),
        }

    def get_manifest(
        self,
        pack_id: str,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load a manifest dict from storage.

        Parameters
        ----------
        pack_id:
            The pack identifier.
        version:
            Specific version.  If ``None``, returns the latest by ``created_at``.

        Returns
        -------
        dict:
            The stored manifest JSON (including ``_primer_text`` if saved).

        Raises
        ------
        PackNotFoundError:
            If no matching manifest is found.
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                if version is not None:
                    cur.execute(
                        """
                        SELECT manifest_json, status, created_by, created_at
                        FROM knowledge_pack_manifests
                        WHERE pack_id = %s AND version = %s
                        """,
                        (pack_id, version),
                    )
                else:
                    # Latest version by created_at
                    cur.execute(
                        """
                        SELECT manifest_json, status, created_by, created_at
                        FROM knowledge_pack_manifests
                        WHERE pack_id = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (pack_id,),
                    )
                row = cur.fetchone()

        if row is None:
            v = f"@{version}" if version else " (latest)"
            raise PackNotFoundError(f"Pack {pack_id}{v} not found")

        manifest_json_raw, status, created_by, created_at = row
        # Handle both dict (psycopg2 JSONB auto-decode) and str (SQLite TEXT)
        if isinstance(manifest_json_raw, str):
            manifest_data = json.loads(manifest_json_raw)
        else:
            manifest_data = manifest_json_raw

        manifest_data["_storage_meta"] = {
            "status": status,
            "created_by": created_by,
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        }
        return manifest_data

    def list_packs(
        self,
        *,
        scope: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List distinct packs with their latest version.

        Returns
        -------
        dict with ``packs`` list and ``total_count``.
        """
        # We use a subquery / GROUP BY to get one row per pack_id (latest version)
        conditions: List[str] = []
        params: List[Any] = []

        if status is not None:
            conditions.append("status = %s")
            params.append(status)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with self._connection() as conn:
            with conn.cursor() as cur:
                # Count distinct packs
                cur.execute(
                    f"SELECT COUNT(DISTINCT pack_id) FROM knowledge_pack_manifests {where}",
                    params,
                )
                total_count = cur.fetchone()[0]

                # Get latest version per pack_id
                # Works on both Postgres (DISTINCT ON) and SQLite (GROUP BY + MAX).
                # Use a portable approach: subquery with MAX(created_at).
                cur.execute(
                    f"""
                    SELECT m.pack_id, m.version, m.status, m.created_by, m.created_at, m.manifest_json
                    FROM knowledge_pack_manifests m
                    INNER JOIN (
                        SELECT pack_id, MAX(created_at) AS max_created
                        FROM knowledge_pack_manifests
                        {where}
                        GROUP BY pack_id
                    ) latest ON m.pack_id = latest.pack_id AND m.created_at = latest.max_created
                    ORDER BY m.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                rows = cur.fetchall()

        packs = []
        for row in rows:
            pack_id_val, version_val, status_val, created_by_val, created_at_val, mj = row
            # Parse manifest_json for scope
            if isinstance(mj, str):
                mdata = json.loads(mj)
            else:
                mdata = mj
            pack_scope = mdata.get("scope", "workspace")

            # Apply scope filter in Python (simpler than JSON extraction in SQL for both backends)
            if scope is not None and pack_scope != scope:
                continue

            packs.append({
                "pack_id": pack_id_val,
                "version": version_val,
                "scope": pack_scope,
                "status": status_val,
                "created_by": created_by_val,
                "created_at": created_at_val.isoformat() if hasattr(created_at_val, "isoformat") else str(created_at_val),
            })

        return {
            "packs": packs,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
        }

    def update_status(
        self,
        pack_id: str,
        version: str,
        new_status: str,
    ) -> None:
        """Update the status of a stored manifest.

        Raises PackNotFoundError if the version doesn't exist.
        """
        with self._connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE knowledge_pack_manifests
                    SET status = %s
                    WHERE pack_id = %s AND version = %s
                    """,
                    (new_status, pack_id, version),
                )
                if cur.rowcount == 0:
                    raise PackNotFoundError(
                        f"Pack {pack_id}@{version} not found"
                    )
            conn.commit()

        logger.info("Updated %s@%s → status=%s", pack_id, version, new_status)

    def delete_pack(
        self,
        pack_id: str,
        version: str,
    ) -> None:
        """Delete a specific pack version.

        Does NOT cascade to activations — callers must deactivate first.
        Activation rows serve as audit trail.

        Also deletes associated overlays.
        """
        with self._connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                # Delete overlays first
                cur.execute(
                    "DELETE FROM knowledge_pack_overlays WHERE pack_id = %s AND pack_version = %s",
                    (pack_id, version),
                )
                # Delete manifest
                cur.execute(
                    "DELETE FROM knowledge_pack_manifests WHERE pack_id = %s AND version = %s",
                    (pack_id, version),
                )
                if cur.rowcount == 0:
                    raise PackNotFoundError(
                        f"Pack {pack_id}@{version} not found"
                    )
            conn.commit()

        logger.info("Deleted %s@%s and associated overlays", pack_id, version)

    # ==================================================================
    # Overlay CRUD
    # ==================================================================

    def save_overlays(
        self,
        pack_id: str,
        pack_version: str,
        overlays: List[OverlayFragment],
    ) -> int:
        """Persist overlay fragments for a pack version.

        Returns the number of overlays saved.
        """
        if not overlays:
            return 0

        with self._connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                for overlay in overlays:
                    applies_to_json = json.dumps(overlay.applies_to)
                    instructions_json = json.dumps(overlay.instructions)
                    # retrieval_keywords is a PostgreSQL ARRAY(Text),
                    # so pass the Python list directly — do NOT json.dumps.
                    keywords_list = list(overlay.retrieval_keywords or [])
                    # Namespace overlay_id to ensure uniqueness across packs
                    # (overlay_id is a single-column PK).
                    scoped_oid = f"{pack_id}/{pack_version}/{overlay.overlay_id}"
                    now = _now()
                    cur.execute(
                        """
                        INSERT INTO knowledge_pack_overlays
                            (overlay_id, pack_id, pack_version, kind,
                             applies_to, instructions, retrieval_keywords, priority, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            scoped_oid,
                            pack_id,
                            pack_version,
                            overlay.kind.value,
                            applies_to_json,
                            instructions_json,
                            keywords_list,
                            overlay.priority,
                            now,
                        ),
                    )
            conn.commit()

        logger.info("Saved %d overlays for %s@%s", len(overlays), pack_id, pack_version)
        return len(overlays)

    def get_overlays(
        self,
        pack_id: str,
        pack_version: str,
        *,
        kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Load overlay fragments for a pack version.

        Parameters
        ----------
        kind:
            Optional filter — ``"task"``, ``"surface"``, or ``"role"``.

        Returns
        -------
        List of overlay dicts.
        """
        conditions = ["pack_id = %s", "pack_version = %s"]
        params: List[Any] = [pack_id, pack_version]

        if kind is not None:
            conditions.append("kind = %s")
            params.append(kind)

        where = "WHERE " + " AND ".join(conditions)

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT overlay_id, kind, applies_to, instructions,
                           retrieval_keywords, priority, created_at
                    FROM knowledge_pack_overlays
                    {where}
                    ORDER BY priority DESC, overlay_id
                    """,
                    params,
                )
                rows = cur.fetchall()

        overlays = []
        for row in rows:
            oid, okind, applies_to_raw, instr_raw, kw_raw, priority, created_at = row
            overlays.append({
                "overlay_id": oid,
                "kind": okind,
                "applies_to": json.loads(applies_to_raw) if isinstance(applies_to_raw, str) else applies_to_raw,
                "instructions": json.loads(instr_raw) if isinstance(instr_raw, str) else instr_raw,
                "retrieval_keywords": json.loads(kw_raw) if isinstance(kw_raw, str) else kw_raw,
                "priority": priority,
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
            })
        return overlays

    # ==================================================================
    # Compound operations
    # ==================================================================

    def save_artifact(
        self,
        artifact: Any,
        *,
        status: str = "draft",
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a full :class:`KnowledgePackArtifact` (manifest + overlays + primer).

        This is the primary save entry point called after ``PackBuilder.build()``.

        Returns
        -------
        dict with ``pack_id``, ``version``, ``status``, ``overlay_count``.
        """
        result = self.save_manifest(
            artifact.manifest,
            primer_text=artifact.primer_text,
            status=status,
            created_by=created_by,
        )
        overlay_count = self.save_overlays(
            artifact.manifest.pack_id,
            artifact.manifest.version,
            artifact.overlays,
        )
        result["overlay_count"] = overlay_count
        logger.info(
            "Saved artifact %s@%s (%d overlays)",
            artifact.manifest.pack_id,
            artifact.manifest.version,
            overlay_count,
        )
        return result

    def get_manifest_for_runtime(
        self,
        pack_id: str,
        version: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load manifest dict for the runtime path (ContextResolver).

        Returns ``None`` instead of raising if not found — the runtime
        path must degrade gracefully.
        """
        try:
            return self.get_manifest(pack_id, version)
        except PackNotFoundError:
            logger.debug("Pack %s not found for runtime (version=%s)", pack_id, version)
            return None
        except Exception:
            logger.warning("Failed to load pack %s for runtime", pack_id, exc_info=True)
            return None
