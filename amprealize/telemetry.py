"""Minimal telemetry client and event structures used across amprealize stubs.

The telemetry implementation aligns with the envelope described in
`docs/contracts/TELEMETRY_SCHEMA.md` while remaining lightweight for unit tests. Surfaces emit
structured events that can be inspected via in-memory sinks during tests or
forwarded to real backends in future implementations.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from amprealize.surfaces import normalize_actor_surface


class TelemetrySink(Protocol):
    """Protocol describing telemetry sinks."""

    def write(self, event: "TelemetryEvent") -> None:  # pragma: no cover - interface only
        ...


@dataclass(frozen=True)
class TelemetryEvent:
    """Telemetry envelope matching the documented schema."""

    event_id: str
    timestamp: str
    event_type: str
    actor: Dict[str, str]
    run_id: Optional[str]
    action_id: Optional[str]
    session_id: Optional[str]
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of the event."""

        return asdict(self)


class NullTelemetrySink:
    """Sink that silently ignores events."""

    def write(self, event: TelemetryEvent) -> None:  # pragma: no cover - intentionally no-op
        return None


class InMemoryTelemetrySink:
    """Sink that accumulates telemetry events for inspection in tests."""

    def __init__(self) -> None:
        self.events: List[TelemetryEvent] = []

    def write(self, event: TelemetryEvent) -> None:
        self.events.append(event)


class FileTelemetrySink:
    """Append-only sink that persists telemetry events to a JSONL file."""

    def __init__(self, path: Path) -> None:
        self._path = path.expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: TelemetryEvent) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")


