"""Kafka sink for log streaming."""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Optional, Tuple

from raze.models import (
    LogAggregateRequest,
    LogAggregation,
    LogEvent,
    LogQueryRequest,
)
from raze.sinks.base import RazeSink


class KafkaSink(RazeSink):
    """Kafka sink for streaming logs to a topic.

    This sink publishes logs to Kafka for real-time streaming pipelines.
    Note that query and aggregate operations are not supported - use a
    separate consumer to populate a queryable store.

    Requires kafka-python: pip install raze[kafka]

    Example:
        sink = KafkaSink(
            bootstrap_servers="localhost:9092",
            topic="logs.events",
        )
        service = RazeService(sink=sink)
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str = "raze.logs",
        *,
        batch_size: int = 1000,
        linger_ms: int = 100,
        compression_type: str = "gzip",
        max_retries: int = 3,
    ) -> None:
        """Initialize Kafka sink.

        Args:
            bootstrap_servers: Kafka broker addresses.
            topic: Topic to publish logs to.
            batch_size: Batch size for producer.
            linger_ms: Linger time before sending batch.
            compression_type: Compression algorithm (gzip, snappy, lz4).
            max_retries: Maximum retries on failure.
        """
        try:
            from kafka import KafkaProducer
        except ImportError as e:
            raise RuntimeError(
                "kafka-python not installed. Install with: pip install raze[kafka]"
            ) from e

        self._topic = topic
        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers.split(","),
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            batch_size=batch_size * 1024,
            linger_ms=linger_ms,
            compression_type=compression_type,
            max_in_flight_requests_per_connection=5,
            retries=max_retries,
            acks="all",
            enable_idempotence=True,
            max_request_size=1048576,
            buffer_memory=33554432,
        )

    def write(self, event: LogEvent) -> None:
        """Write a single log event."""
        self._producer.send(self._topic, value=event.to_dict())

    def write_batch(self, events: List[LogEvent]) -> None:
        """Write a batch of log events."""
        for event in events:
            self._producer.send(self._topic, value=event.to_dict())

    def flush(self) -> None:
        """Flush buffered events."""
        self._producer.flush()

    def close(self) -> None:
        """Close the producer."""
        self._producer.flush()
        self._producer.close()

    def query(self, request: LogQueryRequest) -> Tuple[List[LogEvent], int]:
        """Query is not supported for Kafka sink.

        Kafka is a streaming sink - use a consumer to populate a
        queryable store like TimescaleDB.
        """
        raise NotImplementedError(
            "Query not supported for Kafka sink. "
            "Use a consumer to populate a queryable store."
        )

    def aggregate(self, request: LogAggregateRequest) -> Tuple[List[LogAggregation], int]:
        """Aggregation is not supported for Kafka sink."""
        raise NotImplementedError(
            "Aggregation not supported for Kafka sink. "
            "Use a consumer to populate a queryable store."
        )
