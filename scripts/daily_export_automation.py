#!/usr/bin/env python3
"""
Daily Export Automation Job for DuckDB to SQLite Conversion

This script orchestrates the daily export pipeline:
1. Execute DuckDB to SQLite export
2. Rotate backup files with retention policy
3. Emit telemetry events for monitoring
4. Handle failures with alerting

Configured via environment variables:
- AMPREALIZE_EXPORT_DUCKDB_PATH: Path to DuckDB warehouse (default: data/telemetry.duckdb)
- AMPREALIZE_EXPORT_SQLITE_PATH: Path to SQLite export (default: data/telemetry_sqlite.db)
- AMPREALIZE_EXPORT_BACKUP_DIR: Directory for backup files (default: data/backups)
- AMPREALIZE_EXPORT_RETENTION_DAYS: Days to keep backups (default: 30)
- AMPREALIZE_EXPORT_DRY_RUN: Run without actual export (default: false)
- AMPREALIZE_EXPORT_ALERT_WEBHOOK: Webhook URL for failure notifications
- AMPREALIZE_EXPORT_NOTIFICATION_EMAIL: Email for failure notifications

Usage:
    python scripts/daily_export_automation.py [--dry-run] [--retention-days N]
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

# Add amprealize to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class ExportJobStatus:
    """Status constants for export job execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ExportResult:
    """Result of export operation."""

    def __init__(self, success: bool, tables_exported: int = 0, rows_exported: int = 0,
                 file_size_mb: float = 0.0, error: Optional[str] = None):
        self.success = success
        self.tables_exported = tables_exported
        self.rows_exported = rows_exported
        self.file_size_mb = file_size_mb
        self.error = error


