# Telemetry Schema & Retention Policy

## Goals
- Provide consistent observability across Web, CLI, API, and MCP surfaces.
- Supply evidence for PRD metrics (behavior reuse %, token savings, task completion rate, compliance coverage).
- Meet compliance requirements for auditability (immutable logs, defined retention windows).

## Event Model
All telemetry events share a common envelope:
```json
{
  "event_id": "uuid",
  "timestamp": "RFC3339",
  "actor": {
    "id": "uuid",
    "role": "Strategist|Student|Teacher|Admin",
    "surface": "web|cli|vscode|api|mcp"
  },
  "run_id": "uuid",
  "action_id": "uuid|null",
  "session_id": "uuid",
  "payload": { "...domain-specific fields..." }
}
```

### Domain Events
| Event Type | Required Fields | Purpose |
| --- | --- | --- |
| `behavior_retrieved` | `payload.behavior_ids[]`, `payload.latency_ms`, `payload.relevance_scores[]`, `payload.query_vector_version` | Measure reuse rate, latency, and retriever quality. |
| `plan_created` | `payload.behavior_ids[]`, `payload.steps[]`, `payload.checklist_status` | Track behavior citation and checklist coverage at plan time. |
| `execution_update` | `payload.step`, `payload.status`, `payload.commands[]`, `payload.validation_results[]` | Monitor task completion and validation evidence. |
| `reflection_submitted` | `payload.trace_id`, `payload.behavior_candidates[]`, `payload.retrieval_latency_ms` | Evaluate self-improvement loops. |
| `action_recorded` | `payload.artifact_path`, `payload.summary`, `payload.behaviors_cited[]`, `payload.trace_id`, `payload.span_id` | Ensure reproducibility logs are complete and link action records back to canonical traces. |
| `action.execution.performance` | `payload.action_id`, `payload.status`, `payload.action_type`, `payload.trace_id`, `payload.span_id` | Analyze replay/action execution latency and failure rates separately from created outcomes. |
| `action.replay.performance` | `payload.action_ids[]`, `payload.status`, `payload.succeeded_count`, `payload.failed_count`, `payload.trace_id`, `payload.span_id` | Analyze replay job performance and completion shape without mixing in business outcome payloads. |
| `action.business_outcome` | `payload.outcome_type`, `payload.outcome_ref`, `payload.trace_id`, `payload.span_id` | Query recorded or replayed business outcomes independently from action/tool performance. |
| `compliance_step_recorded` | `payload.checklist_step`, `payload.status`, `payload.evidence_uri` | Demonstrate 95% compliance coverage. |

### Execution Observability Events

Added for `GUIDEAI-1091`. Gateway, worker, agent-loop, and tool-call events share `payload.execution_observability` so chat-triggered and work-item-triggered execution can be correlated without parsing surface-specific payloads.

`payload.execution_observability` includes `run_id`, `cycle_id`, `work_item_id`, `project_id`, `org_id`, `agent_id`, `model_id`, `surface`, `conversation_id`, `message_id`, `request_id`, `execution_mode`, `source_type`, and `queue_job_id` when available. Sensitive fields are redacted through `amprealize.execution_observability.sanitize_observability_payload()` before telemetry or audit persistence.

### Canonical Trace Envelope

**Normative summary:** [`CANONICAL_TRACE_CONTRACT.md`](CANONICAL_TRACE_CONTRACT.md) (capture policy, correlation rules, telemetry → `observability_records` projection matrix and gaps).

`GUIDEAI-1111` defines typed canonical trace envelopes in `amprealize.observability_contracts`. These contracts are the backend-neutral shape used by later storage, exporter, behavior-mining, and dashboard work. They do not replace existing telemetry events immediately; instead they define the normalized target records that event payloads, Postgres/Timescale views, Datadog/Langfuse exporters, and trace analysis can converge on.

The canonical record kinds are:

| Kind | Purpose |
| --- | --- |
| `trace` | Root trace for a chat reply, execution run, or behavior-mining flow. |
| `span` | Timed child span for routing, context composition, generation, tool calls, GEP phases, persistence, queue work, or exports. |
| `event` | Point-in-time event attached to a trace/span, such as a gateway start or policy decision. |
| `generation` | LLM generation record with provider/model, token/cost, latency, first-token latency, and bounded prompt/output summaries. |
| `tool_call` | MCP, platform-action, or execution tool call with tool/call IDs, elapsed time, input summary, and output summary. |
| `action` | Governed platform or replay action with action type and target resource fields. |
| `artifact` | Chat, plan, execution, or behavior artifact emitted by a workflow. |
| `behavior_candidate` | Behavior candidate provenance record with source trace IDs and confidence. |
| `outcome` | Business outcome separated from performance telemetry, such as a created work item or replayed artifact. |

All canonical records share `record_id`, `kind`, `name`, `timestamp`, `status`, `sensitivity`, `attributes`, and a `correlation` object. Required correlation fields for all records are `trace_id`, `span_id`, `project_id`, and `surface`; `generation` records additionally require `model_id`. Optional correlation fields cover org, conversation, message, run, cycle, work item, action, tool call, LLM call, behavior, actor, permission, queue job, and phase metadata. Exporters should use `to_sanitized_payload()` before writing records outside trusted process boundaries.

