"""In-memory sink for testing and development."""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from raze.models import (
    LogAggregateRequest,
    LogAggregation,
    LogEvent,
    LogLevel,
    LogQueryRequest,
)
from raze.sinks.base import RazeSink


class InMemorySink(RazeSink):
    """In-memory sink for testing and development.

    Stores logs in a list with basic filtering and aggregation support.
    Thread-safe for concurrent access.

    Example:
        sink = InMemorySink()
        logger = RazeLogger(service="test", service_instance=RazeService(sink=sink))
        logger.info("Test message")

        # Access stored logs
        assert len(sink.events) == 1
        assert sink.events[0].message == "Test message"
    """

    def __init__(self, max_events: int = 100000) -> None:
        """Initialize in-memory sink.

        Args:
            max_events: Maximum events to store (oldest dropped when exceeded).
        """
        self._events: List[LogEvent] = []
        self._max_events = max_events
        self._lock = threading.RLock()

    @property
    def events(self) -> List[LogEvent]:
        """Get all stored events (copy)."""
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        """Clear all stored events."""
        with self._lock:
            self._events.clear()

    def write(self, event: LogEvent) -> None:
        """Write a single log event."""
        with self._lock:
            self._events.append(event)
            # Trim oldest if exceeded
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]

    def write_batch(self, events: List[LogEvent]) -> None:
        """Write a batch of log events."""
        with self._lock:
            self._events.extend(events)
            # Trim oldest if exceeded
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]

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

        # Full-text search (simple substring match)
        if request.search is not None:
            search_lower = request.search.lower()
            message_match = search_lower in event.message.lower()
            context_match = search_lower in str(event.context).lower()
            if not message_match and not context_match:
                return False

        # Context filters (simple equality)
        if request.context_filters is not None:
            for key, value in request.context_filters.items():
                if event.context.get(key) != value:
                    return False

        return True

    def query(self, request: LogQueryRequest) -> Tuple[List[LogEvent], int]:
        """Query logs with filters."""
        with self._lock:
            # Filter events
            matching = [e for e in self._events if self._matches_filters(e, request)]

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
        with self._lock:
            # Filter by time range
            filtered = [
                e for e in self._events
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
            for key_tuple, events in groups.items():
                group_key = dict(zip(request.group_by, key_tuple))
                timestamps = [e.timestamp for e in events]
                aggregations.append(
                    LogAggregation(
                        group_key=group_key,
                        count=len(events),
                        first_timestamp=min(timestamps),
                        last_timestamp=max(timestamps),
                    )
                )

            # Sort by count descending
            aggregations.sort(key=lambda a: a.count, reverse=True)

            return aggregations, total_count
