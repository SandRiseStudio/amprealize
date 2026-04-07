"""Retention worker for the conversation messaging system (AMPREALIZE-609, Phase 8).

Implements the three-tier retention policy:
  Active  (0 – archive_after_days):   Postgres hot storage, full API access
  Archive (archive–cold):             Postgres warm, read-only, archived_at set
  Cold    (cold_after_days+, enterprise): S3/GCS export then delete from Postgres

Two async jobs run on configurable intervals:
  1. nightly_archive_job:  Active → Archive  (default: every 24 hours)
  2. weekly_cold_job:      Archive → Cold     (default: every 7 days, enterprise only)

Usage (wired by api.py)::

    worker = RetentionWorker(
        conversation_service=conversation_service,
        retention_config=retention_config,
        storage=s3_storage,          # optional, required for cold export
    )
    await worker.start()             # called on app startup
    await worker.stop()              # called on app shutdown
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from amprealize.config.settings import MessagingRetentionConfig

if TYPE_CHECKING:
    from amprealize.services.conversation_service import ConversationService
    from amprealize.storage.s3_storage import S3Storage

logger = logging.getLogger(__name__)


class RetentionWorker:
    """Async retention worker that schedules archive and cold-export jobs.

    Designed to run as a background service alongside the FastAPI app.
    Uses asyncio periodic tasks (no external scheduler dependency).
    """

    def __init__(
        self,
        conversation_service: "ConversationService",
        retention_config: Optional[MessagingRetentionConfig] = None,
        storage: Optional["S3Storage"] = None,
        org_id: Optional[str] = None,
    ) -> None:
        self._conv = conversation_service
        self._config = retention_config or MessagingRetentionConfig()
        self._storage = storage
        self._org_id = org_id

        self._archive_task: Optional[asyncio.Task] = None
        self._cold_task: Optional[asyncio.Task] = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start background retention jobs."""
        if self._running:
            return
        self._running = True

        self._archive_task = asyncio.get_event_loop().create_task(
            self._run_periodic(
                self.run_archive_job,
                interval=self._config.archive_job_interval_seconds,
                name="archive",
            )
        )

        cold_enabled = self._config.is_cold_export_configured(
            getattr(self._storage, "bucket", None)
        )
        if cold_enabled:
            self._cold_task = asyncio.get_event_loop().create_task(
                self._run_periodic(
                    self.run_cold_export_job,
                    interval=self._config.cold_export_job_interval_seconds,
                    name="cold_export",
                )
            )
            logger.info("Retention worker started (archive + cold export)")
        else:
            logger.info("Retention worker started (archive only — cold export disabled)")

    async def stop(self) -> None:
        """Cancel background tasks gracefully."""
        self._running = False
        for task in (self._archive_task, self._cold_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("Retention worker stopped")

    # ------------------------------------------------------------------
    # Periodic runner
    # ------------------------------------------------------------------

    async def _run_periodic(
        self,
        job: Any,
        interval: int,
        name: str,
    ) -> None:
        """Run *job* every *interval* seconds until stopped."""
        while self._running:
            try:
                await job()
            except Exception:
                logger.exception("Retention job '%s' failed", name)
            await asyncio.sleep(interval)

    # ------------------------------------------------------------------
    # Archive job: Active → Archive
    # ------------------------------------------------------------------

    async def run_archive_job(self) -> int:
        """Archive messages older than archive_after_days.

        Runs synchronous DB call in a thread pool to avoid blocking the
        event loop.

        Returns:
            Number of messages archived.
        """
        loop = asyncio.get_event_loop()
        archive_days = self._config.archive_after_days
        batch_size = self._config.archive_batch_size

        logger.info(
            "Running archive job: archiving messages older than %d days (batch=%d)",
            archive_days,
            batch_size,
        )
        count: int = await loop.run_in_executor(
            None,
            lambda: self._conv.archive_messages_older_than(
                archive_days,
                batch_size=batch_size,
                org_id=self._org_id,
            ),
        )
        logger.info("Archive job complete: %d messages archived", count)
        return count

    # ------------------------------------------------------------------
    # Cold export job: Archive → Cold storage
    # ------------------------------------------------------------------

    async def run_cold_export_job(self) -> int:
        """Export archive-eligible conversations to S3 and remove from Postgres.

        Steps per conversation:
        1. Fetch all messages as dicts
        2. Serialize to gzipped JSONL
        3. Upload to S3 with path: <prefix><year>/<month>/<conv_id>.jsonl.gz
        4. Verify upload
        5. Hard-delete conversation from Postgres

        Returns:
            Number of conversations exported.
        """
        if self._storage is None:
            logger.warning("Cold export skipped — no storage configured")
            return 0

        loop = asyncio.get_event_loop()
        cold_days = self._config.cold_after_days
        batch_size = self._config.cold_export_batch_size

        logger.info(
            "Running cold export job: exporting conversations older than %d days (batch=%d)",
            cold_days,
            batch_size,
        )

        conversations: List[Dict[str, Any]] = await loop.run_in_executor(
            None,
            lambda: self._conv.list_cold_eligible_conversations(
                cold_days,
                batch_size=batch_size,
                org_id=self._org_id,
            ),
        )

        if not conversations:
            logger.info("Cold export job: no eligible conversations found")
            return 0

        exported = 0
        for conv in conversations:
            try:
                await self._export_conversation(conv, loop)
                exported += 1
            except Exception:
                logger.exception(
                    "Cold export failed for conversation %s", conv.get("id")
                )

        logger.info("Cold export job complete: %d conversations exported", exported)
        return exported

    async def _export_conversation(
        self,
        conv: Dict[str, Any],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Export a single conversation to S3 and delete from Postgres."""
        conv_id = conv["id"]

        # 1. Fetch all messages
        messages: List[Dict[str, Any]] = await loop.run_in_executor(
            None,
            lambda: self._conv.get_conversation_messages_for_export(
                conv_id, org_id=self._org_id
            ),
        )

        # 2. Build JSONL payload
        export_obj = {
            "conversation": conv,
            "messages": messages,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": "1.0",
        }
        jsonl_bytes = (json.dumps(export_obj) + "\n").encode("utf-8")
        compressed = gzip.compress(jsonl_bytes)

        # 3. Upload to S3
        now = datetime.now(timezone.utc)
        key = (
            f"{self._config.cold_export_prefix}"
            f"{now.year}/{now.month:02d}/{conv_id}.jsonl.gz"
        )

        assert self._storage is not None
        storage = self._storage

        await loop.run_in_executor(
            None,
            lambda: _upload_bytes(
                storage,
                key,
                compressed,
                metadata={
                    "conversation_id": conv_id,
                    "project_id": str(conv.get("project_id", "")),
                    "message_count": str(conv.get("message_count", 0)),
                    "exported_at": now.isoformat(),
                },
            ),
        )
        logger.info("Uploaded cold export to %s/%s", storage.bucket, key)

        # 4. Hard-delete from Postgres
        deleted = await loop.run_in_executor(
            None,
            lambda: self._conv.delete_conversation_for_cold_export(
                conv_id, org_id=self._org_id
            ),
        )
        logger.info(
            "Deleted cold-exported conversation %s (%d messages)", conv_id, deleted
        )


def _upload_bytes(
    storage: "S3Storage",
    key: str,
    data: bytes,
    metadata: Optional[Dict[str, str]] = None,
) -> None:
    """Upload raw bytes to S3 (runs in thread pool)."""
    import io

    storage.s3.put_object(
        Bucket=storage.bucket,
        Key=key,
        Body=io.BytesIO(data),
        ContentType="application/x-ndjson",
        ContentEncoding="gzip",
        Metadata=metadata or {},
    )
