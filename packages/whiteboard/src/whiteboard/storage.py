"""Storage backends for whiteboard room persistence."""

from __future__ import annotations

import abc
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

from whiteboard.models import RoomStatus, WhiteboardRoom, WhiteboardSnapshot

logger = logging.getLogger(__name__)


class StorageBackend(abc.ABC):
    """Abstract storage interface for whiteboard rooms and snapshots."""

    @abc.abstractmethod
    def save_room(self, room: WhiteboardRoom) -> None:
        """Persist a room record."""

    @abc.abstractmethod
    def get_room(self, room_id: str) -> Optional[WhiteboardRoom]:
        """Retrieve a room by ID."""

    @abc.abstractmethod
    def list_rooms(
        self,
        session_id: Optional[str] = None,
        status: Optional[RoomStatus] = None,
        created_by: Optional[str] = None,
        visible_to_user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardRoom]:
        """List rooms, optionally filtered by session, status, or user visibility."""

    @abc.abstractmethod
    def update_room(self, room: WhiteboardRoom) -> None:
        """Update an existing room record."""

    @abc.abstractmethod
    def delete_room(self, room_id: str) -> bool:
        """Delete a room. Returns True if found and deleted."""

    # -- Snapshot persistence (optional for lightweight backends) ---------------

    def save_snapshot(self, snapshot: WhiteboardSnapshot) -> None:
        """Persist a snapshot record. Override in backends with snapshot support."""

    def get_snapshot(self, snapshot_id: str) -> Optional[WhiteboardSnapshot]:
        """Retrieve a snapshot by ID."""
        return None

    def list_snapshots(
        self,
        room_id: Optional[str] = None,
        session_id: Optional[str] = None,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardSnapshot]:
        """List snapshots with optional filters."""
        return []


class InMemoryStorage(StorageBackend):
    """In-memory storage for tests and local development."""

    def __init__(self) -> None:
        self._rooms: Dict[str, WhiteboardRoom] = {}
        self._snapshots: Dict[str, WhiteboardSnapshot] = {}

    def save_room(self, room: WhiteboardRoom) -> None:
        self._rooms[room.id] = room

    def get_room(self, room_id: str) -> Optional[WhiteboardRoom]:
        return self._rooms.get(room_id)

    def list_rooms(
        self,
        session_id: Optional[str] = None,
        status: Optional[RoomStatus] = None,
        created_by: Optional[str] = None,
        visible_to_user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardRoom]:
        results = list(self._rooms.values())
        if session_id:
            results = [r for r in results if r.session_id == session_id]
        if status:
            results = [r for r in results if r.status == status]
        if created_by:
            results = [r for r in results if r.created_by == created_by]
        if visible_to_user_id:
            results = [
                r for r in results
                if r.created_by == visible_to_user_id
                or visible_to_user_id in r.participant_ids
            ]
        return results[offset : offset + limit]

    def update_room(self, room: WhiteboardRoom) -> None:
        if room.id in self._rooms:
            room.updated_at = datetime.now(timezone.utc)
            self._rooms[room.id] = room

    def delete_room(self, room_id: str) -> bool:
        return self._rooms.pop(room_id, None) is not None

    # -- Snapshot persistence --------------------------------------------------

    def save_snapshot(self, snapshot: WhiteboardSnapshot) -> None:
        self._snapshots[snapshot.id] = snapshot

    def get_snapshot(self, snapshot_id: str) -> Optional[WhiteboardSnapshot]:
        return self._snapshots.get(snapshot_id)

    def list_snapshots(
        self,
        room_id: Optional[str] = None,
        session_id: Optional[str] = None,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardSnapshot]:
        results = sorted(
            self._snapshots.values(),
            key=lambda s: s.exported_at,
            reverse=True,
        )
        if room_id:
            results = [s for s in results if s.room_id == room_id]
        if session_id:
            results = [s for s in results if s.session_id == session_id]
        if created_by:
            results = [s for s in results if s.created_by == created_by]
        return results[offset : offset + limit]


