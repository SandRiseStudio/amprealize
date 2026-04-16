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
- **Canvas persistence**: SQLite, Postgres, Neon storage adapters
- **tldraw sync**: WebSocket multiplayer via `@tldraw/sync` (Node.js sidecar)
- **Snapshot export**: PNG and JSON export from canvas state

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
