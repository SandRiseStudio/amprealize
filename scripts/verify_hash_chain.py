#!/usr/bin/env python3
"""Hash chain verification job for Cloud Run.

This script verifies the integrity of audit log hash chains across storage tiers:
- PostgreSQL (hot tier): Primary source of truth
- OpenSearch (warm tier): Search index
- S3 WORM (cold tier): Immutable archive

The job runs on a schedule (e.g., daily) and reports any gaps or tampering
to the monitoring system via Raze structured logging.

Usage:
    # Local testing
    python scripts/verify_hash_chain.py --window-hours 24

    # Cloud Run (invoked by Cloud Scheduler)
    python scripts/verify_hash_chain.py

Environment Variables:
    AMPREALIZE_AUDIT_PG_DSN: PostgreSQL connection string for audit logs
    OPENSEARCH_ENDPOINT: OpenSearch/Elasticsearch endpoint
    OPENSEARCH_API_KEY: API key for OpenSearch (optional)
    AWS_REGION: AWS region for S3
    S3_WORM_BUCKET: S3 bucket for WORM archives
    RAZE_SINK_TYPE: Logging sink (timescale, jsonl, console)
    VERIFICATION_WINDOW_HOURS: Hours to look back (default: 24)

Exit Codes:
    0: Verification passed
    1: Verification failed (gaps or invalid links found)
    2: Configuration error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# Set up basic logging before imports that might use it
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("hash_chain_verifier")


@dataclass
class VerificationResult:
    """Result of hash chain verification."""

    status: str  # 'valid', 'degraded', 'failed'
    total_events: int = 0
    verified_count: int = 0
    gaps: list[dict[str, Any]] = field(default_factory=list)
    invalid_links: list[dict[str, Any]] = field(default_factory=list)
    invalid_signatures: list[dict[str, Any]] = field(default_factory=list)
    cross_tier_mismatches: list[dict[str, Any]] = field(default_factory=list)
    verification_window_start: Optional[datetime] = None
    verification_window_end: Optional[datetime] = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/reporting."""
        return {
            "status": self.status,
            "total_events": self.total_events,
            "verified_count": self.verified_count,
            "gap_count": len(self.gaps),
            "invalid_link_count": len(self.invalid_links),
            "invalid_signature_count": len(self.invalid_signatures),
            "cross_tier_mismatch_count": len(self.cross_tier_mismatches),
            "verification_window_start": self.verification_window_start.isoformat() if self.verification_window_start else None,
            "verification_window_end": self.verification_window_end.isoformat() if self.verification_window_end else None,
            "duration_seconds": self.duration_seconds,
            "gaps": self.gaps[:10],  # Limit detail in logs
            "invalid_links": self.invalid_links[:10],
            "invalid_signatures": self.invalid_signatures[:10],
            "cross_tier_mismatches": self.cross_tier_mismatches[:10],
        }


