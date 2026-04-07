#!/usr/bin/env python3
"""
Phase 6: Consent UX Dashboard Tests

Tests for the JIT (Just-In-Time) consent system from MCP Auth Implementation Plan.
Validates ConsentService, MCP tools, and REST API endpoints.

Run: python -m pytest scripts/test_phase6_consent.py -v
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConsentService:
    """Tests for ConsentService (amprealize/auth/consent_service.py)."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock PostgresPool for testing."""
        pool = MagicMock()
        pool.connection = MagicMock()
        return pool

    def test_consent_request_dataclass(self):
        """Test ConsentRequest dataclass initialization and methods."""
        from amprealize.auth.consent_service import ConsentRequest

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=10)

        request = ConsentRequest(
            id="test-uuid",
            user_id="user-123",
            agent_id="agent-456",
            tool_name="behaviors.create",
            scopes=["behaviors:write"],
            context={"reason": "Creating new behavior"},
            status="pending",
            user_code="ABCD-1234",
            verification_uri="https://consent.amprealize.dev/ABCD-1234",
            expires_at=expires_at,
            created_at=now,
        )

        assert request.id == "test-uuid"
        assert request.user_id == "user-123"
        assert request.agent_id == "agent-456"
        assert request.tool_name == "behaviors.create"
        assert request.scopes == ["behaviors:write"]
        assert request.status == "pending"
        assert request.user_code == "ABCD-1234"
        assert request.is_pending() is True
        assert request.is_expired() is False

    def test_consent_request_to_dict(self):
        """Test ConsentRequest.to_dict() serialization."""
        from amprealize.auth.consent_service import ConsentRequest

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=10)

        request = ConsentRequest(
            id="test-uuid",
            user_id="user-123",
            agent_id="agent-456",
            tool_name="behaviors.create",
            scopes=["behaviors:write"],
            context={"reason": "test"},
            status="pending",
            user_code="ABCD-1234",
            verification_uri="https://consent.amprealize.dev/ABCD-1234",
            expires_at=expires_at,
            created_at=now,
        )

        result = request.to_dict()

        assert result["id"] == "test-uuid"
        assert result["user_id"] == "user-123"
        assert result["status"] == "pending"
        assert result["user_code"] == "ABCD-1234"
        assert "expires_at" in result
        assert "created_at" in result

    def test_consent_request_expired(self):
        """Test expired consent request detection."""
        from amprealize.auth.consent_service import ConsentRequest

        now = datetime.now(timezone.utc)
        expired_at = now - timedelta(minutes=1)  # Already expired

        request = ConsentRequest(
            id="test-uuid",
            user_id="user-123",
            agent_id="agent-456",
            tool_name="behaviors.create",
            scopes=["behaviors:write"],
            context={},
            status="pending",
            user_code="ABCD-1234",
            verification_uri="https://consent.amprealize.dev/ABCD-1234",
            expires_at=expired_at,
            created_at=now - timedelta(minutes=11),
        )

        assert request.is_expired() is True
        assert request.is_pending() is False  # Can't be pending if expired

    def test_consent_poll_result_dataclass(self):
        """Test ConsentPollResult dataclass."""
        from amprealize.auth.consent_service import ConsentPollResult

        # Pending result
        pending = ConsentPollResult(
            status="pending",
            expires_in_seconds=300,
        )
        assert pending.status == "pending"
        assert pending.expires_in_seconds == 300

        result = pending.to_dict()
        assert result["status"] == "pending"

        # Approved result
        approved = ConsentPollResult(
            status="approved",
            scopes=["behaviors:write"],
            decided_at="2025-01-22T12:00:00Z",
        )
        assert approved.status == "approved"
        assert approved.scopes == ["behaviors:write"]

    def test_generate_user_code_format(self):
        """Test user code generation format (ABCD-1234)."""
        from amprealize.auth.consent_service import ConsentService

        service = ConsentService(pool=MagicMock())

        code = service._generate_user_code()

        # Check format: 4 letters - 4 digits
        assert len(code) == 9
        assert code[4] == "-"
        assert code[:4].isalpha()
        assert code[:4].isupper()
        assert code[5:].isdigit()

        # Check no confusing characters (I, O, 0, 1)
        letters = code[:4]
        assert "I" not in letters
        assert "O" not in letters
        digits = code[5:]
        # Digits can include 0 and 1, just not in the letter part

    def test_normalize_user_code(self):
        """Test user code normalization."""
        from amprealize.auth.consent_service import ConsentService

        service = ConsentService(pool=MagicMock())

        # Various input formats should normalize to same output
        assert service._normalize_user_code("ABCD-1234") == "ABCD1234"
        assert service._normalize_user_code("abcd-1234") == "ABCD1234"
        assert service._normalize_user_code("abcd1234") == "ABCD1234"
        assert service._normalize_user_code("  ABCD-1234  ") == "ABCD1234"


