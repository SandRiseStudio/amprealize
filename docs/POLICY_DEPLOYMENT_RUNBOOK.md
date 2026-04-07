# Policy Deployment Runbook

> Applies to AgentAuth policy bundles stored under `schema/policy/agentauth/` and their downstream consumers (CLI, REST, MCP, IDE surfaces). Follow this runbook whenever updating contextual rules, scope mappings, or rollout annotations to maintain parity, auditability, and compliance targets defined in `PRD.md`.

## 1. Purpose & Scope
- Guarantee that every policy change is versioned, reviewed, dry-run validated, and rolled out in a staged manner across staging and production.
- Preserve evidence trails for SOC2/GDPR coverage (95% compliance) and reproducibility commitments linked to ActionService (`contracts/ACTION_SERVICE_CONTRACT.md`).
- Ensure telemetry (`auth.policy.evaluate`, `auth_grant_*`) and governance artifacts (`PRD_ALIGNMENT_LOG.md`, `BUILD_TIMELINE.md`, `PROGRESS_TRACKER.md`) remain accurate after each change.

## 2. Roles & Behaviors
| Role | Responsibilities | Referenced Behaviors |
| --- | --- | --- |
| Security Strategist | Owns policy authoring, peer review, and rollback decisions. | `behavior_handbook_compliance_prompt`, `behavior_lock_down_security_surface` |
| Product Strategist | Confirms user impact, consent UX messaging, and parity with roadmap. | `behavior_update_docs_after_changes`, `behavior_curate_behavior_handbook` |
| DX / Platform Engineer | Executes GitOps pipeline, runs automated tests, updates capability evidence. | `behavior_orchestrate_cicd`, `behavior_wire_cli_to_orchestrator` |
| Compliance Agent | Verifies audit artifacts, telemetry coverage, and progress trackers. | `behavior_instrument_metrics_pipeline`, `behavior_git_governance` |

## 3. Pre-Deployment Checklist
- [ ] Run through `behavior_handbook_compliance_prompt` triggers.
- [ ] Confirm policy diffs are limited to declarative YAML under `schema/policy/agentauth/` (no inline secrets per `SECRETS_MANAGEMENT_PLAN.md`).
- [ ] Update scope catalog (`schema/agentauth/scope_catalog.yaml`) if new scopes or MFA requirements are introduced.
- [ ] Sync references in `docs/AGENT_AUTH_ARCHITECTURE.md` §§16–18 when policy semantics change.
- [ ] Sign into required environments (GitHub/GitLab + staging cluster) with MFA.
- [ ] Install repo hooks: `./scripts/install_hooks.sh`.
- [ ] Run secret scan: `amprealize scan-secrets --fail-on-findings`.
- [ ] Ensure telemetry dashboards (consent + MFA) are live to monitor `auth.policy.evaluate` latency and error rates.

## 4. Environment Matrix
| Environment | Git Branch | Deployment Target | Observability |
| --- | --- | --- | --- |
| Local validation | feature branch `security/policy-<slug>` | Rendered preview only | `pytest`, `amprealize auth policy preview` |
| Staging | `policy/staging` (protected) | AgentAuth staging service | Metrics namespace `auth.staging.*` |
| Production | `policy/main` (protected + signed commits) | AgentAuth production cluster | Metrics namespace `auth.prod.*` + WORM audit logs |

## 5. Deployment Flow
1. **Plan & Ticketing**
   - File a change request describing motivation, impacted tools/scopes, and rollback plan.
   - Link to behavior references and PRD metric impact (e.g., token savings vs. new safeguards).
   - Assign Security Strategist (DRI) and Product Strategist (approver).
2. **Author Policy Change**
   - Branch from `main`: `git checkout -b security/policy-<slug>`.
   - Edit `schema/policy/agentauth/bundle.yaml`; update version tag (`policy-major.minor.patch`).
   - If scope catalog or consent copy shifts, update corresponding docs and SDK fixtures.
   - Commit message format: `policy: <short summary>` and cite behaviors in PR body.
3. **Local Validation**
   - Run formatting check: `yamllint schema/policy/agentauth/bundle.yaml` (install via `pipx` if needed).
   - Execute contract tests: `pytest tests/test_agent_auth_contracts.py` (and future `tests/test_policy_contracts.py`).
   - Preview change:
     ```bash
     amprealize auth policy preview \
       --bundle schema/policy/agentauth/bundle.yaml \
       --environment staging \
       --output tmp/policy-preview.json
     ```
   - Attach preview artifact to PR; ensures `auth.policy.evaluate` diffs are visible for review.