`GUIDEAI-1101` makes the backend targets explicit via `observability_backend_targets()`:

| Profile | Primary Store | Trace/LLM Export | Dashboard | Notes |
| --- | --- | --- | --- | --- |
| `oss` | Postgres-compatible telemetry tables | Disabled by default | Local UI | Keeps the same canonical records without requiring managed observability services. |
| `self_hosted_enterprise` | Timescale/Postgres | Optional self-hosted Langfuse; optional OpenSearch summaries | Metabase | Uses the canonical envelope for warm trace storage and dashboard-friendly views. |
| `managed_enterprise` | Enterprise warehouse | Datadog for traces/logs/metrics; Langfuse Cloud for LLM generations/evals/tool traces | Looker | Exports the same canonical records to managed observability and executive analytics surfaces. |

The telemetry event taxonomy maps into canonical records as follows: chat lifecycle and execution gateway events create `trace`, `span`, and `event` records; `execution.llm.completed` and future LLM client generation events create `generation` records; MCP/platform/tool telemetry creates `tool_call` records; action/replay audit events create `action` records; plan/chat/output attachments create `artifact` records; `reflection.candidate_extracted` creates `behavior_candidate` records; and `*.business_outcome` events create `outcome` records. Performance dashboards should aggregate `span`, `generation`, `tool_call`, and `action`; product analytics should aggregate `outcome`; behavior mining should consume `trace`, `span`, `generation`, `tool_call`, `artifact`, and `behavior_candidate`.

`GUIDEAI-1108` implements the self-hosted Timescale/Postgres profile through Alembic revisions `20260428_observability_timescale` and `20260428_obs_beh_cand_lc`. The migration chain creates `observability_records` as the canonical append-only record table, converts it to a Timescale hypertable when the Timescale extension is installed, and adds typed projection tables for `observability_generations`, `observability_tool_calls`, `observability_actions`, and `observability_outcomes`. The profile also stores retention metadata in `observability_retention_policies` and exposes dashboard-ready views: `observability_trace_summary`, `observability_generation_metrics`, `observability_tool_performance`, `observability_business_outcomes`, and `observability_behavior_candidate_lifecycle`.

For BreakerAmp-native local workflows, `config/breakeramp/environments.yaml` now exposes explicit environment aliases for `local-postgres`, `neon`, `self-hosted-observability`, and `managed-enterprise-observability`, mapping the observability profiles onto the existing `local-dev` and `cloud-dev` blueprints. The `cloud-dev` blueprint also passes through the managed exporter variables required by `observability_exporter_profiles()` (`AMPREALIZE_DATADOG_OTLP_ENDPOINT`, `AMPREALIZE_DATADOG_API_KEY`, `AMPREALIZE_LANGFUSE_PUBLIC_KEY`, `AMPREALIZE_LANGFUSE_SECRET_KEY`, `AMPREALIZE_LANGFUSE_HOST`) so runtime transport configuration stays aligned with the contract layer.

All self-hosted storage writes should preserve `trace_id`, `span_id`, `project_id`, `surface`, `payload`, `data_class`, and `retention_until`. Typed projection tables are optimization targets for Metabase and operational queries; they must remain derivable from the canonical `observability_records` envelope so Datadog, Langfuse, Looker, and future exporters can share one instrumentation model.

`GUIDEAI-1109` adds managed enterprise exporter payload builders in `amprealize.observability_exporters`. `build_datadog_export_payload()` maps canonical records to Datadog-ready `spans`, `logs`, and `metrics` sections while preserving trace/span/run/work-item tags and sanitized payload metadata. `build_langfuse_export_payload()` maps canonical trace roots plus generation/tool/span records into Langfuse-ready `traces` and `observations`, including generation model/provider, usage, cost, latency, first-token latency, and tool input/output summaries. These builders do not perform network calls or read credentials; runtime transports must provide `AMPREALIZE_DATADOG_*` or `AMPREALIZE_LANGFUSE_*` environment variables separately and must not fork the canonical instrumentation model.

`GUIDEAI-1110` defines dashboard source contracts through `observability_dashboard_sources()`. The self-hosted `metabase` source reads Timescale/Postgres views directly: `observability_trace_summary`, `observability_generation_metrics`, `observability_tool_performance`, `observability_business_outcomes`, and `observability_behavior_candidate_lifecycle`. The managed `looker` source reads equivalent `enterprise_warehouse.*` datasets enriched with Datadog and Langfuse trace drilldown URLs; the SQL definition for the lifecycle warehouse projection now lives in `docs/analytics/observability_warehouse_views.sql`. The behavior-candidate lifecycle dataset reserves first-class measures for extraction volume, approval/rejection rate, estimated token savings, decay, and rejection reasons so GUIDEAI-1097 dashboards can be provisioned from governed contracts instead of ad hoc queries. Both dashboard profiles expose dataset dimensions, measures, drilldown fields, connection environment variables, and trace URL templates so dashboards can be provisioned without changing instrumentation code.

`GUIDEAI-1100` defines retention and sensitivity classes in `observability_retention_rules()`:

