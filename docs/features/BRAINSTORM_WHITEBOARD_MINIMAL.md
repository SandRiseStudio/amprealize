# Bare-minimum LIVE whiteboard for the Brainstorm agent

Run the brainstorm agent's whiteboard **live in the local amprealize UI** without
the full `breakeramp cloud-dev` stack. Two paths: raw local processes (no Podman,
lightest) and a dedicated breakeramp blueprint.

---

## Why this exists / how it works

The whiteboard-sync sidecar (what the browser talks to over WebSocket) loads and
saves canvas state from a **FastAPI API** (`PYTHON_API_BASE`), *not* from Claude's
MCP server. Claude's MCP server is a separate process with its own
`WhiteboardService`. So the agent and the browser only see the same board if both
processes use **one shared backing store**.

```
  Claude Code ── /brainstorm ──► MCP server (host) ─┐
                                                     ├─► shared store (sqlite | postgres)
  Browser ──► web-console ──ws──► sync sidecar ──http──► minimal whiteboard API ─┘
              :5173               :3040                  :8000
```

The store is selected everywhere by one env knob (used by the MCP server, the
minimal API, and the full `amprealize.api`), via `whiteboard.create_storage_from_env()`:

| Var | Values |
|-----|--------|
| `WHITEBOARD_STORAGE_BACKEND` | `memory` \| `sqlite` \| `postgres` |
| `WHITEBOARD_SQLITE_PATH` | sqlite file path (sqlite backend) |
| `WHITEBOARD_PG_DSN` | Postgres DSN (postgres backend) |

### Store profile matrix

| Profile | Backend | Local processes | RAM | Cross-process (live)? | Notes |
|---------|---------|-----------------|-----|-----------------------|-------|
| `memory` | in-process dict | API+sync+web | lowest | **No** | single process only; browser 404s agent rooms — for smoke tests only |
| `sqlite` | shared file (WAL) | API+sync+web | low | **Yes** (host procs) | **best for the raw-process path**; no DB to run |
| `postgres` | local PG container | API+sync+web+db | +~256 MB | **Yes** | good for the blueprint path |
| `neon` | cloud PG (your Neon) | API+sync+web | low | **Yes** | zero local DB; uses `DATABASE_URL` |

> Adding a new backend later: subclass `StorageBackend` in
> `packages/whiteboard/src/whiteboard/storage.py` and register it in
> `create_storage_from_env()` — the one extension point.

---

## Path A — raw processes (no Podman, lightest)

1. Make sure `.mcp.json`'s `amprealize` env uses the **same** store profile you'll
   launch. Default is wired for `sqlite`:
   ```json
   "WHITEBOARD_STORAGE_BACKEND": "sqlite",
   "WHITEBOARD_SQLITE_PATH": "/Users/nick/Main/amprealize/.whiteboard-dev.db",
   "AMPREALIZE_WHITEBOARD_SYNC_URL": "http://localhost:3040"
   ```
2. Start the stack:
   ```bash
   amprealize/scripts/brainstorm-min.sh sqlite     # or: neon | postgres | memory
   ```
   Starts the minimal API (:8000), sync sidecar (:3040), web-console (:5173). It
   prints health + the dev-token one-liner, and tears everything down on Ctrl-C.
   Logs: `/tmp/brainstorm-min-sync.log`, `/tmp/brainstorm-min-web.log`.
3. In Claude Code: `/brainstorm`, opt into the whiteboard. Open the `room_url` it
   returns. If you see a login/empty state, run once in the browser console:
   ```js
   localStorage.setItem('amprealize_token', 'dev');  // any non-empty value
   ```

`neon` profile reads `WHITEBOARD_PG_DSN` (or `DATABASE_URL` / `AMPREALIZE_PG_DSN`)
from the env — run `amprealize context use neon` first, or export the DSN.

---

## Path B — dedicated breakeramp blueprint

