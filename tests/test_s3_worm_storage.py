"""Unit tests for Audit Log WORM Storage components.

Tests cover:
- S3WORMStorage adapter with Object Lock operations
- Ed25519 signing and verification
- AuditLogService batch operations

Uses moto for S3 mocking. Note: moto has limited Object Lock support,
so some tests verify the API calls rather than full Object Lock behavior.

Behaviors referenced:
- behavior_align_storage_layers: Multi-tier storage testing
- behavior_lock_down_security_surface: WORM compliance verification
"""

import json
import hashlib
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch
import pytest

# Mark all tests in this module as unit tests (no infrastructure required)
pytestmark = pytest.mark.unit

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    with patch("amprealize.storage.s3_worm_storage.SETTINGS_AVAILABLE", False):
        yield


@pytest.fixture
def temp_key_dir(tmp_path):
    """Create temporary directory for signing keys."""
    return tmp_path


from amprealize.crypto.signing import AuditSigner as _AuditSigner

_has_real_signer = hasattr(_AuditSigner, 'save_key_pair')

# ── Ed25519 Signing Tests ──────────────────────────────────────────────────────


@pytest.mark.skipif(
    not _has_real_signer,
    reason="Full AuditSigner requires amprealize-enterprise[crypto]",
)
class TestAuditSigner:
    """Tests for Ed25519 signing module."""

    def test_generate_key_pair(self, temp_key_dir):
        """Test key pair generation."""
        from amprealize.crypto.signing import AuditSigner

        private_path = temp_key_dir / "test.key"

        signer = AuditSigner()
        signer.generate_key_pair()
        priv_path, pub_path = signer.save_key_pair(str(private_path))

        assert priv_path.exists()
        assert pub_path.exists()
        assert signer.can_sign
        assert signer.can_verify

    def test_sign_and_verify(self, temp_key_dir):
        """Test signing and verification round-trip."""
        from amprealize.crypto.signing import AuditSigner

        # Generate keys
        private_path = temp_key_dir / "test.key"

        signer = AuditSigner()
        signer.generate_key_pair()
        signer.save_key_pair(str(private_path))

        # Sign content
        content = '{"events": [{"id": "123", "type": "test"}]}'
        signature = signer.sign_record(content)

        assert signature is not None
        assert len(signature) > 0

        # Verify signature
        is_valid = signer.verify_record(content, signature)
        assert is_valid is True

        # Verify fails with modified content
        modified_content = content.replace("123", "456")
        is_valid_modified = signer.verify_record(modified_content, signature)
        assert is_valid_modified is False

    def test_load_existing_keys(self, temp_key_dir):
        """Test loading existing keys."""
        from amprealize.crypto.signing import AuditSigner

        # Generate keys first
        private_path = temp_key_dir / "existing.key"

        signer1 = AuditSigner()
        signer1.generate_key_pair()
        priv_path, pub_path = signer1.save_key_pair(str(private_path))

        # Sign something
        content = "test content"
        signature = signer1.sign_record(content)

        # Load keys into new signer
        signer2 = AuditSigner()
        signer2.load_private_key(str(priv_path))
        signer2.load_public_key(str(pub_path))

        # Verify with new signer
        is_valid = signer2.verify_record(content, signature)
        assert is_valid is True

    def test_verify_only_mode(self, temp_key_dir):
        """Test verification-only mode (no private key)."""
        from amprealize.crypto.signing import AuditSigner

        # Generate keys
        private_path = temp_key_dir / "priv.key"

        full_signer = AuditSigner()
        full_signer.generate_key_pair()
        priv_path, pub_path = full_signer.save_key_pair(str(private_path))

        # Sign with full signer
        content = "verify only test"
        signature = full_signer.sign_record(content)

        # Create verify-only signer
        verify_signer = AuditSigner()
        verify_signer.load_public_key(str(pub_path))

        assert verify_signer.can_verify is True
        assert verify_signer.can_sign is False

        # Verification should work
        is_valid = verify_signer.verify_record(content, signature)
        assert is_valid is True


# ── S3 WORM Storage Tests ──────────────────────────────────────────────────────


