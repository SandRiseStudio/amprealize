# Optional OTLP and vendor telemetry export (GUIDEAI-1195)

## Purpose

When enabled, the platform **asynchronously** forwards a copy of each `TelemetryEvent` to:

- **OTLP/HTTP or OTLP/gRPC (traces)** — protocol via `AMPREALIZE_OTLP_PROTOCOL` (`http` default, `grpc` for typical collector port **4317**). One span per event; correlation fields in span attributes.
- **Optional: Datadog Logs HTTP** — JSON array POST to a configurable intake URL.
- **Optional: Langfuse** — best-effort `POST /api/public/ingestion` (schema may change; failures are logged at debug level, not raised).

Primary persistence (Postgres, JSONL, or null sink) is unchanged. Install OTLP support with the **`telemetry`** extra: `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, and `opentelemetry-exporter-otlp-proto-grpc` (install remains one extra; gRPC is used only when `AMPREALIZE_OTLP_PROTOCOL=grpc`).

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `AMPREALIZE_EXPORT_ENABLED` | `false` | Set `true` to start the background export thread and wrap `create_sink_from_env` with `ObservabilityExportForwardingSink` when a non-null primary sink is used. |
| `AMPREALIZE_OTLP_PROTOCOL` | `http` | `http` or `grpc`. |
| `AMPREALIZE_OTLP_ENDPOINT` | (empty) | **HTTP:** full traces URL (e.g. `http://localhost:4318/v1/traces`). **gRPC:** `host:port` or URL; normalized to `host:port` (default port **4317** if omitted in a URL). |
| `AMPREALIZE_OTLP_GRPC_INSECURE` | `true` | gRPC only: plaintext vs TLS (`false` for encrypted backends). |
| `AMPREALIZE_OTLP_HEADERS` | (empty) | JSON object or `k=v,k2=v2` for exporter headers (auth). |
| `AMPREALIZE_OTLP_SERVICE_NAME` | `amprealize` | `service.name` resource attribute. |
| `AMPREALIZE_EXPORT_BATCH_MAX` | `50` | Max events per worker batch before flush. |
| `AMPREALIZE_EXPORT_FLUSH_INTERVAL_SEC` | `2.0` | Worker idle timeout (seconds) to flush a partial batch. |
| `AMPREALIZE_EXPORT_DATADOG_LOGS_URL` | (empty) | Datadog logs HTTP intake URL. |
| `AMPREALIZE_DATADOG_API_KEY` | (empty) | `DD-API-KEY` header for Datadog. |
| `AMPREALIZE_LANGFUSE_HOST` | (empty) | Langfuse base URL, no trailing slash. |
| `AMPREALIZE_LANGFUSE_PUBLIC_KEY` | (empty) | Basic auth (with secret). |
| `AMPREALIZE_LANGFUSE_SECRET_KEY` | (empty) | Basic auth (with public). |

`AMPREALIZE_TELEMETRY_ENABLED=false` still returns `NullTelemetrySink` with **no** export wrapper (no events are emitted).

## OpenTelemetry Collector (local)

Example `receivers` + `exporters` for OTLP HTTP on port **4318** (gRPC is often 4317). Point `AMPREALIZE_OTLP_ENDPOINT` at `http://127.0.0.1:4318/v1/traces` for HTTP, or set `AMPREALIZE_OTLP_PROTOCOL=grpc` and `AMPREALIZE_OTLP_ENDPOINT=127.0.0.1:4317` for gRPC.

### HTTP receiver (4318)

```yaml
# otel-collector-minimal.yaml — run with:
#   docker run -p 4318:4318 -v $(pwd)/otel-collector-minimal.yaml:/etc/otelcol/config.yaml \
#     otel/opentelemetry-collector-contrib:latest --config=/etc/otelcol/config.yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

exporters:
  debug:
    verbosity: detailed

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [debug]
```

### gRPC receiver (4317)

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

exporters:
  debug:
    verbosity: detailed

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [debug]
```

Run with `-p 4317:4317`. Match Amprealize with `AMPREALIZE_OTLP_PROTOCOL=grpc` and `AMPREALIZE_OTLP_ENDPOINT=127.0.0.1:4317`.

## Code references

- `amprealize/observability_export_config.py` — `ObservabilityExportConfig.from_env()`
- `amprealize/observability_export_runtime.py` — queue, OTLP span export, optional HTTP
- `amprealize/telemetry.py` — `ObservabilityExportForwardingSink`, `create_sink_from_env()`

## Failure behavior

Export errors are **never** raised to `TelemetryClient.emit_event` callers; they are counted and logged at debug level (see `ObservabilityExportRuntime.stats()`).
