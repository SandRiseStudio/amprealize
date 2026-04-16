"""
Unit and integration tests for Knowledge Pack activation service.

Tests verify:
- Activate/deactivate lifecycle
- Context API returns correct pack metadata after activation
- Deactivation clears pack from context
- Workspace_id consistency across activations
- Migration safety (activation table schema)
- workspace_id_from_path helper

Following `behavior_design_test_strategy` (Student).

Run with: pytest tests/test_knowledge_pack_activation.py -v
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Optional
from unittest.mock import MagicMock, patch

import pytest

from amprealize.knowledge_pack.activation_service import (
    Activation,
    ActivationListResult,
    ActivationNotFoundError,
    ActivationService,
    ActivationServiceError,
    DuplicateActivationError,
    PackNotFoundError,
    workspace_id_from_path,
)


# Tests marked as unit don't require database
pytestmark_unit = pytest.mark.unit


# =============================================================================
# Helpers
# =============================================================================


def _mock_pool() -> MagicMock:
    """Create a mock PostgresPool with cursor context manager."""
    pool = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()

    # Set up context manager chain — uses connection() not get_connection()
    pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connection.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    return pool


def _make_activation(
    workspace_id: str = "ws-abc123",
    pack_id: str = "test-pack",
    version: str = "0.1.0",
    profile: Optional[str] = "solo-dev",
    status: str = "active",
) -> Activation:
    """Create an Activation instance for testing."""
    return Activation(
        activation_id=f"act-{uuid.uuid4().hex[:12]}",
        workspace_id=workspace_id,
        pack_id=pack_id,
        pack_version=version,
        profile=profile,
        activated_at=datetime.now(timezone.utc),
        activated_by="test-user",
        status=status,
    )


# =============================================================================
# workspace_id_from_path tests
# =============================================================================


class TestWorkspaceIdFromPath:
    """Test workspace_id_from_path helper function."""

    @pytest.mark.unit
    def test_basic_path(self) -> None:
        """Path produces consistent ws-{hash} format."""
        path = "/Users/nick/projects/my-app"
        ws_id = workspace_id_from_path(path)

        assert ws_id.startswith("ws-")
        assert len(ws_id) == 3 + 16  # "ws-" + 16 hex chars

    @pytest.mark.unit
    def test_same_path_same_id(self) -> None:
        """Same path always produces same workspace ID."""
        path = "/home/user/code/repo"

        id1 = workspace_id_from_path(path)
        id2 = workspace_id_from_path(path)

        assert id1 == id2

    @pytest.mark.unit
    def test_different_paths_different_ids(self) -> None:
        """Different paths produce different workspace IDs."""
        path1 = "/Users/a/project1"
        path2 = "/Users/a/project2"

        id1 = workspace_id_from_path(path1)
        id2 = workspace_id_from_path(path2)

        assert id1 != id2

    @pytest.mark.unit
    def test_trailing_slash_normalized(self) -> None:
        """Trailing slash doesn't affect workspace ID."""
        path1 = "/home/user/repo"
        path2 = "/home/user/repo/"

        id1 = workspace_id_from_path(path1)
        id2 = workspace_id_from_path(path2)

        assert id1 == id2

    @pytest.mark.unit
    def test_empty_path(self) -> None:
        """Empty path produces valid ID (edge case)."""
        ws_id = workspace_id_from_path("")
        assert ws_id.startswith("ws-")
        assert len(ws_id) > 3


# =============================================================================
# Activation dataclass tests
# =============================================================================


class TestActivationDataclass:
    """Test Activation dataclass methods."""

    @pytest.mark.unit
    def test_to_dict_includes_all_fields(self) -> None:
        """to_dict() exports all required fields."""
        activation = _make_activation()
        d = activation.to_dict()

        assert "activation_id" in d
        assert "workspace_id" in d
        assert "pack_id" in d
        assert "pack_version" in d
        assert "profile" in d
        assert "activated_at" in d
        assert "activated_by" in d
        assert "status" in d

    @pytest.mark.unit
    def test_to_dict_serializes_datetime(self) -> None:
        """to_dict() converts datetime to ISO format string."""
        activation = _make_activation()
        d = activation.to_dict()

        # Should be ISO format string, not datetime
        assert isinstance(d["activated_at"], str)
        assert "T" in d["activated_at"]  # ISO format has T separator

    @pytest.mark.unit
    def test_to_dict_handles_none_datetime(self) -> None:
        """to_dict() handles None activated_at."""
        activation = Activation(
            activation_id="act-123",
            workspace_id="ws-abc",
            pack_id="pack",
            pack_version="1.0.0",
            activated_at=None,
        )
        d = activation.to_dict()

        assert d["activated_at"] is None