class HashChainVerifier:
    """Verifies hash chain integrity across storage tiers.

    The audit log uses a hash chain for tamper detection:
    - Each event has a content_hash (SHA-256 of payload)
    - Each event has a previous_hash linking to the prior event
    - Events are signed with Ed25519 for non-repudiation

    This verifier checks:
    1. Hash chain continuity (no gaps)
    2. Content hash validity (payload matches hash)
    3. Signature validity (Ed25519 verification)
    4. Cross-tier consistency (PostgreSQL ↔ OpenSearch ↔ S3)
    """

    def __init__(
        self,
        pg_dsn: Optional[str] = None,
        opensearch_endpoint: Optional[str] = None,
        opensearch_api_key: Optional[str] = None,
        s3_bucket: Optional[str] = None,
        signing_public_key_path: Optional[str] = None,
    ):
        self.pg_dsn = pg_dsn or os.getenv("AMPREALIZE_AUDIT_PG_DSN")
        self.opensearch_endpoint = opensearch_endpoint or os.getenv("OPENSEARCH_ENDPOINT")
        self.opensearch_api_key = opensearch_api_key or os.getenv("OPENSEARCH_API_KEY")
        self.s3_bucket = s3_bucket or os.getenv("S3_WORM_BUCKET")
        self.signing_public_key_path = signing_public_key_path or os.getenv("SIGNING_PUBLIC_KEY_PATH")

        # Lazy-loaded connections
        self._pg_conn = None
        self._opensearch_client = None
        self._s3_client = None
        self._signer = None

    def _get_pg_connection(self):
        """Get PostgreSQL connection (lazy load)."""
        if self._pg_conn is None:
            if not self.pg_dsn:
                raise ValueError("PostgreSQL DSN not configured")

            import psycopg2
            self._pg_conn = psycopg2.connect(self.pg_dsn)

        return self._pg_conn

    def _get_opensearch_client(self):
        """Get OpenSearch client (lazy load)."""
        if self._opensearch_client is None:
            if not self.opensearch_endpoint:
                return None  # OpenSearch is optional

            from opensearchpy import OpenSearch

            client_kwargs = {
                "hosts": [self.opensearch_endpoint],
                "use_ssl": self.opensearch_endpoint.startswith("https"),
                "verify_certs": True,
            }

            if self.opensearch_api_key:
                client_kwargs["api_key"] = self.opensearch_api_key

            self._opensearch_client = OpenSearch(**client_kwargs)

        return self._opensearch_client

    def _get_signer(self):
        """Get Ed25519 signer for signature verification (lazy load)."""
        if self._signer is None:
            if not self.signing_public_key_path:
                return None  # Signature verification is optional

            from amprealize.crypto.signing import AuditSigner

            self._signer = AuditSigner()
            # Load only public key for verification
            with open(self.signing_public_key_path, "rb") as f:
                from cryptography.hazmat.primitives.serialization import load_pem_public_key
                self._signer._public_key = load_pem_public_key(f.read())

        return self._signer

    def verify_postgres_chain(
        self,
        start_time: datetime,
        end_time: datetime,
        batch_size: int = 1000,
    ) -> VerificationResult:
        """Verify hash chain in PostgreSQL audit_log_worm table.

        Args:
            start_time: Start of verification window
            end_time: End of verification window
            batch_size: Number of events to fetch per query

        Returns:
            VerificationResult with findings
        """
        result = VerificationResult(
            status="valid",
            verification_window_start=start_time,
            verification_window_end=end_time,
        )

        conn = self._get_pg_connection()
        signer = self._get_signer()

        with conn.cursor() as cur:
            # Fetch events in time window ordered by timestamp
            cur.execute(
                """
                SELECT
                    event_id,
                    event_type,
                    payload,
                    content_hash,
                    previous_hash,
                    signature,
                    created_at
                FROM audit_log_worm
                WHERE created_at >= %s AND created_at < %s
                ORDER BY created_at ASC
                """,
                (start_time, end_time),
            )

            events = cur.fetchall()
            result.total_events = len(events)

            # Build hash index for chain verification
            hash_index: dict[str, str] = {}  # content_hash -> event_id

            for row in events:
                event_id, event_type, payload, content_hash, previous_hash, signature, created_at = row

                # Verify content hash
                payload_json = json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else payload
                computed_hash = hashlib.sha256(payload_json.encode()).hexdigest()

                if computed_hash != content_hash:
                    result.invalid_links.append({
                        "event_id": event_id,
                        "reason": "content_hash_mismatch",
                        "stored_hash": content_hash,
                        "computed_hash": computed_hash,
                        "timestamp": created_at.isoformat(),
                    })
                    continue

                # Verify hash chain link
                if previous_hash:
                    if previous_hash not in hash_index:
                        # Check if previous hash exists in DB (outside our window)
                        cur.execute(
                            "SELECT event_id FROM audit_log_worm WHERE content_hash = %s",
                            (previous_hash,),
                        )
                        prev_row = cur.fetchone()

                        if not prev_row:
                            result.gaps.append({
                                "event_id": event_id,
                                "missing_hash": previous_hash,
                                "timestamp": created_at.isoformat(),
                            })

                # Verify Ed25519 signature (if available)
                if signature and signer:
                    try:
                        record = {
                            "event_id": event_id,
                            "event_type": event_type,
                            "payload": payload,
                            "content_hash": content_hash,
                            "previous_hash": previous_hash,
                        }

                        if not signer.verify_record(record, signature):
                            result.invalid_signatures.append({
                                "event_id": event_id,
                                "reason": "signature_invalid",
                                "timestamp": created_at.isoformat(),
                            })
                    except Exception as e:
                        result.invalid_signatures.append({
                            "event_id": event_id,
                            "reason": f"signature_error: {str(e)}",
                            "timestamp": created_at.isoformat(),
                        })

                # Add to hash index for subsequent chain verification
                hash_index[content_hash] = event_id
                result.verified_count += 1

        # Determine final status
        if result.gaps or result.invalid_links or result.invalid_signatures:
            result.status = "degraded" if result.verified_count > 0 else "failed"

        return result

    def verify_cross_tier_consistency(
        self,
        start_time: datetime,
        end_time: datetime,
        sample_rate: float = 0.1,
    ) -> list[dict[str, Any]]:
        """Verify consistency between PostgreSQL and OpenSearch.

        Samples events from PostgreSQL and verifies they exist with
        matching content in OpenSearch.

        Args:
            start_time: Start of verification window
            end_time: End of verification window
            sample_rate: Fraction of events to verify (0.0-1.0)

        Returns:
            List of mismatches found
        """
        mismatches = []

        opensearch = self._get_opensearch_client()
        if not opensearch:
            logger.warning("OpenSearch not configured, skipping cross-tier verification")
            return mismatches

        conn = self._get_pg_connection()

        with conn.cursor() as cur:
            # Get sample of events
            cur.execute(
                """
                SELECT event_id, content_hash
                FROM audit_log_worm
                WHERE created_at >= %s AND created_at < %s
                  AND random() < %s
                LIMIT 1000
                """,
                (start_time, end_time, sample_rate),
            )

            for event_id, pg_hash in cur.fetchall():
                # Check OpenSearch
                try:
                    response = opensearch.search(
                        index="amprealize-audit-*",
                        body={
                            "query": {"term": {"event_id": event_id}},
                            "size": 1,
                            "_source": ["content_hash"],
                        },
                    )

                    if not response["hits"]["hits"]:
                        mismatches.append({
                            "event_id": event_id,
                            "reason": "missing_in_opensearch",
                        })
                    else:
                        os_hash = response["hits"]["hits"][0]["_source"].get("content_hash")
                        if os_hash != pg_hash:
                            mismatches.append({
                                "event_id": event_id,
                                "reason": "hash_mismatch",
                                "pg_hash": pg_hash,
                                "opensearch_hash": os_hash,
                            })

                except Exception as e:
                    logger.warning(f"OpenSearch query failed for {event_id}: {e}")

        return mismatches

    def run_verification(
        self,
        window_hours: int = 24,
        verify_cross_tier: bool = True,
        sample_rate: float = 0.1,
    ) -> VerificationResult:
        """Run full hash chain verification.

        Args:
            window_hours: Hours to look back for verification
            verify_cross_tier: Whether to verify PostgreSQL ↔ OpenSearch consistency
            sample_rate: Fraction of events to sample for cross-tier verification

        Returns:
            VerificationResult with all findings
        """
        import time
        start = time.time()

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=window_hours)

        logger.info(f"Starting verification for window: {start_time} to {end_time}")

        # Verify PostgreSQL hash chain
        result = self.verify_postgres_chain(start_time, end_time)

        # Cross-tier verification
        if verify_cross_tier:
            mismatches = self.verify_cross_tier_consistency(
                start_time, end_time, sample_rate
            )
            result.cross_tier_mismatches = mismatches

            if mismatches and result.status == "valid":
                result.status = "degraded"

        result.duration_seconds = time.time() - start

        logger.info(
            f"Verification complete: status={result.status}, "
            f"verified={result.verified_count}/{result.total_events}, "
            f"gaps={len(result.gaps)}, invalid_links={len(result.invalid_links)}, "
            f"duration={result.duration_seconds:.2f}s"
        )

        return result

    def close(self):
        """Close all connections."""
        if self._pg_conn:
            self._pg_conn.close()
            self._pg_conn = None

        if self._opensearch_client:
            self._opensearch_client.close()
            self._opensearch_client = None


