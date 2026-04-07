# ActionService Contract

## Purpose
Standardize how actions are recorded, retrieved, and replayed across Platform UI, REST API, CLI, and MCP tools, ensuring parity and reproducibility of all build steps (see `REPRODUCIBILITY_STRATEGY.md`).

## Services & Endpoints
- **gRPC Service:** `amprealize.action.v1.ActionService`
- **REST Base Path:** `/v1/actions`
- **MCP Tools:** `actions.create`, `actions.list`, `actions.get`, `actions.replay`, `actions.replayStatus`

## Schemas (JSON / Proto)
### `Action`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `action_id` | UUID | Yes | Primary identifier. |
| `timestamp` | RFC3339 | Yes | Time of action submission. |
| `actor` | Object | Yes | `{ id: UUID, role: enum, surface: enum }`. |
| `artifact_path` | string | Yes | Path/URI impacted. |
| `summary` | string | Yes | ≤ 160 chars, human readable. |
| `behaviors_cited` | string[] | Yes | Behavior IDs referenced. |
| `metadata` | object | No | Command list, validation outputs, links. |
| `related_run_id` | UUID | No | RunService association. |
| `audit_log_event_id` | UUID | No | Link to audit log entry (`AUDIT_LOG_STORAGE.md`). |
| `checksum` | string | Yes | SHA-256 of resulting artifact (if applicable). |
| `replay_status` | enum | Yes | `NOT_STARTED|QUEUED|RUNNING|SUCCEEDED|FAILED`. |

### `ActionCreateRequest`
- `artifact_path` (string)
- `summary` (string)
- `behaviors_cited` (string[])
- `metadata` (object)
- `related_run_id` (UUID optional)
- `checksum` (string optional; server calculates if omitted)

### `ReplayRequest`
- `action_ids` (UUID[])
- `strategy` (`SEQUENTIAL|PARALLEL`)
- `options.skip_existing` (bool)
- `options.dry_run` (bool)

### `ReplayStatus`
- `replay_id` (UUID)
- `status` (enum)
- `progress` (0-1)
- `logs` (string[] URIs to audit log payloads)
- `failed_action_ids` (UUID[])

## RBAC Scopes
| Scope | Description | Default Roles |
| --- | --- | --- |
| `action.read` | List and fetch actions created by same org/team. | Strategist, Teacher, Student, Admin |
| `action.write` | Record new actions. | Strategist, Teacher, Student |
| `action.replay` | Launch replay jobs. | Strategist, Admin |
| `action.admin` | Cancel replay, purge failed jobs, manage retention. | Admin |

Requests must include AgentAuth-issued OAuth scopes; CLI obtains tokens via device flow (see `SECRETS_MANAGEMENT_PLAN.md`) and tool adapters call `auth.ensureGrant` prior to invoking ActionService endpoints. Legacy PAT support remains for migration-only scenarios and is gated to read-only scope.

## Audit & Compliance Integration
- Every `actions.create` call writes an audit event (link stored in `audit_log_event_id`).
- Replay jobs produce immutable logs persisted per `AUDIT_LOG_STORAGE.md`.
- Schema version changes require update to `schema/action/v1/*.json` and an entry in `PRD_ALIGNMENT_LOG.md`.

## Parity Requirements
- CLI commands (`amprealize record-action`, `amprealize list-actions`, `amprealize replay`) call these endpoints directly via shared SDK.
- Platform UI uses the same REST endpoints; feature toggles gate UI until API parity tests pass.
- MCP tool definitions auto-generated from proto; IDE extension consumes `actions.list` for timeline view.
- Contract tests compare responses across surfaces (CLI vs REST vs MCP) using golden fixtures stored under `tests/contracts/actions/`.

## AgentAuth Phase A Dependencies
- `proto/agentauth/v1/agent_auth.proto` will expose `EnsureGrant`, `RevokeGrant`, `ListGrants`, and `PolicyPreview` RPCs used to authorize ActionService calls; SDKs must request tokens prior to invoking `actions.*` endpoints.
- REST mirror schemas under `schema/agentauth/v1/*.json` provide OpenAPI documentation for auth flows referenced by ActionService clients.
- Scope catalog (`schema/agentauth/scope_catalog.yaml`) defines required `action.*` scopes and maps them to Strategist/Teacher/Student/Admin roles.
- MCP tool specifications (`auth.ensureGrant`, `auth.revoke`, `auth.listGrants`) ship alongside ActionService tool definitions to guarantee CLI/IDE parity during Milestone 1.
- ActionService telemetry must include `auth_grant_id` from AgentAuthService to satisfy audit linkage requirements in `AUDIT_LOG_STORAGE.md`.

## Replay Engine Behavior
1. Fetch actions in requested order.
2. For each action:
   - Verify artifact checksum (if present); skip if `skip_existing` true and checksum matches.
   - Rehydrate commands/metadata to reproduce outputs (e.g., regenerate docs, run scripts).
   - Record success/failure plus new `action_id` for replay if state diverges.
3. Emit telemetry events (`action_replay_start`, `action_replay_complete`).
4. Update `replay_status` for each action; persist overall job status.

## Error Handling
- Validation errors return HTTP 400 / gRPC INVALID_ARGUMENT with details.
- Replay failures produce structured error log referencing failing action, root cause, remediation (if available).
- Idempotency keys supported on create endpoint via `Idempotency-Key` header.

## Implementation Tasks (Milestone 0)
- Generate proto + JSON schemas and publish under `schema/action/v1/`.
- Scaffold service handlers (gRPC + REST gateway) returning stub responses (`amprealize/action_service.py`, `amprealize/adapters.py`).
- Add contract tests ensuring CLI/REST parity for create/list (`tests/test_action_service_parity.py`).
- Integrate audit logging hooks and telemetry emission.

Future enhancements tracked in `PRD_NEXT_STEPS.md` (Milestone 1+).
