# Raze 🔥

**Structured logging with centralized storage, queryable APIs, and multi-surface support.**

Raze is a production-ready structured logging library that replaces ad-hoc `print()` statements and basic `logging` calls with queryable, centralized logs backed by TimescaleDB hypertables.

## Features

- **Structured Logging** - JSON-formatted logs with automatic context enrichment (run_id, action_id, session_id, actor_surface)
- **Multiple Sinks** - TimescaleDB (hypertable), JSONL files, Kafka, in-memory (tests)
- **REST API** - `/v1/logs/ingest` (batch support), `/v1/logs/query`, `/v1/logs/aggregate`
- **MCP Tools** - `raze.ingest`, `raze.query`, `raze.aggregate` for AI agent integration
- **Multi-Surface** - Backend, CLI, VS Code extension, web console all centralized
- **High Performance** - Async batching (1000 events / 100ms linger), gzip compression
- **Schema Versioning** - Forward-compatible log events with `schema_version` field

## Installation

```bash
# Core package
pip install raze

# With TimescaleDB support
pip install raze[timescale]

# With Kafka support
pip install raze[kafka]

# With FastAPI integration
pip install raze[fastapi]

# Everything
pip install raze[all]
```

## Quick Start

### Basic Usage

```python
from raze import RazeLogger, LogLevel

# Create a logger with automatic context
logger = RazeLogger(
    service="my-service",
    default_context={"environment": "production"}
)

# Log with automatic JSON formatting and context
logger.info("User logged in", user_id="user123", ip="192.168.1.1")
logger.warning("Rate limit approaching", current=95, limit=100)
logger.error("Payment failed", error_code="CARD_DECLINED", amount=99.99)
```

### With TimescaleDB Backend

```python
from raze import RazeLogger, RazeService
from raze.sinks import TimescaleDBSink

# Configure TimescaleDB sink
sink = TimescaleDBSink(
    dsn="postgresql://user:pass@localhost:5432/logs",
    batch_size=1000,
    linger_ms=100,
)

# Create service for queries
service = RazeService(sink=sink)

# Create logger
logger = RazeLogger(service=service, service_name="api-server")

# Log events
logger.info("Request processed", endpoint="/v1/users", latency_ms=45)

# Query logs
results = await service.query(
    start_time="2024-01-01T00:00:00Z",
    end_time="2024-01-02T00:00:00Z",
    level="ERROR",
    service="api-server",
    limit=100,
)
```

### FastAPI Integration

```python
from fastapi import FastAPI
from raze.integrations.fastapi import RazeMiddleware, create_log_routes

app = FastAPI()

# Add request/response logging middleware
app.add_middleware(RazeMiddleware, service_name="my-api")

# Add REST endpoints for log ingestion and queries
app.include_router(create_log_routes(), prefix="/v1/logs")
```

### VS Code Extension / Frontend

```typescript
import { RazeClient } from './RazeClient';

const client = new RazeClient('http://localhost:8080');

// Send logs to centralized backend
await client.sendLog('INFO', 'Extension activated', {
  extension_version: '1.0.0',
  vscode_version: vscode.version,
});

// Batch multiple logs
await client.sendLogs([
  { level: 'DEBUG', message: 'Loading config', context: {} },
  { level: 'INFO', message: 'Config loaded', context: { items: 42 } },
]);
```

## Log Event Schema

```json
{
  "log_id": "550e8400-e29b-41d4-a716-446655440000",
  "schema_version": "v1",
  "timestamp": "2024-01-15T10:30:00.123Z",
  "level": "INFO",
  "service": "api-server",
  "message": "Request processed",
  "run_id": "run-abc123",
  "action_id": "action-xyz789",
  "session_id": "sess-def456",
  "actor_surface": "api",
  "context": {
    "endpoint": "/v1/users",
    "method": "GET",
    "latency_ms": 45,
    "status_code": 200
  }
}
```

## REST API

### POST /v1/logs/ingest

Ingest single or batch logs.

```bash
curl -X POST http://localhost:8080/v1/logs/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "logs": [
      {
        "level": "INFO",
        "message": "User action",
        "service": "web-app",
        "context": {"user_id": "123"}
      }
    ]
  }'
```

### GET /v1/logs/query

Query logs with filters.

```bash
curl "http://localhost:8080/v1/logs/query?\
start_time=2024-01-01T00:00:00Z&\
end_time=2024-01-02T00:00:00Z&\
level=ERROR&\
service=api-server&\
limit=100"
```

### GET /v1/logs/aggregate

Get log statistics.

```bash
curl "http://localhost:8080/v1/logs/aggregate?\
start_time=2024-01-01T00:00:00Z&\
end_time=2024-01-02T00:00:00Z&\
group_by=level,service"
```

## MCP Tools

Raze provides MCP (Model Context Protocol) tools for AI agent integration:

- `raze.ingest` - Write structured logs
- `raze.query` - Query logs with filters
- `raze.aggregate` - Get log statistics

## TimescaleDB Setup

```sql
-- Run the migration
\i migrations/001_create_log_events.sql

-- Or manually create the hypertable
CREATE TABLE log_events (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schema_version TEXT NOT NULL DEFAULT 'v1',
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level TEXT NOT NULL,
    service TEXT NOT NULL,
    message TEXT NOT NULL,
    run_id TEXT,
    action_id TEXT,
    session_id TEXT,
    actor_surface TEXT,
    context JSONB NOT NULL DEFAULT '{}',
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

SELECT create_hypertable('log_events', 'event_timestamp',
    chunk_time_interval => INTERVAL '1 day');
```

## Configuration

Environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `RAZE_DSN` | TimescaleDB connection string | (none) |
| `RAZE_LOG_PATH` | JSONL file path for fallback | `~/.raze/logs.jsonl` |
| `RAZE_BATCH_SIZE` | Events per batch | `1000` |
| `RAZE_LINGER_MS` | Batch linger time | `100` |
| `RAZE_DEFAULT_LEVEL` | Minimum log level | `INFO` |

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome! Please read our [Contributing Guide](CONTRIBUTING.md) first.
