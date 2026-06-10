"""Background export of :class:`TelemetryEvent` to OTLP and optional vendor HTTP endpoints.

Opt-in via ``AMPREALIZE_EXPORT_ENABLED``. Failures are logged and never raise into
callers (same contract as :class:`~amprealize.telemetry.TelemetryClient.emit_event`).
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional

from amprealize.observability_export_config import (
    ObservabilityExportConfig,
    normalize_otlp_grpc_endpoint,
)
from amprealize.telemetry import TelemetryEvent

_logger = logging.getLogger(__name__)

_MAX_ATTR_KEY_LEN = 256
_MAX_ATTR_VAL_LEN = 1024
_MAX_ATTRIBUTES = 96


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def telemetry_event_span_attributes(event: TelemetryEvent) -> Dict[str, str]:
    """Bounded OpenTelemetry-style attributes for a telemetry event."""

    attrs: Dict[str, str] = {}
    attrs["amprealize.event_type"] = _truncate(event.event_type, _MAX_ATTR_VAL_LEN)
    attrs["amprealize.event_id"] = _truncate(event.event_id, _MAX_ATTR_VAL_LEN)
    if event.run_id:
        attrs["amprealize.run_id"] = _truncate(event.run_id, _MAX_ATTR_VAL_LEN)
    if event.session_id:
        attrs["amprealize.session_id"] = _truncate(event.session_id, _MAX_ATTR_VAL_LEN)
    actor = event.actor or {}
    if actor.get("id"):
        attrs["amprealize.actor.id"] = _truncate(str(actor["id"]), _MAX_ATTR_VAL_LEN)
    if actor.get("role"):
        attrs["amprealize.actor.role"] = _truncate(str(actor["role"]), _MAX_ATTR_VAL_LEN)
    if actor.get("surface"):
        attrs["amprealize.actor.surface"] = _truncate(str(actor["surface"]), _MAX_ATTR_VAL_LEN)

    payload = event.payload if isinstance(event.payload, dict) else {}
    eo = payload.get("execution_observability") if isinstance(payload, dict) else None
    if isinstance(eo, dict):
        for key in ("surface", "project_id", "work_item_id", "trace_id", "span_id"):
            if eo.get(key):
                nk = _truncate(f"amprealize.execution_observability.{key}", _MAX_ATTR_KEY_LEN)
                attrs[nk] = _truncate(str(eo[key]), _MAX_ATTR_VAL_LEN)

    # Single JSON blob for deep inspection (truncated)
    try:
        blob = json.dumps(payload, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        blob = "{}"
    attrs["amprealize.payload.json"] = _truncate(blob, 4000)

    if len(attrs) > _MAX_ATTRIBUTES:
        trimmed = dict(list(attrs.items())[:_MAX_ATTRIBUTES])
        trimmed["amprealize.export.truncated_attributes"] = "true"
        return trimmed
    return attrs


class ObservabilityExportRuntime:
    """Thread-backed queue; OTLP + optional Datadog / Langfuse HTTP."""

    def __init__(self, config: ObservabilityExportConfig) -> None:
        self._config = config
        self._queue: "queue.Queue[Optional[TelemetryEvent]]" = queue.Queue(maxsize=50_000)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, name="amprealize-export", daemon=True)
        self._tracer: Any = None
        self._export_count = 0
        self._drop_full = 0
        self._errors = 0
        self._init_otel()

    def _init_otel(self) -> None:
        if not self._config.has_otlp():
            return
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create({"service.name": self._config.otlp_service_name})

            if self._config.otlp_protocol == "grpc":
                try:
                    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                except ImportError as exc:
                    _logger.warning(
                        "OTLP gRPC export disabled: install telemetry extras "
                        "(opentelemetry-exporter-otlp-proto-grpc): %s",
                        exc,
                    )
                    return
                ep = normalize_otlp_grpc_endpoint(self._config.otlp_endpoint)
                if not ep:
                    _logger.warning("OTLP gRPC endpoint invalid or empty after normalization")
                    return
                exporter = OTLPSpanExporter(
                    endpoint=ep,
                    insecure=self._config.otlp_grpc_insecure,
                    headers=self._config.otlp_headers or None,
                )
            else:
                try:
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                except ImportError as exc:
                    _logger.warning(
                        "OTLP HTTP export disabled: install telemetry extras "
                        "(opentelemetry-exporter-otlp-proto-http): %s",
                        exc,
                    )
                    return
                exporter = OTLPSpanExporter(
                    endpoint=self._config.otlp_endpoint,
                    headers=self._config.otlp_headers or None,
                )

            provider = TracerProvider(resource=resource)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            self._tracer = provider.get_tracer("amprealize.telemetry_export")
        except Exception as exc:
            _logger.warning("OTLP export initialization failed: %s", exc)

    def start(self) -> None:
        if self._config.enabled:
            self._thread.start()

    def enqueue(self, event: TelemetryEvent) -> None:
        if not self._config.enabled:
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self._drop_full += 1
            if self._drop_full % 100 == 1:
                _logger.warning(
                    "Telemetry export queue full; dropped events (total drops≈%s)",
                    self._drop_full,
                )

    def shutdown(self, timeout: float = 5.0) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=timeout)

    def stats(self) -> Dict[str, Any]:
        return {
            "export_dispatched": self._export_count,
            "queue_full_drops": self._drop_full,
            "export_errors": self._errors,
        }

    def _run_loop(self) -> None:
        batch: List[TelemetryEvent] = []
        deadline = time.monotonic() + self._config.flush_interval_sec
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                item = self._queue.get(timeout=min(remaining, 1.0) if remaining > 0 else 0.05)
            except queue.Empty:
                item = "__idle__"

            if item == "__idle__":
                if batch:
                    self._flush_batch(batch)
                    batch = []
                deadline = time.monotonic() + self._config.flush_interval_sec
                if self._stop.is_set():
                    break
                continue

            if item is None:
                if batch:
                    self._flush_batch(batch)
                    batch = []
                break

            batch.append(item)
            if len(batch) >= self._config.batch_max_events:
                self._flush_batch(batch)
                batch = []
                deadline = time.monotonic() + self._config.flush_interval_sec

    def _flush_batch(self, batch: List[TelemetryEvent]) -> None:
        for event in batch:
            try:
                self._export_one(event)
                self._export_count += 1
            except Exception as exc:
                self._errors += 1
                _logger.debug("Telemetry export failed for %s: %s", event.event_type, exc)

    def _export_one(self, event: TelemetryEvent) -> None:
        if self._tracer:
            self._export_otlp_span(event)
        if self._config.has_datadog_http():
            self._export_datadog_logs_http(event)
        if self._config.has_langfuse_http():
            self._export_langfuse_observation_http(event)

    def _export_otlp_span(self, event: TelemetryEvent) -> None:
        """Emit one span per telemetry event; correlation stays in attributes."""

        assert self._tracer is not None
        attrs = telemetry_event_span_attributes(event)
        with self._tracer.start_as_current_span(event.event_type, attributes=attrs):
            pass

    def _export_datadog_logs_http(self, event: TelemetryEvent) -> None:
        import httpx

        url = self._config.datadog_logs_intake_url
        key = self._config.datadog_api_key
        if not url or not key:
            return
        body = [
            {
                "message": json.dumps(event.to_dict(), default=str, ensure_ascii=False),
                "ddsource": "amprealize",
                "service": self._config.otlp_service_name,
                "status": "info",
            }
        ]
        headers = {"DD-API-KEY": key, "Content-Type": "application/json"}
        resp = httpx.post(url, json=body, headers=headers, timeout=10.0)
        resp.raise_for_status()

    def _export_langfuse_observation_http(self, event: TelemetryEvent) -> None:
        """Best-effort Langfuse public ingestion (batch trace format subset)."""

        import base64

        import httpx

        host = self._config.langfuse_host
        pk = self._config.langfuse_public_key
        sk = self._config.langfuse_secret_key
        if not host or not pk or not sk:
            return
        auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()
        url = f"{host}/api/public/ingestion"
        # Langfuse batch API expects specific schema; send minimal span-like observation
        payload = {
            "batch": [
                {
                    "type": "span-create",
                    "body": {
                        "name": event.event_type,
                        "startTime": event.timestamp,
                        "metadata": {"event_id": event.event_id, "source": "amprealize.export"},
                    },
                }
            ]
        }
        headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        }
        resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
        if resp.status_code >= 400:
            _logger.debug(
                "Langfuse export HTTP %s for %s: %s",
                resp.status_code,
                event.event_type,
                resp.text[:500],
            )


_GLOBAL_RUNTIME: Optional[ObservabilityExportRuntime] = None
_GLOBAL_LOCK = threading.Lock()


def get_or_create_export_runtime(config: ObservabilityExportConfig) -> Optional[ObservabilityExportRuntime]:
    """Singleton runtime when export is enabled."""

    global _GLOBAL_RUNTIME
    if not config.enabled:
        return None
    with _GLOBAL_LOCK:
        if _GLOBAL_RUNTIME is None:
            _GLOBAL_RUNTIME = ObservabilityExportRuntime(config)
            _GLOBAL_RUNTIME.start()
        return _GLOBAL_RUNTIME


def reset_export_runtime_for_tests() -> None:
    """Clear singleton (tests only)."""

    global _GLOBAL_RUNTIME
    with _GLOBAL_LOCK:
        if _GLOBAL_RUNTIME is not None:
            _GLOBAL_RUNTIME.shutdown(timeout=0.5)
            _GLOBAL_RUNTIME = None


__all__ = [
    "ObservabilityExportRuntime",
    "get_or_create_export_runtime",
    "reset_export_runtime_for_tests",
    "telemetry_event_span_attributes",
]
