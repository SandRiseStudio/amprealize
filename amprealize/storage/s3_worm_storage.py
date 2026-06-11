"""S3 WORM (Write Once Read Many) storage adapter for compliance audit logs.

Implements S3 Object Lock for immutable, tamper-proof audit log storage with:
- COMPLIANCE mode: Cannot be overridden, even by root account
- GOVERNANCE mode: Can be overridden by users with special permissions
- Legal Hold: Indefinite retention for litigation/investigation

Supports multi-tier storage per docs/contracts/AUDIT_LOG_STORAGE.md:
- Hot: PostgreSQL (30-day retention)
- Warm: S3 Standard with Object Lock
- Cold: S3 Glacier Deep Archive (after 3 years)

Behaviors referenced:
- behavior_align_storage_layers: WORM archival tier
- behavior_lock_down_security_surface: Immutable audit logs
- behavior_externalize_configuration: Settings-based configuration
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

try:
    import boto3
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

# Import base S3Storage and settings
try:
    from amprealize.storage.s3_storage import S3Storage, S3JSONEncoder
    S3_STORAGE_AVAILABLE = True
except ImportError:
    S3_STORAGE_AVAILABLE = False

try:
    from amprealize.config.settings import settings
    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False


class ObjectLockMode(str, Enum):
    """S3 Object Lock retention modes."""
    COMPLIANCE = "COMPLIANCE"  # Cannot be overridden by any user
    GOVERNANCE = "GOVERNANCE"  # Can be overridden by users with s3:BypassGovernanceRetention


class LegalHoldStatus(str, Enum):
    """S3 Legal Hold status."""
    ON = "ON"
    OFF = "OFF"


@dataclass
class RetentionInfo:
    """Object Lock retention information."""
    mode: ObjectLockMode
    retain_until_date: datetime
    legal_hold: bool = False
    version_id: Optional[str] = None


@dataclass
class AuditArchive:
    """Metadata for an audit log archive file."""
    key: str
    version_id: str
    event_count: int
    start_timestamp: datetime
    end_timestamp: datetime
    sha256_hash: str
    previous_hash: Optional[str] = None  # For hash chain
    signature: Optional[str] = None  # Ed25519 signature
    retention_until: Optional[datetime] = None


class S3WORMStorage:
    """S3 WORM storage adapter for audit log archival with Object Lock.

    Usage:
        # Initialize from settings
        worm = S3WORMStorage()

        # Store audit archive with Object Lock
        archive = worm.store_audit_archive(
            events=audit_events,
            previous_hash="abc123...",
            signature="ed25519sig..."
        )

        # Verify immutability
        is_valid, info = worm.verify_immutability(archive.key)

        # Apply legal hold for investigations
        worm.apply_legal_hold(archive.key, archive.version_id)
    """

    def __init__(
        self,
        bucket: Optional[str] = None,
        endpoint: Optional[str] = None,
        region: Optional[str] = None,
        object_lock_mode: ObjectLockMode = ObjectLockMode.COMPLIANCE,
        retention_days: int = 2555,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ):
        """Initialize WORM storage client.

        Args:
            bucket: S3 bucket with Object Lock enabled (default: from settings.audit.audit_bucket)
            endpoint: S3 endpoint URL (default: from settings.audit.audit_endpoint)
            region: AWS region (default: us-east-1)
            object_lock_mode: COMPLIANCE or GOVERNANCE (default: from settings)
            retention_days: Retention period in days (default: from settings, 2555 = 7 years)
            aws_access_key_id: AWS access key (default: from settings.storage)
            aws_secret_access_key: AWS secret key (default: from settings.storage)

        Raises:
            ImportError: If boto3 is not installed
            ValueError: If bucket is not configured
        """
        if not BOTO3_AVAILABLE:
            raise ImportError(
                "boto3 is required for S3WORMStorage. Install with: pip install boto3"
            )

        # Resolve configuration from settings or parameters
        if SETTINGS_AVAILABLE:
            self.bucket = bucket or settings.audit.audit_bucket
            self.endpoint = endpoint or settings.audit.audit_endpoint or settings.storage.s3_endpoint
            self.region = region or settings.storage.s3_region
            self.object_lock_mode = ObjectLockMode(
                object_lock_mode if bucket else settings.audit.object_lock_mode
            )
            self.retention_days = retention_days if bucket else settings.audit.retention_days
            aws_access_key_id = aws_access_key_id or settings.storage.aws_access_key_id
            aws_secret_access_key = aws_secret_access_key or settings.storage.aws_secret_access_key
        else:
            self.bucket = bucket
            self.endpoint = endpoint
            self.region = region or "us-east-1"
            self.object_lock_mode = ObjectLockMode(object_lock_mode)
            self.retention_days = retention_days

        if not self.bucket:
            raise ValueError(
                "S3WORMStorage requires bucket parameter or settings module with "
                "AUDIT__AUDIT_BUCKET configured"
            )

        # Initialize boto3 S3 client
        client_kwargs: Dict[str, Any] = {
            "region_name": self.region,
        }

        if self.endpoint:
            client_kwargs["endpoint_url"] = self.endpoint

        if aws_access_key_id and aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = aws_access_key_id
            client_kwargs["aws_secret_access_key"] = aws_secret_access_key

        self.s3 = boto3.client("s3", **client_kwargs)

    def _compute_retention_date(self, days: Optional[int] = None) -> datetime:
        """Compute retention until date from days."""
        retention_days = days or self.retention_days
        return datetime.now(timezone.utc) + timedelta(days=retention_days)

    def _compute_content_hash(self, content: bytes) -> str:
        """Compute SHA-256 hash of content."""
        return hashlib.sha256(content).hexdigest()

    def _generate_archive_key(self, timestamp: datetime) -> str:
        """Generate S3 key for audit archive with date-based partitioning.

        Format: audit-logs/YYYY/MM/DD/HH/events_TIMESTAMP.json
        """
        return (
            f"audit-logs/{timestamp.year:04d}/{timestamp.month:02d}/"
            f"{timestamp.day:02d}/{timestamp.hour:02d}/"
            f"events_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.json"
        )

    def store_audit_archive(
        self,
        events: List[Dict[str, Any]],
        previous_hash: Optional[str] = None,
        signature: Optional[str] = None,
        retention_days: Optional[int] = None,
    ) -> AuditArchive:
        """Store audit events as WORM archive with Object Lock.

        Args:
            events: List of audit event dictionaries
            previous_hash: SHA-256 hash of previous archive (for hash chain)
            signature: Ed25519 signature of the archive
            retention_days: Override retention period (default: from settings)

        Returns:
            AuditArchive with key, version_id, and metadata

        Raises:
            ClientError: If S3 operation fails
            ValueError: If events list is empty
        """
        if not events:
            raise ValueError("events list cannot be empty")

        now = datetime.now(timezone.utc)
        key = self._generate_archive_key(now)

        # Extract timestamp range from events
        timestamps = []
        for event in events:
            if "timestamp" in event:
                ts = event["timestamp"]
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                elif isinstance(ts, datetime):
                    pass
                else:
                    ts = now
                timestamps.append(ts)

        start_ts = min(timestamps) if timestamps else now
        end_ts = max(timestamps) if timestamps else now

        # Build archive document
        archive_doc = {
            "version": "1.0",
            "created_at": now.isoformat(),
            "event_count": len(events),
            "start_timestamp": start_ts.isoformat(),
            "end_timestamp": end_ts.isoformat(),
            "previous_hash": previous_hash,
            "events": events,
        }

        # Serialize and compute hash
        content = json.dumps(archive_doc, cls=S3JSONEncoder, sort_keys=True).encode("utf-8")
        content_hash = self._compute_content_hash(content)

        # Add hash and optional signature to metadata
        metadata = {
            "content-sha256": content_hash,
            "event-count": str(len(events)),
            "start-timestamp": start_ts.isoformat(),
            "end-timestamp": end_ts.isoformat(),
        }
        if previous_hash:
            metadata["previous-hash"] = previous_hash
        if signature:
            metadata["ed25519-signature"] = signature

        # Calculate retention date
        retain_until = self._compute_retention_date(retention_days)

        # Store with Object Lock retention
        response = self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType="application/json",
            ContentMD5=self._compute_md5_base64(content),
            Metadata=metadata,
            ObjectLockMode=self.object_lock_mode.value,
            ObjectLockRetainUntilDate=retain_until,
        )

        version_id = response.get("VersionId", "null")

        return AuditArchive(
            key=key,
            version_id=version_id,
            event_count=len(events),
            start_timestamp=start_ts,
            end_timestamp=end_ts,
            sha256_hash=content_hash,
            previous_hash=previous_hash,
            signature=signature,
            retention_until=retain_until,
        )

    def _compute_md5_base64(self, content: bytes) -> str:
        """Compute base64-encoded MD5 for Content-MD5 header."""
        import base64
        md5_digest = hashlib.md5(content).digest()
        return base64.b64encode(md5_digest).decode("ascii")

    def get_retention_info(self, key: str, version_id: Optional[str] = None) -> Optional[RetentionInfo]:
        """Get Object Lock retention information for an archive.

        Args:
            key: S3 object key
            version_id: Optional version ID (for versioned buckets)

        Returns:
            RetentionInfo or None if object doesn't exist
        """
        try:
            # Get object retention
            retention_kwargs = {"Bucket": self.bucket, "Key": key}
            if version_id:
                retention_kwargs["VersionId"] = version_id

            retention_response = self.s3.get_object_retention(**retention_kwargs)
            retention = retention_response.get("Retention", {})

            # Get legal hold status
            try:
                hold_response = self.s3.get_object_legal_hold(**retention_kwargs)
                legal_hold = hold_response.get("LegalHold", {}).get("Status") == "ON"
            except ClientError as e:
                if e.response["Error"]["Code"] == "NoSuchObjectLockConfiguration":
                    legal_hold = False
                else:
                    raise

            return RetentionInfo(
                mode=ObjectLockMode(retention.get("Mode", "COMPLIANCE")),
                retain_until_date=retention.get("RetainUntilDate", datetime.now(timezone.utc)),
                legal_hold=legal_hold,
                version_id=version_id,
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ("NoSuchKey", "NoSuchObjectLockConfiguration"):
                return None
            raise

    def verify_immutability(self, key: str, version_id: Optional[str] = None) -> Tuple[bool, Optional[RetentionInfo]]:
        """Verify that an archive is properly protected by Object Lock.

        Args:
            key: S3 object key
            version_id: Optional version ID

        Returns:
            Tuple of (is_valid, retention_info)
            - is_valid: True if properly protected (COMPLIANCE mode, future retention)
            - retention_info: RetentionInfo object or None if not found
        """
        info = self.get_retention_info(key, version_id)

        if not info:
            return False, None

        now = datetime.now(timezone.utc)
        is_valid = (
            info.mode == ObjectLockMode.COMPLIANCE
            and info.retain_until_date > now
        )

        return is_valid, info

    def apply_legal_hold(self, key: str, version_id: Optional[str] = None) -> bool:
        """Apply legal hold to an archive (for litigation/investigation).

        Legal hold prevents deletion regardless of retention period.

        Args:
            key: S3 object key
            version_id: Optional version ID

        Returns:
            True if legal hold applied successfully
        """
        try:
            kwargs = {
                "Bucket": self.bucket,
                "Key": key,
                "LegalHold": {"Status": LegalHoldStatus.ON.value},
            }
            if version_id:
                kwargs["VersionId"] = version_id

            self.s3.put_object_legal_hold(**kwargs)
            return True
        except ClientError:
            return False

    def remove_legal_hold(self, key: str, version_id: Optional[str] = None) -> bool:
        """Remove legal hold from an archive.

        Note: Only removes legal hold; Object Lock retention still applies.

        Args:
            key: S3 object key
            version_id: Optional version ID

        Returns:
            True if legal hold removed successfully
        """
        try:
            kwargs = {
                "Bucket": self.bucket,
                "Key": key,
                "LegalHold": {"Status": LegalHoldStatus.OFF.value},
            }
            if version_id:
                kwargs["VersionId"] = version_id

            self.s3.put_object_legal_hold(**kwargs)
            return True
        except ClientError:
            return False

    def list_archives(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        max_keys: int = 1000,
    ) -> List[Dict[str, Any]]:
        """List audit archives with optional date filtering.

        Args:
            start_date: Filter archives after this date
            end_date: Filter archives before this date
            max_keys: Maximum number of results

        Returns:
            List of archive metadata dictionaries
        """
        # Build prefix from date range
        prefix = "audit-logs/"
        if start_date:
            prefix = f"audit-logs/{start_date.year:04d}/"
            if start_date.month and (not end_date or start_date.month == end_date.month):
                prefix += f"{start_date.month:02d}/"

        response = self.s3.list_objects_v2(
            Bucket=self.bucket,
            Prefix=prefix,
            MaxKeys=max_keys,
        )

        archives = []
        for obj in response.get("Contents", []):
            key = obj["Key"]

            # Get metadata
            try:
                head = self.s3.head_object(Bucket=self.bucket, Key=key)
                metadata = head.get("Metadata", {})

                archives.append({
                    "key": key,
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                    "version_id": head.get("VersionId"),
                    "content_hash": metadata.get("content-sha256"),
                    "event_count": int(metadata.get("event-count", 0)),
                    "start_timestamp": metadata.get("start-timestamp"),
                    "end_timestamp": metadata.get("end-timestamp"),
                    "previous_hash": metadata.get("previous-hash"),
                    "has_signature": "ed25519-signature" in metadata,
                })
            except ClientError:
                continue

        return archives

    def get_archive(self, key: str, version_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve an audit archive by key.

        Args:
            key: S3 object key
            version_id: Optional version ID

        Returns:
            Archive document as dictionary or None if not found
        """
        try:
            kwargs = {"Bucket": self.bucket, "Key": key}
            if version_id:
                kwargs["VersionId"] = version_id

            response = self.s3.get_object(**kwargs)
            body = response["Body"].read().decode("utf-8")
            return json.loads(body)
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise

    def verify_hash_chain(
        self,
        start_key: Optional[str] = None,
        max_archives: int = 100,
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """Verify hash chain integrity across archives.

        Args:
            start_key: Starting archive key (default: earliest)
            max_archives: Maximum archives to verify

        Returns:
            Tuple of (is_valid, verification_results)
        """
        archives = self.list_archives(max_keys=max_archives)

        if not archives:
            return True, []

        # Sort by timestamp
        archives.sort(key=lambda x: x.get("start_timestamp", ""))

        results = []
        previous_hash = None
        all_valid = True

        for archive in archives:
            key = archive["key"]
            doc = self.get_archive(key)

            if not doc:
                results.append({
                    "key": key,
                    "valid": False,
                    "error": "Archive not found",
                })
                all_valid = False
                continue

            # Verify content hash
            content = json.dumps(doc, cls=S3JSONEncoder, sort_keys=True).encode("utf-8")
            computed_hash = self._compute_content_hash(content)
            stored_hash = archive.get("content_hash")

            hash_valid = computed_hash == stored_hash

            # Verify chain link
            chain_valid = True
            if previous_hash and doc.get("previous_hash"):
                chain_valid = doc["previous_hash"] == previous_hash

            result = {
                "key": key,
                "valid": hash_valid and chain_valid,
                "hash_valid": hash_valid,
                "chain_valid": chain_valid,
                "computed_hash": computed_hash,
                "stored_hash": stored_hash,
            }

            if not (hash_valid and chain_valid):
                all_valid = False

            results.append(result)
            previous_hash = computed_hash

        return all_valid, results

    def verify_object_lock_configuration(self) -> Dict[str, Any]:
        """Verify bucket has Object Lock properly configured.

        Returns:
            Dictionary with configuration status and details
        """
        result = {
            "bucket": self.bucket,
            "object_lock_enabled": False,
            "versioning_enabled": False,
            "default_retention": None,
            "errors": [],
        }

        try:
            # Check Object Lock configuration
            lock_config = self.s3.get_object_lock_configuration(Bucket=self.bucket)
            result["object_lock_enabled"] = (
                lock_config.get("ObjectLockConfiguration", {}).get("ObjectLockEnabled") == "Enabled"
            )

            rule = lock_config.get("ObjectLockConfiguration", {}).get("Rule", {})
            if rule:
                default_retention = rule.get("DefaultRetention", {})
                result["default_retention"] = {
                    "mode": default_retention.get("Mode"),
                    "days": default_retention.get("Days"),
                    "years": default_retention.get("Years"),
                }
        except ClientError as e:
            result["errors"].append(f"Object Lock: {e.response['Error']['Message']}")

        try:
            # Check versioning
            versioning = self.s3.get_bucket_versioning(Bucket=self.bucket)
            result["versioning_enabled"] = versioning.get("Status") == "Enabled"
        except ClientError as e:
            result["errors"].append(f"Versioning: {e.response['Error']['Message']}")

        return result