| Data Class | Sensitivity | Default / Max Retention | Access Tiers | Purge Rule |
| --- | --- | --- | --- | --- |
| `metadata_trace` | `metadata` | 3 years / 7 years, archive 7 years | viewer, data analyst, admin, compliance | Anonymize actor fields and keep aggregate trace facts. |
| `summary` | `summary` | 3 years / 7 years, archive 7 years | viewer, data analyst, admin, compliance | Anonymize actor fields and keep sanitized bounded summaries. |
| `hash` | `metadata` | 7 years / 7 years, archive 7 years | data analyst, admin, compliance | Retain non-reversible hashes after actor anonymization. |
| `behavior_mining_feature` | `summary` | 3 years / 7 years, archive 7 years | data analyst, admin, compliance | Anonymize actor fields and keep derived feature data only. |
| `raw_prompt` | `raw` | 30 / 90 days | admin, compliance | Delete. |
| `raw_response` | `raw` | 30 / 90 days | admin, compliance | Delete. |
| `tool_args` | `restricted` | 30 / 90 days | admin, compliance | Delete. |
| `output_preview` | `restricted` | 30 / 90 days | admin, compliance | Delete. |
| `command_output` | `restricted` | 30 / 90 days | admin, compliance | Delete. |
| `file_diff` | `restricted` | 30 / 90 days | admin, compliance | Delete. |

Storage adapters and exporters should prefer `metadata_trace`, `summary`, `hash`, and `behavior_mining_feature` for durable dashboards and behavior mining. `raw_prompt`, `raw_response`, `tool_args`, `output_preview`, `command_output`, and `file_diff` are short-lived debugging data: they must stay behind admin/compliance access, pass through redaction before display, and be purged rather than archived unless a separate legal hold policy applies.