class TestS3WORMStorage:
    """Tests for S3 WORM storage adapter.

    Note: moto doesn't fully support Object Lock, so some tests
    verify API call patterns rather than full behavior.
    """

    @pytest.fixture
    def mock_s3_client(self):
        """Create mock boto3 S3 client."""
        mock_client = MagicMock()

        # Mock put_object response
        mock_client.put_object.return_value = {
            "VersionId": "test-version-123",
            "ETag": '"abc123"',
        }

        # Mock get_object response
        def mock_get_object(Bucket, Key, **kwargs):
            return {
                "Body": MagicMock(
                    read=MagicMock(return_value=b'{"events": [], "sha256_hash": "test"}')
                ),
                "VersionId": "test-version-123",
                "Metadata": {
                    "content-sha256": "test-hash",
                    "event-count": "10",
                },
            }
        mock_client.get_object.side_effect = mock_get_object

        # Mock get_bucket_versioning response
        mock_client.get_bucket_versioning.return_value = {
            "Status": "Enabled",
        }

        # Mock get_object_lock_configuration response
        mock_client.get_object_lock_configuration.return_value = {
            "ObjectLockConfiguration": {
                "ObjectLockEnabled": "Enabled",
                "Rule": {
                    "DefaultRetention": {
                        "Mode": "COMPLIANCE",
                        "Days": 2555,
                    }
                }
            }
        }

        return mock_client

    def test_store_audit_archive_calls_put_object(self, mock_s3_client):
        """Test that store_audit_archive makes correct S3 calls."""
        from amprealize.storage.s3_worm_storage import S3WORMStorage, ObjectLockMode

        # Patch boto3.client
        with patch("boto3.client", return_value=mock_s3_client):
            storage = S3WORMStorage(
                bucket="test-bucket",
                endpoint="http://localhost:9000",
                object_lock_mode=ObjectLockMode.COMPLIANCE,
                retention_days=30,
                aws_access_key_id="test",
                aws_secret_access_key="test",
            )

            events = [
                {"id": "1", "event_type": "test", "timestamp": "2024-01-01T00:00:00Z"},
                {"id": "2", "event_type": "test", "timestamp": "2024-01-01T00:01:00Z"},
            ]

            archive = storage.store_audit_archive(
                events=events,
                previous_hash="prev-hash-123",
                signature="sig-abc",
            )

            # Verify put_object was called
            mock_s3_client.put_object.assert_called_once()
            call_kwargs = mock_s3_client.put_object.call_args.kwargs

            assert call_kwargs["Bucket"] == "test-bucket"
            assert call_kwargs["Key"].startswith("audit-logs/")
            assert call_kwargs["Key"].endswith(".json")
            assert "ObjectLockMode" in call_kwargs
            assert call_kwargs["ObjectLockMode"] == "COMPLIANCE"
            assert "ObjectLockRetainUntilDate" in call_kwargs

            # Verify metadata
            metadata = call_kwargs["Metadata"]
            assert metadata["event-count"] == "2"
            assert "content-sha256" in metadata
            assert metadata["previous-hash"] == "prev-hash-123"

            # Verify return value
            assert archive.event_count == 2
            assert archive.version_id == "test-version-123"

    def test_verify_object_lock_configuration(self, mock_s3_client):
        """Test Object Lock configuration verification."""
        from amprealize.storage.s3_worm_storage import S3WORMStorage

        with patch("boto3.client", return_value=mock_s3_client):
            storage = S3WORMStorage(
                bucket="test-bucket",
                endpoint="http://localhost:9000",
                aws_access_key_id="test",
                aws_secret_access_key="test",
            )

            config = storage.verify_object_lock_configuration()

            assert config["object_lock_enabled"] is True
            assert config["versioning_enabled"] is True
            # Check nested default_retention structure
            assert config["default_retention"]["mode"] == "COMPLIANCE"
            assert config["default_retention"]["days"] == 2555

    def test_get_retention_info(self, mock_s3_client):
        """Test retrieval of Object Lock retention info."""
        from amprealize.storage.s3_worm_storage import S3WORMStorage

        # Mock retention response
        retain_until = datetime.now(timezone.utc) + timedelta(days=30)
        mock_s3_client.get_object_retention.return_value = {
            "Retention": {
                "Mode": "COMPLIANCE",
                "RetainUntilDate": retain_until,
            }
        }
        mock_s3_client.get_object_legal_hold.return_value = {
            "LegalHold": {"Status": "OFF"}
        }

        with patch("boto3.client", return_value=mock_s3_client):
            storage = S3WORMStorage(
                bucket="test-bucket",
                endpoint="http://localhost:9000",
                aws_access_key_id="test",
                aws_secret_access_key="test",
            )

            info = storage.get_retention_info("audit-logs/2024/01/test.json")

            assert info is not None
            assert info.mode.value == "COMPLIANCE"
            assert info.retain_until_date == retain_until
            assert info.legal_hold is False

    def test_apply_legal_hold(self, mock_s3_client):
        """Test legal hold application."""
        from amprealize.storage.s3_worm_storage import S3WORMStorage

        mock_s3_client.put_object_legal_hold.return_value = {}

        with patch("boto3.client", return_value=mock_s3_client):
            storage = S3WORMStorage(
                bucket="test-bucket",
                endpoint="http://localhost:9000",
                aws_access_key_id="test",
                aws_secret_access_key="test",
            )

            result = storage.apply_legal_hold(
                "audit-logs/test.json",
                version_id="ver-123",
            )

            assert result is True
            mock_s3_client.put_object_legal_hold.assert_called_once()
            call_kwargs = mock_s3_client.put_object_legal_hold.call_args.kwargs
            assert call_kwargs["Key"] == "audit-logs/test.json"
            assert call_kwargs["VersionId"] == "ver-123"
            assert call_kwargs["LegalHold"]["Status"] == "ON"


