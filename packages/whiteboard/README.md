# Whiteboard

Real-time collaborative whiteboard service with tldraw sync, room lifecycle management, and canvas persistence.

## Installation

```bash
pip install whiteboard
# Or with extras:
pip install whiteboard[fastapi]
pip install whiteboard[postgres]
pip install whiteboard[all]
```

## Quick Start

```python
from whiteboard import WhiteboardService, RoomCreateRequest

service = WhiteboardService()
room = service.create_room(RoomCreateRequest(
    session_id="brainstorm-session-123",
    title="Architecture Brainstorm",
    created_by="user@example.com",
))
print(f"Room URL: {room.url}")
```

## Architecture

- **Zero amprealize core deps** — standalone package with hook architecture
- **Room lifecycle**: create → active → closed
- **Canvas persistence**: In-memory, SQLite, or Postgres storage backends
- **tldraw sync**: WebSocket multiplayer via `@tldraw/sync` (Node.js sidecar or Cloudflare Durable Object)
- **Snapshot export**: PNG and JSON export from canvas state
- **Edition routing**: `WHITEBOARD_STORAGE_BACKEND` selects backend; enterprise deployments use Cloudflare DO

## Storage Backends

The whiteboard package supports three storage backends, selected via environment variables.

### InMemoryStorage (default)

No configuration needed. Suitable for tests and ephemeral demos.

```python
from whiteboard import InMemoryStorage, WhiteboardService

service = WhiteboardService(storage=InMemoryStorage())
```

### SqliteStorageBackend

Single-node local development. Data persists across restarts.

```bash
WHITEBOARD_STORAGE_BACKEND=sqlite
WHITEBOARD_SQLITE_PATH=/data/whiteboard.db   # default: whiteboard.db in CWD
```

```python
from whiteboard import SqliteStorageBackend, WhiteboardService

service = WhiteboardService(storage=SqliteStorageBackend(db_path="/data/whiteboard.db"))
```

### PostgresStorageBackend

Production multi-node deployments.

```bash
WHITEBOARD_STORAGE_BACKEND=postgres
WHITEBOARD_PG_DSN=postgresql://<user>:<password>@<host>:5432/<database>
```

```python
from whiteboard import PostgresStorageBackend, WhiteboardService

storage = PostgresStorageBackend(dsn="postgresql://...")
storage.ensure_schema_ready()   # idempotent schema migration
service = WhiteboardService(storage=storage)
```

### Factory: create_storage_from_env

Reads `WHITEBOARD_STORAGE_BACKEND` and the appropriate DSN/path env vars, and returns the correct backend. This is the recommended entry point for `api.py` and service startup.

```python
from whiteboard import create_storage_from_env, WhiteboardService

storage = create_storage_from_env()   # reads env vars
service = WhiteboardService(storage=storage)
```

| `WHITEBOARD_STORAGE_BACKEND` | Backend | Required additional env |
|---|---|---|
| `memory` (default) | `InMemoryStorage` | — |
| `sqlite` | `SqliteStorageBackend` | `WHITEBOARD_SQLITE_PATH` (optional) |
| `postgres` | `PostgresStorageBackend` | `WHITEBOARD_PG_DSN` |

## WebSocket Sync Architecture

The `whiteboard` Python package handles room lifecycle and canvas snapshot storage. Live WebSocket multiplayer is handled by a separate sidecar.

### OSS — Local sidecar (`packages/whiteboard-sync-core`)

- Node.js process, runs alongside the Python API
- `LocalSyncBackend` from `@amprealize/whiteboard-sync-core`
- BreakerAmp env vars (see `local-dev.yaml` `whiteboard-sync` service):

```bash
WHITEBOARD_STORAGE_BACKEND=sqlite         # or memory
WHITEBOARD_SQLITE_PATH=/data/whiteboard.db
WHITEBOARD_PG_DSN=                        # optional, overrides BACKEND=postgres
WHITEBOARD_SERVICE_TOKEN=                 # auth token for Python API calls
SYNC_PORT=4300
PYTHON_API_BASE=http://amprealize:8000
```

### Enterprise — Cloudflare Durable Objects (`packages/whiteboard-do`)

- `@amprealize/whiteboard-do` CF Worker, one DO instance per room
- Snapshot persistence via DO storage + best-effort Python API back-sync
- Deployed via `wrangler deploy` (see `packages/whiteboard-do/wrangler.toml`)

## Integration

Use hooks to wire into ActionService, ComplianceService, or any external system:

```python
from whiteboard import WhiteboardService, WhiteboardHooks

class MyHooks(WhiteboardHooks):
    def on_room_created(self, room):
        print(f"Room created: {room.id}")

    def on_room_closed(self, room):
        print(f"Room closed: {room.id}")

service = WhiteboardService(hooks=MyHooks())
```

## License

Apache-2.0