| Event Type | Required Fields | Purpose |
| --- | --- | --- |
| `execution.gateway.started` | `payload.execution_observability`, `payload.mode`, `payload.output_target`, `payload.source_type` | Establish the root correlation point for an execution request across chat, board, API, MCP, CLI, and worker dispatch. |
| `execution.gateway.enqueued` | `payload.execution_observability`, `payload.queue_job_id`, `payload.mode`, `payload.output_target` | Link gateway-created run/cycle records to the queue job accepted by workers. |
| `execution.gateway.completed` | `payload.execution_observability`, `payload.mode` | Mark terminal gateway success and link any output handler result. |
| `execution.gateway.failed` | `payload.execution_observability`, `payload.mode`, `payload.error` | Preserve failure context with bounded, sanitized error text. |
| `chat.trace.started` | `payload.trace_id`, `payload.span_id`, `payload.chat_trace` | Establish the root chat reply trace for routing, context, deterministic answers, LLM generation, persistence, streaming, and execution handoff spans. |
| `chat.trace.completed` | `payload.trace_id`, `payload.span_id`, `payload.latency_ms`, `payload.chat_trace` | Mark successful chat reply completion and link final reply metrics to the root chat trace. |
| `chat.trace.failed` | `payload.trace_id`, `payload.span_id`, `payload.latency_ms`, `payload.error_class` (wrapper, often `RuntimeError`), `payload.provider_error_class` (SDK/provider, e.g. `APITimeoutError` when streamed), `payload.chat_trace` | Preserve failed chat reply context with sanitized error details and optional execution observability correlation. |
| `chat.span.completed` | `payload.trace_id`, `payload.span_id`, `payload.parent_span_id`, `payload.span_name`, `payload.latency_ms`, `payload.chat_trace` | Record completed child spans for routing, context, fast path, platform action, LLM generation, persistence, SSE streaming, completion, and execution handoff. |
| `chat.span.failed` | `payload.trace_id`, `payload.span_id`, `payload.parent_span_id`, `payload.span_name`, `payload.latency_ms`, `payload.error_class`, `payload.chat_trace` | Record failed child spans for chat reply phases while preserving bounded sanitized errors. |
| `chat.planning.started` | `payload.intent`, `payload.source_counts` | Begin LLM-planned targeted workspace fetch for `workspace_prioritize` intents. |
| `chat.planning.completed` | `payload.queries_planned`, `payload.rationale`, optional `payload.project_ids_in_plan`, `payload.project_ids_in_inventory_count`, **`payload.planner_latency_ms`**, **`payload.planner_attempts`**, **`payload.planner_model_id`** | Planner produced a bounded fetch plan; planner timing separates synthesis latency from Phase B planning. |
| `chat.planning.failed` | `payload.reason` (`invalid_or_empty_plan`, `planner_timeout`, `planner_error`), optional `payload.error_class`, `payload.error_message`, optional **`payload.planner_latency_ms`**, **`payload.planner_attempts`**, **`payload.planner_model_id`** | Planner produced no usable plan, timed out, or raised; distinguishes JSON/validation gaps from provider/timeouts. |
| `conversation_reply.generated` | `payload.user_message_id`, `payload.source_counts`, `payload.answer_path`, `payload.used_targeted_fetch`, `payload.composed_sources_count`, optional `payload.project_ids_in_plan`, `payload.project_ids_in_inventory_count`, `payload.rows_per_project`, optional **`payload.fairness_mode`**, **`payload.projects_activity_tiers`**, **`payload.disclosure_required`**, **`payload.planner_latency_ms`**, **`payload.planner_attempts`**, **`payload.planner_model_id`** when targeted fetch ran, plus existing routing/context fields. **`answer_path`** values include `deterministic`, `llm`, `platform_action`, `llm_followup_bypass` (referential follow-up bypass of generic clarification), and `capability.agent_execution` (static capability fact answered without LLM). When `answer_path=capability.agent_execution`, **`payload.capability_answer`** is also present with sub-keys `feature_flag` (string or null), `related_work_item_count` (int), and `related_work_items` (array of `{id, title, status}` objects). | Correlate replies with user turns and workspace composition without joining `chat.context.source_count`. |
| `chat.targeted_fetch.completed` | `payload.rows_fetched`, `payload.queries_run`, optional `payload.rows_per_project`, `payload.distinct_projects_in_results`, **`payload.fairness_mode`**, **`payload.projects_activity_tiers`**, **`payload.disclosure_required`** | Executor finished `BoardService.list_work_items` for planned queries; activity tiers gate balanced vs disclosure synthesis policy. |
| `chat.targeted_fetch.failed` | `payload.error_class` | Executor or board service failed during planned fetch. |
| `execution.worker.started` | `payload.execution_observability`, `payload.job_id`, `payload.retry_count` | Mark the worker claim/start point for queued execution. |
| `execution.worker.completed` | `payload.execution_observability`, `payload.job_id`, `payload.status`, `payload.duration_ms` | Mark queue worker success with the same correlation shape as gateway events. |
| `execution.worker.failed` | `payload.execution_observability`, `payload.job_id`, `payload.status`, `payload.error`, `payload.retry_count` | Preserve queue worker failure, retry, timeout, or cancellation context with sanitized error text. |
| `execution.phase.started` | `payload.execution_observability`, `payload.phase`, `payload.available_tool_count` | Mark the start of a GEP or Session Mode phase. |
| `execution.phase.completed` | `payload.execution_observability`, `payload.phase`, `payload.elapsed_ms`, `payload.tool_call_count`, `payload.phase_bci` | Mark phase completion with behavior-injection and tool-count summaries. |
| `execution.phase.failed` | `payload.execution_observability`, `payload.phase`, `payload.elapsed_ms`, `payload.error`, `payload.error_class` | Preserve phase failure context with bounded, sanitized error details. |
| `llm.generation.completed` | `payload.model_id`, `payload.provider`, `payload.operation`, `payload.latency_ms`, `payload.input_tokens`, `payload.output_tokens`, `payload.cost_usd` | Record provider-level `LLMClient` generation metrics for sync, async, and streaming calls, with optional `payload.execution_observability` when invoked inside a run. |
| `llm.generation.failed` | `payload.model_id`, `payload.provider`, `payload.operation`, `payload.latency_ms`, `payload.error_class` | Record sanitized provider-level `LLMClient` failures with credential scope, retry configuration, streaming mode, and first-token latency when known. |
| `execution.llm.completed` | `payload.execution_observability`, `payload.phase`, `payload.model_id`, `payload.input_tokens`, `payload.output_tokens`, `payload.cost_usd` | Record LLM response metrics and sanitized output preview for agent execution. |
| `execution.tool.started` | `payload.execution_observability`, `payload.tool_name`, `payload.call_id`, `payload.phase`, `payload.inputs` | Mark the start of an AgentExecutionLoop tool invocation with sanitized inputs. |
| `execution.tool.completed` | `payload.execution_observability`, `payload.tool_name`, `payload.call_id`, `payload.phase`, `payload.elapsed_ms`, `payload.output_preview` | Mark successful tool completion while preserving existing `tool.executed` compatibility events. |
| `execution.tool.denied` | `payload.execution_observability`, `payload.tool_name`, `payload.call_id`, `payload.phase`, `payload.reason`, `payload.policy` | Record permission decisions for denied tools with shared run/cycle/work-item correlation. |
| `execution.tool.failed` | `payload.execution_observability`, `payload.tool_name`, `payload.call_id`, `payload.phase`, `payload.elapsed_ms`, `payload.error`, `payload.error_class` | Preserve failed tool execution context with bounded, sanitized error details. |
| `execution.tool.performance` | `payload.execution_observability`, `payload.tool_name`, `payload.call_id`, `payload.phase`, `payload.status`, `payload.elapsed_ms` | Analyze tool latency, denial, and failure rates without output previews or created-resource data. |
| `execution.tool.business_outcome` | `payload.execution_observability`, `payload.tool_name`, `payload.call_id`, `payload.outcome_type`, `payload.resource_type`, `payload.resource_id`, `payload.outcome_ref` | Query resources or other business outcomes produced by tools independently from performance metrics. |
| `run.checkpoint_committed` | `payload.run_id`, `payload.cycle_id`, `payload.checkpoint_seq`, `payload.phase_keys[]`, optional `payload.execution_observability`, `payload.truncated` | GEP phase-output checkpoint persisted to `runs.metadata` for worker resume. |
| `tool.retry_exhausted` | `payload.run_id`, `payload.tool_name`, `payload.dependency_key`, `payload.attempts`, `payload.error_class`, optional `payload.execution_observability` | Per-tool retry budget exhausted (separate from LLM `RetryMiddleware` retries). |
| `circuit_breaker.opened` | `payload.run_id`, `payload.dependency_key`, `payload.open_until`, `payload.failure_threshold`, optional `payload.execution_observability` | Run-scoped breaker opened after repeated transport failures. |
| `circuit_breaker.half_open` | `payload.run_id`, `payload.dependency_key`, optional `payload.execution_observability` | Breaker allows a probe attempt (reserved for future half-open probes). |
| `circuit_breaker.closed` | `payload.run_id`, `payload.dependency_key`, optional `payload.execution_observability` | Breaker reset after successful call. |
| `api.http.completed` | `payload.execution_observability`, `payload.route`, `payload.method`, `payload.status_code`, `payload.elapsed_ms`, optional `payload.path` | Sampled REST request latency and status for API dashboards (low-cardinality `route`; see **Surface implementation status**). |

