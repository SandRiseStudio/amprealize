"""File sink for JSONL log storage."""

from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from raze.models import (
    LogAggregateRequest,
    LogAggregation,
    LogEvent,
    LogLevel,
    LogQueryRequest,
)
from raze.sinks.base import RazeSink


class FileSink(RazeSink):
    """JSONL file sink for log storage.

    Writes logs as newline-delimited JSON (JSONL) for easy streaming
    and compatibility with log processors like jq.

    Example:
        sink = FileSink(path=Path("logs/app.jsonl"))
        service = RazeService(sink=sink)
    """

    def __init__(
        self,
        path: Path,
        *,
        append: bool = True,
        flush_after_write: bool = True,
        create_dirs: bool = True,
    ) -> None:
        """Initialize file sink.

        Args:
            path: Path to the JSONL file.
            append: Whether to append to existing file.
            flush_after_write: Whether to flush after each write.
            create_dirs: Whether to create parent directories.
        """
        self._path = Path(path).expanduser().resolve()
        self._append = append
        self._flush_after_write = flush_after_write
        self._lock = threading.Lock()
        self._handle: Optional[Any] = None

        if create_dirs:
            self._path.parent.mkdir(parents=True, exist_ok=True)

        # Open file handle
        mode = "a" if append else "w"
        self._handle = open(self._path, mode, encoding="utf-8")

    def _serialize(self, event: LogEvent) -> str:
        """Serialize event to JSON string."""
        return json.dumps(event.to_dict(), ensure_ascii=False, default=str)

    def write(self, event: LogEvent) -> None:
        """Write a single log event."""
        line = self._serialize(event) + "\n"
        with self._lock:
            if self._handle:
                self._handle.write(line)
                if self._flush_after_write:
                    self._handle.flush()

    def write_batch(self, events: List[LogEvent]) -> None:
        """Write a batch of log events."""
        lines = [self._serialize(e) + "\n" for e in events]
        with self._lock:
            if self._handle:
                self._handle.writelines(lines)
                if self._flush_after_write:
                    self._handle.flush()

    def flush(self) -> None:
        """Flush buffered writes."""
        with self._lock:
            if self._handle:
                self._handle.flush()

    def close(self) -> None:
        """Close the file handle."""
        with self._lock:
            if self._handle:
                self._handle.close()
                self._handle = None

    def _read_all_events(self) -> List[LogEvent]:
        """Read all events from file for querying."""
        events = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            events.append(LogEvent(**data))
                        except (json.JSONDecodeError, ValueError):
                            # Skip malformed lines
                            pass
        except FileNotFoundError:
            pass
        return events

    def _matches_filters(self, event: LogEvent, request: LogQueryRequest) -> bool:
        """Check if event matches query filters."""
        # Time range
        if event.timestamp < request.start_time or event.timestamp > request.end_time:
            return False

        # Level filter (minimum level)
        if request.level is not None and event.level < request.level:
            return False

        # Specific levels
        if request.levels is not None and event.level not in request.levels:
            return False

        # Service filter
        if request.service is not None and event.service != request.service:
            return False

        if request.services is not None and event.service not in request.services:
            return False

        # Correlation ID filters
        if request.run_id is not None and event.run_id != request.run_id:
            return False

        if request.action_id is not None and event.action_id != request.action_id:
            return False

        if request.session_id is not None and event.session_id != request.session_id:
            return False

        if request.actor_surface is not None and event.actor_surface != request.actor_surface:
            return False

        # Full-text search
        if request.search is not None:
            search_lower = request.search.lower()
            message_match = search_lower in event.message.lower()
            context_match = search_lower in str(event.context).lower()
            if not message_match and not context_match:
                return False

        # Context filters
        if request.context_filters is not None:
            for key, value in request.context_filters.items():
                if event.context.get(key) != value:
                    return False

        return True

    def query(self, request: LogQueryRequest) -> Tuple[List[LogEvent], int]:
        """Query logs with filters.

        Note: File sink loads all events into memory for filtering.
        For large log files, use TimescaleDBSink instead.
        """
        events = self._read_all_events()

        # Filter events
        matching = [e for e in events if self._matches_filters(e, request)]

        # Sort
        reverse = request.order == "desc"
        matching.sort(key=lambda e: e.timestamp, reverse=reverse)

        # Total before pagination
        total_count = len(matching)

        # Paginate
        start = request.offset
        end = start + request.limit
        page = matching[start:end]

        return page, total_count

    def aggregate(self, request: LogAggregateRequest) -> Tuple[List[LogAggregation], int]:
        """Aggregate log statistics."""
        events = self._read_all_events()

        # Filter by time range
        filtered = [
            e for e in events
            if request.start_time <= e.timestamp <= request.end_time
        ]

        # Apply level filter
        if request.level is not None:
            filtered = [e for e in filtered if e.level >= request.level]

        # Apply service filter
        if request.service is not None:
            filtered = [e for e in filtered if e.service == request.service]

        total_count = len(filtered)

        # Group by
        groups: Dict[Tuple[str, ...], List[LogEvent]] = defaultdict(list)
        for event in filtered:
            key_values = []
            for field in request.group_by:
                if field == "level":
                    key_values.append(event.level.value)
                elif field == "service":
                    key_values.append(event.service)
                elif field == "actor_surface":
                    key_values.append(event.actor_surface or "unknown")
                elif field == "run_id":
                    key_values.append(event.run_id or "unknown")
                else:
                    key_values.append("unknown")
            groups[tuple(key_values)].append(event)

        # Build aggregations
        aggregations = []
        for key_tuple, events_group in groups.items():
            group_key = dict(zip(request.group_by, key_tuple))
            timestamps = [e.timestamp for e in events_group]
            aggregations.append(
                LogAggregation(
                    group_key=group_key,
                    count=len(events_group),
                    first_timestamp=min(timestamps),
                    last_timestamp=max(timestamps),
                )
            )

        # Sort by count descending
        aggregations.sort(key=lambda a: a.count, reverse=True)

        return aggregations, total_count

    def __enter__(self) -> "FileSink":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
