# Canonical trace contract and capture policy

**Normative companion** to [`TELEMETRY_SCHEMA.md`](TELEMETRY_SCHEMA.md). This document ties together the typed envelope (`GUIDEAI-1111`), retention classes (`GUIDEAI-1100`), warehouse storage (`GUIDEAI-1108`), and **where** telemetry is captured versus **what** is written to `observability_records`.

**Implementation source of truth (Python):** [`amprealize/observability_contracts.py`](../../amprealize/amprealize/observability_contracts.py) — dataclasses, `ObservabilityRecordKind`, `ObservabilityCorrelation`, `missing_required_correlation()`, `canonical_trace_examples()`, `observability_retention_rules()`, `observability_backend_targets()`, `observability_timescale_schema()`. Chat reply wiring also uses [`amprealize/observability_tracing.py`](../../amprealize/amprealize/observability_tracing.py) and [`amprealize/observability_attributes.py`](../../amprealize/amprealize/observability_attributes.py) (§7).

**Warehouse projection (Postgres/Timescale):** [`amprealize/storage/postgres_telemetry.py`](../../amprealize/amprealize/storage/postgres_telemetry.py) — `PostgresTelemetryWarehouse._project_event` and helpers.

**JSON Schema (canonical envelope, JSON payloads):** [`schemas/canonical_observability_envelope.schema.json`](schemas/canonical_observability_envelope.schema.json) — Draft 2020-12; aligns with `ObservabilityRecord.to_dict()` / exporters. Timescale row shape (`payload`, `data_class`, flattened correlation columns) is **not** covered by this file; see `observability_timescale_schema()` in Python.

---

## 1. Canonical record kinds

Each stored/exported **canonical** row is an `ObservabilityRecord` with `kind` ∈:

| Kind | Role |
| --- | --- |
| `trace` | Root trace for a chat reply, execution run, or behavior-mining flow. |
| `span` | Timed child span (routing, context, generation, tool, phase, persistence, export). |
| `event` | Point-in-time event (e.g. gateway lifecycle). |
| `generation` | LLM generation (provider, model, tokens, cost, latency, bounded summaries). |
| `tool_call` | MCP, platform-action, or execution tool invocation. |
| `action` | Governed platform or replay action. |
| `artifact` | Plan, chat, execution, or behavior artifact. |
| `behavior_candidate` | Reflection / trace-analysis candidate provenance. |
| `outcome` | Business outcome (resource created, replay URN, etc.), separate from performance. |

Shared envelope fields (see Python `ObservabilityRecord`): `record_id`, `kind`, `name`, `timestamp`, `correlation`, `status`, `sensitivity`, `attributes`. Storage adds `payload`, `data_class`, `retention_until`, and flattened correlation columns per [`observability_timescale_schema()`](../../amprealize/amprealize/observability_contracts.py).

---

## 2. Correlation (required fields)

Authoritative rules live in `_required_correlation_fields()` in `observability_contracts.py`.

| Kind | Required correlation fields |
| --- | --- |
| All kinds | `trace_id`, `span_id`, `project_id`, `surface` |
| `generation` | Above **plus** `model_id` |

Optional correlation (when known): `parent_span_id`, `org_id`, `conversation_id`, `message_id`, `run_id`, `cycle_id`, `work_item_id`, `action_id`, `tool_call_id`, `llm_call_id`, `behavior_id`, `actor_id`, `actor_role`, `permission_action`, `queue_job_id`, `phase`.

**Validation:** Use `ObservabilityRecord.missing_required_correlation()` before treating a record as export-ready.

---

## 3. Identifiers and versioning

- **`record_id`:** Stable identifier for the canonical row. For rows projected from telemetry, the implementation uses `TelemetryEvent.event_id` unless a dedicated ID is defined in the projector.
- **`trace_id` / `span_id`:** Execution-path projectors derive these via `_trace_span_ids_for_execution()` when `payload.execution_observability` lacks explicit IDs: prefer EO `trace_id` / `span_id`, else `run:{run_id}`, else `event_id`-based suffixes (see [`postgres_telemetry.py`](../../amprealize/amprealize/storage/postgres_telemetry.py)).
- **Contract versioning:** The Python module is the versioned contract surface. Doc changes that **narrow** required fields or **change** kind semantics must ship with updated `tests/test_observability_contracts.py` and projection tests. Optional: add explicit `attributes.schema_version` when exporters need a bump without code migration.