Tool/action analytics should query `*.performance` events for latency, status, retries, and error classes. Product/business analytics should query `*.business_outcome` or governed audit `metadata.business_outcome` for created resources, replay audit URNs, and outcome refs.

#### Fast Chat Query Planner Payload

When `feature.chat_query_planner` answers a reply, `conversation_reply.generated` sets `answer_path="chat_query_planner"` and includes compact `payload.chat_query_plan` metadata:

- `operation`, `resource_type`, `latency_tier`, and `confidence` from the validated typed plan.
- `validation_result` and bounded `validation_reason` from deterministic validation.
- `planner_latency_ms`, `planner_source`, and `fallback_reason` for timeout/fallback tuning.
- `retrieval_count` and `render_path` for executor/renderer debugging.

The event intentionally omits raw resource text, full planner prompts, and work item descriptions. Source rows remain in the reply's persisted structured payload subject to the same workspace access and observability redaction policies.

### Observability Access Views

Added for `GUIDEAI-1123` and enforced for runtime analytics in `GUIDEAI-1113`. Query surfaces that expose execution telemetry must pass events through `amprealize.observability_access.filter_observability_event()`, `amprealize.observability_analytics.GovernedObservabilityQueryService`, or an equivalent warehouse view before returning data to users. The access tiers are:

| Tier | Payload Access | Intended Use |
| --- | --- | --- |
| `viewer` | Aggregates, counts, status, and correlation metadata only. Raw prompts, tool inputs, full outputs, command output, and diffs are redacted. | Product/status dashboards and work item trace summaries. |
| `data_analyst` | Same restricted-field redaction as viewer, with queryable aggregate dimensions and preserved `execution_observability` context. | Analytics dashboards and trend investigations. |
| `admin` | Sanitized restricted payloads, with credential-like keys and values still redacted. | Operational debugging and trusted project administration. |
| `compliance` | Sanitized restricted payloads, with credential-like keys and values still redacted. | Audit review and evidence collection. |

High-cardinality dashboard summaries should use bounded series output like `summarize_observability_events(max_series=...)`: include event totals, unique run counts, top event types/surfaces, truncation counts, and small filtered samples. Do not return unbounded trace IDs, span IDs, prompts, tool arguments, or output previews to aggregate dashboards.

Actor roles resolve to access tiers before query execution. Admin/owner roles map to `admin`; compliance/auditor roles map to `compliance`; analyst/product roles map to `data_analyst`; unknown/member/student roles default to `viewer`. Runtime list queries should cap record output, report truncation, and apply the same restricted-field policy as dashboard summaries.

`GUIDEAI-1112` exposes the first REST query contracts for these views: `POST /api/v1/observability/events` returns filtered event records with `access_tier`, `count`, `truncated`, and query metadata; `POST /api/v1/observability/dashboard` returns bounded aggregate summaries with `event_count`, `unique_run_count`, top event types/surfaces, truncation counts, and filtered samples. Both endpoints use the same request shape: `event_types[]`, optional `run_id`, `limit`, and `max_series`.

`GUIDEAI-1114` reuses the same governed query boundary for chat-powered observability questions. `ObservabilityChatAnswerService` converts common natural-language questions into bounded list or summary queries, and `ConversationReplyService` stores the result as a deterministic direct answer with `structured_payload.card_kind = "observability_analysis"`, `access_tier`, trace steps, and filtered source rows. Viewer and data-analyst chat answers must not expose restricted payload keys such as raw prompts, tool inputs, output previews, or command output.

### E4 Domain Events (Knowledge Pack, BCI, Reflection)

Added as part of Epic E4 — Learning Loop, Analytics, and Governance (AMPREALIZE-278 / T4.1.1).
Typed payloads live in `amprealize/telemetry_events.py`; JSON Schemas under `schema/telemetry/v1/`.

