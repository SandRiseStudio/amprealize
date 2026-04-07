# BehaviorService Contract

## Purpose
Provide CRUD, governance, and retrieval contracts for the behavior handbook so Strategist → Teacher → Student workflows can discover, draft, approve, and reuse behaviors. The service exposes consistent APIs across Platform UI, REST API, CLI, and MCP tools, and persists behavior data in a **PostgreSQL (production) / SQLite (local)** backend with a companion vector index (FAISS/Qdrant) for semantic search. This contract builds on the versioning model in `docs/BEHAVIOR_VERSIONING.md` and the parity expectations defined in `MCP_SERVER_DESIGN.md`.

## Services & Endpoints
- **gRPC Service:** `amprealize.behavior.v1.BehaviorService`
- **REST Base Path:** `/v1/behaviors`
- **MCP Tools:** `behaviors.search`, `behaviors.get`, `behaviors.createDraft`, `behaviors.update`, `behaviors.approve`, `behaviors.deprecate`

## Schemas (JSON / Proto)
### `Behavior`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `behavior_id` | UUID | Yes | Stable identifier for the behavior. |
| `name` | string | Yes | ≤ 80 chars, unique per tenant. |
| `description` | string | Yes | High-level summary for UI listings. |
| `tags` | string[] | No | Free-form tags aiding retrieval filters. |
| `created_at` | RFC3339 | Yes | Creation timestamp. |
| `updated_at` | RFC3339 | Yes | Last mutation timestamp. |
| `latest_version` | string | Yes | Semantic version (`MAJOR.MINOR.PATCH`). |
| `status` | enum | Yes | `DRAFT|IN_REVIEW|APPROVED|DEPRECATED`. Reflects the status of `latest_version`. |
| `embedding` | vector<float> | No | 1024-dim embedding stored in vector index (optional when `metadata.requires_embedding=false`). |

### `BehaviorVersion`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `behavior_id` | UUID | Yes | Parent behavior reference. |
| `version` | string | Yes | Semantic version string (`MAJOR.MINOR.PATCH`). |
| `instruction` | string | Yes | Behavior instruction used during inference. |
| `role_focus` | enum | Yes | `STRATEGIST|TEACHER|STUDENT|MULTI_ROLE`. |
| `status` | enum | Yes | `DRAFT|IN_REVIEW|APPROVED|DEPRECATED`. |
| `trigger_keywords` | string[] | No | Control-plane keywords for fast lookup. |
| `examples` | array<Object> | No | Example snippets (fields: `title`, `body`). |
| `metadata` | Object | No | Arbitrary JSON metadata (e.g., domain, compliance flags). |
| `effective_from` | RFC3339 | Yes | When the version becomes active. |
| `effective_to` | RFC3339 | No | Null if active; set when deprecated. |
| `created_by` | UUID | Yes | Actor ID of creator. |
| `approval_action_id` | UUID | No | Link to action log for approval step. |
| `embedding_checksum` | string | No | Hash of embedding payload for reproducibility. |

### `CreateBehaviorDraftRequest`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | Yes | Unique behavior name. |
| `description` | string | Yes | Summary for UI catalogs. |
| `instruction` | string | Yes | Initial instruction text. |
| `role_focus` | enum | Yes | Intended role. |
| `trigger_keywords` | string[] | No | Optional keyword hints. |
| `tags` | string[] | No | Tags applied to behavior record. |
| `metadata` | Object | No | Additional metadata. |
| `examples` | array<Object> | No | Optional examples. |
| `embedding` | float[] | No | Pre-computed embedding vector (length 1024). |
| `base_version` | string | No | Optional semantic version to clone metadata/instruction. |
| `actor` | Actor | Yes | Creator metadata (`id`, `role`, `surface`). |

### `UpdateBehaviorDraftRequest`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `behavior_id` | UUID | Yes | Behavior to update. |
| `version` | string | Yes | Version being updated (`status` must be `DRAFT` or `IN_REVIEW`). |
| `instruction` | string | No | Updated instruction text. |
| `description` | string | No | Updated description (mirrors behavior record). |
| `trigger_keywords` | string[] | No | Replacement keyword list. |
| `tags` | string[] | No | Replacement tags list. |
| `examples` | array<Object> | No | Replacement examples. |
| `metadata` | Object | No | Replacement metadata JSON. |
| `embedding` | float[] | No | Replacement embedding vector. |
| `actor` | Actor | Yes | Mutation actor metadata. |