---

## 4. Capture policy

### 4.1 Execution observability payload

For work-item and chat-linked execution, emitters **must** populate `payload.execution_observability` with the shared shape documented in [`TELEMETRY_SCHEMA.md`](TELEMETRY_SCHEMA.md) (Execution Observability Events). Fields include `run_id`, `cycle_id`, `work_item_id`, `project_id`, `org_id`, `agent_id`, `model_id`, `surface`, `conversation_id`, `message_id`, `request_id`, `execution_mode`, `source_type`, `queue_job_id` when applicable.

**Sanitization boundary:** Before persistence to telemetry sinks, audit logs, or cross-trust export, payloads pass through `amprealize.execution_observability.sanitize_observability_payload()`. Canonical Python records use `ObservabilityRecord.to_sanitized_payload()` for exporter-safe views.

### 4.2 Mandatory vs best-effort

| Situation | Policy |
| --- | --- |
| Gateway / queue execution start and terminal events | **Mandatory** `execution_observability` when the run is scoped to a project or work item; `project_id` and `surface` are required for warehouse correlation. |
| Chat reply traces (`chat.trace.*`, `chat.span.*`, `conversation_reply.generated`, other `chat.*`) | Emit per [`TELEMETRY_SCHEMA.md`](TELEMETRY_SCHEMA.md); **projection** to `observability_records` is implemented for these families per §5. |
| Degraded mode | If `project_id` is missing, projectors may fall back to actor surface only where code allows; new emitters **should not** rely on this — fail closed in governed paths. |

### 4.3 Sensitivity and `data_class` at write

Retention and access classes are defined in `observability_retention_rules()` (`GUIDEAI-1100`). When writing `observability_records`:

| Writer path | Typical `data_class` | Notes |
| --- | --- | --- |
| `execution.gateway.*` → `observability_records` | `metadata_trace` | Payload copy is sanitized; `retention_until` set in warehouse code (~1095 days from event in current implementation). |
| `execution.llm.completed` | `summary` on canonical row | Typed `observability_generations` insert when migration applied. |
| `reflection.candidate_*` | `behavior_mining_feature` (rejected path uses denied status) | Long-lived provenance for dashboards. |

Short-lived classes (`raw_prompt`, `raw_response`, `tool_args`, etc.) **must not** be promoted to durable `observability_records` without explicit compliance approval; keep them in restricted admin paths per TELEMETRY_SCHEMA.

### 4.4 Metadata-first defaults and “opt-in raw” (GUIDEAI-1189)

The platform ships **metadata-first** capture: emitters use sanitized payloads and bounded previews (for example `output_preview` truncated on `llm.generation.*`), and canonical **`ObservabilitySensitivity`** defaults emphasize **`metadata`** / **`summary`** for durable rows. There is **no** single environment flag or user toggle that writes **full** prompts or responses into **`observability_records`**. Classes **`raw_prompt`** / **`raw_response`** remain **restricted** per §4.3 and TELEMETRY_SCHEMA; promoting them to durable canonical storage requires explicit compliance/admin flows, not only configuration. A future **opt-in raw** product feature would need governance UX, retention, access control, and projector/export updates together.

### 4.5 `execution_traces` hypertable vs `observability_records`

| Store | Purpose |
| --- | --- |
| `execution_traces` | Distributed span-style traces (e.g. `start_span` / `end_span`, `record_completed_execution_trace`) for operational drilldown and LLM phase timings. |
| `observability_records` | Append-only canonical envelope (kinds in §1) for Timescale analytics, Metabase/Looker views, and exporter builders. |

Product UI **trace_summary** merges gateway/execution telemetry and run steps; treat **both** stores as complementary, not duplicates. Prefer `observability_records` for cross-backend analytics contracts.

### 4.6 Capture points (emitters)

| Phase | Typical `event_type` / mechanism | Notes |
| --- | --- | --- |
| Execution gateway | `execution.gateway.started`, `.enqueued`, `.completed`, `.failed`, `execution.gateway.*` | Normalized queue + policy boundary. |
| Queue worker | `execution.worker.*` | Correlation via same EO object. |
| GEP / agent loop | `execution.phase.*`, `execution.tool.*`, `execution.llm.completed` | Tool performance vs business outcome split per `*.performance` / `*.business_outcome` events in TELEMETRY_SCHEMA. |
| Chat reply | `chat.trace.*`, `chat.span.*`, `conversation_reply.generated` | Bounded `chat_trace` in payloads where applicable. |
| LLM client | `llm.generation.completed` / `.failed` | Provider-level metrics; may attach EO when inside a run. |
| Reflection | `reflection.candidate_extracted`, `.approved`, `.rejected` | Maps to canonical `behavior_candidate`. |