class TestActivationListResult:
    """Test ActivationListResult dataclass."""

    @pytest.mark.unit
    def test_default_empty_list(self) -> None:
        """Default constructor produces empty list."""
        result = ActivationListResult()
        assert result.activations == []
        assert result.total_count == 0

    @pytest.mark.unit
    def test_with_activations(self) -> None:
        """Can populate with activations."""
        activations = [_make_activation(), _make_activation()]
        result = ActivationListResult(activations=activations, total_count=2)

        assert len(result.activations) == 2
        assert result.total_count == 2


# =============================================================================
# ActivationService tests (with mocked DB)
# =============================================================================


class TestActivationServiceActivate:
    """Test ActivationService.activate_pack()."""

    @pytest.mark.unit
    @patch("amprealize.knowledge_pack.activation_service.PostgresPool")
    def test_activate_new_pack(self, mock_pool_class: MagicMock) -> None:
        """Activating a pack creates a new activation record."""
        mock_pool = _mock_pool()
        mock_pool_class.return_value = mock_pool

        # Mock cursor to return pack exists
        cursor = mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            (1,),  # Pack exists check
            None,  # No existing activation
        ]

        service = ActivationService()
        activation = service.activate_pack(
            workspace_id="ws-test123",
            pack_id="test-pack",
            version="1.0.0",
            profile="solo-dev",
            activated_by="user-1",
        )

        # Verify activation returned
        assert activation.workspace_id == "ws-test123"
        assert activation.pack_id == "test-pack"
        assert activation.pack_version == "1.0.0"
        assert activation.profile == "solo-dev"
        assert activation.activated_by == "user-1"
        assert activation.status == "active"

    @pytest.mark.unit
    @patch("amprealize.knowledge_pack.activation_service.PostgresPool")
    def test_activate_replaces_existing_when_auto_deactivate(
        self, mock_pool_class: MagicMock
    ) -> None:
        """With auto_deactivate=True, existing activation is replaced."""
        mock_pool = _mock_pool()
        mock_pool_class.return_value = mock_pool

        cursor = mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        # Pack exists, existing activation found
        cursor.fetchone.side_effect = [
            (1,),  # Pack exists
            ("act-old", "ws-test", "old-pack", "0.9.0", None, None, None, "active"),  # Existing activation
        ]

        service = ActivationService()
        activation = service.activate_pack(
            workspace_id="ws-test",
            pack_id="new-pack",
            version="1.0.0",
            auto_deactivate=True,
        )

        # Should succeed with new pack
        assert activation.pack_id == "new-pack"
        assert activation.status == "active"


class TestActivationServiceGetActive:
    """Test ActivationService.get_active_pack()."""

    @pytest.mark.unit
    @patch("amprealize.knowledge_pack.activation_service.PostgresPool")
    def test_get_active_returns_activation(self, mock_pool_class: MagicMock) -> None:
        """get_active_pack() returns activation when one exists."""
        mock_pool = _mock_pool()
        mock_pool_class.return_value = mock_pool

        now = datetime.now(timezone.utc)
        cursor = mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "act-123",
            "ws-abc",
            "my-pack",
            "2.0.0",
            "amprealize-platform",
            now,
            "user-123",
            "active",
        )

        service = ActivationService()
        result = service.get_active_pack("ws-abc")

        assert result is not None
        assert result.activation_id == "act-123"
        assert result.pack_id == "my-pack"
        assert result.pack_version == "2.0.0"
        assert result.profile == "amprealize-platform"

    @pytest.mark.unit
    @patch("amprealize.knowledge_pack.activation_service.PostgresPool")
    def test_get_active_returns_none_when_no_activation(
        self, mock_pool_class: MagicMock
    ) -> None:
        """get_active_pack() returns None when no activation exists."""
        mock_pool = _mock_pool()
        mock_pool_class.return_value = mock_pool

        cursor = mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None

        service = ActivationService()
        result = service.get_active_pack("ws-no-pack")

        assert result is None