### `ApproveBehaviorRequest`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `behavior_id` | UUID | Yes | Target behavior. |
| `version` | string | Yes | Version to approve. |
| `effective_from` | RFC3339 | Yes | When approval takes effect. |
| `approval_action_id` | UUID | No | Link to action log entry. |
| `actor` | Actor | Yes | Approver metadata. |

### `DeprecateBehaviorRequest`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `behavior_id` | UUID | Yes | Target behavior. |
| `version` | string | Yes | Version to deprecate. |
| `effective_to` | RFC3339 | Yes | Retirement timestamp. |
| `successor_behavior_id` | UUID | No | Optional reference to replacement behavior. |
| `actor` | Actor | Yes | Approver metadata. |

### `SearchBehaviorsRequest`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `query` | string | No | Free-text query (analyzed for keyword search). |
| `tags` | string[] | No | Filter by tags. |
| `role_focus` | enum | No | Filter by role. |
| `status` | enum | No | Filter by behavior status. |
| `limit` | integer | No | Default 25, max 100. |
| `include_embeddings` | bool | No | Defaults false; true returns embedding vector (requires `behavior:admin`). |

### `BehaviorSearchResult`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `behavior` | Behavior | Yes | Top-level record. |
| `active_version` | BehaviorVersion | Yes | Currently approved version. |
| `score` | float | Yes | Combined lexical/vector score (0-1). |

## Operations
| Operation | REST | CLI | MCP | Description |
| --- | --- | --- | --- | --- |
| List behaviors | `GET /v1/behaviors` | `amprealize behaviors list [--status --tag]` | `behaviors.search` (no query) | Returns paginated behaviors with active version metadata. |
| Search behaviors | `POST /v1/behaviors:search` | `amprealize behaviors search --query ...` | `behaviors.search` | Hybrid lexical/vector search with filters. |
| Get behavior | `GET /v1/behaviors/{id}` | `amprealize behaviors get <id> [--version X.Y.Z]` | `behaviors.get` | Returns all versions or specific version when requested. |
| Create draft | `POST /v1/behaviors` | `amprealize behaviors create --name --role ...` | `behaviors.createDraft` | Creates a new behavior + version in `DRAFT`. |
| Update draft | `PATCH /v1/behaviors/{id}/versions/{version}` | `amprealize behaviors update <id> --version ...` | `behaviors.update` | Mutates draft/ in-review versions. |
| Submit for review | `POST /v1/behaviors/{id}/versions/{version}:submit` | `amprealize behaviors submit <id> --version ...` | `behaviors.update` (status change) | Moves version to `IN_REVIEW`. |
| Approve version | `POST /v1/behaviors/{id}/versions/{version}:approve` | `amprealize behaviors approve <id> --version ... --effective-from ...` | `behaviors.approve` | Marks version approved and updates `behaviors.latest_version`. Emits telemetry. |
| Deprecate version | `POST /v1/behaviors/{id}/versions/{version}:deprecate` | `amprealize behaviors deprecate <id> --version ...` | `behaviors.deprecate` | Sets `effective_to` and status `DEPRECATED`. |
| Delete draft | `DELETE /v1/behaviors/{id}/versions/{version}` | `amprealize behaviors delete-draft <id> --version ...` | `behaviors.update` | Removes draft versions (approved versions cannot be deleted). |

## RBAC & Scopes
| Operation | Scope(s) |
| --- | --- |
| Search/List/Get | `behavior:read` |
| Create/Update Draft | `behavior:write` |
| Submit for Review | `behavior:write` |
| Approve/Deprecate | `behavior:approve` + `compliance:validate` (dual control) |
| Delete Draft | `behavior:write` |
| Retrieve embedding vectors | `behavior:admin` |

## Persistence & Storage
- **Primary store:** PostgreSQL for production, SQLite (`amprealize_behaviors.db`) for local development/testing. Tables mirror schema in `docs/BEHAVIOR_VERSIONING.md` (`behaviors`, `behavior_versions`).
- **Vector index:** FAISS (local) / Qdrant (cloud). Stored embeddings keyed by `(behavior_id, version)`; `embedding_checksum` ensures reproducibility.
- **Transactions:** Draft creation and version insertions happen in a single transaction to avoid orphaned records. SQLite uses `BEGIN IMMEDIATE` for write operations.
- **Migrations:** Alembic (future) or SQL migration scripts. Local dev auto-creates schema if missing; production relies on migration pipeline.

