# Audit Log Storage Plan

## Objectives
- Guarantee immutable, tamper-evident storage for compliance evidence and PRD metric reporting (95% run coverage).
- Provide consistent APIs across Platform/UI, API, CLI, and MCP for querying audit events.
- Support reproducibility by linking audit entries with ActionService records and telemetry events.

## Storage Architecture
1. **Primary Store (Hot):**
   - Append-only Postgres table `audit_log_events` with `INSERT`-only permissions.
   - Partitioned by week; retention 30 days for rapid access.
2. **Immutable Archive (Warm):**
   - AWS S3 (or compatible) bucket with Object Lock (WORM) + versioning enabled.
   - Data replicated to secondary region.
   - Retention 7 years to satisfy SOC2/GDPR evidence requirements.
3. **Indexing Layer:**
   - Elasticsearch/OpenSearch cluster indexing metadata for search (`run_id`, `action_id`, `actor`, `surface`).
   - Read-only access for analytics dashboards.

## Data Model
| Field | Type | Notes |
| --- | --- | --- |
| `event_id` | UUID | Generated server-side. |
| `timestamp` | RFC3339 | UTC. |
| `actor_id` | UUID | User or service principal. |
| `actor_role` | enum | Strategist, Student, Teacher, Admin, Service. |
| `surface` | enum | web, cli, vscode, api, mcp. |
| `action_id` | UUID? | Links to ActionService record. |
| `run_id` | UUID? | Links to RunService record. |
| `checklist_step` | string? | Populated for compliance events. |
| `event_type` | enum | plan_created, execution_update, reflection_submitted, action_recorded, compliance_step_recorded, audit_admin_event. |
| `payload_hash` | string | SHA-256 hash of serialized event payload stored in S3. |
| `s3_uri` | string | Pointer to immutable object. |
| `signature` | string | Ed25519 signature to detect tampering. |

## Write Path
1. Client actions trigger audit events via MCP/APIs.
2. Events serialized (JSON), hashed, signed, and written to Postgres within transaction.
3. Background job batches events every minute to S3 (gzip JSON) with metadata copy to OpenSearch.
4. Confirmation logged via `amprealize record-action` when configuration changes (retention updates, rotation).

## Read Path
- Platform UI and CLI call `auditLogs.list` (MCP tool) to page through events by filters.
- Access controlled by RBAC:
  - Strategist/Student: only runs they participated in.
  - Compliance/Admin: full dataset.
  - Service principals: limited to automation contexts.

## Security Controls
- Postgres role has `INSERT` only (no `UPDATE`/`DELETE`).
- S3 bucket policy denies delete/version overwrite for compliance roles; only platform automation can run lifecycle transitions.
- Signatures rotated quarterly; public keys stored in `config/audit_signing_keys/` with change logged via ActionService.
- Quarterly immutability verification job compares Postgres metadata with S3 content hash.

## Monitoring
- Metrics: `audit_events_written_total`, `audit_archive_lag_seconds`, `audit_verification_failures_total`.
- Alerts when archive lag > 5 minutes or verification job fails.

## Implementation Tasks
- Create database migration for `audit_log_events` table.
- Implement MCP tool `auditLogs.list` + REST `/v1/audit-logs` with filtering & pagination.
- Configure S3 bucket with Object Lock + lifecycle policy (transition to Glacier after 3 years).
- Build verification job (Lambda / Cloud Run) and report status in telemetry pipeline.

## Dependencies
- ActionService (for linking actions), Telemetry pipeline (for cross referencing), IAM policies for storage access, compliance review process.