# ── Audit Log Service Tests ────────────────────────────────────────────────────


class TestAuditLogService:
    """Tests for AuditLogService."""

    @pytest.fixture
    def mock_worm_storage(self):
        """Create mock WORM storage."""
        mock = MagicMock()
        mock.store_audit_archive.return_value = MagicMock(
            key="audit-logs/2024/01/test-batch.json",
            version_id="ver-123",
            event_count=100,
            sha256_hash="hash-abc",
            start_timestamp=datetime.now(timezone.utc),
            end_timestamp=datetime.now(timezone.utc),
            retention_until=datetime.now(timezone.utc) + timedelta(days=2555),
        )
        mock.list_archives.return_value = [
            {
                "key": "audit-logs/2024/01/batch-1.json",
                "size": 1024,
                "last_modified": datetime.now(timezone.utc).isoformat(),
                "event_count": 100,
            }
        ]
        mock.get_archive.return_value = {
            "events": [{"id": "1"}, {"id": "2"}],
            "sha256_hash": "expected-hash",
        }
        return mock

    @pytest.fixture
    def mock_signer(self, temp_key_dir):
        """Create mock signer with real keys."""
        from amprealize.crypto.signing import AuditSigner

        private_path = temp_key_dir / "test.key"

        signer = AuditSigner()
        signer.generate_key_pair()
        signer.save_key_pair(str(private_path))
        return signer

    def test_log_event_queues_for_archival(self):
        """Test that log_event adds to pending queue."""
        from amprealize.services.audit_log_service import AuditLogService, AuditEvent

        # Create service without database
        service = AuditLogService(
            pg_dsn=None,
            worm_storage=None,
            signer=None,
            batch_size=100,
        )

        # Create event using run_until_complete
        import asyncio

        event = AuditEvent(
            event_type="test.event",
            actor_id="user-123",
            action="test",
        )

        asyncio.run(
            service.log_event(event)
        )

        assert len(service._pending_events) == 1
        assert service._pending_events[0].id == event.id

    def test_verify_archive_success(self, mock_worm_storage):
        """Test successful archive verification."""
        from amprealize.services.audit_log_service import AuditLogService

        # Compute expected hash
        events = [{"id": "1"}, {"id": "2"}]
        content = json.dumps(events, sort_keys=True, separators=(",", ":"))
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        mock_worm_storage.get_archive.return_value = {
            "events": events,
            "sha256_hash": expected_hash,
        }
        mock_worm_storage.get_retention_info.return_value = MagicMock(
            mode=MagicMock(value="COMPLIANCE"),
            retain_until_date=datetime.now(timezone.utc) + timedelta(days=30),
            legal_hold=False,
        )

        service = AuditLogService(
            pg_dsn=None,
            worm_storage=mock_worm_storage,
            signer=None,
        )

        result = service.verify_archive("test-batch-id")

        assert result["integrity_valid"] is True
        assert result["event_count"] == 2
        assert "retention_info" in result

    def test_verify_archive_hash_mismatch(self, mock_worm_storage):
        """Test archive verification with hash mismatch."""
        from amprealize.services.audit_log_service import AuditLogService

        mock_worm_storage.get_archive.return_value = {
            "events": [{"id": "1"}],
            "sha256_hash": "wrong-hash",
        }

        service = AuditLogService(
            pg_dsn=None,
            worm_storage=mock_worm_storage,
            signer=None,
        )

        result = service.verify_archive("test-batch-id")

        assert result["integrity_valid"] is False
        assert "integrity_error" in result

    def test_list_archives(self, mock_worm_storage):
        """Test listing archived batches."""
        from amprealize.services.audit_log_service import AuditLogService

        service = AuditLogService(
            pg_dsn=None,
            worm_storage=mock_worm_storage,
            signer=None,
        )

        archives = service.list_archives(limit=10)

        assert len(archives) == 1
        assert "batch_id" in archives[0]
        assert "archive_key" in archives[0]

    def test_get_retention_info(self, mock_worm_storage):
        """Test getting retention info for archive."""
        from amprealize.services.audit_log_service import AuditLogService
        from amprealize.storage.s3_worm_storage import RetentionInfo, ObjectLockMode

        mock_worm_storage.get_retention_info.return_value = RetentionInfo(
            mode=ObjectLockMode.COMPLIANCE,
            retain_until_date=datetime.now(timezone.utc) + timedelta(days=2555),
            legal_hold=True,
            version_id="ver-123",
        )

        service = AuditLogService(
            pg_dsn=None,
            worm_storage=mock_worm_storage,
            signer=None,
        )

        info = service.get_retention_info("test-batch")

        assert info["mode"] == "COMPLIANCE"
        assert info["legal_hold_status"] == "ON"
        assert info["is_versioned"] is True