# ---------------------------------------------------------------------------
# SqliteStorageBackend
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS whiteboard_rooms (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT 'Untitled',
    status TEXT NOT NULL DEFAULT 'creating',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    participant_ids TEXT NOT NULL DEFAULT '[]',
    canvas_state TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS whiteboard_snapshots (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'json',
    canvas_data TEXT NOT NULL DEFAULT '{}',
    exported_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}'
);
"""


class SqliteStorageBackend(StorageBackend):
    """SQLite-backed storage for local development and single-node deployments.

    Thread-safety: ``check_same_thread=False`` is set and all mutations are
    wrapped in explicit transactions so multiple threads can call concurrently.

    Usage::

        storage = SqliteStorageBackend(db_path="whiteboard.db")
        service = WhiteboardService(storage=storage)

    Set ``WHITEBOARD_SQLITE_PATH`` (or pass ``db_path``) to control the file.
    Defaults to ``whiteboard.db`` in the current directory.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or os.environ.get("WHITEBOARD_SQLITE_PATH", "whiteboard.db")
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SQLITE_SCHEMA)
        self._conn.commit()

    @contextmanager
    def _tx(self) -> Generator[sqlite3.Cursor, None, None]:
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    # -- Helpers --

    @staticmethod
    def _row_to_room(row: sqlite3.Row) -> WhiteboardRoom:
        d = dict(row)
        return WhiteboardRoom(
            id=d["id"],
            session_id=d["session_id"],
            title=d["title"],
            status=RoomStatus(d["status"]),
            created_by=d["created_by"],
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
            closed_at=datetime.fromisoformat(d["closed_at"]) if d["closed_at"] else None,
            participant_ids=json.loads(d["participant_ids"]),
            canvas_state=json.loads(d["canvas_state"]) if d["canvas_state"] else None,
            metadata=json.loads(d["metadata"]),
        )

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> WhiteboardSnapshot:
        from whiteboard.models import SnapshotFormat
        d = dict(row)
        return WhiteboardSnapshot(
            id=d["id"],
            room_id=d["room_id"],
            session_id=d["session_id"],
            format=SnapshotFormat(d["format"]),
            canvas_data=json.loads(d["canvas_data"]),
            exported_at=datetime.fromisoformat(d["exported_at"]),
            created_by=d["created_by"],
            metadata=json.loads(d["metadata"]),
        )

    # -- StorageBackend --

    def save_room(self, room: WhiteboardRoom) -> None:
        with self._tx() as cur:
            cur.execute(
                """
                INSERT INTO whiteboard_rooms
                    (id, session_id, title, status, created_by,
                     created_at, updated_at, closed_at,
                     participant_ids, canvas_state, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    session_id = excluded.session_id,
                    title = excluded.title,
                    status = excluded.status,
                    created_by = excluded.created_by,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    closed_at = excluded.closed_at,
                    participant_ids = excluded.participant_ids,
                    canvas_state = excluded.canvas_state,
                    metadata = excluded.metadata
                """,
                (
                    room.id,
                    room.session_id,
                    room.title,
                    room.status.value if hasattr(room.status, "value") else str(room.status),
                    room.created_by,
                    room.created_at.isoformat(),
                    room.updated_at.isoformat(),
                    room.closed_at.isoformat() if room.closed_at else None,
                    json.dumps(room.participant_ids),
                    json.dumps(room.canvas_state) if room.canvas_state is not None else None,
                    json.dumps(room.metadata),
                ),
            )

    def get_room(self, room_id: str) -> Optional[WhiteboardRoom]:
        cur = self._conn.execute(
            "SELECT * FROM whiteboard_rooms WHERE id = ?", (room_id,)
        )
        row = cur.fetchone()
        return self._row_to_room(row) if row else None

    def list_rooms(
        self,
        session_id: Optional[str] = None,
        status: Optional[RoomStatus] = None,
        created_by: Optional[str] = None,
        visible_to_user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardRoom]:
        clauses: List[str] = []
        params: List[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status:
            clauses.append("status = ?")
            params.append(status.value if hasattr(status, "value") else str(status))
        if created_by:
            clauses.append("created_by = ?")
            params.append(created_by)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        cur = self._conn.execute(
            f"SELECT * FROM whiteboard_rooms {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [self._row_to_room(r) for r in cur.fetchall()]

    def update_room(self, room: WhiteboardRoom) -> None:
        self.save_room(room)

    def delete_room(self, room_id: str) -> None:
        with self._tx() as cur:
            cur.execute("DELETE FROM whiteboard_rooms WHERE id = ?", (room_id,))

    def save_snapshot(self, snapshot: WhiteboardSnapshot) -> None:
        with self._tx() as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO whiteboard_snapshots
                    (id, room_id, session_id, format, canvas_data,
                     exported_at, created_by, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.id,
                    snapshot.room_id,
                    snapshot.session_id,
                    snapshot.format.value if hasattr(snapshot.format, "value") else str(snapshot.format),
                    json.dumps(snapshot.canvas_data),
                    snapshot.exported_at.isoformat(),
                    snapshot.created_by,
                    json.dumps(snapshot.metadata),
                ),
            )

    def get_snapshot(self, snapshot_id: str) -> Optional[WhiteboardSnapshot]:
        cur = self._conn.execute(
            "SELECT * FROM whiteboard_snapshots WHERE id = ?", (snapshot_id,)
        )
        row = cur.fetchone()
        return self._row_to_snapshot(row) if row else None

    def list_snapshots(
        self,
        room_id: Optional[str] = None,
        session_id: Optional[str] = None,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardSnapshot]:
        clauses: List[str] = []
        params: List[Any] = []
        if room_id:
            clauses.append("room_id = ?")
            params.append(room_id)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if created_by:
            clauses.append("created_by = ?")
            params.append(created_by)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        cur = self._conn.execute(
            f"SELECT * FROM whiteboard_snapshots {where} ORDER BY exported_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [self._row_to_snapshot(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# PostgresStorageBackend
# ---------------------------------------------------------------------------

_POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS whiteboard_rooms (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT 'Untitled',
    status TEXT NOT NULL DEFAULT 'creating',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    participant_ids JSONB NOT NULL DEFAULT '[]',
    canvas_state JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS whiteboard_snapshots (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'json',
    canvas_data JSONB NOT NULL DEFAULT '{}',
    exported_at TIMESTAMPTZ NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'
);
"""


class PostgresStorageBackend(StorageBackend):
    """psycopg2-backed Postgres storage for the standalone whiteboard package.

    Compatible with Neon serverless Postgres (standard psycopg2 protocol).

    Usage::

        storage = PostgresStorageBackend(dsn="postgresql://user:pass@host/db")
        service = WhiteboardService(storage=storage)

    Set ``WHITEBOARD_PG_DSN`` to configure via environment.  If ``dsn`` is
    not provided and the env var is absent, ``ValueError`` is raised.
    """

    def __init__(self, dsn: Optional[str] = None) -> None:
        import psycopg2
        import psycopg2.extras

        resolved_dsn = dsn or os.environ.get("WHITEBOARD_PG_DSN")
        if not resolved_dsn:
            raise ValueError(
                "PostgresStorageBackend requires a DSN via 'dsn' arg or WHITEBOARD_PG_DSN env var"
            )
        self._dsn = resolved_dsn
        self._psycopg2 = psycopg2
        self._extras = psycopg2.extras
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_POSTGRES_SCHEMA)

    @contextmanager
    def _conn(self) -> Generator[Any, None, None]:
        conn = self._psycopg2.connect(self._dsn)
        conn.autocommit = False
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _row_to_room(row: Dict[str, Any]) -> WhiteboardRoom:
        return WhiteboardRoom(
            id=str(row["id"]),
            session_id=row.get("session_id") or "",
            title=row.get("title") or "Untitled",
            status=RoomStatus(row["status"]),
            created_by=row.get("created_by") or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            closed_at=row.get("closed_at"),
            participant_ids=row.get("participant_ids") or [],
            canvas_state=row.get("canvas_state"),
            metadata=row.get("metadata") or {},
        )

    @staticmethod
    def _row_to_snapshot(row: Dict[str, Any]) -> WhiteboardSnapshot:
        from whiteboard.models import SnapshotFormat
        return WhiteboardSnapshot(
            id=str(row["id"]),
            room_id=str(row["room_id"]),
            session_id=row.get("session_id") or "",
            format=SnapshotFormat(row["format"]),
            canvas_data=row.get("canvas_data") or {},
            exported_at=row["exported_at"],
            created_by=row.get("created_by") or "",
            metadata=row.get("metadata") or {},
        )

    @staticmethod
    def _jsonb(value: Any) -> str:
        return json.dumps(value, default=str) if value is not None else "null"

    # -- StorageBackend --

    def save_room(self, room: WhiteboardRoom) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO whiteboard_rooms
                        (id, session_id, title, status, created_by,
                         created_at, updated_at, closed_at,
                         participant_ids, canvas_state, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                        session_id = EXCLUDED.session_id,
                        title = EXCLUDED.title,
                        status = EXCLUDED.status,
                        created_by = EXCLUDED.created_by,
                        updated_at = EXCLUDED.updated_at,
                        closed_at = EXCLUDED.closed_at,
                        participant_ids = EXCLUDED.participant_ids,
                        canvas_state = EXCLUDED.canvas_state,
                        metadata = EXCLUDED.metadata
                    """,
                    (
                        room.id,
                        room.session_id,
                        room.title,
                        room.status.value if hasattr(room.status, "value") else str(room.status),
                        room.created_by,
                        room.created_at,
                        room.updated_at,
                        room.closed_at,
                        self._jsonb(room.participant_ids),
                        self._jsonb(room.canvas_state),
                        self._jsonb(room.metadata),
                    ),
                )

    def get_room(self, room_id: str) -> Optional[WhiteboardRoom]:
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=self._extras.RealDictCursor)
            cur.execute("SELECT * FROM whiteboard_rooms WHERE id = %s", (room_id,))
            row = cur.fetchone()
            return self._row_to_room(dict(row)) if row else None

    def list_rooms(
        self,
        session_id: Optional[str] = None,
        status: Optional[RoomStatus] = None,
        created_by: Optional[str] = None,
        visible_to_user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardRoom]:
        clauses: List[str] = []
        params: List[Any] = []
        if session_id:
            clauses.append("session_id = %s")
            params.append(session_id)
        if status:
            clauses.append("status = %s")
            params.append(status.value if hasattr(status, "value") else str(status))
        if created_by:
            clauses.append("created_by = %s")
            params.append(created_by)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=self._extras.RealDictCursor)
            cur.execute(
                f"SELECT * FROM whiteboard_rooms {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params,
            )
            return [self._row_to_room(dict(r)) for r in cur.fetchall()]

    def update_room(self, room: WhiteboardRoom) -> None:
        self.save_room(room)

    def delete_room(self, room_id: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM whiteboard_rooms WHERE id = %s", (room_id,))

    def save_snapshot(self, snapshot: WhiteboardSnapshot) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO whiteboard_snapshots
                        (id, room_id, session_id, format, canvas_data,
                         exported_at, created_by, metadata)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                        canvas_data = EXCLUDED.canvas_data,
                        exported_at = EXCLUDED.exported_at,
                        metadata = EXCLUDED.metadata
                    """,
                    (
                        snapshot.id,
                        snapshot.room_id,
                        snapshot.session_id,
                        snapshot.format.value if hasattr(snapshot.format, "value") else str(snapshot.format),
                        self._jsonb(snapshot.canvas_data),
                        snapshot.exported_at,
                        snapshot.created_by,
                        self._jsonb(snapshot.metadata),
                    ),
                )

    def get_snapshot(self, snapshot_id: str) -> Optional[WhiteboardSnapshot]:
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=self._extras.RealDictCursor)
            cur.execute("SELECT * FROM whiteboard_snapshots WHERE id = %s", (snapshot_id,))
            row = cur.fetchone()
            return self._row_to_snapshot(dict(row)) if row else None

    def list_snapshots(
        self,
        room_id: Optional[str] = None,
        session_id: Optional[str] = None,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WhiteboardSnapshot]:
        clauses: List[str] = []
        params: List[Any] = []
        if room_id:
            clauses.append("room_id = %s")
            params.append(room_id)
        if session_id:
            clauses.append("session_id = %s")
            params.append(session_id)
        if created_by:
            clauses.append("created_by = %s")
            params.append(created_by)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        with self._conn() as conn:
            cur = conn.cursor(cursor_factory=self._extras.RealDictCursor)
            cur.execute(
                f"SELECT * FROM whiteboard_snapshots {where} ORDER BY exported_at DESC LIMIT %s OFFSET %s",
                params,
            )
            return [self._row_to_snapshot(dict(r)) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_storage_from_env() -> StorageBackend:
    """Create a StorageBackend from the ``WHITEBOARD_STORAGE_BACKEND`` env var.

    Supported values (case-insensitive):

    - ``"memory"`` (default) — :class:`InMemoryStorage`
    - ``"sqlite"`` — :class:`SqliteStorageBackend`, reads ``WHITEBOARD_SQLITE_PATH``
    - ``"postgres"`` — :class:`PostgresStorageBackend`, reads ``WHITEBOARD_PG_DSN``

    Example::

        WHITEBOARD_STORAGE_BACKEND=sqlite WHITEBOARD_SQLITE_PATH=/data/wb.db
        WHITEBOARD_STORAGE_BACKEND=postgres WHITEBOARD_PG_DSN=postgresql://...
    """
    backend = os.environ.get("WHITEBOARD_STORAGE_BACKEND", "memory").strip().lower()
    if backend == "sqlite":
        return SqliteStorageBackend()
    if backend in ("postgres", "postgresql"):
        return PostgresStorageBackend()
    if backend == "memory":
        return InMemoryStorage()
    raise ValueError(
        f"Unknown WHITEBOARD_STORAGE_BACKEND={backend!r}. "
        "Supported values: 'memory', 'sqlite', 'postgres'."
    )