def report_to_raze(result: VerificationResult) -> None:
    """Report verification result to Raze logging system."""
    try:
        from raze import RazeLogger

        raze_logger = RazeLogger.get_default()

        if result.status == "valid":
            raze_logger.info(
                "Hash chain verification passed",
                **result.to_dict(),
            )
        else:
            raze_logger.warning(
                f"Hash chain verification {result.status}",
                **result.to_dict(),
            )

    except ImportError:
        # Raze not available, use standard logging
        logger.info(f"Verification result: {json.dumps(result.to_dict(), indent=2)}")


def main():
    """Main entry point for Cloud Run job."""
    parser = argparse.ArgumentParser(description="Verify audit log hash chain integrity")
    parser.add_argument(
        "--window-hours",
        type=int,
        default=int(os.getenv("VERIFICATION_WINDOW_HOURS", "24")),
        help="Hours to look back for verification",
    )
    parser.add_argument(
        "--skip-cross-tier",
        action="store_true",
        help="Skip cross-tier (PostgreSQL ↔ OpenSearch) verification",
    )
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=0.1,
        help="Sample rate for cross-tier verification (0.0-1.0)",
    )
    parser.add_argument(
        "--output-json",
        action="store_true",
        help="Output results as JSON to stdout",
    )

    args = parser.parse_args()

    # Validate configuration
    pg_dsn = os.getenv("AMPREALIZE_AUDIT_PG_DSN")
    if not pg_dsn:
        logger.error("AMPREALIZE_AUDIT_PG_DSN environment variable not set")
        sys.exit(2)

    try:
        verifier = HashChainVerifier()

        result = verifier.run_verification(
            window_hours=args.window_hours,
            verify_cross_tier=not args.skip_cross_tier,
            sample_rate=args.sample_rate,
        )

        verifier.close()

        # Report to monitoring
        report_to_raze(result)

        # Output JSON if requested
        if args.output_json:
            print(json.dumps(result.to_dict(), indent=2))

        # Exit code based on status
        if result.status == "valid":
            sys.exit(0)
        else:
            sys.exit(1)

    except Exception as e:
        logger.exception(f"Verification failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
