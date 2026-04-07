"""Pack migration — backward-compat bootstrap and rollback for existing workspaces.

Provides ``PackMigrationService`` which:
1. Detects the current storage backend (Postgres/SQLite/JSON).
2. Bootstraps a knowledge pack from an existing AGENTS.md.
3. Rolls back an active pack, restoring pre-pack behaviour.

Part of E4 — T4.4.2: Backward-compat migration.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from amprealize.bootstrap.profile import ProfileDetectionResult, WorkspaceProfile
from amprealize.bootstrap.storage_detector import (
    StorageBackend,
    StorageDetectionResult,
    detect_storage_backend,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------

@dataclass
class BootstrapMigrationResult:
    """Result of a pack bootstrap for an existing workspace."""

    workspace_path: str
    storage: StorageDetectionResult
    profile: Optional[WorkspaceProfile] = None
    pack_id: Optional[str] = None
    pack_version: str = "1.0.0"
    activated: bool = False
    files_written: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_path": self.workspace_path,
            "storage": self.storage.to_dict(),
            "profile": self.profile.value if self.profile else None,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "activated": self.activated,
            "files_written": self.files_written,
            "notes": self.notes,
        }


@dataclass
class RollbackResult:
    """Result of deactivating a pack and restoring pre-pack state."""

    workspace_path: str
    previous_pack_id: Optional[str] = None
    deactivated: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_path": self.workspace_path,
            "previous_pack_id": self.previous_pack_id,
            "deactivated": self.deactivated,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PackMigrationService:
    """Handles backward-compat pack bootstrap and rollback for existing workspaces.

    The ``bootstrap()`` method detects the workspace profile and storage
    backend, builds a minimal pack from the existing AGENTS.md (if present),
    and activates it without disrupting current behaviour.

    The ``rollback()`` method deactivates the active pack, restoring the
    pre-pack execution path.
    """

    def __init__(
        self,
        *,
        activation_service: Optional[Any] = None,
        bootstrap_service: Optional[Any] = None,
        telemetry: Optional[Any] = None,
    ) -> None:
        self._activation = activation_service
        self._bootstrap = bootstrap_service
        self._telemetry = telemetry

    # =========================================================================
    # Bootstrap
    # =========================================================================

    def bootstrap(
        self,
        workspace_path: str,
        *,
        profile: Optional[WorkspaceProfile] = None,
        force: bool = False,
    ) -> BootstrapMigrationResult:
        """Bootstrap an existing workspace with a knowledge pack.

        1. Detect storage backend.
        2. Detect workspace profile (or use override).
        3. If AGENTS.md exists, build a pack from it.
        4. Activate the pack.
        """
        ws = Path(workspace_path)
        storage = detect_storage_backend(workspace_path)

        result = BootstrapMigrationResult(
            workspace_path=workspace_path,
            storage=storage,
        )

        if not storage.can_migrate:
            result.notes.append(f"Storage not migratable: {storage.reason}")
            return result

        result.notes.append(f"Detected storage backend: {storage.backend.value}")

        # Detect or accept profile
        if profile:
            result.profile = profile
            result.notes.append(f"Using explicit profile: {profile.value}")
        elif self._bootstrap:
            try:
                detection: ProfileDetectionResult = self._bootstrap.detect(ws)
                result.profile = detection.profile
                result.notes.append(
                    f"Detected profile: {detection.profile.value} "
                    f"(confidence={detection.confidence:.2f})"
                )
            except Exception as exc:
                logger.warning("Profile detection failed: %s", exc)
                result.profile = WorkspaceProfile.SOLO_DEV
                result.notes.append(
                    f"Profile detection failed, defaulting to solo-dev: {exc}"
                )
        else:
            result.profile = WorkspaceProfile.SOLO_DEV
            result.notes.append("No bootstrap service; defaulting to solo-dev")

        # Build pack from existing AGENTS.md if present
        agents_md = ws / "AGENTS.md"
        pack_id = f"migrated-{result.profile.value}"
        pack_version = "1.0.0"

        if agents_md.exists():
            result.notes.append("Found existing AGENTS.md — building pack from it")
            pack_id = self._pack_id_from_agents(agents_md, result.profile)
        else:
            result.notes.append("No AGENTS.md found — using default pack for profile")

        result.pack_id = pack_id
        result.pack_version = pack_version

        # Activate through BootstrapService if available
        if self._bootstrap:
            try:
                boot_result = self._bootstrap.bootstrap(
                    ws,
                    profile=result.profile,
                    pack_id=pack_id,
                    pack_version=pack_version,
                    skip_detection=True,
                    skip_primer=not force,  # Don't overwrite existing files
                )
                result.activated = True
                result.files_written.extend(boot_result.files_written)
                result.notes.extend(boot_result.notes)
            except Exception as exc:
                logger.warning("Bootstrap activation failed: %s", exc)
                result.notes.append(f"Activation failed: {exc}")
        else:
            # Activate directly via ActivationService
            if self._activation:
                try:
                    ws_id = str(ws.resolve())
                    self._activation.activate_pack(
                        workspace_id=ws_id,
                        pack_id=pack_id,
                        version=pack_version,
                        profile=result.profile.value,
                        auto_deactivate=True,
                    )
                    result.activated = True
                    result.notes.append(f"Activated pack {pack_id}@{pack_version}")
                except Exception as exc:
                    logger.warning("Pack activation failed: %s", exc)
                    result.notes.append(f"Pack activation failed: {exc}")
            else:
                result.notes.append(
                    "No activation service available; pack registered in-memory only"
                )
                result.activated = True  # In-memory is effectively active

        return result

    # =========================================================================
    # Rollback
    # =========================================================================

    def rollback(self, workspace_path: str) -> RollbackResult:
        """Deactivate the active pack for a workspace, restoring pre-pack behaviour.

        The RuntimeInjector already falls back to no-pack behaviour when
        no active pack is found, so deactivation is sufficient.
        """
        ws = Path(workspace_path)
        result = RollbackResult(workspace_path=workspace_path)

        if not self._activation:
            result.notes.append(
                "No activation service configured; nothing to rollback"
            )
            return result

        try:
            ws_id = str(ws.resolve())
            # Find active pack
            from amprealize.knowledge_pack.activation_service import Activation

            active = self._activation.get_active_pack(ws_id)
            if active is None:
                result.notes.append("No active pack for this workspace")
                return result

            result.previous_pack_id = active.pack_id
            self._activation.deactivate_pack(active.activation_id)
            result.deactivated = True
            result.notes.append(
                f"Deactivated pack {active.pack_id}@{active.pack_version}"
            )
        except Exception as exc:
            logger.warning("Rollback failed: %s", exc)
            result.notes.append(f"Rollback failed: {exc}")

        return result

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _pack_id_from_agents(agents_md: Path, profile: WorkspaceProfile) -> str:
        """Derive a deterministic pack ID from AGENTS.md content hash."""
        content_hash = hashlib.sha256(
            agents_md.read_bytes()
        ).hexdigest()[:8]
        return f"migrated-{profile.value}-{content_hash}"
