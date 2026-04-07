"""RazeService - Core service for log ingestion, querying, and aggregation.

This module provides the main service class that coordinates log storage
and retrieval across different sink backends.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, TYPE_CHECKING

from raze.models import (
    LogAggregateRequest,
    LogAggregateResponse,
    LogAggregation,
    LogEvent,
    LogEventInput,
    LogIngestRequest,
    LogIngestResponse,
    LogLevel,
    LogQueryRequest,
    LogQueryResponse,
)

if TYPE_CHECKING:
    from raze.sinks.base import RazeSink


class RazeService:
    """Core service for log operations.

    RazeService manages log ingestion with batching, querying with filters,
    and aggregation for statistics. It coordinates with sink backends for
    actual storage and retrieval.

    Example:
        from raze import RazeService
        from raze.sinks import TimescaleDBSink

        sink = TimescaleDBSink(dsn="postgresql://...")
        service = RazeService(sink=sink)

        # Ingest logs
        await service.ingest([log1, log2, log3])

        # Query logs
        results = await service.query(
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 2),
            level=LogLevel.ERROR,
        )
    """

    def __init__(
        self,
        sink: "RazeSink",
        *,
        batch_size: int = 1000,
        linger_ms: int = 100,
        max_buffer_size: int = 100000,
    ) -> None:
        """Initialize RazeService.

        Args:
            sink: Storage sink for log persistence.
            batch_size: Number of logs per batch before flush.
            linger_ms: Maximum time to wait before flushing (milliseconds).
            max_buffer_size: Maximum buffer size before blocking.
        """
        self._sink = sink
        self._batch_size = batch_size
        self._linger_ms = linger_ms
        self._max_buffer_size = max_buffer_size

        # Batching state
        self._buffer: Deque[LogEvent] = deque(maxlen=max_buffer_size)
        self._lock = threading.Lock()
        self._flush_thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()
        self._last_flush = time.monotonic()

        # Start background flush thread
        self._start_flush_thread()

    def _start_flush_thread(self) -> None:
        """Start the background flush thread."""
        if self._flush_thread is not None and self._flush_thread.is_alive():
            return

        self._shutdown.clear()
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="raze-flush",
        )
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        """Background loop that flushes batches based on size or time."""
        while not self._shutdown.is_set():
            try:
                time.sleep(self._linger_ms / 1000.0)
                self._maybe_flush()
            except Exception:
                # Log flush errors shouldn't crash the thread
                pass

    def _maybe_flush(self, force: bool = False) -> None:
        """Flush buffer if conditions are met.

        Args:
            force: Force flush regardless of size/time conditions.
        """
        with self._lock:
            now = time.monotonic()
            elapsed_ms = (now - self._last_flush) * 1000

            should_flush = (
                force
                or len(self._buffer) >= self._batch_size
                or (len(self._buffer) > 0 and elapsed_ms >= self._linger_ms)
            )

            if not should_flush:
                return

            # Extract batch
            batch = []
            while self._buffer and len(batch) < self._batch_size:
                batch.append(self._buffer.popleft())

            self._last_flush = now

        # Write outside lock
        if batch:
            try:
                self._sink.write_batch(batch)
            except Exception:
                # Best effort - don't lose logs silently in production
                # TODO: Add fallback sink or retry logic
                pass

    def shutdown(self, timeout: float = 5.0) -> None:
        """Shutdown the service, flushing remaining logs.

        Args:
            timeout: Maximum time to wait for flush (seconds).
        """
        self._shutdown.set()
        self._maybe_flush(force=True)

        if self._flush_thread is not None:
            self._flush_thread.join(timeout=timeout)

    def ingest_sync(self, events: List[LogEvent]) -> LogIngestResponse:
        """Synchronously ingest log events into the buffer.

        Args:
            events: List of log events to ingest.

        Returns:
            Response with ingestion results.
        """
        log_ids = []
        errors = []

        with self._lock:
            for event in events:
                if len(self._buffer) >= self._max_buffer_size:
                    errors.append(f"Buffer full, dropped log {event.log_id}")
                    continue
                self._buffer.append(event)
                log_ids.append(event.log_id)

        # Check if we should flush immediately
        if len(self._buffer) >= self._batch_size:
            self._maybe_flush()

        return LogIngestResponse(
            ingested_count=len(log_ids),
            log_ids=log_ids,
            errors=errors,
        )

    async def ingest(self, events: List[LogEvent]) -> LogIngestResponse:
        """Asynchronously ingest log events.

        Args:
            events: List of log events to ingest.

        Returns:
            Response with ingestion results.
        """
        # Use thread pool for sync operations
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.ingest_sync, events)

    async def ingest_request(self, request: LogIngestRequest) -> LogIngestResponse:
        """Ingest logs from a request object.

        Args:
            request: Ingestion request with log event inputs.

        Returns:
            Response with ingestion results.
        """
        events = [log_input.to_log_event() for log_input in request.logs]
        return await self.ingest(events)

    async def query(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        level: Optional[LogLevel] = None,
        levels: Optional[List[LogLevel]] = None,
        service: Optional[str] = None,
        services: Optional[List[str]] = None,
        run_id: Optional[str] = None,
        action_id: Optional[str] = None,
        session_id: Optional[str] = None,
        actor_surface: Optional[str] = None,
        search: Optional[str] = None,
        context_filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
        order: str = "desc",
    ) -> LogQueryResponse:
        """Query logs with filters.

        Args:
            start_time: Start of time range.
            end_time: End of time range.
            level: Minimum log level filter.
            levels: Specific levels filter.
            service: Service name filter.
            services: Multiple service names filter.
            run_id: Run ID filter.
            action_id: Action ID filter.
            session_id: Session ID filter.
            actor_surface: Actor surface filter.
            search: Full-text search query.
            context_filters: JSONB context filters.
            limit: Maximum results.
            offset: Pagination offset.
            order: Sort order ("asc" or "desc").

        Returns:
            Query response with matching logs.
        """
        request = LogQueryRequest(
            start_time=start_time,
            end_time=end_time,
            level=level,
            levels=levels,
            service=service,
            services=services,
            run_id=run_id,
            action_id=action_id,
            session_id=session_id,
            actor_surface=actor_surface,
            search=search,
            context_filters=context_filters,
            limit=limit,
            offset=offset,
            order=order,  # type: ignore
        )
        return await self.query_request(request)

    async def query_request(self, request: LogQueryRequest) -> LogQueryResponse:
        """Execute a query request.

        Args:
            request: Query request object.

        Returns:
            Query response with matching logs.
        """
        start_time = time.monotonic()

        # Delegate to sink
        loop = asyncio.get_event_loop()
        logs, total_count = await loop.run_in_executor(
            None,
            self._sink.query,
            request,
        )

        elapsed_ms = (time.monotonic() - start_time) * 1000

        return LogQueryResponse(
            logs=logs,
            total_count=total_count,
            has_more=total_count > request.offset + len(logs),
            query_time_ms=elapsed_ms,
        )

    async def aggregate(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        group_by: Optional[List[str]] = None,
        level: Optional[LogLevel] = None,
        service: Optional[str] = None,
        interval: Optional[str] = None,
    ) -> LogAggregateResponse:
        """Aggregate log statistics.

        Args:
            start_time: Start of time range.
            end_time: End of time range.
            group_by: Fields to group by.
            level: Minimum log level filter.
            service: Service name filter.
            interval: Time bucket interval.

        Returns:
            Aggregation response with statistics.
        """
        request = LogAggregateRequest(
            start_time=start_time,
            end_time=end_time,
            group_by=group_by or ["level"],
            level=level,
            service=service,
            interval=interval,
        )
        return await self.aggregate_request(request)

    async def aggregate_request(self, request: LogAggregateRequest) -> LogAggregateResponse:
        """Execute an aggregation request.

        Args:
            request: Aggregation request object.

        Returns:
            Aggregation response with statistics.
        """
        start_time = time.monotonic()

        # Delegate to sink
        loop = asyncio.get_event_loop()
        aggregations, total_count = await loop.run_in_executor(
            None,
            self._sink.aggregate,
            request,
        )

        elapsed_ms = (time.monotonic() - start_time) * 1000

        return LogAggregateResponse(
            aggregations=aggregations,
            total_count=total_count,
            query_time_ms=elapsed_ms,
        )

    def flush(self) -> None:
        """Force flush all buffered logs."""
        self._maybe_flush(force=True)

    @property
    def buffer_size(self) -> int:
        """Get current buffer size."""
        with self._lock:
            return len(self._buffer)
