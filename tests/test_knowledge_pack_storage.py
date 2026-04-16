"""
Unit tests for KnowledgePackStorage.

Tests verify:
- save_manifest / get_manifest round-trip
- Latest-version resolution (ORDER BY created_at DESC)
- list_packs with scope/status filters
- update_status lifecycle
- delete_pack (overlays removed, not activations)
- save_overlays / get_overlays with kind filter
- save_artifact compound operation
- get_manifest_for_runtime graceful fallback
- Duplicate pack_id+version raises PackVersionExistsError
- PackNotFoundError raised when missing

Following `behavior_design_test_strategy` (Student).

Run with: pytest tests/test_knowledge_pack_storage.py -v
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from amprealize.knowledge_pack.storage import (
    KnowledgePackStorage,
    PackNotFoundError,
    PackStorageError,
    PackVersionExistsError,
)
from amprealize.knowledge_pack.schema import (
    KnowledgePackManifest,
    OverlayFragment,
    OverlayKind,
    PackConstraints,
    PackScope,
    PackSource,
    PackSourceType,
    SourceScope,
)
from amprealize.knowledge_pack.builder import KnowledgePackArtifact


pytestmark = pytest.mark.unit


# =============================================================================
# Helpers
# =============================================================================


def _mock_pool() -> MagicMock:
    """Create a mock pool with connection() context-manager chain."""
    pool = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()

    pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connection.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    return pool


def _cursor_from_pool(pool: MagicMock) -> MagicMock:
    """Extract the mock cursor from a mock pool."""
    conn = pool.connection.return_value.__enter__.return_value
    return conn.cursor.return_value.__enter__.return_value


def _make_manifest(
    pack_id: str = "test-pack",
    version: str = "1.0.0",
    scope: PackScope = PackScope.WORKSPACE,
) -> KnowledgePackManifest:
    """Create a minimal valid manifest for testing."""
    return KnowledgePackManifest(
        pack_id=pack_id,
        version=version,
        scope=scope,
        workspace_profiles=["solo_dev"],
        surfaces=["cli"],
        sources=[],
        doctrine_fragments=[],
        behavior_refs=["behavior_test"],
        task_overlays=[],
        surface_overlays=[],
        constraints=PackConstraints(
            strict_role_declaration=False,
            strict_behavior_citation=False,
            mandatory_overlays=[],
        ),
    )


def _make_overlays(
    pack_id: str = "test-pack",
    pack_version: str = "1.0.0",
    count: int = 2,
) -> List[OverlayFragment]:
    """Create sample overlay fragments for testing."""
    overlays = []
    for i in range(count):
        overlays.append(
            OverlayFragment(
                overlay_id=f"overlay-{i}",
                kind=OverlayKind.TASK if i % 2 == 0 else OverlayKind.SURFACE,
                applies_to={"task_family": "code_generation"},
                instructions=[f"Instruction {i}"],
                retrieval_keywords=[f"keyword-{i}"],
                priority=i + 1,
            )
        )
    return overlays


def _make_artifact(
    pack_id: str = "test-pack",
    version: str = "1.0.0",
) -> KnowledgePackArtifact:
    """Create a minimal artifact for testing."""
    manifest = _make_manifest(pack_id=pack_id, version=version)
    overlays = _make_overlays(pack_id=pack_id, pack_version=version)
    return KnowledgePackArtifact(
        manifest=manifest,
        primer_text="Test primer text content",
        overlays=overlays,
        retrieval_metadata={"token_count": 500},
        build_log=["Built successfully"],
    )


# =============================================================================
# save_manifest
# =============================================================================


class TestSaveManifest:
    """Tests for KnowledgePackStorage.save_manifest."""

    def test_save_manifest_success(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        # No existing row for this pack_id+version
        cursor.fetchone.return_value = None

        storage = KnowledgePackStorage(pool=pool)
        manifest = _make_manifest()
        result = storage.save_manifest(manifest, primer_text="Hello", status="draft", created_by="user-1")

        assert result["pack_id"] == "test-pack"
        assert result["version"] == "1.0.0"
        assert result["status"] == "draft"
        # Cursor execute should have been called at least twice (SELECT check + INSERT)
        assert cursor.execute.call_count >= 2

    def test_save_manifest_duplicate_raises(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        # Existing row found
        cursor.fetchone.return_value = ("test-pack", "1.0.0")

        storage = KnowledgePackStorage(pool=pool)
        manifest = _make_manifest()

        with pytest.raises(PackVersionExistsError):
            storage.save_manifest(manifest, status="draft")

    def test_save_manifest_stores_primer_in_json(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        cursor.fetchone.return_value = None

        storage = KnowledgePackStorage(pool=pool)
        manifest = _make_manifest()
        storage.save_manifest(manifest, primer_text="My primer")

        # Find the INSERT call and verify _primer_text is in the JSON blob
        insert_call = None
        for call in cursor.execute.call_args_list:
            sql = call[0][0] if call[0] else ""
            if "INSERT INTO knowledge_pack_manifests" in sql:
                insert_call = call
                break
        assert insert_call is not None
        # INSERT params: (pack_id, version, manifest_json, status, created_by, created_at)
        params = insert_call[0][1]
        manifest_json = params[2]
        # Could be a string (SQLite) or dict (passed to Postgres JSONB)
        if isinstance(manifest_json, str):
            data = json.loads(manifest_json)
        else:
            data = manifest_json
        assert data["_primer_text"] == "My primer"


# =============================================================================
# get_manifest
# =============================================================================


class TestGetManifest:
    """Tests for KnowledgePackStorage.get_manifest."""

    def test_get_manifest_specific_version(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        manifest_json = json.dumps({
            "pack_id": "test-pack",
            "version": "1.0.0",
            "_primer_text": "Hello",
        })
        # SQL: SELECT manifest_json, status, created_by, created_at
        cursor.fetchone.return_value = (
            manifest_json,
            "published",
            "user-1",
            "2026-03-18T12:00:00+00:00",
        )

        storage = KnowledgePackStorage(pool=pool)
        result = storage.get_manifest("test-pack", "1.0.0")

        assert result["pack_id"] == "test-pack"
        assert result["version"] == "1.0.0"
        assert result["_primer_text"] == "Hello"
        assert result["_storage_meta"]["status"] == "published"

    def test_get_manifest_latest_version(self):
        """When version=None, should use ORDER BY created_at DESC LIMIT 1."""
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        # SQL: SELECT manifest_json, status, created_by, created_at
        cursor.fetchone.return_value = (
            json.dumps({"pack_id": "test-pack", "version": "2.0.0"}),
            "published",
            "user-1",
            "2026-03-19T12:00:00+00:00",
        )

        storage = KnowledgePackStorage(pool=pool)
        result = storage.get_manifest("test-pack")

        # Verify SQL uses ORDER BY ... DESC LIMIT 1
        sql_call = cursor.execute.call_args[0][0]
        assert "ORDER BY" in sql_call
        assert "DESC" in sql_call
        assert "LIMIT 1" in sql_call
        assert result["version"] == "2.0.0"

    def test_get_manifest_not_found_raises(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        cursor.fetchone.return_value = None

        storage = KnowledgePackStorage(pool=pool)

        with pytest.raises(PackNotFoundError):
            storage.get_manifest("nonexistent")

    def test_get_manifest_handles_json_string(self):
        """SQLite stores JSON as TEXT, Postgres auto-decodes JSONB."""
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        json_str = json.dumps({"pack_id": "pk", "version": "1.0.0"})
        # SQL: SELECT manifest_json, status, created_by, created_at
        cursor.fetchone.return_value = (json_str, "draft", None, None)

        storage = KnowledgePackStorage(pool=pool)
        result = storage.get_manifest("pk", "1.0.0")
        assert result["pack_id"] == "pk"

    def test_get_manifest_handles_dict(self):
        """Postgres returns dict from JSONB column."""
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        json_dict = {"pack_id": "pk", "version": "1.0.0"}
        # SQL: SELECT manifest_json, status, created_by, created_at
        cursor.fetchone.return_value = (json_dict, "draft", None, None)

        storage = KnowledgePackStorage(pool=pool)
        result = storage.get_manifest("pk", "1.0.0")
        assert result["pack_id"] == "pk"


# =============================================================================
# list_packs
# =============================================================================


class TestListPacks:
    """Tests for KnowledgePackStorage.list_packs."""

    def test_list_packs_returns_structure(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        # list_packs does COUNT first, then SELECT with 6 cols
        # SQL: pack_id, version, status, created_by, created_at, manifest_json
        cursor.fetchone.return_value = (2,)  # COUNT result
        cursor.fetchall.return_value = [
            ("pack-a", "2.0.0", "published", "user-1", "2026-03-19T00:00:00+00:00", json.dumps({"scope": "workspace"})),
            ("pack-b", "1.0.0", "draft", "user-2", "2026-03-18T00:00:00+00:00", json.dumps({"scope": "workspace"})),
        ]

        storage = KnowledgePackStorage(pool=pool)
        result = storage.list_packs()

        assert result["total_count"] == 2
        assert len(result["packs"]) == 2
        assert result["packs"][0]["pack_id"] == "pack-a"
        assert result["packs"][1]["pack_id"] == "pack-b"

    def test_list_packs_with_scope_filter(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        cursor.fetchone.return_value = (0,)  # COUNT result
        cursor.fetchall.return_value = []

        storage = KnowledgePackStorage(pool=pool)
        result = storage.list_packs(scope="workspace")

        # Scope filter is applied in Python, not SQL
        assert result["packs"] == []

    def test_list_packs_empty(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        cursor.fetchone.return_value = (0,)  # COUNT result
        cursor.fetchall.return_value = []

        storage = KnowledgePackStorage(pool=pool)
        result = storage.list_packs()

        assert result["total_count"] == 0
        assert result["packs"] == []


# =============================================================================
# update_status
# =============================================================================


class TestUpdateStatus:
    """Tests for KnowledgePackStorage.update_status."""

    def test_update_status_success(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        cursor.rowcount = 1

        storage = KnowledgePackStorage(pool=pool)
        storage.update_status("test-pack", "1.0.0", "archived")

        sql = cursor.execute.call_args[0][0]
        assert "UPDATE" in sql
        assert "knowledge_pack_manifests" in sql

    def test_update_status_not_found(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        cursor.rowcount = 0

        storage = KnowledgePackStorage(pool=pool)

        with pytest.raises(PackNotFoundError):
            storage.update_status("missing", "1.0.0", "archived")


# =============================================================================
# delete_pack
# =============================================================================


class TestDeletePack:
    """Tests for KnowledgePackStorage.delete_pack."""

    def test_delete_pack_removes_overlays_and_manifest(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        # First execute deletes overlays, second deletes manifest
        # manifest delete affects 1 row
        cursor.rowcount = 1

        storage = KnowledgePackStorage(pool=pool)
        storage.delete_pack("test-pack", "1.0.0")

        # Should have executed two DELETEs
        delete_calls = [
            c for c in cursor.execute.call_args_list
            if "DELETE" in c[0][0]
        ]
        assert len(delete_calls) == 2

        # First DELETE should be overlays
        assert "knowledge_pack_overlays" in delete_calls[0][0][0]
        # Second DELETE should be manifests
        assert "knowledge_pack_manifests" in delete_calls[1][0][0]

    def test_delete_pack_not_found(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        cursor.rowcount = 0

        storage = KnowledgePackStorage(pool=pool)

        with pytest.raises(PackNotFoundError):
            storage.delete_pack("nonexistent", "1.0.0")


# =============================================================================
# save_overlays / get_overlays
# =============================================================================


class TestOverlays:
    """Tests for KnowledgePackStorage overlay operations."""

    def test_save_overlays_inserts_batch(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)

        storage = KnowledgePackStorage(pool=pool)
        overlays = _make_overlays(count=3)
        result = storage.save_overlays("test-pack", "1.0.0", overlays)

        # save_overlays returns int, not dict
        assert result == 3
        # Should have 3 INSERT calls for overlays
        insert_calls = [
            c for c in cursor.execute.call_args_list
            if "INSERT INTO knowledge_pack_overlays" in c[0][0]
        ]
        assert len(insert_calls) == 3

    def test_get_overlays_returns_list(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        # SQL: SELECT overlay_id, kind, applies_to, instructions,
        #             retrieval_keywords, priority, created_at
        cursor.fetchall.return_value = [
            (
                "overlay-0",
                "task",
                json.dumps({"task_family": "code_generation"}),
                json.dumps(["Do the thing"]),
                json.dumps(["keyword-1"]),
                1,
                "2026-03-18T00:00:00+00:00",
            ),
        ]

        storage = KnowledgePackStorage(pool=pool)
        result = storage.get_overlays("test-pack", "1.0.0")

        assert len(result) == 1
        assert result[0]["overlay_id"] == "overlay-0"
        assert result[0]["kind"] == "task"

    def test_get_overlays_with_kind_filter(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        cursor.fetchall.return_value = []

        storage = KnowledgePackStorage(pool=pool)
        storage.get_overlays("test-pack", "1.0.0", kind="surface")

        sql = cursor.execute.call_args[0][0]
        assert "kind" in sql


# =============================================================================
# save_artifact (compound operation)
# =============================================================================


class TestSaveArtifact:
    """Tests for KnowledgePackStorage.save_artifact."""

    def test_save_artifact_stores_manifest_and_overlays(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        # No existing row for duplicate check
        cursor.fetchone.return_value = None

        storage = KnowledgePackStorage(pool=pool)
        artifact = _make_artifact()
        result = storage.save_artifact(artifact, status="published", created_by="user-1")

        assert result["pack_id"] == "test-pack"
        assert result["version"] == "1.0.0"
        assert result["overlay_count"] == 2

        # Should have INSERTs for both manifest and overlays
        all_sqls = [c[0][0] for c in cursor.execute.call_args_list]
        has_manifest_insert = any("INSERT INTO knowledge_pack_manifests" in s for s in all_sqls)
        has_overlay_insert = any("INSERT INTO knowledge_pack_overlays" in s for s in all_sqls)
        assert has_manifest_insert
        assert has_overlay_insert


# =============================================================================
# get_manifest_for_runtime (graceful fallback)
# =============================================================================


class TestGetManifestForRuntime:
    """Tests for KnowledgePackStorage.get_manifest_for_runtime."""

    def test_returns_none_when_not_found(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        cursor.fetchone.return_value = None

        storage = KnowledgePackStorage(pool=pool)
        result = storage.get_manifest_for_runtime("nonexistent")

        assert result is None

    def test_returns_dict_when_found(self):
        pool = _mock_pool()
        cursor = _cursor_from_pool(pool)
        # SQL: SELECT manifest_json, status, created_by, created_at
        cursor.fetchone.return_value = (
            json.dumps({"pack_id": "pk", "version": "1.0.0", "_primer_text": "Hi"}),
            "published",
            "user-1",
            "2026-03-18T12:00:00+00:00",
        )

        storage = KnowledgePackStorage(pool=pool)
        result = storage.get_manifest_for_runtime("pk", "1.0.0")

        assert result is not None
        assert result["pack_id"] == "pk"
        assert result["_primer_text"] == "Hi"

    def test_returns_none_on_exception(self):
        pool = _mock_pool()
        pool.connection.side_effect = Exception("DB down")

        storage = KnowledgePackStorage(pool=pool)
        result = storage.get_manifest_for_runtime("pk")

        assert result is None


# =============================================================================
# Lazy pool initialization
# =============================================================================


class TestPoolInit:
    """Tests for lazy pool initialization."""

    def test_injected_pool_used_directly(self):
        pool = _mock_pool()
        storage = KnowledgePackStorage(pool=pool)
        assert storage._get_pool() is pool

    @patch("amprealize.knowledge_pack.storage.PostgresPool")
    @patch("amprealize.knowledge_pack.storage.resolve_postgres_dsn")
    def test_lazy_creates_pool_from_dsn(self, mock_resolve, mock_pg_pool):
        mock_resolve.return_value = "postgresql://test:test@localhost/test"
        mock_pg_pool.return_value = MagicMock()

        storage = KnowledgePackStorage(dsn="postgresql://test:test@localhost/test")
        pool = storage._get_pool()

        assert pool is not None
        mock_pg_pool.assert_called_once()
