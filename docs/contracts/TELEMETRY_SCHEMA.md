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
| `action_recorded` | `payload.artifact_path`, `payload.summary`, `payload.behaviors_cited[]` | Ensure reproducibility logs are complete. |
| `compliance_step_recorded` | `payload.checklist_step`, `payload.status`, `payload.evidence_uri` | Demonstrate 95% compliance coverage. |

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
| `reflection.candidate_extracted` | `payload.candidate_id`, `payload.confidence` | Track reflection pipeline yield and quality. |
| `reflection.candidate_approved` | `payload.candidate_id`, `payload.auto_approved` | Measure approval rates and auto-approval confidence calibration. |

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
| Hot (Kafka) | 7 days | Supports replay for incident response. |
| Warm (Warehouse) | 3 years | Required for PRD metrics trending and audits. |
| Cold (WORM object store) | 7 years | Meets SOC2/GDPR evidence requirements; immutable storage. |

Deletion requests (GDPR) executed via anonymization job that strips actor PII while retaining aggregate metrics; log via `amprealize record-action`.

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
