# Run reliability contract (GEP work-item execution)

## Purpose

Define how Amprealize persists **mid-run checkpoints** and applies **outbound reliability policy** (per-tool retries, timeouts, optional circuit breakers) for governed work-item execution, aligned with `RunService` metadata and `ExecutionPolicy` without introducing a second workflow engine.

## Checkpoint payload (`runs.metadata`)

| Key | Type | Description |
| --- | --- | --- |
| `gep_phase_outputs_checkpoint` | `object` | Map of GEP phase name (string) → JSON-serializable phase output dict. Keys use `CyclePhase` values (e.g. `planning`, `executing`). |
| `gep_checkpoint_seq` | `integer` | Monotonic sequence incremented on each committed checkpoint. |
| `gep_checkpoint_cycle_id` | `string` | `cycle_id` the checkpoint belongs to; hydration ignores mismatched cycles. |
| `gep_checkpoint_updated_at` | `string` | RFC3339 timestamp of last checkpoint write. |
| `reliability_circuits` | `object` | Map of `dependency_key` → `{ "failures": int, "open_until": string | null }` for half-open breaker state scoped to this run. |

### Commit boundaries

Checkpoints are committed after:

1. A GEP phase completes successfully and outputs are merged into `phase_outputs`.
2. The terminal `completing` phase produces outputs (before run completion).

Implementations must not store raw secrets or unbounded tool payloads; prefer summaries, artifact IDs, and redacted fields consistent with `TELEMETRY_SCHEMA.md` restricted classes.

## Outbound reliability policy (`ExecutionPolicy.outbound_reliability`)

Serialized inside `runs.metadata.execution_policy` (full policy snapshot on work-item run creation) and optional agent defaults.

| Field | Description |
| --- | --- |
| `default_max_retries` | Max **additional** attempts after the first try for tool transport failures (default `2`). |
| `default_tool_timeout_seconds` | `asyncio.wait_for` budget around the inner tool call (default `120`). |
| `per_tool` | Map of tool name → overrides (`max_retries`, `timeout_seconds`, `circuit_failure_threshold`, `circuit_open_seconds`). |
| `per_dependency_key` | Map of `dependency_key` → same overrides (takes precedence over per-tool when both match). |

### `dependency_key`

Stable key for breaker accounting, typically `tool:{tool_name}` or `host:{hostname}` when a URL host is present in tool arguments.

## Telemetry

See `TELEMETRY_SCHEMA.md` rows: `run.checkpoint_committed`, `tool.retry_exhausted`, `circuit_breaker.opened`, `circuit_breaker.half_open`, `circuit_breaker.closed`.

## API surfaces

- `GET /api/v1/runs/{run_id}/reliability` — checkpoint summary + resolved outbound defaults + circuit snapshot.
- MCP `runs.getReliability` — same payload as REST (parity).
- CLI `amprealize run reliability <run_id>` — JSON or table.

## Related documents

- [`WORK_ITEM_EXECUTION_PLAN.md`](../WORK_ITEM_EXECUTION_PLAN.md) §6.3 Error handling
- [`MCP_SERVER_DESIGN.md`](MCP_SERVER_DESIGN.md) run orchestration
- [`REPRODUCIBILITY_STRATEGY.md`](REPRODUCIBILITY_STRATEGY.md)