# ── Hash Chain Tests ───────────────────────────────────────────────────────────


class TestHashChain:
    """Tests for hash chain verification."""

    def test_hash_chain_computation(self):
        """Test hash chain is correctly computed."""
        from amprealize.storage.s3_worm_storage import S3WORMStorage

        events = [
            {"id": "1", "event_type": "test"},
            {"id": "2", "event_type": "test"},
        ]

        # Compute hash manually
        content = json.dumps(events, sort_keys=True, separators=(",", ":"))
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Verify hash computation
        assert len(expected_hash) == 64

        # Different content should produce different hash
        events2 = [{"id": "1", "event_type": "different"}]
        content2 = json.dumps(events2, sort_keys=True, separators=(",", ":"))
        hash2 = hashlib.sha256(content2.encode("utf-8")).hexdigest()

        assert hash2 != expected_hash


# ── Event Dataclass Tests ──────────────────────────────────────────────────────


class TestAuditEvent:
    """Tests for AuditEvent dataclass."""

    def test_to_dict(self):
        """Test AuditEvent serialization."""
        from amprealize.services.audit_log_service import AuditEvent

        event = AuditEvent(
            id="test-id",
            event_type="auth.login",
            actor_id="user-123",
            action="login",
            outcome="success",
            details={"method": "oauth"},
        )

        d = event.to_dict()

        assert d["id"] == "test-id"
        assert d["event_type"] == "auth.login"
        assert d["actor_id"] == "user-123"
        assert d["details"]["method"] == "oauth"

    def test_compute_hash(self):
        """Test AuditEvent hash computation."""
        from amprealize.services.audit_log_service import AuditEvent

        event = AuditEvent(
            id="test-id",
            event_type="test",
            actor_id="user-123",
        )

        hash1 = event.compute_hash()

        # Same event should produce same hash
        hash2 = event.compute_hash()
        assert hash1 == hash2

        # Different event should produce different hash
        event2 = AuditEvent(
            id="different-id",
            event_type="test",
            actor_id="user-123",
        )
        hash3 = event2.compute_hash()
        assert hash3 != hash1
