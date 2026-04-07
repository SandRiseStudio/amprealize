#!/usr/bin/env python3
"""Audit Log Archival Job - Archives aged audit log partitions to S3 WORM storage.

This script archives PostgreSQL audit log partitions older than the retention period
to S3 with Object Lock for WORM compliance. Designed to run as a Cloud Run job.

Environment Variables:
    AMPREALIZE_AUDIT_PG_DSN: PostgreSQL connection string (required)
    AWS_S3_BUCKET: S3 bucket for archives (required)
    AWS_S3_PREFIX: Prefix for archive keys (default: audit-archives/)
    AWS_REGION: AWS region (default: us-east-1)
    AUDIT_RETENTION_DAYS: Days before archival (default: 30)
    AUDIT_WORM_RETENTION_DAYS: S3 Object Lock retention (default: 2555 = 7 years)
    ED25519_SIGNING_KEY_PATH: Path to signing key for archive signatures
    DRY_RUN: If set, don't actually archive (default: false)

Usage:
    python archive_audit_logs.py
    python archive_audit_logs.py --dry-run
    python archive_audit_logs.py --retention-days 14 --worm-days 365
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def get_env_int(key: str, default: int) -> int:
    """Get integer from environment variable."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(f"Invalid integer for {key}: {value}, using default {default}")
        return default


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean from environment variable."""
    value = os.getenv(key, "").lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    return default


class AuditArchiver:
    """Archives audit log partitions to S3 with WORM compliance."""

    def __init__(
        self,
        pg_dsn: str,
        s3_bucket: str,
        s3_prefix: str = "audit-archives/",
        aws_region: str = "us-east-1",
        retention_days: int = 30,
        worm_retention_days: int = 2555,
        signing_key_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        self.pg_dsn = pg_dsn
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix.rstrip("/") + "/"
        self.aws_region = aws_region
        self.retention_days = retention_days
        self.worm_retention_days = worm_retention_days
        self.signing_key_path = signing_key_path
        self.dry_run = dry_run

        self._conn = None
        self._s3_client = None
        self._signing_key = None

    def _get_connection(self) -> Any:
        """Get PostgreSQL connection."""
        if self._conn is None:
            try:
                import psycopg2
                self._conn = psycopg2.connect(self.pg_dsn)
            except ImportError:
                logger.error("psycopg2 not installed. Install with: pip install psycopg2-binary")
                sys.exit(1)
        return self._conn

    def _get_s3_client(self) -> Any:
        """Get S3 client."""
        if self._s3_client is None:
            try:
                import boto3
                self._s3_client = boto3.client("s3", region_name=self.aws_region)
            except ImportError:
                logger.error("boto3 not installed. Install with: pip install boto3")
                sys.exit(1)
        return self._s3_client

    def _load_signing_key(self) -> Optional[Any]:
        """Load Ed25519 signing key if available."""
        if self._signing_key is not None:
            return self._signing_key

        if not self.signing_key_path:
            return None

        try:
            from cryptography.hazmat.primitives import serialization

            key_path = Path(self.signing_key_path)
            if not key_path.exists():
                logger.warning(f"Signing key not found: {self.signing_key_path}")
                return None

            key_data = key_path.read_bytes()
            self._signing_key = serialization.load_pem_private_key(key_data, password=None)
            logger.info(f"Loaded signing key from {self.signing_key_path}")
            return self._signing_key
        except Exception as e:
            logger.warning(f"Failed to load signing key: {e}")
            return None

    def _sign_data(self, data: bytes) -> Optional[str]:
        """Sign data with Ed25519 key, return base64 signature."""
        key = self._load_signing_key()
        if key is None:
            return None

        try:
            import base64
            signature = key.sign(data)
            return base64.b64encode(signature).decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to sign data: {e}")
            return None

    def _get_last_archive_hash(self) -> Optional[str]:
        """Get the hash of the last archive for chain continuity."""
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT archive_hash FROM audit_log_archives
                ORDER BY created_at DESC
                LIMIT 1
            """)
            row = cur.fetchone()
            return row[0] if row else None

    def _list_partitions_to_archive(self) -> List[str]:
        """List partitions older than retention period."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        cutoff_week = cutoff_date.strftime("%G_w%V")  # ISO year and week

        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pt.relname
                FROM pg_class pt
                JOIN pg_inherits i ON i.inhrelid = pt.oid
                JOIN pg_class parent ON i.inhparent = parent.oid
                WHERE parent.relname = 'audit_log_events'
                AND pt.relname LIKE 'audit_log_events_%'
                ORDER BY pt.relname
            """)

            partitions = []
            for row in cur.fetchall():
                partition_name = row[0]
                # Extract year_wXX from partition name
                parts = partition_name.replace("audit_log_events_", "").split("_")
                if len(parts) >= 2:
                    year_week = f"{parts[0]}_{parts[1]}"
                    if year_week < cutoff_week:
                        partitions.append(partition_name)

            return partitions

    def _export_partition_data(self, partition_name: str) -> Tuple[List[Dict[str, Any]], str, str]:
        """Export partition data and compute hash."""
        conn = self._get_connection()
        with conn.cursor() as cur:
            # Get partition time range
            cur.execute(f"""
                SELECT MIN(timestamp), MAX(timestamp), COUNT(*)
                FROM {partition_name}
            """)
            min_ts, max_ts, count = cur.fetchone()

            if count == 0:
                return [], "", ""

            # Export all records
            cur.execute(f"""
                SELECT id, timestamp, event_type, actor_id, actor_type,
                       resource_type, resource_id, action, outcome,
                       client_ip::text, user_agent, session_id, run_id,
                       details, event_hash, content_hash, previous_hash, signature
                FROM {partition_name}
                ORDER BY timestamp
            """)

            records = []
            for row in cur.fetchall():
                records.append({
                    "id": row[0],
                    "timestamp": row[1].isoformat() if row[1] else None,
                    "event_type": row[2],
                    "actor_id": row[3],
                    "actor_type": row[4],
                    "resource_type": row[5],
                    "resource_id": row[6],
                    "action": row[7],
                    "outcome": row[8],
                    "client_ip": row[9],
                    "user_agent": row[10],
                    "session_id": row[11],
                    "run_id": row[12],
                    "details": row[13],
                    "event_hash": row[14],
                    "content_hash": row[15],
                    "previous_hash": row[16],
                    "signature": row[17],
                })

            return records, min_ts.isoformat(), max_ts.isoformat()

    def _upload_to_s3(
        self,
        partition_name: str,
        records: List[Dict[str, Any]],
        start_ts: str,
        end_ts: str,
        previous_hash: Optional[str],
    ) -> Dict[str, Any]:
        """Upload archive to S3 with Object Lock."""
        # Serialize and compress
        archive_data = {
            "partition": partition_name,
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
            "event_count": len(records),
            "previous_hash": previous_hash,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "events": records,
        }

        json_bytes = json.dumps(archive_data, indent=None, sort_keys=True).encode("utf-8")
        compressed = gzip.compress(json_bytes)

        # Compute archive hash
        archive_hash = hashlib.sha256(compressed).hexdigest()

        # Sign the archive
        signature = self._sign_data(compressed)

        # Build S3 key
        s3_key = f"{self.s3_prefix}{partition_name}.json.gz"

        if self.dry_run:
            logger.info(f"[DRY RUN] Would upload {len(compressed)} bytes to s3://{self.s3_bucket}/{s3_key}")
            return {
                "s3_key": s3_key,
                "version_id": "dry-run",
                "archive_hash": archive_hash,
                "signature": signature,
                "size_bytes": len(compressed),
            }

        # Upload with Object Lock
        s3 = self._get_s3_client()

        retention_until = datetime.now(timezone.utc) + timedelta(days=self.worm_retention_days)

        response = s3.put_object(
            Bucket=self.s3_bucket,
            Key=s3_key,
            Body=compressed,
            ContentType="application/gzip",
            ContentEncoding="gzip",
            ObjectLockMode="GOVERNANCE",
            ObjectLockRetainUntilDate=retention_until,
            Metadata={
                "partition": partition_name,
                "archive-hash": archive_hash,
                "event-count": str(len(records)),
                "start-timestamp": start_ts,
                "end-timestamp": end_ts,
            },
        )

        logger.info(f"Uploaded archive to s3://{self.s3_bucket}/{s3_key} ({len(compressed)} bytes)")

        return {
            "s3_key": s3_key,
            "version_id": response.get("VersionId"),
            "archive_hash": archive_hash,
            "signature": signature,
            "size_bytes": len(compressed),
        }

    def _record_archive_metadata(
        self,
        partition_name: str,
        s3_key: str,
        version_id: Optional[str],
        event_count: int,
        start_ts: str,
        end_ts: str,
        archive_hash: str,
        previous_hash: Optional[str],
        signature: Optional[str],
    ) -> None:
        """Record archive metadata in PostgreSQL."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would record archive metadata for {partition_name}")
            return

        conn = self._get_connection()
        with conn.cursor() as cur:
            retention_until = datetime.now(timezone.utc) + timedelta(days=self.worm_retention_days)

            cur.execute("""
                INSERT INTO audit_log_archives (
                    s3_key, version_id, event_count,
                    start_timestamp, end_timestamp,
                    archive_hash, previous_hash,
                    signature, signing_key_id,
                    retention_until
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                s3_key,
                version_id,
                event_count,
                start_ts,
                end_ts,
                archive_hash,
                previous_hash,
                signature,
                os.path.basename(self.signing_key_path) if self.signing_key_path else None,
                retention_until,
            ))
            conn.commit()

    def _detach_partition(self, partition_name: str) -> None:
        """Detach archived partition from main table."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would detach partition {partition_name}")
            return

        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute(f"ALTER TABLE audit_log_events DETACH PARTITION {partition_name}")
            conn.commit()
            logger.info(f"Detached partition {partition_name}")

    def _drop_partition(self, partition_name: str) -> None:
        """Drop detached partition after successful archive."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would drop partition {partition_name}")
            return

        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {partition_name}")
            conn.commit()
            logger.info(f"Dropped partition {partition_name}")

    def archive_partition(self, partition_name: str) -> bool:
        """Archive a single partition to S3."""
        logger.info(f"Archiving partition: {partition_name}")

        try:
            # Export data
            records, start_ts, end_ts = self._export_partition_data(partition_name)

            if not records:
                logger.info(f"Partition {partition_name} is empty, skipping")
                return True

            # Get chain hash
            previous_hash = self._get_last_archive_hash()

            # Upload to S3
            result = self._upload_to_s3(partition_name, records, start_ts, end_ts, previous_hash)

            # Record metadata
            self._record_archive_metadata(
                partition_name=partition_name,
                s3_key=result["s3_key"],
                version_id=result.get("version_id"),
                event_count=len(records),
                start_ts=start_ts,
                end_ts=end_ts,
                archive_hash=result["archive_hash"],
                previous_hash=previous_hash,
                signature=result.get("signature"),
            )

            # Detach and drop partition
            self._detach_partition(partition_name)
            self._drop_partition(partition_name)

            logger.info(f"Successfully archived partition {partition_name} ({len(records)} events)")
            return True

        except Exception as e:
            logger.error(f"Failed to archive partition {partition_name}: {e}")
            return False

    def run(self) -> int:
        """Run the archival job. Returns exit code."""
        logger.info(f"Starting audit log archival (retention={self.retention_days} days, dry_run={self.dry_run})")

        # List partitions to archive
        partitions = self._list_partitions_to_archive()

        if not partitions:
            logger.info("No partitions ready for archival")
            return 0

        logger.info(f"Found {len(partitions)} partitions to archive: {partitions}")

        # Archive each partition
        success_count = 0
        fail_count = 0

        for partition in partitions:
            if self.archive_partition(partition):
                success_count += 1
            else:
                fail_count += 1

        logger.info(f"Archival complete: {success_count} succeeded, {fail_count} failed")

        return 0 if fail_count == 0 else 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Archive audit logs to S3 WORM storage")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually archive")
    parser.add_argument("--retention-days", type=int, help="Days before archival")
    parser.add_argument("--worm-days", type=int, help="S3 Object Lock retention days")
    args = parser.parse_args()

    # Get configuration from environment
    pg_dsn = os.getenv("AMPREALIZE_AUDIT_PG_DSN")
    if not pg_dsn:
        logger.error("AMPREALIZE_AUDIT_PG_DSN environment variable is required")
        return 1

    s3_bucket = os.getenv("AWS_S3_BUCKET")
    if not s3_bucket:
        logger.error("AWS_S3_BUCKET environment variable is required")
        return 1

    archiver = AuditArchiver(
        pg_dsn=pg_dsn,
        s3_bucket=s3_bucket,
        s3_prefix=os.getenv("AWS_S3_PREFIX", "audit-archives/"),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        retention_days=args.retention_days or get_env_int("AUDIT_RETENTION_DAYS", 30),
        worm_retention_days=args.worm_days or get_env_int("AUDIT_WORM_RETENTION_DAYS", 2555),
        signing_key_path=os.getenv("ED25519_SIGNING_KEY_PATH"),
        dry_run=args.dry_run or get_env_bool("DRY_RUN"),
    )

    return archiver.run()


if __name__ == "__main__":
    sys.exit(main())