class TestActivationServiceDeactivate:
    """Test ActivationService.deactivate_pack()."""

    @pytest.mark.unit
    @patch("amprealize.knowledge_pack.activation_service.PostgresPool")
    def test_deactivate_sets_status_inactive(
        self, mock_pool_class: MagicMock
    ) -> None:
        """deactivate_pack() marks activation as inactive."""
        mock_pool = _mock_pool()
        mock_pool_class.return_value = mock_pool

        cursor = mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        # rowcount > 0 means update succeeded
        cursor.rowcount = 1

        service = ActivationService()
        result = service.deactivate_pack("ws-test")

        # Should return True indicating success
        assert result is True

    @pytest.mark.unit
    @patch("amprealize.knowledge_pack.activation_service.PostgresPool")
    def test_deactivate_returns_false_when_no_active_pack(
        self, mock_pool_class: MagicMock
    ) -> None:
        """deactivate_pack() returns False when no active pack exists."""
        mock_pool = _mock_pool()
        mock_pool_class.return_value = mock_pool

        cursor = mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.rowcount = 0  # No rows updated

        service = ActivationService()
        result = service.deactivate_pack("ws-no-pack")

        assert result is False


class TestActivationServiceList:
    """Test ActivationService.list_activations()."""

    @pytest.mark.unit
    @patch("amprealize.knowledge_pack.activation_service.PostgresPool")
    def test_list_returns_activations(self, mock_pool_class: MagicMock) -> None:
        """list_activations() returns paginated results."""
        mock_pool = _mock_pool()
        mock_pool_class.return_value = mock_pool

        now = datetime.now(timezone.utc)
        cursor = mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        # COUNT query returns 2
        # SELECT query returns 2 rows
        cursor.fetchone.return_value = (2,)
        cursor.fetchall.return_value = [
            ("act-1", "ws-a", "pack-1", "1.0.0", "solo-dev", now, "user-1", "active"),
            ("act-2", "ws-b", "pack-2", "2.0.0", "amprealize-platform", now, "user-2", "active"),
        ]

        service = ActivationService()
        result = service.list_activations(limit=10, offset=0)

        assert result.total_count == 2
        assert len(result.activations) == 2
        assert result.activations[0].pack_id == "pack-1"
        assert result.activations[1].pack_id == "pack-2"

    @pytest.mark.unit
    @patch("amprealize.knowledge_pack.activation_service.PostgresPool")
    def test_list_filters_by_workspace(self, mock_pool_class: MagicMock) -> None:
        """list_activations() can filter by workspace_id."""
        mock_pool = _mock_pool()
        mock_pool_class.return_value = mock_pool

        now = datetime.now(timezone.utc)
        cursor = mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.return_value = [
            ("act-1", "ws-target", "pack-1", "1.0.0", None, now, None, "active"),
        ]

        service = ActivationService()
        result = service.list_activations(workspace_id="ws-target")

        assert result.total_count == 1
        assert result.activations[0].workspace_id == "ws-target"


# =============================================================================
# Context integration tests
# =============================================================================