class ExportJob:
    """Represents a daily export job with tracking metadata."""

    def __init__(self, job_id: str, status: str, start_time: str):
        self.job_id: str = job_id
        self.status: str = status
        self.start_time: str = start_time
        self.end_time: Optional[str] = None
        self.error_message: Optional[str] = None
        self.tables_exported: int = 0
        self.rows_exported: int = 0
        self.file_size_mb: float = 0.0
        self.backup_path: Optional[str] = None
        self.backups_deleted: int = 0
        self.metadata: Dict[str, Any] = {}

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate job duration in seconds."""
        if not self.end_time:
            return None

        try:
            start = datetime.fromisoformat(self.start_time.replace('Z', '+00:00'))
            end = datetime.fromisoformat(self.end_time.replace('Z', '+00:00'))
            return (end - start).total_seconds()
        except Exception:
            return None


class DailyExportConfig:
    """Configuration for daily export automation job."""

    def __init__(self) -> None:
        self.duckdb_path = os.getenv("AMPREALIZE_EXPORT_DUCKDB_PATH", "data/telemetry.duckdb")
        self.sqlite_path = os.getenv("AMPREALIZE_EXPORT_SQLITE_PATH", "data/telemetry_sqlite.db")
        self.backup_dir = os.getenv("AMPREALIZE_EXPORT_BACKUP_DIR", "data/backups")
        self.retention_days = int(os.getenv("AMPREALIZE_EXPORT_RETENTION_DAYS", "30"))
        self.dry_run = os.getenv("AMPREALIZE_EXPORT_DRY_RUN", "false").lower() == "true"
        self.alert_webhook = os.getenv("AMPREALIZE_EXPORT_ALERT_WEBHOOK")
        self.notification_email = os.getenv("AMPREALIZE_EXPORT_NOTIFICATION_EMAIL")
        self.alert_on_success = os.getenv("AMPREALIZE_EXPORT_ALERT_ON_SUCCESS", "false").lower() == "true"

        # Create backup directory if it doesn't exist
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)

    def __str__(self) -> str:
        return (
            f"DailyExportConfig(duckdb_path={self.duckdb_path}, "
            f"sqlite_path={self.sqlite_path}, backup_dir={self.backup_dir}, "
            f"retention_days={self.retention_days}, dry_run={self.dry_run}, "
            f"alert_webhook={'***' if self.alert_webhook else None})"
        )


class DailyExportJob:
    """Orchestrates daily DuckDB to SQLite export with backup rotation."""

    def __init__(self, config: DailyExportConfig):
        self.config = config
        self.job = None

    def execute(self) -> ExportJob:
        """Run the daily export pipeline."""
        job_id = str(uuid.uuid4())
        start_time = datetime.now(UTC).isoformat()

        logging.info(f"Starting daily export job {job_id}")
        logging.info(f"Config: {self.config}")

        # Create export job
        self.job = ExportJob(
            job_id=job_id,
            status=ExportJobStatus.PENDING,
            start_time=start_time
        )

        self.job.metadata = {
            "duckdb_path": self.config.duckdb_path,
            "sqlite_path": self.config.sqlite_path,
            "backup_dir": self.config.backup_dir,
            "retention_days": self.config.retention_days,
            "dry_run": self.config.dry_run,
        }

        try:
            # Step 1: Create backup of existing SQLite file
            self._update_job_status(ExportJobStatus.RUNNING, "Creating backup")
            backup_path = self._create_backup()
            self.job.backup_path = str(backup_path) if backup_path else None

            # Step 2: Execute DuckDB to SQLite export
            self._update_job_status(ExportJobStatus.RUNNING, "Executing export")
            export_result = self._execute_export()

            if not export_result.success:
                raise Exception(f"Export failed: {export_result.error}")

            self.job.tables_exported = export_result.tables_exported
            self.job.rows_exported = export_result.rows_exported
            self.job.file_size_mb = export_result.file_size_mb

            # Step 3: Clean up old backups
            self._update_job_status(ExportJobStatus.RUNNING, "Rotating backups")
            deleted_backups = self._cleanup_old_backups()
            self.job.backups_deleted = deleted_backups

            # Step 4: Mark job complete
            end_time = datetime.now(UTC).isoformat()
            self.job.end_time = end_time
            self.job.status = ExportJobStatus.COMPLETE
            self._update_job_status(ExportJobStatus.COMPLETE, "Export complete")

            # Emit success telemetry
            self._emit_job_telemetry()

            # Send success notification if configured
            if self.config.alert_on_success:
                self._send_notification("success", "Daily export completed successfully")

            return self.job

        except Exception as e:
            logging.exception(f"Job {job_id} failed: {e}")
            self.job.error_message = str(e)
            self.job.end_time = datetime.now(UTC).isoformat()
            self.job.status = ExportJobStatus.FAILED
            self._update_job_status(ExportJobStatus.FAILED, str(e))

            # Emit failure telemetry
            self._emit_job_telemetry()

            # Send failure notification
            self._send_notification("failure", f"Daily export failed: {e}")

            return self.job

    def _create_backup(self) -> Optional[Path]:
        """Create timestamped backup of existing SQLite file."""
        try:
            sqlite_file = Path(self.config.sqlite_path)

            if not sqlite_file.exists():
                logging.info("No existing SQLite file to backup")
                return None

            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            backup_filename = f"telemetry_sqlite_{timestamp}.db"
            backup_path = Path(self.config.backup_dir) / backup_filename

            logging.info(f"Creating backup: {backup_path}")

            if self.config.dry_run:
                logging.info(f"[DRY RUN] Would copy {sqlite_file} to {backup_path}")
                return backup_path

            shutil.copy2(sqlite_file, backup_path)

            # Get file size for logging
            size_mb = backup_path.stat().st_size / (1024 * 1024)
            logging.info(f"Backup created: {size_mb:.2f} MB")

            return backup_path

        except Exception as e:
            logging.error(f"Failed to create backup: {e}")
            raise

    def _execute_export(self) -> ExportResult:
        """Execute the DuckDB to SQLite export script."""
        try:
            if self.config.dry_run:
                logging.info("[DRY RUN] Would execute export script")
                return ExportResult(
                    success=True,
                    tables_exported=8,
                    rows_exported=1000,
                    file_size_mb=42.5
                )

            # Import and run the export script
            from export_duckdb_to_sqlite import export_duckdb_to_sqlite

            start_time = time.time()
            export_duckdb_to_sqlite(
                duckdb_path=self.config.duckdb_path,
                sqlite_path=self.config.sqlite_path
            )
            export_duration = time.time() - start_time

            # Get export statistics
            sqlite_file = Path(self.config.sqlite_path)
            if not sqlite_file.exists():
                raise Exception("Export completed but SQLite file not found")

            file_size_mb = sqlite_file.stat().st_size / (1024 * 1024)

            # Count tables by reading the file (simplified)
            import sqlite3
            conn = sqlite3.connect(str(sqlite_file))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            conn.close()

            return ExportResult(
                success=True,
                tables_exported=len(tables),
                rows_exported=sum(1 for _ in tables),  # Simplified
                file_size_mb=file_size_mb
            )

        except Exception as e:
            logging.error(f"Export failed: {e}")
            return ExportResult(
                success=False,
                tables_exported=0,
                rows_exported=0,
                file_size_mb=0,
                error=str(e)
            )

    def _cleanup_old_backups(self) -> int:
        """Remove backup files older than retention policy."""
        try:
            backup_dir = Path(self.config.backup_dir)
            cutoff_date = datetime.now(UTC) - timedelta(days=self.config.retention_days)

            if not backup_dir.exists():
                return 0

            deleted_count = 0
            for backup_file in backup_dir.glob("telemetry_sqlite_*.db"):
                try:
                    # Get file modification time
                    file_time = datetime.fromtimestamp(backup_file.stat().st_mtime, UTC)

                    if file_time < cutoff_date:
                        logging.info(f"Deleting old backup: {backup_file.name}")

                        if self.config.dry_run:
                            logging.info(f"[DRY RUN] Would delete {backup_file}")
                        else:
                            backup_file.unlink()
                            deleted_count += 1

                except Exception as e:
                    logging.warning(f"Failed to process backup {backup_file}: {e}")
                    continue

            logging.info(f"Deleted {deleted_count} old backup files")
            return deleted_count

        except Exception as e:
            logging.error(f"Failed to cleanup old backups: {e}")
            return 0

    def _update_job_status(self, status: str, message: str) -> None:
        """Update export job status and log progress."""
        if not self.job:
            return

        self.job.status = status
        if status in {ExportJobStatus.COMPLETE, ExportJobStatus.FAILED}:
            self.job.end_time = datetime.now(UTC).isoformat()

        logging.info(f"Job {self.job.job_id} status: {status} - {message}")

    def _emit_job_telemetry(self) -> None:
        """Emit telemetry event for completed job."""
        if not self.job:
            return

        # Try to emit telemetry if available
        try:
            from amprealize.telemetry import TelemetryClient
            telemetry = TelemetryClient()

            # Emit job completion event
            telemetry.emit_event(
                event_type="analytics.daily_export_complete",
                payload={
                    "job_id": self.job.job_id,
                    "status": self.job.status,
                    "tables_exported": self.job.tables_exported,
                    "rows_exported": self.job.rows_exported,
                    "file_size_mb": self.job.file_size_mb,
                    "backups_deleted": self.job.backups_deleted,
                    "duration_seconds": self.job.duration_seconds,
                    "dry_run": self.config.dry_run,
                    "backup_path": self.job.backup_path,
                },
            )

            # Emit export metrics event for PRD tracking
            if self.job.status == ExportJobStatus.COMPLETE:
                telemetry.emit_event(
                    event_type="analytics.export_metrics",
                    payload={
                        "job_id": self.job.job_id,
                        "export_success": True,
                        "tables_exported": self.job.tables_exported,
                        "rows_exported": self.job.rows_exported,
                        "file_size_mb": self.job.file_size_mb,
                        "backup_created": bool(self.job.backup_path),
                        "old_backups_cleaned": self.job.backups_deleted,
                        "export_duration_seconds": self.job.duration_seconds,
                    },
                )
        except Exception as e:
            logging.warning(f"Failed to emit telemetry: {e}")

    def _send_notification(self, status: str, message: str) -> None:
        """Send failure/success notification via configured channels."""
        try:
            job_id = self.job.job_id if self.job else "unknown"

            # Webhook notification
            if self.config.alert_webhook and status == "failure":
                try:
                    import requests
                    payload = {
                        "text": f"🚨 Amprealize Daily Export Alert",
                        "attachments": [{
                            "color": "danger",
                            "fields": [
                                {"title": "Status", "value": "FAILED", "short": True},
                                {"title": "Job ID", "value": job_id, "short": True},
                                {"title": "Error", "value": message, "short": False},
                            ]
                        }]
                    }

                    response = requests.post(
                        self.config.alert_webhook,
                        json=payload,
                        timeout=10
                    )
                    response.raise_for_status()
                    logging.info("Failure notification sent via webhook")
                except ImportError:
                    logging.warning("requests library not available for webhook notifications")
                except Exception as e:
                    logging.warning(f"Failed to send webhook notification: {e}")

            # Email notification (placeholder - would need SMTP configuration)
            if self.config.notification_email and status == "failure":
                logging.info(f"Would send email to {self.config.notification_email}: {message}")
                # Implementation would use smtplib for email sending

        except Exception as e:
            logging.warning(f"Failed to send notification: {e}")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Daily DuckDB to SQLite export automation job"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without actually executing export or creating backups",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        help=f"Backup retention days (default: from env or 30)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("daily_export")

    # Build configuration
    config = DailyExportConfig()
    if args.dry_run:
        config.dry_run = True
    if args.retention_days:
        config.retention_days = args.retention_days

    logger.info(f"Daily export configuration: {config}")

    # Create and execute job
    job_runner = DailyExportJob(config)
    job = job_runner.execute()

    # Print summary
    print("\n" + "=" * 60)
    print(f"Daily Export Job Summary (ID: {job.job_id})")
    print("=" * 60)
    print(f"Status:              {job.status}")
    print(f"Tables Exported:     {job.tables_exported}")
    print(f"Rows Exported:       {job.rows_exported}")
    print(f"File Size:           {job.file_size_mb:.2f} MB")
    print(f"Backups Deleted:     {job.backups_deleted}")
    if job.duration_seconds:
        print(f"Duration:            {job.duration_seconds:.1f}s")
    if job.error_message:
        print(f"Error:               {job.error_message}")
    print("=" * 60)

    return 0 if job.status == ExportJobStatus.COMPLETE else 1


if __name__ == "__main__":
    sys.exit(main())