---

## 5. Telemetry → `observability_records` projection matrix

This table reflects **`PostgresTelemetryWarehouse._project_event`** as of the contract publish date. Rows **not** listed here either do not call `_project_event` for `observability_records` or only update **fact_** tables / `execution_traces` via other methods.

| Telemetry `event_type` (pattern) | `observability_records.kind` | Typed projection table | Tests (representative) |
| --- | --- | --- | --- |
| `reflection.candidate_extracted` | `behavior_candidate` | — (view rolls up records) | `test_reflection_candidate_event_projects_observability_record` |
| `reflection.candidate_approved` | `behavior_candidate` | — | same |
| `reflection.candidate_rejected` | `behavior_candidate` | — | same |
| `execution.gateway.*` | `event` | — | `test_execution_gateway_started_projects_observability_record` |
| `execution.llm.completed` | `generation` | `observability_generations` (if migration present) | `test_execution_llm_completed_projects_observability_and_generation` |
| `execution.worker.*` | `event` | — | `test_execution_worker_started_projects_observability_record` |
| `execution.phase.*` | `event` | — | `test_execution_phase_completed_projects_observability_record` |
| `execution.tool.*` (except `business_outcome`) | `tool_call` | `observability_tool_calls` for `*.completed`, `*.performance`, `*.failed`, `*.denied` | `test_execution_tool_completed_projects_observability_and_tool_call` |
| `execution.tool.business_outcome` | `outcome` | `observability_outcomes` | `test_execution_tool_business_outcome_projects_outcome_typed` |
| `llm.generation.*` | `generation` | `observability_generations` | `test_llm_generation_failed_projects_generation_typed` |
| `chat.trace.*` | `trace` | — | `test_chat_trace_started_projects_trace_kind` |
| `chat.span.*` | `span` | — | `test_chat_span_completed_projects_span_kind` |
| `chat.*` (other), `conversation_reply.generated` | `event` (default) | — | `test_conversation_reply_generated_projects_event_kind` |

**Ingestion without `observability_records` projection (same `_project_event` module):** `plan_created`, `execution_update`, `compliance_step_recorded`, `behavior_retrieved` — write **Postgres telemetry `fact_*` tables** only (`fact_behavior_usage`, `fact_token_savings`, `fact_execution_status`, `fact_compliance_steps`), not the canonical Timescale envelope.

**Read models (SQL views, Metabase / Looker):** In addition to the projection matrix above, dashboard-facing views include `observability_trace_summary`, `observability_generation_metrics`, `observability_tool_performance`, `observability_business_outcomes`, `observability_behavior_candidate_lifecycle`, and (GUIDEAI-1192) `observability_span_tree`, `observability_run_summary`, and `observability_conversation_summary`. App Postgres migrations (`20260505_observability_analytics`) and the dedicated telemetry Alembic chain (`migrations_telemetry`, revision `telemetry_obs_analytics`) stay aligned. Managed-enterprise Looker models consume **`enterprise_warehouse.*`** definitions in [`docs/analytics/observability_warehouse_views.sql`](../../docs/analytics/observability_warehouse_views.sql).

### 5.1 Documented gaps (follow-up work)

**Status (2026-05-05, GUIDEAI-1192):** Schema parity for typed tables and dashboard SQL views is complete on both migration chains; §5.1 below remains the authoritative backlog for **event → `_project_event`** coverage (`action.*`, `pack.*`, etc.), not for missing DB objects.

The following **telemetry** families remain **not** projected into `observability_records` by `_project_event` (or are only partially covered elsewhere). Treat as backlog for future warehouse work:

- Actions / outcomes: `action.*`, `action_recorded`
- E4 / flags / packs: `pack.*`, `bci.*`, `quality_gate.*`, `feature_flag.*`, and related families in [`TELEMETRY_SCHEMA.md`](TELEMETRY_SCHEMA.md) not matching the table in §5

Exporters and governed query services may still consume **raw `telemetry_events`** for these types until projection coverage lands.

---

## 6. JSON Schema artifact

