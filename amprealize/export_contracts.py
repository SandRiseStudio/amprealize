#!/usr/bin/env python3
"""
Export Job Contracts for Daily Export Automation

Defines data structures for export job tracking, backup management,
and retention policy configuration.
"""

from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime


class ExportJobStatus(str, Enum):
    """Status of export job execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class ExportJob:
    """Represents a daily export job with tracking metadata."""
    job_id: str
    status: ExportJobStatus
    start_time: str
    end_time: Optional[str] = None
    error_message: Optional[str] = None

    # Export results
    tables_exported: int = 0
    rows_exported: int = 0
    file_size_mb: float = 0.0

    # Backup management
    backup_path: Optional[str] = None
    backups_deleted: int = 0

    # Job metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

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


@dataclass
class BackupConfig:
    """Configuration for backup creation and management."""
    backup_dir: str
    retention_days: int = 30
    max_backups: Optional[int] = None
    compress: bool = False
    timestamp_format: str = "%Y%m%d_%H%M%S"


@dataclass
class RetentionPolicy:
    """Defines backup retention policy rules."""
    days: int
    max_count: Optional[int] = None
    min_free_space_gb: Optional[float] = None

    def should_retain_backup(self, backup_age_days: int, current_count: int) -> bool:
        """Determine if a backup should be retained."""
        if backup_age_days > self.days:
            return False

        if self.max_count and current_count > self.max_count:
            return False

        return True