## Telemetry
Emit the following events via `TelemetryClient`:
- `behaviors.draft_created`
- `behaviors.draft_updated`
- `behaviors.submitted_for_review`
- `behaviors.approved`
- `behaviors.deprecated`
- `behaviors.search_performed`
Each event must include `{behavior_id, version, actor_id, actor_role, surface, tags, role_focus}` and latency measurements where applicable. Approval/Deprecation events also include `approval_action_id` or `successor_behavior_id`.

## Error Codes
| Code | Scenario |
| --- | --- |
| `BEHAVIOR_NOT_FOUND` | Behavior ID missing or no matching version. |
| `VERSION_CONFLICT` | Version already exists or status transition invalid. |
| `VALIDATION_ERROR` | Invalid fields (e.g., missing instruction, role, name). |
| `UNAUTHORIZED` | Actor lacks required scopes. |
| `EMBEDDING_MISMATCH` | Provided embedding length/checksum invalid. |

## CLI Experience (Milestone 1)
```
$ amprealize behaviors create --name "behavior_inclusion_exclusion" --role strategist --description "Avoid double counting by subtracting intersections" --instruction "When counting combinations..." --tags math --keywords inclusion,exclusion
$ amprealize behaviors list --status approved
$ amprealize behaviors get {behavior_id} --version 1.0.0 --format json
$ amprealize behaviors submit {behavior_id} --version 1.0.0
$ amprealize behaviors approve {behavior_id} --version 1.0.0 --effective-from 2025-10-15T10:00:00Z
```

## Parity & Testing Requirements
1. **Contract tests:** Schema validation for REST + MCP payloads (to be added in `tests/test_behavior_service_parity.py`).
2. **Functional tests:** CRUD lifecycle tests ensuring persistence across service instances (SQLite-backed). CLI/REST/MCP adapters must return identical payloads.
3. **Search tests:** Validate lexical + tag filtering and vector similarity (vector search stubbed in Milestone 1 with lexical fallback; integration with FAISS planned Milestone 2).
4. **Telemetry tests:** Ensure telemetry events fire with expected metadata during lifecycle transitions.

## Milestone 1 Scope
- Implement BehaviorService with SQLite-backed persistence (file path `~/.amprealize/data/behaviors.db` or env-configurable).
- Provide CRUD lifecycle (create draft, update draft, submit, approve, deprecate, list, search, get).
- Stub vector search: store embeddings when provided; fallback to keyword/tag filtering until FAISS integration (Milestone 2).
- CLI parity commands and REST/MCP adapters (structured like ActionService/ComplianceService counterparts).
- Tests verifying persistence across service instances to simulate CLI command invocations.

## Milestone 2 Enhancements
- Swap SQLite for Postgres in shared environments with Alembic migrations.
- Integrate FAISS/Qdrant for vector search with background index refresh jobs.
- Add reflection pipeline hooks (`reflections.suggestBehaviors`) to auto-draft behaviors from traces.
- Implement approval workflow notifications and multi-reviewer support.
- Expose behavior analytics endpoints (usage frequency, approval SLAs).

## Dependencies
- `docs/BEHAVIOR_VERSIONING.md` (versioning strategy & DB schema)
- `RETRIEVAL_ENGINE_PERFORMANCE.md` (latency/recall targets for search)
- `TELEMETRY_SCHEMA.md` (event envelope definitions)
- `MCP_SERVER_DESIGN.md` (parity expectations, tool identifiers)
- `ACTION_REGISTRY_SPEC.md` (action logging requirements for approvals)

## Open Questions
- Do we enforce unique tags per behavior? (Current approach: free-form; duplicates allowed).
- Should embeddings be optional or required for approved behaviors? (Milestone 1: optional).
- Do we auto-generate embeddings on draft creation using platform LLM connectors? (Out of scope for Milestone 1).
- When multiple versions are approved (overlap windows), do we allow multi-active? (Default: only one active approved version; enforced via DB constraint).