| Event Type | Required Fields | Purpose |
| --- | --- | --- |
| `pack.activated` | `payload.pack_id`, `payload.pack_version`, `payload.workspace_id`, `payload.surface` | Track knowledge-pack adoption and workspace coverage. |
| `pack.deactivated` | `payload.pack_id`, `payload.workspace_id`, `payload.surface` | Track pack lifecycle and churn. |
| `pack.overlay_applied` | `payload.pack_id`, `payload.overlay_kind` | Measure overlay rule effectiveness per surface/role/task. |
| `bci.retrieval_completed` | `payload.top_k`, `payload.behaviors_returned[]`, `payload.latency_ms`, `payload.strategy` | Measure retrieval quality, latency, and strategy distribution. |
| `bci.injection_completed` | `payload.behaviors_count`, `payload.token_estimate`, `payload.latency_ms` | Track injection performance, token budget, and pack utilisation. |
| `bci.citation_validated` | `payload.valid_count`, `payload.invalid_count` | Evaluate adherence accuracy—feeds accuracy dashboard. |
| `reflection.candidate_extracted` | `payload.candidate_id`, `payload.confidence`, `payload.pattern_id`, `payload.source_trace_ids[]`, `payload.extraction_job_id` | Track reflection pipeline yield and quality while preserving trace-analysis provenance for review joins and dashboards. |
| `reflection.candidate_approved` | `payload.candidate_id`, `payload.auto_approved` | Measure approval rates and auto-approval confidence calibration. |
| `reflection.candidate_rejected` | `payload.candidate_id`, `payload.rejection_reason` | Measure rejection reasons and review outcomes for behavior-candidate dashboards. |

`GUIDEAI-1097` extends `reflection.candidate_extracted` with optional `pattern_id`, `source_trace_ids`, `extraction_job_id`, and `execution_observability` so candidate review records can join back to trace-analysis jobs and canonical observability traces without depending on markdown-only audit artifacts. Auto-reflection persists the same provenance metadata alongside `source_run_id` and `execution_observability`. Review decisions now emit both approval and rejection events with inherited provenance context so dashboard layers can report approval rate, rejection reasons, and downstream lifecycle outcomes from typed telemetry instead of only storage-side metadata.

`PostgresTelemetrySink` now projects `reflection.candidate_extracted`, `reflection.candidate_approved`, and `reflection.candidate_rejected` into `observability_records` as canonical `behavior_candidate` rows. That makes `observability_behavior_candidate_lifecycle` a live projection over stored observability records rather than a contract-only view definition.

**Runtime projections (Postgres/Timescale telemetry warehouse)** — `PostgresTelemetryWarehouse._project_event` also materializes:

| Telemetry `event_type` | `observability_records.kind` | Typed table |
| --- | --- | --- |
| `execution.gateway.started`, `execution.gateway.enqueued`, `execution.gateway.completed`, `execution.gateway.failed`, `execution.gateway.research_completed` | `event` | — |
| `execution.llm.completed` | `generation` | `observability_generations` (when the table exists; telemetry Alembic revision `telemetry_obs_generations`) |
| `llm.generation.completed`, `llm.generation.failed` | `generation` | `observability_generations` |
| `behaviors.search_performed`, `behaviors.task_retrieval_with_role`, `behaviors.task_context_retrieved`, and other `behaviors.*` product events | `event` (`phase=behaviors`) | — |

Correlation uses envelope `run_id` / `session_id` on `telemetry_events` plus `payload.execution_observability` inside projected rows. Completed LLM agent steps also append a row to `execution_traces` via `TelemetryClient.record_completed_execution_trace` when using `PostgresTelemetrySink`. Gateway background execution opens a root span (`execution.gateway.run`) through `start_span` / `end_span` on the same sink.

### Postgres warehouse: E2E trace stitching (join keys)

**Source of truth:** `telemetry_events` stores every emitted event. `PostgresTelemetryWarehouse._project_event` (in `amprealize/storage/postgres_telemetry.py`) projects selected types into `observability_records` and typed tables (`observability_generations`, `observability_tool_calls`, …).

| What you are stitching | Primary join keys | Notes |
| --- | --- | --- |
| **Conversation-scoped raw stream** | `telemetry_events.session_id = <conversation_uuid>` | Chat-aligned emitters set top-level `session_id` to `execution_observability.conversation_id` (e.g. `LLMClient` `llm.generation.*`, `BehaviorService` `behaviors.*` via `telemetry_session_id`). |
| **Work-item / execution runs** | `telemetry_events.run_id`; `payload.execution_observability.run_id` | Same run id on gateway, worker, phase, tool, and agent LLM events when EO is attached. |
| **Trace / span graph** | `observability_records.trace_id`, `span_id`, `parent_span_id` | EO may carry `trace_id` / `span_id`; chat events use `payload.trace_id` / `payload.span_id` or `payload.chat_trace.*`. |
| **MCP tool calls** | `payload.trace_id` = `mcp:{debug_trace}` on `execution.tool.*`; `payload.execution_observability.request_id` = same suffix; `observability_tool_calls.trace_id` | Correlates denied/completed/failed/performance pairs for one invocation. `payload.execution_observability.conversation_id` when tools pass `conversation_id` or `_session.conversation_id`. |
| **Token-level LLM (`LLMClient`)** | Event types `llm.generation.completed` / `llm.generation.failed`; typed row `observability_generations` keyed by `record_id` = `event_id` | `session_id` on the event mirrors `execution_observability.conversation_id` when present. Payload carries `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`. |
| **Behaviors retrieval** | Events `behaviors.search_performed`, `behaviors.task_retrieval_with_role`, `behaviors.task_context_retrieved`, … | `session_id` should be the conversation id when callers pass `telemetry_session_id` into `BehaviorService`. Projected `observability_records` use `kind=event`, `phase=behaviors`. |