- **File:** [`schemas/canonical_observability_envelope.schema.json`](schemas/canonical_observability_envelope.schema.json) (`$id`: `urn:amprealize:schemas:canonical_observability_envelope:v1`, extension field `x-amprealize-schema-version`).
- **Scope:** In-memory / API / exporter JSON matching `ObservabilityRecord` and subclasses (`canonical_trace_examples()`). `correlation` uses `additionalProperties: false` with the same keys as `ObservabilityCorrelation`. **`kind: "generation"`** implies **`correlation.model_id`** is required (matches `missing_required_correlation()` in Python).
- **Validation:** `tests/test_observability_contracts.py` (schema vs `canonical_trace_examples()`); CI installs `jsonschema` via the `dev` extra.

---

## 7. Chat trace context and Python tracer (GUIDEAI-1191)

**Goal:** Keep `chat_trace` identifiers on `contextvars` for the happy path so inner helpers do not need a `chat_trace` parameter on every span/event, while keeping **failure** paths explicit when the happy-path context was never attached.

| Component | Role |
| --- | --- |
| `TraceContext` | Immutable `trace_id`, `span_id`, `parent_span_id`, and the `chat_trace` dict; built via `TraceContext.from_chat_trace(...)`. |
| `attach_trace_context` / `detach_trace_context` | Push/pop the current `TraceContext` (returned token must be passed to `detach_trace_context` in `finally`). |
| `bind_context(ctx)` | Sync/async context manager alternative to manual attach/detach. |
| `Tracer` | Emits `chat.*` telemetry through `TelemetryClient.emit_event` with **non-fatal** error handling; merges OpenInference / OTel GenAI-style keys into `observability.record` payloads via `merge_otel_into_attributes()` from [`observability_attributes.py`](../../amprealize/amprealize/observability_attributes.py). Also wraps **`start_execution_span` / `end_execution_span`** for any surface that passes an explicit `ObservabilityCorrelation` (same sink, same `_safe_call` behavior). |
| `ConversationReplyService` | After `_chat_trace_metadata(...)` is built, calls `attach_trace_context(TraceContext.from_chat_trace(chat_trace))` and **`detach_trace_context`** in a `finally` on `generate_reply`. `chat.trace.*` / `chat.span.*` helpers resolve `chat_trace` from context unless overridden (e.g. `chat.trace.failed` uses the synthesized `failure_trace`). |
| `ExecutionGateway` | Work-item runs: **all** gateway-owned `TelemetryClient.emit_event` traffic goes through **`Tracer.emit_execution_gateway_event`** (including `execution.gateway.started` / `.enqueued` / `.completed` / `.failed` / `.research_completed` and policy audit `event_type` values from the composition engine). Payloads remain **event-specific**; only the transport and sanitization are unified. Run lifecycle **spans** use `_gateway_run_span_correlation` + **`Tracer.start_execution_span` / `end_execution_span`** (`service_name` = `execution-gateway`, `amprealize.span.scope` = `execution_gateway`). **`self._telemetry`** is still passed into **`AgentExecutionLoop`** / tool wiring that expect a raw client. |

**Dependencies:** Runtime packages `opentelemetry-api` and `opentelemetry-semantic-conventions` supply stable GenAI attribute names when available; [`observability_attributes._otel_gen_ai_keys()`](../../amprealize/amprealize/observability_attributes.py) falls back to string literals if imports fail.

**Tests:** `tests/test_observability_tracing_context.py`, `tests/test_observability_attributes.py` (representative); chat golden traces remain in `tests/test_chat_answer_golden_traces.py`. Gateway span correlation + Tracer wiring: `tests/test_execution_gateway.py` (`TestExecutionGatewaySpanCorrelation`).

---

## 8. Related documents

- [`TELEMETRY_SCHEMA.md`](TELEMETRY_SCHEMA.md) — full event taxonomy, access tiers, retention table.
- [`TRACE_ANALYSIS_SERVICE_CONTRACT.md`](TRACE_ANALYSIS_SERVICE_CONTRACT.md) — behavior mining inputs.
- [`WORK_ITEM_EXECUTION_PLAN.md`](../WORK_ITEM_EXECUTION_PLAN.md) — gateway, `trace_summary`, golden traces.
- [`MCP_SERVER_DESIGN.md`](MCP_SERVER_DESIGN.md) — telemetry / observability MCP surfaces (when applicable).
