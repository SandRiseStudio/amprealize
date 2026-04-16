"""PostgreSQL storage backend for the Whiteboard service.

This module bridges the standalone ``whiteboard`` package (which has zero
core dependencies) with the Amprealize PostgresPool infrastructure and
context system.  It implements :class:`whiteboard.storage.StorageBackend`
so that room data is persisted to the ``whiteboard_rooms`` table managed
by Alembic migration ``20260413_whiteboard_rooms``.

Usage in ``api.py``::

    from amprealize.storage.whiteboard_postgres import PostgresWhiteboardStorage
    storage = PostgresWhiteboardStorage(pool=pool)
    service = WhiteboardService(storage=storage)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from whiteboard.models import RoomStatus, SnapshotFormat, WhiteboardRoom, WhiteboardSnapshot
from whiteboard.storage import StorageBackend

from amprealize.storage.postgres_pool import PostgresPool

__all__ = ["PostgresWhiteboardStorage"]


class PostgresWhiteboardStorage(StorageBackend):
    """Postgres-backed storage for whiteboard rooms.

    Reads/writes against the ``whiteboard_rooms`` table whose schema is
    defined by migration ``20260413_whiteboard_rooms``.
    """

    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    def ensure_schema_ready(self) -> None:
        """Raise if the whiteboard table is unavailable in the target database."""

        with self._pool.connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM whiteboard_rooms LIMIT 1")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_room(row: Dict[str, Any]) -> WhiteboardRoom:
        """Convert a database row dict to a WhiteboardRoom model."""
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
    def _json(value: Any) -> str:
        """Serialize a Python object to a JSON string for JSONB columns."""
        return json.dumps(value, default=str) if value is not None else "null"

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

    def save_room(self, room: WhiteboardRoom) -> None:
        with self._pool.connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO whiteboard_rooms
                        (id, session_id, title, status, created_by,
                         participant_ids, canvas_state, metadata,
                         created_at, updated_at, closed_at)
                    VALUES (%s, %s, %s, %s, %s,
                            %s::jsonb, %s::jsonb, %s::jsonb,
                            %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        session_id       = EXCLUDED.session_id,
                        title            = EXCLUDED.title,
                        status           = EXCLUDED.status,
                        created_by       = EXCLUDED.created_by,
                        participant_ids  = EXCLUDED.participant_ids,
                        canvas_state     = EXCLUDED.canvas_state,
                        metadata         = EXCLUDED.metadata,
                        updated_at       = EXCLUDED.updated_at,
                        closed_at        = EXCLUDED.closed_at
                    """,
                    (
                        room.id,
                        room.session_id,
                        room.title,
                        room.status.value,
                        room.created_by,
                        self._json(room.participant_ids),
                        self._json(room.canvas_state),
                        self._json(room.metadata),
                        room.created_at,
                        room.updated_at,
                        room.closed_at,
                    ),
                )

    def get_room(self, room_id: str) -> Optional[WhiteboardRoom]:
        with self._pool.connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM whiteboard_rooms WHERE id = %s",
                    (room_id,),
                )
                columns = [desc[0] for desc in cur.description]
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_room(dict(zip(columns, row)))

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

        if session_id is not None:
            clauses.append("session_id = %s")
            params.append(session_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status.value)
        if created_by is not None:
            clauses.append("created_by = %s")
            params.append(created_by)
        if visible_to_user_id is not None:
            # User can see rooms they created OR are a participant of
            clauses.append(
                "(created_by = %s OR participant_ids @> %s::jsonb)"
            )
            params.append(visible_to_user_id)
            params.append(self._json([visible_to_user_id]))

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        query = f"SELECT * FROM whiteboard_rooms {where} ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with self._pool.connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                columns = [desc[0] for desc in cur.description]
                return [
                    self._row_to_room(dict(zip(columns, row)))
                    for row in cur.fetchall()
                ]

    def update_room(self, room: WhiteboardRoom) -> None:
        room.updated_at = datetime.now(timezone.utc)
        self.save_room(room)

    def delete_room(self, room_id: str) -> bool:
        with self._pool.connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM whiteboard_rooms WHERE id = %s",
                    (room_id,),
                )
                return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Snapshot persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_snapshot(row: Dict[str, Any]) -> WhiteboardSnapshot:
        """Convert a database row dict to a WhiteboardSnapshot model."""
        return WhiteboardSnapshot(
            id=str(row["id"]),
            room_id=str(row["room_id"]),
            session_id=row.get("session_id") or "",
            title=row.get("title") or "Untitled",
            format=SnapshotFormat(row.get("format", "json")),
            data=row.get("data"),
            canvas_elements=row.get("canvas_elements"),
            thumbnail_url=row.get("thumbnail_url"),
            created_by=row.get("created_by") or "",
            exported_at=row["exported_at"],
            metadata=row.get("metadata") or {},
            shared_with=row.get("shared_with") or [],
        )

    def save_snapshot(self, snapshot: WhiteboardSnapshot) -> None:
        with self._pool.connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO whiteboard_snapshots
                        (id, room_id, session_id, title, format, data,
                         canvas_elements, thumbnail_url, created_by,
                         exported_at, metadata, shared_with)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb,
                            %s::jsonb, %s, %s,
                            %s, %s::jsonb, %s::jsonb)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        snapshot.id,
                        snapshot.room_id,
                        snapshot.session_id,
                        snapshot.title,
                        snapshot.format.value,
                        self._json(snapshot.data),
                        self._json(snapshot.canvas_elements),
                        snapshot.thumbnail_url,
                        snapshot.created_by,
                        snapshot.exported_at,
                        self._json(snapshot.metadata),
                        self._json(snapshot.shared_with),
                    ),
                )

    def get_snapshot(self, snapshot_id: str) -> Optional[WhiteboardSnapshot]:
        with self._pool.connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM whiteboard_snapshots WHERE id = %s",
                    (snapshot_id,),
                )
                columns = [desc[0] for desc in cur.description]
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_snapshot(dict(zip(columns, row)))

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

        if room_id is not None:
            clauses.append("room_id = %s")
            params.append(room_id)
        if session_id is not None:
            clauses.append("session_id = %s")
            params.append(session_id)
        if created_by is not None:
            clauses.append("created_by = %s")
            params.append(created_by)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        query = f"SELECT * FROM whiteboard_snapshots {where} ORDER BY exported_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with self._pool.connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                columns = [desc[0] for desc in cur.description]
                return [
                    self._row_to_snapshot(dict(zip(columns, row)))
                    for row in cur.fetchall()
                ]
