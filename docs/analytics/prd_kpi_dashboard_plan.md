# PRD KPI Dashboard Implementation Plan

> **Owner:** Product Analytics (Agent Product)
> **Last Updated:** 2025-10-16
> **Milestone Target:** Milestone 1 (6-week gate)

## 1. Objectives
- Deliver production dashboards that track the four PRD success metrics:
  1. **Behavior reuse %** – share of runs that cite at least one handbook behavior.
  2. **Token savings %** – relative reduction in output tokens vs. baseline chains-of-thought.
  3. **Task completion rate** – percent of workflow runs that reach a terminal success state.
  4. **Compliance coverage %** – ratio of required checklist steps with recorded evidence.
- Provide drill-down views for Strategist → Teacher → Student pipeline to surface bottlenecks.
- Ensure telemetry parity across Web, CLI, VS Code, API, and MCP surfaces.

## 2. Data Requirements
| Metric | Primary Events | Derived Fields | Notes |
| --- | --- | --- | --- |
| Behavior reuse % | `behavior_retrieved`, `plan_created`, `execution_update`, `action_recorded` | `run_id`, `payload.behavior_ids[]`, `payload.behaviors_cited[]`, `payload.token_counts` | Need consistent behavior identifiers and run linkage. |
| Token savings % | `execution_update` (token accounting), baseline reference table | `payload.output_tokens`, `payload.baseline_tokens`, `payload.token_savings_pct` | Baseline derives from Strategist prototype runs; store in warehouse dimension. |
| Task completion rate | `execution_update` | `payload.status` (SUCCESS/FAILED/CANCELLED), `run_id` | Success defined as final `status=SUCCESS`. |
| Compliance coverage % | `compliance_step_recorded`, `plan_created` | `payload.checklist_status`, `payload.step`, `payload.status`, `payload.evidence_uri` | Require checklist metadata (required vs. optional) from ComplianceService. |

### Supporting Dimensions
- **dim_behaviors**: behavior_id, name, role_focus, version, status.
- **dim_runs**: run_id, workflow_id, initiating_surface, initiating_agent, created_at.
- **dim_workflows**: workflow_id, template_name, role_focus, milestones.
- **dim_checklists**: checklist_id, required_step_count.

## 3. Event Instrumentation Audit
| Event | Current Status | Gaps | Owner |
| --- | --- | --- | --- |
| `behavior_retrieved` | Emitted by BehaviorService CLI/MCP adapters and VS Code extension sidebar/search (2025-10-16). | — | DX + Engineering |
| `plan_created` | WorkflowService emits on run kickoff; VS Code Plan Composer emits with behavior + checklist context (2025-10-16). | — | DX |
| `execution_update` | WorkflowService `update_run_status` now emits token metrics (`output_tokens`, `baseline_tokens`, `token_savings_pct`) (2025-10-16). | — | Engineering |
| `compliance_step_recorded` | ComplianceService CLI emits. | Need REST/MCP parity post-storage migration. | Engineering + Compliance |
| `action_recorded` | ActionService parity tests cover event. | None (monitor for volume). | Engineering |

_Action Items_: backfill compliance events when checklist engine moves to persistent store. (VS Code telemetry sink and execution_update token metrics shipped 2025-10-16.)

## 4. Pipeline Architecture
1. **Collection** – Clients call `TelemetryService` (MCP control-plane) via gRPC/HTTP.
2. **Validation** – Enforce JSON Schema in `schema/telemetry/v1/*.json`; reject non-conforming payloads.
3. **Streaming** – Publish to Kafka topic `telemetry.events` with envelope metadata.
4. **Processing** – Flink job `telemetry-kpi-projector` transforms streams into:
   - `fact_behavior_usage`
   - `fact_token_savings`
   - `fact_execution_status`
   - `fact_compliance_steps`
5. **Warehouse** – Load daily snapshots into DuckDB warehouse `data/telemetry.duckdb` with schema `prd_metrics` (see `docs/analytics/prd_metrics_schema.sql`) supporting SCD for dimensions.
6. **Dashboard Layer** – Expose aggregated views via Metabase/Looker:
   - KPI overview (current week vs. goal vs. trailing 4 weeks).
   - Surface comparison (web/cli/vscode/api/mcp).
   - Role pipeline funnel (Strategist → Teacher → Student conversion).
   - Compliance evidence explorer (filterable by checklist, run, agent).