4. **Peer Review & Approvals**
   - Require at least two approvals: Security Strategist + Product Strategist.
   - Compliance agent verifies GitOps plan, telemetry hooks, and ActionService evidence logging plan.
   - Document dry-run results in PR discussion, including key metrics deltas.
5. **Stage via GitOps**
   - Merge into `policy/staging` using protected branch workflow (`behavior_orchestrate_cicd`).
   - GitOps controller (ArgoCD/Flux) applies bundle to staging cluster; monitor deployment logs.
   - Validate staging metrics: `auth.policy.evaluate_latency_ms`, `auth.policy.decision_denied_total`.
   - Run smoke tests:
     ```bash
     amprealize auth ensure-grant --tool actions.replay --scope agentauth.manage --environment staging
     ```
   - Record ActionService evidence:
     ```bash
     amprealize record-action \
       --artifact schema/policy/agentauth/bundle.yaml \
       --summary "Promote policy <version> to staging" \
       --behavior behavior_orchestrate_cicd \
       --behavior behavior_instrument_metrics_pipeline
     ```
6. **Promotion Gate**
   - Verify no staging regression for 24 hours or agreed window.
   - Confirm dashboard snapshots stored under `docs/analytics/consent_mfa_snapshot.md` if metrics shift.
   - Update PR with staging validation report and set Production approval checklist to ✅.
7. **Production Deployment**
   - Fast-forward merge staging tag into `policy/main` using signed commit.
   - GitOps pushes new bundle to production; monitor `auth.prod.*` metrics + WORM audit logs.
   - Notify #security-ops and #product-guided-agents Slack channels with deployment summary, linking ActionService `action_id`.
8. **Post-Deployment Verification**
   - Confirm telemetry ingestion in MetricsService (no dropped events) and dashboards reflect new policy version hash.
   - Update `PRD_ALIGNMENT_LOG.md`, `BUILD_TIMELINE.md`, `PRD_NEXT_STEPS.md`, and `PROGRESS_TRACKER.md` with completion evidence.
   - Close change ticket with references to action logs, telemetry snapshots, and reviewer approvals.

## 6. Rollback Procedure
1. **Trigger Conditions**: Elevated deny/allow errors, unexpected consent prompts, or security incident flagged by anomaly detection.
2. **Immediate Response**
   - Notify incident channel, create hot fix branch `revert/policy-<version>`.
   - Run:
     ```bash
     amprealize auth policy rollback --target schema/policy/agentauth/bundle.yaml --environment production
     ```
     *(Until CLI command ships, manually revert Git tag to prior semantic version and push to `policy/main`)*
   - Confirm rollback success through `auth.policy.evaluate` telemetry and ActionService log.
3. **Post-Rollback Tasks**
   - Record `amprealize record-action` summarizing rollback cause and next steps.
   - Update `PRD_ALIGNMENT_LOG.md` with incident notes and mitigation.
   - Schedule retrospective and capture learnings in `docs/AGENT_AUTH_ARCHITECTURE.md` §17 footnotes.

## 7. Evidence & Reporting
- **ActionService Logging**: Every staging/production promotion and rollback must be captured via `amprealize record-action` referencing relevant artifacts.
- **Telemetry Snapshots**: Export metrics (success rate, decision latency) before and after change, attaching charts to change ticket.
- **Progress Tracking**: Update `PROGRESS_TRACKER.md` entry "Policy deployment runbook executed" with new action IDs once CLI parity for logging is live.
- **Audit Logs**: Ensure WORM storage records `auth.policy.evaluate` events with the new version hash; include links in compliance reports.

## 8. Appendix
- **Related Documents**: `docs/AGENT_AUTH_ARCHITECTURE.md`, `schema/policy/agentauth/bundle.yaml`, `schema/agentauth/scope_catalog.yaml`, `docs/CONSENT_UX_PROTOTYPE.md`, `docs/COMPLIANCE_CONTROL_MATRIX.md`.
- **Telemetry Fields**: `event_type`, `policy_version`, `decision`, `scope`, `mfa_verified`, `actor_role`, `surface`, `action_id`.
- **Checklist Template** (copy into change ticket):
  1. [ ] Ticket approved by Security & Product.
  2. [ ] Dry-run artifact attached.
  3. [ ] Staging ActionService record created.
  4. [ ] Staging metrics monitored for 24h.
  5. [ ] Production deployment announced.
  6. [ ] Production ActionService record created.
  7. [ ] Telemetry snapshots archived.
  8. [ ] Governance docs updated.
- **Future Enhancements**: Automate `amprealize auth policy preview` + `rollback` commands in CI, add contract tests for bundle schema, and integrate incident bot that opens change tickets when policy telemetry anomaly occurs.
