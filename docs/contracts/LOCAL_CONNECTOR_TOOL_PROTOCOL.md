# Local connector tool delegation protocol

Version: **1**

Hybrid execution keeps `AgentExecutionLoop` on the Amprealize API/worker process while filesystem and bounded shell tools run on the user’s machine via the paired **local connector daemon** (outbound WebSocket).

## Transport

- Same WebSocket as today: `GET /api/v1/execution-connector/ws?device_token=…`
- Server → daemon: JSON messages sent with `WebSocket.send_json` (Starlette/FastAPI).
- Daemon → server: JSON messages received by the daemon client; the API routes them through `apply_connector_daemon_message` or hub RPC resolvers.

All delegated-tool messages include `protocol_version: 1`.

## Lifecycle

1. **`run_lease`** (server → daemon): Existing lease payload (`run_id`, `cycle_id`, `work_item_id`, …).
2. **`run.lease_ack`** (daemon → server): Daemon claimed the lease and is ready for `tool.invoke`. Server waits on this before starting `AgentExecutionLoop`.
3. **`tool.invoke`** (server → daemon): Execute one tool with arguments (bounded by daemon env limits).
4. **`tool.result`** (daemon → server): Success or failure for that invoke; correlates with `invoke_id`.
5. **`run.connector_release`** (server → daemon): Delegation for this run is finished; daemon should leave the lease loop (success or cancel).
6. **`run.cancel_requested`** / **`run.progress`** / **`run.complete`** / **`run.fail`**: Unchanged semantics where applicable. For hybrid execution the platform completes the run via `RunService` after the loop; the daemon should **not** send `run.complete` for successful hybrid runs unless explicitly requested later.

## `tool.invoke` (server → daemon)

```json
{
  "type": "tool.invoke",
  "protocol_version": 1,
  "invoke_id": "uuid",
  "run_id": "run-…",
  "tool_name": "read_file",
  "tool_args": {}
}
```

## `tool.result` (daemon → server)

```json
{
  "type": "tool.result",
  "protocol_version": 1,
  "invoke_id": "uuid",
  "run_id": "run-…",
  "ok": true,
  "output": "string payload for LLM (tool result text)",
  "error": null
}
```

On failure:

```json
{
  "type": "tool.result",
  "protocol_version": 1,
  "invoke_id": "uuid",
  "run_id": "run-…",
  "ok": false,
  "output": "",
  "error": "human-readable error"
}
```

## Cancellation

- If the run is cancelled on the server, existing **`run.cancel_requested`** is sent to the daemon.
- The daemon should abort any in-flight shell/tool, respond to pending invokes with `ok: false`, and exit the lease loop.

## Supported tools (v1)

Daemon implements a bounded subset aligned with `ToolExecutor` naming:

| `tool_name` | Notes |
|-------------|--------|
| `read_file` | Args: `path`, optional `start_line`, `end_line` |
| `write_file` | Args: `path`, `content` |
| `edit_file` | Args: `path`, `old_string`, `new_string` (single occurrence replace) |
| `list_dir` | Args: `path` (default `.`) |
| `run_in_terminal` | Args: `command`, optional `cwd` |

Other tools continue to execute on the server (e.g. GitHub API fallbacks, resource analysis) when permitted by policy.

## Connectivity probe (no `run_lease`)

For **REST/MCP connection checks** (`GET .../connection-status?depth=invoke`, `executionConnector.verifyConnection`), the server may send **`tool.invoke`** with a fixed sentinel **`run_id`** equal to **`__amprealize_connector_probe__`** (constant `CONNECTOR_PROBE_RUN_ID` in `local_execution_connector_hub.py`). The daemon handles this **outside** the hybrid lease loop: it runs the delegated tool (typically **`list_dir`** with `path: "."`) and returns **`tool.result`** the same way as under a lease. This verifies the full hub ↔ daemon tool path without starting a run.

## Queue dispatch

`execution_workspace_kind=local_connector` with **hybrid delegation** is intended for **API `background` dispatch** where the loop runs in-process and can await hub futures. **`queue` dispatch** does not run the hybrid loop in the worker; starting `local_connector` runs while `dispatch_mode=queue` raises a clear configuration error (see `ExecutionGateway`).