**Typical union for one chat turn:** `chat.trace.*`, `chat.span.*`, `chat.planning.*`, `chat.targeted_fetch.*`, `conversation_reply.generated`, `llm.generation.*`, `behaviors.*` (with session wired), MCP `execution.tool.*` (`surface: mcp`), plus governed audit `governed_chat.audit_record` / `session.tool_call` where enabled.

**SQL examples:**

```sql
-- Raw events for one conversation (fast path)
SELECT event_type, event_timestamp, run_id, session_id
FROM telemetry_events
WHERE session_id = '<conversation_uuid>'
ORDER BY event_timestamp;

-- Projected generations for that conversation
SELECT g.model_id, g.input_tokens, g.output_tokens, g.latency_ms, g.status
FROM observability_generations g
JOIN observability_records r
  ON r.record_id = g.record_id AND r.record_timestamp = g.record_timestamp
WHERE r.conversation_id = '<conversation_uuid>';
```

#### Deployment prerequisite: observability DDL on the telemetry Postgres

`PostgresTelemetryWarehouse._project_event` runs **after** each insert into `telemetry_events` and issues separate `INSERT`s into **`observability_records`** and, for matching event types, typed tables such as **`observability_generations`**, **`observability_tool_calls`**, and **`observability_outcomes`**. If the telemetry database has only the legacy hypertable stack (`telemetry_events`, `execution_traces`, fact tables) and **not** the observability relations, those projection statements **fail at runtime** (the raw event row may still land in `telemetry_events` depending on transaction boundaries—operators should treat schema drift as a blocking misconfiguration).

**What to apply:** run the **telemetry** Alembic environment to **head** on the DSN used by `AMPREALIZE_TELEMETRY_PG_DSN` / `create_sink_from_env` for `PostgresTelemetrySink`. Revision sources live under `migrations_telemetry/versions/`, including at minimum:

| Revision file (excerpt) | Purpose |
| --- | --- |
| `20260428_observability_records.py` | Canonical `observability_records` table |
| `20260501_observability_generations.py` (`revision = telemetry_obs_generations`) | `observability_generations` typed table |
| `20260505_telemetry_observability_typed_tables_views.py` | Additional typed tables and dashboard-oriented views |
| `20260505_telemetry_observability_analytics.py` | Analytics helpers |

Core app migrations under `migrations/versions/` may also include Timescale packaging (e.g. `20260428_add_observability_timescale_storage.py`) when the same host doubles as the observability profile; keep the **telemetry** chain aligned with the Git revision that ships `amprealize/storage/postgres_telemetry.py`.

**Dual-repo (`amprealize` + `amprealize-enterprise`):** both distributions share the same projection code path. Any Postgres used as the telemetry sink for either build **must** carry the **same** observability schema revision set, or disable the Postgres sink until migrations are applied.

### E4 Quality Gate & Feature Flag Events

Added as part of Epic E4 — Story 4.3 (Quality Gates) and Story 4.4 (Operational Readiness).

| Event Type | Required Fields | Purpose |
| --- | --- | --- |
| `quality_gate.evaluated` | `payload.domain`, `payload.gate_name`, `payload.passed`, `payload.score`, `payload.threshold` | Track quality gate pass/fail rates and score distributions per domain. |
| `quality_gate.regression_detected` | `payload.domain`, `payload.metric`, `payload.baseline`, `payload.current`, `payload.delta` | Alert on regressions caught by CI quality gates. |
| `benchmark.run_completed` | `payload.corpus_id`, `payload.task_count`, `payload.pass_rate`, `payload.avg_token_savings` | Track benchmark corpus execution outcomes. |
| `comparison.completed` | `payload.variant_a`, `payload.variant_b`, `payload.winner`, `payload.p_value` | Record A/B comparison harness results. |
| `feature_flag.evaluated` | `payload.flag_name`, `payload.scope`, `payload.result`, `payload.flag_type` | Track feature flag evaluation frequency and outcomes. |
| `feature_flag.changed` | `payload.flag_name`, `payload.old_value`, `payload.new_value`, `payload.actor` | Audit trail for flag configuration changes. |
| `pack.bootstrapped` | `payload.workspace_path`, `payload.profile`, `payload.pack_id`, `payload.storage_backend` | Track pack bootstrap adoption for existing workspaces. |
| `pack.rollback_completed` | `payload.workspace_path`, `payload.pack_id` | Track pack rollback events. |

### Governed Chat Audit Events

Added for `guideai-1053`. These events are emitted from append-only governed chat audit records and must never include raw secrets or unbounded user payloads.

| Event Type | Required Fields | Purpose |
| --- | --- | --- |
| `session.tool_call` | `payload.run_id`, `payload.tool_name`, `payload.call_id`, `payload.decision`, `payload.elapsed_ms`, `payload.target_resources[]`, `payload.execution_observability` | Preserve Session Mode tool audit details with shared run/cycle/work-item correlation, sanitized args, bounded output previews, and error classes. |
| `governed_chat.audit_record` | `payload.audit_id`, `payload.event_type`, `payload.user_id`, `payload.action`, `payload.decision`, `payload.target_resources[]` | Preserve governed chat decisions and actions for review, including intent classification, scope resolution, policy decisions, tool calls, approvals, denials, and execution starts. Tool-call records may also include `payload.execution_observability` for run/cycle/work-item correlation. |

