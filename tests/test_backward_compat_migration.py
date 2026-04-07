"""Tests for T4.4.2: Backward-compat migration for existing workspaces.

Covers:
- Workspace storage detection (Postgres / SQLite / JSON / Unknown)
- Pack bootstrap for existing workspaces
- Pack rollback (deactivation)
- RuntimeInjector no-pack backward compatibility
- Alembic migration structure
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ===========================================================================
# Storage Detector Tests
# ===========================================================================

class TestStorageDetector:
    """Verify workspace storage backend detection."""

    def test_detects_postgres_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When AMPREALIZE_PG_DSN is set, detect Postgres."""
        from amprealize.bootstrap.storage_detector import StorageBackend, detect_storage_backend

        monkeypatch.setenv("AMPREALIZE_PG_DSN", "postgresql://user:pw@localhost/db")
        # Patch the postgres check to avoid real DB connection
        with patch("amprealize.bootstrap.storage_detector._check_postgres_tables"):
            result = detect_storage_backend("/tmp/test-ws")
        assert result.backend == StorageBackend.POSTGRES
        assert "postgresql://" in result.path_or_dsn

    def test_detects_postgres_from_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to DATABASE_URL env var."""
        from amprealize.bootstrap.storage_detector import StorageBackend, detect_storage_backend

        monkeypatch.delenv("AMPREALIZE_PG_DSN", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host/db")
        with patch("amprealize.bootstrap.storage_detector._check_postgres_tables"):
            result = detect_storage_backend("/tmp/test-ws")
        assert result.backend == StorageBackend.POSTGRES

    def test_detects_sqlite(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When .amprealize/amprealize.db exists, detect SQLite."""
        from amprealize.bootstrap.storage_detector import StorageBackend, detect_storage_backend

        monkeypatch.delenv("AMPREALIZE_PG_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with tempfile.TemporaryDirectory() as td:
            amprealize_dir = Path(td) / ".amprealize"
            amprealize_dir.mkdir()
            (amprealize_dir / "amprealize.db").write_bytes(b"")

            with patch("amprealize.bootstrap.storage_detector._check_sqlite_tables"):
                result = detect_storage_backend(td)
            assert result.backend == StorageBackend.SQLITE
            assert "amprealize.db" in result.path_or_dsn

    def test_detects_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When .amprealize/ directory exists but no DB, detect JSON."""
        from amprealize.bootstrap.storage_detector import StorageBackend, detect_storage_backend

        monkeypatch.delenv("AMPREALIZE_PG_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with tempfile.TemporaryDirectory() as td:
            amprealize_dir = Path(td) / ".amprealize"
            amprealize_dir.mkdir()
            result = detect_storage_backend(td)
            assert result.backend == StorageBackend.JSON
            assert result.can_migrate

    def test_detects_unknown_fresh_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When nothing exists, report unknown."""
        from amprealize.bootstrap.storage_detector import StorageBackend, detect_storage_backend

        monkeypatch.delenv("AMPREALIZE_PG_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with tempfile.TemporaryDirectory() as td:
            result = detect_storage_backend(td)
            assert result.backend == StorageBackend.UNKNOWN
            assert result.can_migrate
            assert "Fresh workspace" in result.reason

    def test_result_to_dict(self) -> None:
        """StorageDetectionResult serialises cleanly."""
        from amprealize.bootstrap.storage_detector import StorageBackend, StorageDetectionResult

        result = StorageDetectionResult(
            backend=StorageBackend.POSTGRES,
            path_or_dsn="pg://localhost/db",
            has_feature_flags_table=True,
            has_activations_table=False,
            can_migrate=True,
        )
        d = result.to_dict()
        assert d["backend"] == "postgres"
        assert d["has_feature_flags_table"] is True
        assert d["has_activations_table"] is False


# ===========================================================================
# Pack Migration Service Tests
# ===========================================================================

class TestPackMigrationBootstrap:
    """Verify pack bootstrap for existing workspaces."""

    def test_bootstrap_fresh_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bootstrap on a fresh workspace with no AGENTS.md."""
        from amprealize.bootstrap.pack_migration import PackMigrationService

        monkeypatch.delenv("AMPREALIZE_PG_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with tempfile.TemporaryDirectory() as td:
            svc = PackMigrationService()
            result = svc.bootstrap(td)

            assert result.activated
            assert result.pack_id is not None
            assert "solo-dev" in result.pack_id  # default profile
            assert any("Fresh workspace" in n or "defaulting" in n for n in result.notes)

    def test_bootstrap_with_agents_md(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bootstrap builds a deterministic pack ID when AGENTS.md exists."""
        from amprealize.bootstrap.pack_migration import PackMigrationService

        monkeypatch.delenv("AMPREALIZE_PG_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with tempfile.TemporaryDirectory() as td:
            agents = Path(td) / "AGENTS.md"
            agents.write_text("# My Agent Handbook\n## Behaviors\n")

            svc = PackMigrationService()
            result = svc.bootstrap(td)

            assert result.activated
            assert "migrated-solo-dev-" in result.pack_id
            assert any("AGENTS.md" in n for n in result.notes)

    def test_bootstrap_with_explicit_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit profile override is respected."""
        from amprealize.bootstrap.pack_migration import PackMigrationService
        from amprealize.bootstrap.profile import WorkspaceProfile

        monkeypatch.delenv("AMPREALIZE_PG_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with tempfile.TemporaryDirectory() as td:
            svc = PackMigrationService()
            result = svc.bootstrap(td, profile=WorkspaceProfile.API_BACKEND)

            assert result.profile == WorkspaceProfile.API_BACKEND
            assert "api-backend" in result.pack_id

    def test_bootstrap_with_activation_service(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When ActivationService is provided, activation is persisted."""
        from amprealize.bootstrap.pack_migration import PackMigrationService

        monkeypatch.delenv("AMPREALIZE_PG_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        mock_activation = MagicMock()

        with tempfile.TemporaryDirectory() as td:
            svc = PackMigrationService(activation_service=mock_activation)
            result = svc.bootstrap(td)

            assert result.activated
            mock_activation.activate_pack.assert_called_once()
            call_kwargs = mock_activation.activate_pack.call_args
            assert call_kwargs[1]["auto_deactivate"] is True

    def test_bootstrap_activation_failure_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When ActivationService fails, it's reported (not raised)."""
        from amprealize.bootstrap.pack_migration import PackMigrationService

        monkeypatch.delenv("AMPREALIZE_PG_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        mock_activation = MagicMock()
        mock_activation.activate_pack.side_effect = RuntimeError("DB down")

        with tempfile.TemporaryDirectory() as td:
            svc = PackMigrationService(activation_service=mock_activation)
            result = svc.bootstrap(td)

            assert not result.activated
            assert any("failed" in n.lower() for n in result.notes)

    def test_bootstrap_with_bootstrap_service(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When BootstrapService is provided, full detection flow runs."""
        from amprealize.bootstrap.pack_migration import PackMigrationService
        from amprealize.bootstrap.profile import (
            ProfileDetectionResult,
            WorkspaceProfile,
        )

        monkeypatch.delenv("AMPREALIZE_PG_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        mock_bootstrap = MagicMock()
        mock_bootstrap.detect.return_value = ProfileDetectionResult(
            profile=WorkspaceProfile.API_BACKEND,
            confidence=0.85,
        )
        mock_boot_result = MagicMock()
        mock_boot_result.files_written = ["AGENTS.md"]
        mock_boot_result.notes = ["Activated pack"]
        mock_bootstrap.bootstrap.return_value = mock_boot_result

        with tempfile.TemporaryDirectory() as td:
            svc = PackMigrationService(bootstrap_service=mock_bootstrap)
            result = svc.bootstrap(td)

            assert result.activated
            assert result.profile == WorkspaceProfile.API_BACKEND
            mock_bootstrap.bootstrap.assert_called_once()

    def test_bootstrap_result_to_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BootstrapMigrationResult serialises to dict."""
        from amprealize.bootstrap.pack_migration import PackMigrationService

        monkeypatch.delenv("AMPREALIZE_PG_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with tempfile.TemporaryDirectory() as td:
            svc = PackMigrationService()
            result = svc.bootstrap(td)
            d = result.to_dict()

            assert "workspace_path" in d
            assert "storage" in d
            assert "pack_id" in d
            assert isinstance(d["notes"], list)


class TestPackMigrationRollback:
    """Verify pack rollback (deactivation)."""

    def test_rollback_no_activation_service(self) -> None:
        """Rollback without ActivationService reports gracefully."""
        from amprealize.bootstrap.pack_migration import PackMigrationService

        svc = PackMigrationService()
        result = svc.rollback("/tmp/test-ws")

        assert not result.deactivated
        assert any("No activation service" in n for n in result.notes)

    def test_rollback_no_active_pack(self) -> None:
        """Rollback when no pack is active reports correctly."""
        from amprealize.bootstrap.pack_migration import PackMigrationService

        mock_activation = MagicMock()
        mock_activation.get_active_pack.return_value = None

        svc = PackMigrationService(activation_service=mock_activation)
        result = svc.rollback("/tmp/test-ws")

        assert not result.deactivated
        assert any("No active pack" in n for n in result.notes)

    def test_rollback_deactivates_pack(self) -> None:
        """Rollback deactivates the active pack."""
        from amprealize.bootstrap.pack_migration import PackMigrationService

        mock_active = MagicMock()
        mock_active.pack_id = "test-pack"
        mock_active.pack_version = "1.0.0"
        mock_active.activation_id = "act-123"

        mock_activation = MagicMock()
        mock_activation.get_active_pack.return_value = mock_active

        svc = PackMigrationService(activation_service=mock_activation)
        result = svc.rollback("/tmp/test-ws")

        assert result.deactivated
        assert result.previous_pack_id == "test-pack"
        mock_activation.deactivate_pack.assert_called_once_with("act-123")

    def test_rollback_failure_reported(self) -> None:
        """Rollback failure is caught and reported."""
        from amprealize.bootstrap.pack_migration import PackMigrationService

        mock_activation = MagicMock()
        mock_activation.get_active_pack.side_effect = RuntimeError("Connection lost")

        svc = PackMigrationService(activation_service=mock_activation)
        result = svc.rollback("/tmp/test-ws")

        assert not result.deactivated
        assert any("failed" in n.lower() for n in result.notes)

    def test_rollback_result_to_dict(self) -> None:
        """RollbackResult serialises to dict."""
        from amprealize.bootstrap.pack_migration import RollbackResult

        result = RollbackResult(
            workspace_path="/tmp/ws",
            previous_pack_id="old-pack",
            deactivated=True,
            notes=["Done"],
        )
        d = result.to_dict()
        assert d["previous_pack_id"] == "old-pack"
        assert d["deactivated"] is True


# ===========================================================================
# RuntimeInjector No-Pack Backward Compat Tests
# ===========================================================================

class TestRuntimeInjectorNoPack:
    """Verify RuntimeInjector works identically when no pack is active."""

    def test_inject_without_pack(self) -> None:
        """inject() with no pack produces a valid result."""
        from amprealize.runtime_injector import RuntimeInjector

        injector = RuntimeInjector()
        result = injector.inject(
            task_description="Add a REST endpoint",
            surface="cli",
        )

        assert result is not None
        assert result.composed_prompt
        assert result.context.active_pack_id is None

    def test_inject_no_retriever_returns_empty_behaviors(self) -> None:
        """Without a BehaviorRetriever, no behaviors are injected."""
        from amprealize.runtime_injector import RuntimeInjector

        injector = RuntimeInjector()
        result = injector.inject(
            task_description="Fix a bug",
            surface="mcp",
        )

        assert result.behaviors_injected == []

    def test_inject_no_bci_produces_fallback_prompt(self) -> None:
        """Without BCIService, a simple fallback prompt is generated."""
        from amprealize.runtime_injector import RuntimeInjector

        injector = RuntimeInjector()
        result = injector.inject(
            task_description="Deploy to production",
            surface="web",
        )

        assert "Deploy to production" in result.composed_prompt

    def test_inject_no_context_resolver_uses_minimal(self) -> None:
        """Without ContextResolver, minimal context is built."""
        from amprealize.runtime_injector import RuntimeInjector

        injector = RuntimeInjector()
        result = injector.inject(
            task_description="Test task",
            surface="vscode",
            org_id="org-1",
            project_id="proj-1",
            user_id="user-1",
        )

        assert result.context.org_id == "org-1"
        assert result.context.project_id == "proj-1"
        assert result.context.user_id == "user-1"
        assert result.context.surface == "vscode"

    def test_inject_with_pack_fields_passes_through(self) -> None:
        """Pack fields are carried through even without a resolver."""
        from amprealize.runtime_injector import RuntimeInjector

        injector = RuntimeInjector()
        result = injector.inject(
            task_description="Test task",
            surface="cli",
            active_pack_id="my-pack",
            active_pack_version="2.0.0",
        )

        assert result.context.active_pack_id == "my-pack"
        assert result.context.active_pack_version == "2.0.0"


# ===========================================================================
# Alembic Migration Structure Tests
# ===========================================================================

class TestFeatureFlagsMigration:
    """Verify the Alembic migration file structure."""

    def test_migration_file_exists(self) -> None:
        """Migration file is present."""
        migration_path = Path(__file__).parent.parent / "migrations" / "versions" / "20260319_add_feature_flags_table.py"
        assert migration_path.exists(), f"Migration not found at {migration_path}"

    def test_migration_has_correct_revision_chain(self) -> None:
        """Migration references the correct down_revision."""
        import importlib.util

        migration_path = Path(__file__).parent.parent / "migrations" / "versions" / "20260319_add_feature_flags_table.py"
        spec = importlib.util.spec_from_file_location("migration", migration_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod.revision == "20260319_add_feature_flags"
        assert mod.down_revision == "20260318_add_kp_tables"

    def test_migration_has_upgrade_and_downgrade(self) -> None:
        """Migration defines both upgrade() and downgrade()."""
        import importlib.util

        migration_path = Path(__file__).parent.parent / "migrations" / "versions" / "20260319_add_feature_flags_table.py"
        spec = importlib.util.spec_from_file_location("migration", migration_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert callable(getattr(mod, "upgrade", None))
        assert callable(getattr(mod, "downgrade", None))


# ===========================================================================
# Pack ID Determinism Tests
# ===========================================================================

class TestPackIdDeterminism:
    """Verify pack IDs are deterministic from AGENTS.md content."""

    def test_same_content_same_id(self) -> None:
        """Same AGENTS.md content produces the same pack ID."""
        from amprealize.bootstrap.pack_migration import PackMigrationService
        from amprealize.bootstrap.profile import WorkspaceProfile

        with tempfile.TemporaryDirectory() as td:
            agents = Path(td) / "AGENTS.md"
            agents.write_text("# Handbook v1\n## Behaviors\n")

            id1 = PackMigrationService._pack_id_from_agents(agents, WorkspaceProfile.SOLO_DEV)
            id2 = PackMigrationService._pack_id_from_agents(agents, WorkspaceProfile.SOLO_DEV)
            assert id1 == id2

    def test_different_content_different_id(self) -> None:
        """Different AGENTS.md content produces different pack IDs."""
        from amprealize.bootstrap.pack_migration import PackMigrationService
        from amprealize.bootstrap.profile import WorkspaceProfile

        with tempfile.TemporaryDirectory() as td:
            agents = Path(td) / "AGENTS.md"

            agents.write_text("# Version 1\n")
            id1 = PackMigrationService._pack_id_from_agents(agents, WorkspaceProfile.SOLO_DEV)

            agents.write_text("# Version 2\n")
            id2 = PackMigrationService._pack_id_from_agents(agents, WorkspaceProfile.SOLO_DEV)

            assert id1 != id2

    def test_different_profile_different_id(self) -> None:
        """Same content but different profile produces different pack ID."""
        from amprealize.bootstrap.pack_migration import PackMigrationService
        from amprealize.bootstrap.profile import WorkspaceProfile

        with tempfile.TemporaryDirectory() as td:
            agents = Path(td) / "AGENTS.md"
            agents.write_text("# Same content\n")

            id1 = PackMigrationService._pack_id_from_agents(agents, WorkspaceProfile.SOLO_DEV)
            id2 = PackMigrationService._pack_id_from_agents(agents, WorkspaceProfile.API_BACKEND)

            assert id1 != id2