class KafkaTelemetrySink:
    """Sink that publishes telemetry events to a Kafka topic with production-grade batching.

    Implements high-volume ingestion optimizations:
    - Async batching: Accumulates 1000 events or 100ms linger time
    - Compression: gzip compression (3-5x reduction)
    - Retries: Exponential backoff with max 3 retries
    - Idempotence: Exactly-once semantics when supported by broker
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str = "telemetry.events",
        batch_size: int = 1000,
        linger_ms: int = 100,
        compression_type: str = "gzip",
        max_retries: int = 3,
    ) -> None:
        try:
            from kafka import KafkaProducer
        except ImportError:
            raise RuntimeError(
                "kafka-python not installed. Install with: pip install kafka-python"
            )

        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers.split(","),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            # Batching configuration for high throughput
            batch_size=batch_size * 1024,  # Convert to bytes (1000 events ~= 1MB)
            linger_ms=linger_ms,
            # Compression for reduced network overhead
            compression_type=compression_type,
            # Reliability configuration
            max_in_flight_requests_per_connection=5,
            retries=max_retries,
            acks="all",  # Wait for all in-sync replicas
            enable_idempotence=True,  # Exactly-once semantics
            # Connection pooling
            max_request_size=1048576,  # 1MB max message size
            buffer_memory=33554432,  # 32MB buffer
        )
        self._topic = topic

    def write(self, event: TelemetryEvent) -> None:
        """Send event asynchronously with batching (non-blocking)."""
        self._producer.send(self._topic, value=event.to_dict())
        # Note: flush() removed for async batching - producer auto-flushes per linger_ms

    def flush(self) -> None:
        """Explicitly flush any buffered events (useful at shutdown)."""
        self._producer.flush()

    def close(self) -> None:
        """Close producer and flush remaining events."""
        self._producer.flush()
        self._producer.close()


def create_sink_from_env(*, default_path: Optional[Path] = None) -> TelemetrySink:
    """Create a telemetry sink using the standard environment configuration.

    Environment variables:

    ``AMPREALIZE_TELEMETRY_ENABLED``
        When set to ``false`` (case-insensitive), returns a :class:`NullTelemetrySink`
        that silently discards all events.  Useful for cloud-dev where no telemetry
        database is available.

    ``AMPREALIZE_TELEMETRY_PG_DSN``
        When set, a :class:`PostgresTelemetrySink` will be created using the
        provided DSN.  Optionally accepts ``AMPREALIZE_TELEMETRY_PG_TIMEOUT`` to
        override the connection timeout (seconds).

    ``AMPREALIZE_TELEMETRY_PATH``
        When Postgres is not configured, falls back to a JSONL file sink.  This
        variable overrides the default location used by :class:`FileTelemetrySink`.
    """

    if os.environ.get("AMPREALIZE_TELEMETRY_ENABLED", "true").lower() == "false":
        return NullTelemetrySink()

    default_path = default_path or Path.home() / ".amprealize" / "telemetry" / "events.jsonl"

    dsn = os.environ.get("AMPREALIZE_TELEMETRY_PG_DSN")
    if dsn:
        timeout_raw = os.environ.get("AMPREALIZE_TELEMETRY_PG_TIMEOUT")
        kwargs: Dict[str, Any] = {}
        if timeout_raw:
            try:
                kwargs["connect_timeout"] = int(timeout_raw)
            except ValueError as exc:
                raise ValueError("AMPREALIZE_TELEMETRY_PG_TIMEOUT must be an integer") from exc

        from amprealize.storage.postgres_telemetry import PostgresTelemetrySink

        try:
            return PostgresTelemetrySink(dsn, **kwargs)
        except RuntimeError as exc:
            raise RuntimeError(
                "Failed to initialise Postgres telemetry sink. Install psycopg2 and "
                "validate the connection string."
            ) from exc

    path_override = os.environ.get("AMPREALIZE_TELEMETRY_PATH")
    sink_path = Path(path_override) if path_override else default_path
    sink_path.parent.mkdir(parents=True, exist_ok=True)
    return FileTelemetrySink(sink_path)


class TelemetryClient:
    """Simple telemetry emitter supporting pluggable sinks."""

    _DEFAULT_ACTOR = {"id": "system", "role": "SYSTEM", "surface": "api"}

    def __init__(
        self,
        sink: Optional[TelemetrySink] = None,
        default_actor: Optional[Dict[str, str]] = None,
    ) -> None:
        self._sink: TelemetrySink = sink or NullTelemetrySink()
        actor_template = (
            dict(default_actor) if default_actor else dict(self._DEFAULT_ACTOR)
        )
        actor_template["surface"] = normalize_actor_surface(
            actor_template.get("surface")
        )
        self._default_actor = actor_template

    @classmethod
    def noop(cls) -> "TelemetryClient":
        """Return a telemetry client that discards all events."""

        return cls()

    def emit_event(
        self,
        *,
        event_type: str,
        payload: Dict[str, Any],
        actor: Optional[Dict[str, str]] = None,
        run_id: Optional[str] = None,
        action_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> TelemetryEvent:
        """Emit a telemetry event to the configured sink."""

        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        actor_payload = dict(actor) if actor else dict(self._default_actor)
        actor_payload["surface"] = normalize_actor_surface(actor_payload.get("surface"))

        event = TelemetryEvent(
            event_id=str(uuid.uuid4()),
            timestamp=timestamp,
            event_type=event_type,
            actor=actor_payload,
            run_id=run_id,
            action_id=action_id,
            session_id=session_id,
            payload=dict(payload),
        )
        try:
            self._sink.write(event)
        except Exception as exc:
            # Telemetry failures should never crash the main request
            # Log and continue - data can be recovered from other sources
            import logging
            logging.getLogger(__name__).warning(
                f"Telemetry write failed (event_type={event_type}): {exc}"
            )
        return event


from amprealize.telemetry_events import TelemetryEventType  # noqa: E402 – late import to avoid circular deps

__all__ = [
    "TelemetrySink",
    "TelemetryEvent",
    "NullTelemetrySink",
    "InMemoryTelemetrySink",
    "FileTelemetrySink",
    "KafkaTelemetrySink",
    "create_sink_from_env",
    "TelemetryClient",
    "TelemetryEventType",
]
