# Compliance Control Matrix

## Mission
Provide a single reference that maps our regulatory obligations (initial focus: SOC 2 and GDPR) to the Amprealize platform controls that satisfy them. This matrix helps Strategist → Teacher → Student roles confirm compliance evidence is current before each milestone gate and ensures the PRD target of 95% checklist coverage remains auditable.

## How to use this matrix
1. **Before a release** – Walk each row to confirm the documented control is still effective. If a gap exists, open a follow-up item in `PRD_NEXT_STEPS.md` and record an action (`amprealize record-action`).
2. **During audits** – Share the relevant evidence links (telemetry snapshots, policy bundles, CI artifacts) so auditors can trace controls to immutable records (`AUDIT_LOG_STORAGE.md`).
3. **After updates** – When a control changes, update this matrix, refresh `PRD_ALIGNMENT_LOG.md`, and attach the latest evidence (action IDs, dashboard exports, policy hashes).

## SOC 2 Trust Service Criteria Coverage
| Control Area | Requirement / Risk | Implementation & Owners | Evidence Links | Status |
| --- | --- | --- | --- | --- |
| Security (Logical Access) | Enforce least privilege across Web, API, CLI, IDE surfaces. | AgentAuth service with scoped grants (`amprealize/agent_auth.py`, `schema/agentauth/scope_catalog.yaml`); policies managed via GitOps (`schema/policy/agentauth/bundle.yaml`). Owners: Security + Engineering. | `docs/AGENT_AUTH_ARCHITECTURE.md` §§12-19, `tests/test_agent_auth_contracts.py`, MCP tool descriptors. | ✅ In place |
| Security (Change Management) | Track and approve production-affecting changes. | Action capture & replay pipeline (`amprealize/action_service.py`, CLI parity backlog), CI guardrails enforcing tests + secret scans. Owners: Engineering + DevOps. | `docs/README.md` runbook, `.github/workflows/ci.yml`, `tests/test_action_service_parity.py`, `tests/test_scan_secrets_cli.py`. | ✅ In place (CLI parity pending Milestone 1) |
| Availability | Maintain uptime targets for critical services (ActionService, AgentAuth, Token Vault). | SLOs + failover plan (`docs/AGENT_AUTH_ARCHITECTURE.md` §16); CI catch on regression; monitoring hooks in telemetry pipeline. Owners: Platform + Security. | `docs/AGENT_AUTH_ARCHITECTURE.md` §16, `web-console/dashboard/src/telemetry.ts`, `docs/AGENT_DEVOPS.md`. | ✅ In place |
| Processing Integrity | Ensure recorded actions are complete, accurate, timely. | Unified execution record and parity tests, behavior handbook reuse to reduce drift. Owners: Engineering. | `amprealize/action_service.py`, `tests/test_action_service_parity.py`, `AGENTS.md`. | ✅ In place |
| Confidentiality | Protect secrets and sensitive configuration. | Secrets management policy + automated scanning (`SECRETS_MANAGEMENT_PLAN.md`, `amprealize scan-secrets`). Owners: Security + Engineering. | `.pre-commit-config.yaml`, `scripts/scan_secrets.sh`, `.github/workflows/ci.yml`. | ✅ In place |
| Privacy | Respect user/agent consent and data minimization. | Consent UX + telemetry, data retention policy (`AUDIT_LOG_STORAGE.md`). Owners: Product + Compliance. | `docs/CONSENT_UX_PROTOTYPE.md`, `docs/analytics/consent_mfa_snapshot.md`, `schema/policy/agentauth/bundle.yaml`. | ✅ In place |
| Auditability | Provide immutable evidence for every run. | WORM audit storage, Progress Tracker, Build Timeline ingestion. Owners: Compliance + Platform. | `AUDIT_LOG_STORAGE.md`, `PROGRESS_TRACKER.md`, `BUILD_TIMELINE.md`. | ✅ In place |

> **Note:** Items marked "CLI parity pending" are tracked as Milestone 1 follow-ups; see `PRD_NEXT_STEPS.md` for ownership and due dates.

## GDPR Obligations Coverage
| Obligation | Implementation | Evidence | Status | Notes |
| --- | --- | --- | --- | --- |
| Lawful Basis & Consent (Art. 6, 7) | AgentAuth consent flows with telemetry + audit logs; explicit scope catalog definitions. | `docs/CONSENT_UX_PROTOTYPE.md`, `schema/agentauth/scope_catalog.yaml`, telemetry events (`auth_consent_*`). | ✅ | MFA validation playbook ensures continued consent quality. |
| Data Minimization (Art. 5) | Behavior/action logs exclude payload data; telemetry captures metadata only. | `TELEMETRY_SCHEMA.md`, `REPRODUCIBILITY_STRATEGY.md` (action taxonomy). | ✅ | Periodic schema review required each milestone. |
| Right of Access / Portability (Art. 15, 20) | Planned `actions.export` endpoint (Milestone 2); interim support via ActionService replay exports. | `ACTION_SERVICE_CONTRACT.md` (replay schema), `docs/README.md` runbook. | ⏳ Planned | Add parity tests once endpoint lands. |
| Right to Erasure (Art. 17) | Pending retention policy extension to support selective deletion with audit trail. | `AUDIT_LOG_STORAGE.md` (retention), `SECRETS_MANAGEMENT_PLAN.md` (rotation). | ⏳ Planned | Capture in PRD mid-term tasks. |
| Breach Notification (Art. 33) | Incident response flow referencing secret rotation + telemetry alerts. | `AGENT_COMPLIANCE.md`, `SECRETS_MANAGEMENT_PLAN.md`, `docs/AGENT_DEVOPS.md`. | ✅ | Alerts triggered via consent/MFA telemetry anomalies. |

## Monitoring & Review Cadence
- **Quarterly** – Compliance agent reviews this matrix and updates evidence links.
- **Before Milestone gates** – Strategist verifies "Status" column, filing issues for any "⏳ Planned" items.
- **After incidents** – Append lessons learned and control adjustments here and in `PRD_ALIGNMENT_LOG.md`.

## Related Artifacts
- `PRD.md` success metrics (95% compliance coverage).
- `agent-compliance-checklist.md` procedural steps executed per run.
- `docs/AGENT_DEVOPS.md` deployment guardrails.
- `SECRETS_MANAGEMENT_PLAN.md`, `TELEMETRY_SCHEMA.md`, `AUDIT_LOG_STORAGE.md` for underlying control definitions.