class TestConsentMCPTools:
    """Tests for consent.* MCP tool manifests and routing."""

    def test_consent_create_manifest_exists(self):
        """Test consent.create tool manifest exists."""
        import json
        from pathlib import Path

        manifest_path = Path(__file__).parent.parent / "mcp/tools/consent.create.json"
        assert manifest_path.exists(), f"Missing: {manifest_path}"

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["name"] == "consent.create"
        assert "inputSchema" in manifest
        assert "user_id" in manifest["inputSchema"]["properties"]
        assert "agent_id" in manifest["inputSchema"]["properties"]
        assert "tool_name" in manifest["inputSchema"]["properties"]
        assert "scopes" in manifest["inputSchema"]["properties"]

    def test_consent_poll_manifest_exists(self):
        """Test consent.poll tool manifest exists."""
        import json
        from pathlib import Path

        manifest_path = Path(__file__).parent.parent / "mcp/tools/consent.poll.json"
        assert manifest_path.exists(), f"Missing: {manifest_path}"

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["name"] == "consent.poll"
        assert "user_code" in manifest["inputSchema"]["properties"]

    def test_consent_list_manifest_exists(self):
        """Test consent.list tool manifest exists."""
        import json
        from pathlib import Path

        manifest_path = Path(__file__).parent.parent / "mcp/tools/consent.list.json"
        assert manifest_path.exists(), f"Missing: {manifest_path}"

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["name"] == "consent.list"
        assert "user_id" in manifest["inputSchema"]["properties"]

    def test_consent_lookup_manifest_exists(self):
        """Test consent.lookup tool manifest exists."""
        import json
        from pathlib import Path

        manifest_path = Path(__file__).parent.parent / "mcp/tools/consent.lookup.json"
        assert manifest_path.exists(), f"Missing: {manifest_path}"

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["name"] == "consent.lookup"
        assert "user_code" in manifest["inputSchema"]["properties"]

    def test_consent_approve_manifest_exists(self):
        """Test consent.approve tool manifest exists."""
        import json
        from pathlib import Path

        manifest_path = Path(__file__).parent.parent / "mcp/tools/consent.approve.json"
        assert manifest_path.exists(), f"Missing: {manifest_path}"

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["name"] == "consent.approve"

    def test_consent_deny_manifest_exists(self):
        """Test consent.deny tool manifest exists."""
        import json
        from pathlib import Path

        manifest_path = Path(__file__).parent.parent / "mcp/tools/consent.deny.json"
        assert manifest_path.exists(), f"Missing: {manifest_path}"

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["name"] == "consent.deny"


class TestConsentMigration:
    """Tests for consent_requests database migration."""

    def test_migration_file_exists(self):
        """Test migration file exists."""
        from pathlib import Path

        migration_path = Path(__file__).parent.parent / "migrations/versions/20260122_add_consent_requests.py"
        assert migration_path.exists(), f"Missing: {migration_path}"

    def test_migration_structure(self):
        """Test migration has correct structure."""
        from pathlib import Path

        migration_path = Path(__file__).parent.parent / "migrations/versions/20260122_add_consent_requests.py"
        content = migration_path.read_text()

        # Check required elements
        assert "consent_requests" in content
        assert "user_id" in content
        assert "agent_id" in content
        assert "tool_name" in content
        assert "scopes" in content
        assert "status" in content
        assert "user_code" in content
        assert "verification_uri" in content
        assert "expires_at" in content
        assert "def upgrade" in content
        assert "def downgrade" in content


class TestConsentServiceRegistry:
    """Tests for ConsentService integration in MCPServiceRegistry."""

    def test_consent_service_attribute_exists(self):
        """Test MCPServiceRegistry has _consent_service attribute."""
        from amprealize.mcp_server import MCPServiceRegistry

        registry = MCPServiceRegistry()
        assert hasattr(registry, "_consent_service")

    def test_consent_service_method_exists(self):
        """Test MCPServiceRegistry has consent_service() method."""
        from amprealize.mcp_server import MCPServiceRegistry

        registry = MCPServiceRegistry()
        assert hasattr(registry, "consent_service")
        assert callable(registry.consent_service)


class TestConsentRESTEndpoints:
    """Tests for consent REST API endpoints."""

    def test_endpoints_registered(self):
        """Test consent endpoints are registered in the app."""
        # This is a simplified check - full integration tests would use TestClient
        import inspect
        from amprealize import api

        # Check source code for endpoint definitions
        source = inspect.getsource(api)

        assert "/api/v1/consent/{user_code}" in source or 'consent/{user_code}' in source
        assert "approve_consent_request" in source
        assert "deny_consent_request" in source
        assert "poll_consent_status" in source
        assert "list_pending_consents" in source


class TestConsentServiceSingleton:
    """Tests for ConsentService singleton pattern."""

    def test_get_consent_service_creates_singleton(self):
        """Test get_consent_service returns singleton."""
        from amprealize.auth.consent_service import get_consent_service, _consent_service
        from unittest.mock import MagicMock

        # Reset singleton
        import amprealize.auth.consent_service as cs_module
        cs_module._consent_service = None

        mock_pool = MagicMock()
        service1 = get_consent_service(mock_pool)
        service2 = get_consent_service(mock_pool)

        assert service1 is service2

        # Reset for other tests
        cs_module._consent_service = None


# Summary function for test results
def run_tests():
    """Run all Phase 6 tests and print summary."""
    print("=" * 60)
    print("Phase 6: Consent UX Dashboard - Test Suite")
    print("=" * 60)
    print()
    print("Components tested:")
    print("  1. ConsentService (amprealize/auth/consent_service.py)")
    print("  2. MCP tool manifests (mcp/tools/consent.*.json)")
    print("  3. Database migration (migrations/versions/20260122_add_consent_requests.py)")
    print("  4. MCPServiceRegistry integration")
    print("  5. REST API endpoints (amprealize/api.py)")
    print()
    print("Running pytest...")
    print()

    # Run pytest
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(run_tests())