## 5. Metric Definitions
- **Behavior Reuse %**
  - Numerator: distinct `run_id` with `plan_created.payload.behavior_ids.length > 0` or `execution_update.payload.behaviors_cited.length > 0`.
  - Denominator: total distinct `run_id` in interval.
  - Aggregation window: daily & weekly.
- **Token Savings %**
  - For each run step, compute `1 - (output_tokens / baseline_tokens)`.
  - Average per run, then across interval; exclude runs without baseline reference.
- **Task Completion Rate**
  - Numerator: runs with terminal `execution_update.payload.status = "SUCCESS"`.
  - Denominator: runs with terminal status in {SUCCESS, FAILED, CANCELLED}.
- **Compliance Coverage %**
  - Numerator: required checklist steps where latest `payload.status = "COMPLETED"` and `payload.evidence_uri` present.
  - Denominator: total required steps for the run’s checklist.

## 6. Dashboard Wireframes
1. **Executive KPI Overview** – Single page with four number tiles, sparkline trends, and goal thresholds.
2. **Behavior Usage Explorer** – Table & heatmap by role, workflow template, behavior category; includes search-to-insert conversion.
3. **Token Efficiency Drilldown** – Distribution plots, top saving behaviors, anomaly detection for regressions.
4. **Completion & Compliance Funnel** – Sankey from plan creation→execution→validation with compliance overlays.
5. **Alert Feed** – List of validation errors, pipeline lag events, compliance breaches.

## 7. Validation & QA
- Automated contract tests in `tests/test_telemetry_integration.py` extended to assert new fields.
- End-to-end smoke: trigger sample workflow run via CLI, verify Kafka topic ingestion and warehouse load (local docker-compose harness).
- CLI sink selection: `amprealize telemetry emit --sink file --telemetry-path ~/.amprealize/telemetry/events.jsonl` for JSONL exports or `--sink kafka --kafka-servers localhost:9092 --kafka-topic telemetry.events` when validating the streaming pipeline; `--sink auto` keeps the previous env-based behavior.
- Dashboard snapshot tests using Playwright to detect metric tile regressions.

## 8. Next Steps & Owners
| Task | Owner | Due | Dependencies |
| --- | --- | --- | --- |
| Implement VS Code telemetry emission | DX | ✅ Complete (2025-10-16) | Extension runtime hooks delivered |
| Add token accounting to `execution_update` | Engineering | ✅ Complete (2025-10-16) | WorkflowService BCI stats |
| Define DuckDB schema (`prd_metrics`) | Product Analytics | ✅ Complete (2025-10-16) | `docs/analytics/prd_metrics_schema.sql` |
| Build `telemetry-kpi-projector` job | Engineering | +10 days | Kafka connectors (Python prototype: `amprealize.analytics.TelemetryKPIProjector`) |
| Stand up Metabase space + seed dashboards | Product Analytics | +12 days | Warehouse schema |
| Update `PRD_NEXT_STEPS.md` + capability matrix | Product Analytics | +1 day | This plan |

## 9. Risks & Mitigations
- **Data latency** – Mitigate with pipeline lag alerts, ensure Flink job autoscaling.
- **Schema drift** – Weekly drift report with auto-created tickets via `amprealize record-action`.
- **Access control** – Implement role-scoped views; audit via ComplianceService.
- **Baseline accuracy** – Maintain baseline tokens table; refresh monthly with Strategist benchmark suite.

## 10. Artifacts & Reporting
- Track progress in `BUILD_TIMELINE.md` and `PROGRESS_TRACKER.md` under Milestone 1 analytics row.
- Log significant updates in `PRD_ALIGNMENT_LOG.md` referencing this plan.
- Once dashboards live, attach screenshot evidence to `docs/analytics/prd_kpi_dashboard_snapshots/`.
- Use `amprealize analytics project-kpi` (documented in `amprealize/cli.py`, covered by `tests/test_cli_analytics.py`) to validate telemetry JSONL exports locally before promoting warehouse loads.
