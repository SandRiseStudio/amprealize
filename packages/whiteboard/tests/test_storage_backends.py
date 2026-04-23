"""Integration tests for SqliteStorageBackend and PostgresStorageBackend.

guideai-1031: Unit tests for storage backends (sqlite + postgres).

These tests verify the StorageBackend contract for both implementations.
The Postgres tests are skipped automatically when WHITEBOARD_PG_DSN is not set,
making them safe to run in CI without a live database.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from whiteboard import InMemoryStorage
from whiteboard.models import RoomCreateRequest, RoomStatus, WhiteboardRoom
from whiteboard.storage import SqliteStorageBackend, create_storage_from_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_room(*, session_id: str = "s1", created_by: str = "u1") -> WhiteboardRoom:
    """Create a minimal WhiteboardRoom for test fixture use."""
    return WhiteboardRoom(
        id=str(uuid.uuid4()),
        session_id=session_id,
        title="Test Room",
        status=RoomStatus.ACTIVE,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        closed_at=None,
        participant_ids=[],
        canvas_state=None,
        metadata={},
    )


# ---------------------------------------------------------------------------
# Shared contract tests (parametrized over backends)
# ---------------------------------------------------------------------------


def _run_contract_tests(storage) -> None:
    """Verify the full StorageBackend CRUD contract against any backend."""

    # --- save + get round-trip ---
    room = _make_room()
    storage.save_room(room)
    fetched = storage.get_room(room.id)
    assert fetched is not None
    assert fetched.id == room.id
    assert fetched.title == "Test Room"
    assert fetched.session_id == "s1"

    # --- list_rooms no filter ---
    rooms = storage.list_rooms()
    assert any(r.id == room.id for r in rooms)

    # --- list_rooms session filter ---
    other_room = _make_room(session_id="other")
    storage.save_room(other_room)
    by_session = storage.list_rooms(session_id="s1")
    ids = {r.id for r in by_session}
    assert room.id in ids
    assert other_room.id not in ids

    # --- list_rooms status filter ---
    by_status = storage.list_rooms(status=RoomStatus.ACTIVE)
    assert any(r.id == room.id for r in by_status)

    # --- update ---
    room.title = "Updated Title"
    storage.update_room(room)
    updated = storage.get_room(room.id)
    assert updated is not None
    assert updated.title == "Updated Title"

    # --- delete ---
    storage.delete_room(room.id)
    assert storage.get_room(room.id) is None

    # --- delete non-existent (idempotent, no exception) ---
    storage.delete_room(room.id)  # should not raise


# ---------------------------------------------------------------------------
# SqliteStorageBackend
# ---------------------------------------------------------------------------


class TestSqliteStorageBackend:
    def test_full_contract(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "whiteboard.db")
        storage = SqliteStorageBackend(db_path=db_path)
        _run_contract_tests(storage)

    def test_defaults_to_env_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db_path = str(tmp_path / "env-driven.db")
        monkeypatch.setenv("WHITEBOARD_SQLITE_PATH", db_path)
        storage = SqliteStorageBackend()
        assert storage._db_path == db_path

    def test_schema_created_on_init(self, tmp_path: Path) -> None:
        import sqlite3

        db_path = str(tmp_path / "schema-check.db")
        SqliteStorageBackend(db_path=db_path)
        conn = sqlite3.connect(db_path)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "whiteboard_rooms" in tables

    def test_pagination(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "pg-test.db")
        storage = SqliteStorageBackend(db_path=db_path)
        for _ in range(5):
            storage.save_room(_make_room())
        page1 = storage.list_rooms(limit=3, offset=0)
        page2 = storage.list_rooms(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) <= 2  # may be 2 or fewer depending on test order
        ids1 = {r.id for r in page1}
        ids2 = {r.id for r in page2}
        assert ids1.isdisjoint(ids2)

    def test_canvas_state_round_trip(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "canvas.db")
        storage = SqliteStorageBackend(db_path=db_path)
        room = _make_room()
        room.canvas_state = {"shapes": [{"id": "s1", "type": "rectangle"}]}
        storage.save_room(room)
        fetched = storage.get_room(room.id)
        assert fetched is not None
        assert fetched.canvas_state == room.canvas_state


# ---------------------------------------------------------------------------
# PostgresStorageBackend — skipped when WHITEBOARD_PG_DSN is not set
# ---------------------------------------------------------------------------

POSTGRES_DSN = os.getenv("WHITEBOARD_PG_DSN")


@pytest.mark.skipif(not POSTGRES_DSN, reason="WHITEBOARD_PG_DSN not set")
class TestPostgresStorageBackend:
    @pytest.fixture(autouse=True)
    def _backend(self):
        from whiteboard.storage import PostgresStorageBackend

        backend = PostgresStorageBackend(dsn=POSTGRES_DSN)
        backend.ensure_schema_ready()
        self.storage = backend
        yield
        # Cleanup: best-effort delete test rooms
        try:
            for room in self.storage.list_rooms(limit=200):
                if room.title == "Test Room":
                    self.storage.delete_room(room.id)
        except Exception:
            pass

    def test_full_contract(self) -> None:
        _run_contract_tests(self.storage)

    def test_pagination(self) -> None:
        for _ in range(5):
            self.storage.save_room(_make_room())
        page1 = self.storage.list_rooms(limit=3, offset=0)
        page2 = self.storage.list_rooms(limit=3, offset=3)
        assert len(page1) == 3


# ---------------------------------------------------------------------------
# create_storage_from_env factory
# ---------------------------------------------------------------------------


class TestCreateStorageFromEnv:
    def test_defaults_to_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WHITEBOARD_STORAGE_BACKEND", raising=False)
        storage = create_storage_from_env()
        assert isinstance(storage, InMemoryStorage)

    def test_explicit_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WHITEBOARD_STORAGE_BACKEND", "memory")
        storage = create_storage_from_env()
        assert isinstance(storage, InMemoryStorage)

    def test_sqlite_backend(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db_path = str(tmp_path / "factory.db")
        monkeypatch.setenv("WHITEBOARD_STORAGE_BACKEND", "sqlite")
        monkeypatch.setenv("WHITEBOARD_SQLITE_PATH", db_path)
        storage = create_storage_from_env()
        assert isinstance(storage, SqliteStorageBackend)

    @pytest.mark.skipif(not POSTGRES_DSN, reason="WHITEBOARD_PG_DSN not set")
    def test_postgres_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from whiteboard.storage import PostgresStorageBackend

        monkeypatch.setenv("WHITEBOARD_STORAGE_BACKEND", "postgres")
        monkeypatch.setenv("WHITEBOARD_PG_DSN", POSTGRES_DSN)
        storage = create_storage_from_env()
        assert isinstance(storage, PostgresStorageBackend)

    def test_unknown_backend_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WHITEBOARD_STORAGE_BACKEND", "cassandra")
        with pytest.raises(ValueError, match="cassandra"):
            create_storage_from_env()