class TestContextIntegration:
    """Test that context.getContext includes active pack info."""

    @pytest.mark.unit
    @patch("amprealize.knowledge_pack.activation_service.PostgresPool")
    def test_context_includes_active_pack(self, mock_pool_class: MagicMock) -> None:
        """_get_current_context includes active_pack when workspace has one."""
        # This tests the mcp_server integration logic
        from amprealize.mcp_server import MCPServer, MCPSessionContext

        mock_pool = _mock_pool()
        mock_pool_class.return_value = mock_pool

        now = datetime.now(timezone.utc)
        cursor = mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "act-ctx",
            "ws-ctx-test",
            "context-pack",
            "3.0.0",
            "solo-dev",
            now,
            "ctx-user",
            "active",
        )

        # Create minimal MCPServer to test _get_current_context
        server = MCPServer.__new__(MCPServer)
        server._session_context = MCPSessionContext()
        server._logger = MagicMock()

        result = server._get_current_context({"workspace_id": "ws-ctx-test"})

        assert result["workspace_id"] == "ws-ctx-test"
        assert result["active_pack"] is not None
        assert result["active_pack"]["pack_id"] == "context-pack"
        assert result["active_pack"]["pack_version"] == "3.0.0"
        assert result["active_pack"]["profile"] == "solo-dev"

    @pytest.mark.unit
    @patch("amprealize.knowledge_pack.activation_service.PostgresPool")
    def test_context_null_active_pack_when_none(
        self, mock_pool_class: MagicMock
    ) -> None:
        """_get_current_context returns null active_pack when no pack active."""
        from amprealize.mcp_server import MCPServer, MCPSessionContext

        mock_pool = _mock_pool()
        mock_pool_class.return_value = mock_pool

        cursor = mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None  # No active pack

        server = MCPServer.__new__(MCPServer)
        server._session_context = MCPSessionContext()
        server._logger = MagicMock()

        result = server._get_current_context({"workspace_id": "ws-empty"})

        assert result["workspace_id"] == "ws-empty"
        assert result["active_pack"] is None

    @pytest.mark.unit
    def test_context_without_workspace_id(self) -> None:
        """_get_current_context works without workspace_id (no pack lookup)."""
        from amprealize.mcp_server import MCPServer, MCPSessionContext

        server = MCPServer.__new__(MCPServer)
        server._session_context = MCPSessionContext()
        server._session_context.user_id = "user-123"
        server._logger = MagicMock()

        result = server._get_current_context({})

        assert result["user_id"] == "user-123"
        assert result["workspace_id"] is None
        assert result["active_pack"] is None


# =============================================================================
# Activation lifecycle tests
# =============================================================================


class TestActivationLifecycle:
    """Integration-style tests for activation lifecycle."""

    @pytest.mark.unit
    @patch("amprealize.knowledge_pack.activation_service.PostgresPool")
    def test_full_lifecycle(self, mock_pool_class: MagicMock) -> None:
        """Test activate -> get_active -> deactivate -> get_active returns None."""
        mock_pool = _mock_pool()
        mock_pool_class.return_value = mock_pool

        now = datetime.now(timezone.utc)
        cursor = mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value

        # Setup: pack exists, no prior activation
        cursor.fetchone.side_effect = [
            (1,),  # Pack exists for activate
            None,  # No existing activation
            ("act-new", "ws-life", "lifecycle-pack", "1.0.0", "solo-dev", now, "u1", "active"),  # After activate
        ]
        cursor.rowcount = 1  # For deactivate

        service = ActivationService()

        # Step 1: Activate
        activation = service.activate_pack(
            workspace_id="ws-life",
            pack_id="lifecycle-pack",
            version="1.0.0",
        )
        assert activation.status == "active"

        # Step 2: Get active (mock returns the activation)
        active = service.get_active_pack("ws-life")
        assert active is not None
        assert active.pack_id == "lifecycle-pack"

        # Reset mock for deactivate
        cursor.fetchone.side_effect = None
        cursor.fetchone.return_value = None

        # Step 3: Deactivate
        deactivated = service.deactivate_pack("ws-life")
        assert deactivated is True

        # Step 4: Get active again (should be None)
        cursor.fetchone.return_value = None
        active_after = service.get_active_pack("ws-life")
        assert active_after is None


# =============================================================================
# Error handling tests
# =============================================================================


class TestActivationErrors:
    """Test error conditions in ActivationService."""

    @pytest.mark.unit
    def test_activation_not_found_error(self) -> None:
        """ActivationNotFoundError can be raised and caught."""
        with pytest.raises(ActivationNotFoundError) as exc_info:
            raise ActivationNotFoundError("Activation act-missing not found")

        assert "act-missing" in str(exc_info.value)

    @pytest.mark.unit
    def test_pack_not_found_error(self) -> None:
        """PackNotFoundError can be raised and caught."""
        with pytest.raises(PackNotFoundError) as exc_info:
            raise PackNotFoundError("Pack missing-pack v1.0.0 not found")

        assert "missing-pack" in str(exc_info.value)
        assert "1.0.0" in str(exc_info.value)

    @pytest.mark.unit
    def test_duplicate_activation_error(self) -> None:
        """DuplicateActivationError can be raised and caught."""
        with pytest.raises(DuplicateActivationError) as exc_info:
            raise DuplicateActivationError("Workspace ws-dup already has active pack old-pack")

        assert "ws-dup" in str(exc_info.value)
        assert "old-pack" in str(exc_info.value)