Runs only api+sync+web-console (+ optional local Postgres) — no execution-worker,
socket-proxy, telemetry-db, redis, or gateway.

```bash
# Neon / external Postgres (no local DB container):
WHITEBOARD_PG_DSN="$DATABASE_URL" breakeramp up brainstorm-min

# Local Postgres container instead:
WHITEBOARD_STORAGE_BACKEND=postgres breakeramp up brainstorm-min --module db
```

Then point Claude's MCP server at the **same** Postgres: set
`WHITEBOARD_STORAGE_BACKEND=postgres` + `WHITEBOARD_PG_DSN=<same DSN>` in `.mcp.json`.

> Across the host↔container boundary, prefer **postgres/neon**. SQLite sharing
> between the host MCP server and a containerized API over a Podman volume is
> fragile (WAL locking through the Podman VM on macOS) — use Path A for sqlite.

Inspect / tear down:
```bash
breakeramp list ; breakeramp services
breakeramp cleanup            # or: breakeramp stop --env brainstorm-min
```

---

## Ports

| Service | Port | Env |
|---------|------|-----|
| minimal whiteboard API | 8000 | `WHITEBOARD_MIN_API_PORT` / `API_PORT` |
| whiteboard-sync sidecar | 3040 | `SYNC_PORT` |
| web-console (Vite) | 5173 | `WEB_PORT` |
| local Postgres (Path B `db`) | 5432 | `WHITEBOARD_DB_PORT` |

---

## Live agent-push (implemented)

Agent edits appear on the live canvas in real time, not just on refresh:

- The sidecar exposes `POST /reload/whiteboard/{roomId}` — it re-reads the room's
  snapshot from the API and merges the records into the live `TLSocketRoom` via
  `updateStore`, which broadcasts to all connected clients
  ([room-manager.ts](../../packages/whiteboard-sync/src/room-manager.ts) `reloadFromBackend`).
- The MCP whiteboard write-tools ping it best-effort after each write —
  `brainstorm_addidea`/themes (via `BrainstormBridge`) and
  `whiteboard_addshape`/`annotate`/`savecanvas` (via the handlers), using
  `amprealize/services/whiteboard_sync_notify.py`. Requires
  `AMPREALIZE_WHITEBOARD_SYNC_URL` to be set for the MCP server (it is, in `.mcp.json`).
- Records are **merged** (put), so the sidecar's next periodic save preserves the
  agent's writes instead of clobbering them. Invalid records are skipped, never 500.
- If no client is connected yet, reload is a no-op (`active:false`) — the next
  connection loads fresh from the store anyway.

Auth: if `WHITEBOARD_SERVICE_TOKEN` is set, `/reload` requires it as a Bearer token
(the same secret the sidecar uses to call the API). Unset = open, for local dev.

> This also depended on fixing the shape schema: the Python generators emitted
> tldraw v2-era `note`/`text` shapes (`props.text`) and color-less frames, which
> **failed validation in tldraw 4.5.9** — so agent shapes never rendered, even when
> seeded before load. `canvas_ops.py` now emits `props.richText` + `scale`
> (note/text) and a frame `color`, validated against the real 4.5.9 validators.

---

## Troubleshooting

- **Browser canvas empty / 404:** profiles mismatched (`.mcp.json` vs launcher), or
  no dev token set. Confirm `curl localhost:8000/healthz` and that
  `GET localhost:8000/api/v1/whiteboard/rooms/<room_id>` returns 200.
- **`No module named whiteboard` (API):** the API must run from `amprealize/.venv`
  (has fastapi/uvicorn/psycopg2); the launcher already uses it. `import amprealize`
  must precede `import whiteboard` (path setup) — see `scripts/whiteboard_min_api.py`.
- **postgres/neon errors from the MCP server:** the MCP server venv needs `psycopg2`.
  `.mcp.json` points at `amprealize/.venv`, which has it.
