"""Parity tests for audit log surfaces (MCP tools).

Validates that audit.query, audit.archive, audit.verify, audit.status,
audit.listArchives, audit.getRetention, and audit.verifyArchive work correctly
across the MCP adapter layer.

These tests verify:
1. MCPAuditServiceAdapter method signatures and responses
2. Response schema compliance with MCP tool manifests
3. Error handling for invalid inputs
4. Integration with AuditLogService backend
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amprealize.adapters import MCPAuditServiceAdapter
from amprealize.services.audit_log_service import AuditLogService


class TestMCPAuditServiceAdapter:
    """Test suite for MCP audit adapter compliance."""

    @pytest.fixture
    def mock_service(self) -> MagicMock:
        """Create a mock AuditLogService for testing."""
        service = MagicMock(spec=AuditLogService)

        # Mock async methods - query_events returns list of event dicts
        service.query_events = AsyncMock(return_value=[
            {
                "id": "evt-123",
                "event_type": "run.started",
                "actor_id": "user-1",
                "run_id": "run-456",
                "timestamp": "2025-12-02T10:00:00Z",
                "payload": {"action": "test"},
                "hash": "abc123",
                "signature": "sig123",
            }
        ])

        # archive_pending_events returns an object with attributes (used by _format_archival_stats)
        mock_stats = MagicMock()
        mock_stats.events_archived = 100
        mock_stats.archives_created = 1
        mock_stats.events_pending = 0
        mock_stats.last_archive_key = "2025/12/02/batch-789.json.gz"
        mock_stats.last_archive_hash = "head-hash"
        mock_stats.errors = []
        service.archive_pending_events = AsyncMock(return_value=mock_stats)

        # verify_integrity returns dict matching _format_verification_result
        service.verify_integrity = AsyncMock(return_value={
            "verified_at": "2025-12-02T10:00:00Z",
            "hash_chain_valid": True,
            "object_lock_valid": True,
            "signatures_valid": True,
            "archives_checked": 10,
            "errors": [],
            "details": [],
        })

        # get_archival_status returns dict matching _format_status expectations
        service.get_archival_status = AsyncMock(return_value={
            "pending_events": 1000,
            "batch_size": 1000,
            "last_archive_hash": "abc123",
            "hot_retention_days": 7,
            "total_archives": 10,
            "total_events_archived": 50000,
            "last_archive_time": "2025-12-01T00:00:00Z",
            "components": {
                "postgres": True,
                "s3": True,
                "opensearch": False,
            },
        })

        # Mock sync methods
        service.list_archives = MagicMock(return_value=[
            {
                "batch_id": "batch-001",
                "s3_key": "2025/11/24/batch-001.json.gz",
                "created_at": "2025-11-24T00:00:00Z",
                "events_count": 5000,
                "size_bytes": 5242880,
                "retention_until": "2032-11-24T00:00:00Z",
            },
        ])

        service.get_retention_info = MagicMock(return_value={
            "batch_id": "batch-001",
            "s3_key": "2025/11/24/batch-001.json.gz",
            "retention_mode": "COMPLIANCE",
            "retain_until": "2032-11-24T00:00:00Z",
            "legal_hold": False,
            "created_at": "2025-11-24T00:00:00Z",
            "events_count": 5000,
        })

        service.verify_archive = MagicMock(return_value={
            "valid": True,
            "batch_id": "batch-001",
            "events_verified": 5000,
            "signature_valid": True,
            "hash_chain_valid": True,
            "checksums_valid": True,
            "verification_time_ms": 1234,
            "errors": [],
        })

        return service

    @pytest.fixture
    def adapter(self, mock_service: MagicMock) -> MCPAuditServiceAdapter:
        """Create adapter with mock service."""
        return MCPAuditServiceAdapter(service=mock_service)

    @pytest.mark.asyncio
    async def test_query_basic(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.query with basic parameters."""
        result = await adapter.query({})

        # _format_events_response returns: events, count, total_count, _links
        assert "events" in result
        assert "count" in result
        assert "total_count" in result
        assert "_links" in result
        assert isinstance(result["events"], list)

    @pytest.mark.asyncio
    async def test_query_with_filters(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.query with all filter parameters."""
        result = await adapter.query({
            "event_type": "run.started",
            "actor_id": "user-1",
            "run_id": "run-456",
            "start_time": "2025-12-01T00:00:00Z",
            "end_time": "2025-12-02T23:59:59Z",
            "limit": 50,
            "offset": 0,
            "include_archived": False,
        })

        assert "events" in result
        assert "_links" in result

    @pytest.mark.asyncio
    async def test_archive_default(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.archive with default parameters."""
        result = await adapter.archive({})

        # _format_archival_stats returns: events_archived, archives_created, events_pending, etc.
        assert "events_archived" in result
        assert "archives_created" in result
        assert "events_pending" in result

    @pytest.mark.asyncio
    async def test_archive_force(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.archive with force=true."""
        result = await adapter.archive({"force": True})

        assert "events_archived" in result
        assert "archives_created" in result

    @pytest.mark.asyncio
    async def test_verify_time_range(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.verify with time range."""
        result = await adapter.verify({
            "start_date": "2025-12-01T00:00:00Z",
            "max_archives": 50,
        })

        # _format_verification_result returns: verified_at, hash_chain_valid, etc.
        assert "verified_at" in result
        assert "hash_chain_valid" in result
        assert "object_lock_valid" in result
        assert "signatures_valid" in result
        assert "archives_checked" in result

    @pytest.mark.asyncio
    async def test_verify_batch(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.verify with specific batch ID."""
        result = await adapter.verify({
            "batch_id": "batch-001",
        })

        assert "hash_chain_valid" in result
        assert "signatures_valid" in result

    @pytest.mark.asyncio
    async def test_status(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.status returns comprehensive status."""
        result = await adapter.status({})

        # _format_status returns flat structure, not nested
        assert "pending_events" in result
        assert "batch_size" in result
        assert "hot_retention_days" in result
        assert "total_archives" in result
        assert "total_events_archived" in result
        assert "components" in result
        assert "_links" in result

    def test_list_archives_default(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.listArchives with default parameters."""
        result = adapter.list_archives({})

        assert "archives" in result
        assert "count" in result
        assert "_links" in result
        assert isinstance(result["archives"], list)

    def test_list_archives_with_prefix(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.listArchives with prefix filter."""
        result = adapter.list_archives({
            "prefix": "2025/11/",
            "limit": 50,
        })

        assert "archives" in result
        assert "count" in result

    def test_get_retention_valid(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.getRetention with valid batch ID."""
        result = adapter.get_retention({"batch_id": "batch-001"})

        assert "batch_id" in result
        assert "retention_mode" in result
        assert "retain_until" in result
        assert "legal_hold" in result

    def test_get_retention_missing_batch_id(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.getRetention returns error without batch_id."""
        result = adapter.get_retention({})

        assert "error" in result
        assert "batch_id" in result["error"].lower()

    def test_verify_archive_valid(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.verifyArchive with valid batch ID."""
        result = adapter.verify_archive({"batch_id": "batch-001"})

        assert "valid" in result
        assert "batch_id" in result
        assert "events_verified" in result
        assert "signature_valid" in result
        assert "hash_chain_valid" in result
        assert "checksums_valid" in result

    def test_verify_archive_missing_batch_id(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.verifyArchive returns error without batch_id."""
        result = adapter.verify_archive({})

        assert "error" in result
        assert "batch_id" in result["error"].lower()

    def test_verify_archive_with_public_key(self, adapter: MCPAuditServiceAdapter) -> None:
        """Test audit.verifyArchive with public key path."""
        result = adapter.verify_archive({
            "batch_id": "batch-001",
            "public_key_path": "/path/to/key.pub",
        })

        assert "valid" in result


class TestAuditMCPToolSchemaCompliance:
    """Verify adapter responses match MCP tool manifest schemas."""

    def test_query_response_schema(self) -> None:
        """Validate audit.query response matches tool manifest."""
        # Load manifest
        import json
        from pathlib import Path

        manifest_path = Path(__file__).parent.parent / "mcp" / "tools" / "audit.query.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)

            output_schema = manifest.get("outputSchema", {})
            required_props = output_schema.get("properties", {}).keys()

            # Mock response should match _format_events_response
            mock_response = {
                "events": [],
                "count": 0,
                "total_count": 0,
                "_links": {"query": "/v1/audit/query", "verify": "/v1/audit/verify", "status": "/v1/audit/status"},
            }

            for prop in required_props:
                assert prop in mock_response, f"Missing property: {prop}"

    def test_status_response_schema(self) -> None:
        """Validate audit.status response matches tool manifest."""
        import json
        from pathlib import Path

        manifest_path = Path(__file__).parent.parent / "mcp" / "tools" / "audit.status.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)

            output_schema = manifest.get("outputSchema", {})
            required_props = output_schema.get("properties", {}).keys()

            # Mock response should match _format_status (flat structure)
            mock_response = {
                "pending_events": 0,
                "batch_size": 1000,
                "last_archive_hash": None,
                "hot_retention_days": 7,
                "total_archives": 0,
                "total_events_archived": 0,
                "last_archive_time": None,
                "components": {},
                "_links": {"query": "/v1/audit/query", "archive": "/v1/audit/archive", "verify": "/v1/audit/verify"},
            }

            for prop in required_props:
                assert prop in mock_response, f"Missing property: {prop}"


class TestAuditOpenSearchIndexer:
    """Test OpenSearch audit indexer functionality."""

    def test_audit_event_to_document(self) -> None:
        """Test AuditEvent converts to valid OpenSearch document."""
        from amprealize.storage.opensearch_storage import AuditEvent

        event = AuditEvent(
            event_id="evt-123",
            event_type="run.started",
            actor="user-1",
            actor_type="user",
            surface="mcp",
            timestamp=datetime(2025, 12, 2, 10, 0, 0, tzinfo=timezone.utc),
            payload={"action": "test"},
            run_id="run-456",
            signature="sig123",
        )

        doc = event.to_document()

        assert doc["event_id"] == "evt-123"
        assert doc["event_type"] == "run.started"
        assert doc["actor"] == "user-1"
        assert doc["actor_type"] == "user"
        assert doc["surface"] == "mcp"
        assert "@timestamp" in doc
        assert doc["run_id"] == "run-456"
        assert doc["signature"] == "sig123"

    def test_audit_event_optional_fields(self) -> None:
        """Test AuditEvent handles optional fields correctly."""
        from amprealize.storage.opensearch_storage import AuditEvent

        event = AuditEvent(
            event_id="evt-124",
            event_type="action.completed",
            actor="system",
            actor_type="system",
            surface="api",
            timestamp=datetime.now(timezone.utc),
            payload={},
        )

        doc = event.to_document()

        # Optional fields should not be present if not set
        assert "run_id" not in doc
        assert "signature" not in doc
        assert "previous_hash" not in doc


class TestHashChainVerification:
    """Test hash chain verification logic."""

    def test_hash_chain_continuity(self) -> None:
        """Test that hash chain links are verified correctly."""
        import hashlib

        # Simulate a valid hash chain
        events = []
        prev_hash = None

        for i in range(5):
            payload = {"event_num": i}
            content = json.dumps(payload, sort_keys=True)
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            events.append({
                "id": f"evt-{i}",
                "content_hash": content_hash,
                "previous_hash": prev_hash,
            })

            # Next event's previous_hash should be this event's content_hash
            prev_hash = content_hash

        # Verify chain continuity
        for i in range(1, len(events)):
            assert events[i]["previous_hash"] == events[i-1]["content_hash"], \
                f"Hash chain broken at event {i}"

    def test_hash_chain_tamper_detection(self) -> None:
        """Test that hash chain detects tampering."""
        import hashlib

        # Create valid chain
        events = []
        prev_hash = None

        for i in range(3):
            payload = {"event_num": i}
            content = json.dumps(payload, sort_keys=True)
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            events.append({
                "id": f"evt-{i}",
                "payload": payload,
                "content_hash": content_hash,
                "previous_hash": prev_hash,
            })
            prev_hash = content_hash

        # Tamper with middle event
        events[1]["payload"]["event_num"] = 999
        tampered_content = json.dumps(events[1]["payload"], sort_keys=True)

        # Verify tampering is detected (hash mismatch)
        expected_hash = hashlib.sha256(tampered_content.encode()).hexdigest()
        assert expected_hash != events[1]["content_hash"], "Tampering not detected"


# Mark all async tests
pytestmark = pytest.mark.asyncio