`payload.decision` uses `allow`, `review_required`, `denied`, `error`, or `recorded`. `review_required` and `denied` records are queryable through `GovernedChatAuditLogger.denied_or_review_required()` for security review and operator follow-up. `metadata`, target resources, tool args, output previews, and execution observability context are sanitized before emission, with credential-like values redacted and long strings truncated.

### Surface implementation status (GUIDEAI-1193)

| Surface / path | `execution.tool.*` (EO envelope) | HTTP / performance | `execution.worker.*` | Notes |
| --- | --- | --- | --- | --- |
| **MCP** `tools/call` | **Yes** — `amprealize.mcp_server.MCPServer` emits `execution.tool.completed`, `denied` (rate limit), `failed` (timeout/exception), and `execution.tool.performance` with `ExecutionObservabilityContext` (`surface: mcp`, `work_item_id` / `project_id` from tool args or session, else `-`). | N/A (stdio) | N/A | Opt out: `AMPREALIZE_MCP_TOOL_TELEMETRY=false`. |
| **REST API** | N/A (not agent tool loop) | **Sampled** — `api.http.completed` from middleware when `AMPREALIZE_API_HTTP_TELEMETRY_SAMPLE_RATE` in `(0,1]`. Excludes `/health`, `/metrics`, `/docs`, `/openapi.json`, `/redoc`, `/favicon.ico`. | N/A | Low-cardinality `route` (OpenAPI template when resolved, else path with UUID/numeric segments replaced by `{id}`). |
| **Execution worker** | N/A (worker does not emit per-tool events) | N/A | **Yes** — `execution.worker.started` / `completed` / `failed` via `_emit_worker_event` with `execution_observability` from job payload (see `ExecutionWorker._observability_context_from_job`). | Queue job correlation: `queue_job_id` in EO. |
| **Agent loop + `ToolExecutor`** | **Yes** — in-process tools emit full `execution.tool.*` when `ToolExecutor` has observability context set by `AgentExecutionLoop` (`set_observability_context`). | N/A | N/A | Chat / work-item runs share the same EO fields on tool events. |
| **LLM / chat** | N/A for raw LLM; tool events follow chat/execution paths above. | `llm.generation.*`, `chat.*`, `execution.llm.*` per tables above. | N/A | Governed query path: `GovernedObservabilityQueryService`. |

**Out of scope for this matrix:** OTLP or third-party trace export transport (see **GUIDEAI-1195**).

## Storage & Pipeline
1. **Ingestion:**
   - Clients emit events via gRPC/HTTP to `TelemetryService`.
   - Events validated against JSON Schema (versioned under `schema/telemetry/`).
2. **Processing:**
   - Write-once append to Kafka topic `telemetry.events` with schema registry.
   - Stream processors project into OLAP warehouse (Snowflake) tables `fact_events`, `fact_behaviors`, `fact_compliance`.
3. **Cold Storage:**
   - Daily roll-up archived to S3-compatible bucket with WORM policy.
4. **Access Control:**
   - Role-based views: Compliance (full), Product (aggregates), Engineering (operational metrics).

## Retention Policy
| Data Tier | Retention | Notes |
| --- | --- | --- |
| Hot (Kafka) | 7 days | Supports replay for incident response. Raw and restricted fields should be minimized even in hot storage. |
| Warm (Warehouse) | 30 days to 3 years by data class | Raw/restricted classes expire in 30 days by default and never beyond 90 days; metadata, summaries, hashes, and behavior-mining features can support trend analysis. |
| Cold (WORM object store) | Up to 7 years by data class | Only metadata, summaries, hashes, and behavior-mining features are archived by default. Raw prompts/responses, tool args, output previews, command output, and file diffs are deleted unless a legal hold policy overrides the default. |

Deletion requests (GDPR) are executed by anonymizing actor PII for durable metadata/summary/hash/behavior-mining classes and deleting raw or restricted debugging classes; log via `amprealize record-action`.

## Monitoring & Quality
- Metrics: `telemetry_ingest_qps`, `telemetry_validation_errors_total`, `telemetry_pipeline_lag_seconds`.
- Alerts: validation error rate > 0.5% (warn), pipeline lag > 120s (page), warehouse load failures.
- Weekly schema drift report compares live payloads against stored schema; deviations trigger update workflow in `AGENT_ENGINEERING.md`.

## Implementation Tasks
- Generate schemas in `schema/telemetry/v1/*.json`.
- Implement TelemetryService ingestion endpoint (part of MCP server) with request signing.
- Configure Kafka topic and connector to warehouse with encryption at rest.
- Document querying patterns in developer guide (`docs/analytics/telemetry_queries.md`).

## Owners & Dependencies
- **Owners:** Engineering (Telemetry), Compliance (retention policy review), Product Analytics (reporting dashboards).
- **Dependencies:** MCP server ActionService linkage, warehouse infrastructure, IAM policies for least privilege.
