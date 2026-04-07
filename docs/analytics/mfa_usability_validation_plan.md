# MFA Re-Prompt Usability Validation Playbook

## Mission
Ensure MFA re-prompts feel consistent, fast, and trustworthy across Web, CLI, and VS Code surfaces so behavior completion stays above PRD targets while meeting compliance obligations. This playbook guides Strategist → Teacher → Student roles through validation activities that prove parity, telemetry coverage, and user trust signals ahead of Milestone 1.

## Success Criteria
- \*Behavior impact\*: Maintain ≥70% behavior reuse and ≥80% task completion during MFA-requiring flows; document deltas if MFA friction impacts these KPIs.
- \*Token savings\*: Ensure MFA prompts do not increase median token usage per task by more than 5% compared to the consent baseline.
- \*Security/compliance\*: Confirm 95% of MFA events emit required audit evidence (`audit_action_id`, `consent_request_id`, `mfa_required`, `mfa_verified`).
- \*Latency\*: Keep MFA decision latency under 12s p95 on every surface and improve CLI p95 by ≥10% versus the snapshot in `docs/analytics/consent_mfa_snapshot.md`.
- \*User sentiment\*: Collect qualitative pain points and classify blockers vs. nits; funnel blockers into `PRD_NEXT_STEPS.md`.

## Inputs & Dependencies
- Telemetry schema (`contracts/TELEMETRY_SCHEMA.md`) and AgentAuth instrumentation (`amprealize/agent_auth.py`, `web-console/dashboard/src/telemetry.ts`).
- Consent UX prototypes (`docs/CONSENT_UX_PROTOTYPE.md`, `designs/consent/mockups.md`).
- Scope catalog high-risk mapping (`schema/agentauth/scope_catalog.yaml`) and policy bundle (`schema/policy/agentauth/bundle.yaml`).
- Dashboard baseline snapshot (`docs/analytics/consent_mfa_snapshot.md`).
- Behavior handbook entries: `behavior_prototype_consent_ux`, `behavior_instrument_metrics_pipeline`, `behavior_update_docs_after_changes`.

## Validation Matrix
| Scenario | Surface | Trigger | Expected Path | Telemetry Assertions | Notes |
| --- | --- | --- | --- | --- | --- |
| Approve high-risk replay | Web | `actions.replay` with expired grant | Inline modal → MFA step → success toast | `auth_consent_prompt_shown`, `auth_consent_approved`, `mfa_required=true`, `mfa_verified=true`, decision latency ≤12s p95 | Verify snooze disabled after MFA begins. |
| Deny elevated command | CLI | `amprealize replay --run-id …` from new machine | Device code prompt → MFA challenge → denial CLI confirmation | `auth_consent_cli_prompt_rendered`, `auth_consent_cli_manual_action=deny`, `mfa_required=true`, audit log entry created | Check fallback copy for offline mode. |
| Retry with cached grant | VS Code | IDE task rerun within grant TTL | Notification → panel skip MFA | `auth_consent_vscode_panel_opened`, `auth_consent_vscode_approved`, `mfa_required=false` | Ensure telemetry still includes `consent_request_id` for audit stitching. |
| Forced re-prompt after snooze cap | Web | Third snooze on high-risk scope | Modal → forced MFA → approval | `auth_consent_prompt_shown`, `auth_consent_snoozed` (count=2 limit), `auth_consent_escalated` optional, `mfa_verified=true` | Confirm escalation policy triggers compliance alert. |
| Offline CLI | CLI | Device flow during lost connectivity | Timeout fallback → offline recovery doc link | `auth_consent_cli_timeout`, `auth_consent_cli_manual_action` absent, `mfa_verified=false` | Add log review for retries once connectivity restored. |
| API parity smoke | API | `EnsureGrant` via REST client | MFA OTP → grant issuance | `auth_consent_api_prompt_shown`, `auth_consent_api_approved`, `mfa_verified=true` | Validate parity hooks used by third-party surfaces. |
| MCP/Extension | MCP | VS Code via MCP transport | Panel approval → MFA redirect | `auth_consent_vscode_approved`, MCP bridge emits `mfa_verified` | Ensure MCP tooling records same payload as CLI/API.

## Strategist → Teacher → Student Workflow
- **Strategist**: Sequence scenarios, map required telemetry hooks, and align success criteria with PRD metrics. Update `PRD_NEXT_STEPS.md` if new follow-ups emerge.
- **Teacher**: Brief participants, share run scripts (Appendix), and ensure behavior references (`behavior_prototype_consent_ux`, `behavior_instrument_metrics_pipeline`) are cited in notes.
- **Student**: Execute scenarios, capture telemetry payloads, run dashboards, and log evidence in `PROGRESS_TRACKER.md` with action IDs or CLI transcripts.

## Telemetry & Monitoring Hooks
- Required event fields: `surface`, `agent_id`, `scopes`, `consent_request_id`, `mfa_required`, `mfa_verified`, `decision_latency_ms`, `audit_action_id`.
- Dashboard updates: add consent/MFA card deltas compared to baseline snapshot; highlight surfaces breaching latency goals.
- Alerting: configure warning if `mfa_verified=false` occurs >5% within 1h window per surface; escalate on repeated failures.
- Storage: verify audit log WORM retention captures MFA transcript references (see `contracts/AUDIT_LOG_STORAGE.md`).

## Execution Checklist
1. **Pre-flight**
   - Refresh synthetic datasets; ensure MFA enforcement flag enabled for high-risk scopes.
   - Reset telemetry caches so new events surface cleanly in the dashboard.
   - Capture baseline metrics from the dashboard (export CSV).
2. **Run Scenarios**
   - Follow Validation Matrix order; log timestamp, surface, tester, outcome.
   - Record screen captures or CLI transcripts for each failure.
   - Trigger forced re-prompts and offline flows explicitly.
3. **Telemetry QA**
   - Query analytics sink for each event; confirm schema alignment with `contracts/TELEMETRY_SCHEMA.md`.
   - Update `docs/analytics/consent_mfa_snapshot.md` with refreshed stats.
4. **Synthesis**
   - Summarize findings (latency, success rate, friction) and map to PRD KPIs.
   - File issues for blockers (`severity=high` for latency breaches or missing telemetry).
   - Update `PRD_ALIGNMENT_LOG.md`, `BUILD_TIMELINE.md`, `PROGRESS_TRACKER.md` with outcomes.

## Edge Cases & Risk Mitigations
- Handle users with hardware tokens (FIDO) by verifying `mfa_method` telemetry property and fallback flow copy.
- Ensure repeated consent denials escalate to compliance channel (`auth_consent_escalated` event) with MFA context.
- Validate timeouts gracefully prompt retry instructions without leaking device codes.
- Confirm localization placeholders cover MFA messaging across supported locales before Milestone 1.

## Parity Notes (Web/API/CLI/MCP)
- Web modal uses shared consent component; ensure API surfaces reuse the same policy copy via `ActionService` metadata.
- CLI device flow and MCP VS Code panel both rely on AgentAuth service; any schema change must be versioned and rolled out via CLI + extension updates simultaneously.
- API clients need REST + gRPC parity; test `EnsureGrant` and `PolicyPreview` endpoints when MFA is required.
- MCP tool definitions (`mcp/tools/auth.*.json`) must stay synchronized with CLI command options to preserve guided prompts.

## Reporting & Timeline
- **2025-10-16:** Kickoff and pre-flight readiness review (Strategist).
- **2025-10-18:** Execute validation matrix with internal participants; capture telemetry exports.
- **2025-10-19:** Publish findings summary, update dashboards, and finalize go/no-go recommendation for Milestone 1 gate.
- Deliverable: attach CSV exports, raw telemetry queries, and qualitative notes to `PROGRESS_TRACKER.md` evidence column once available.

## Validation Execution – 2025-10-15 Dry Run

We executed a dry-run of the playbook using the current telemetry harness and ActionService stubs to confirm instrumentation coverage ahead of the scheduled full validation window.

### Summary
- Triggered synthetic MFA-required events through the integration tests in `tests/test_telemetry_integration.py` to verify required fields (`mfa_required`, `mfa_verified`, `consent_request_id`, `audit_action_id`).
- Exercised CLI denial and replay flows via the new `amprealize` action parity commands to ensure ActionService logging still captures MFA metadata.
- Confirmed dashboards ingest consent/MFA payloads without schema drift by running the dashboard build (`npm run build` in `web-console/dashboard/`).
- Captured qualitative notes for surfaces that still require manual UX observation (flagged in the table below).

### Scenario Results
| Scenario | Surface | Status | Evidence | Follow-ups |
| --- | --- | --- | --- | --- |
| Approve high-risk replay | Web | ✅ Simulated via telemetry unit test | `tests/test_telemetry_integration.py::test_action_mfa_events` | Capture real modal latency once staging UI is wired.
| Deny elevated command | CLI | ✅ Verified CLI parity commands emit action logs with MFA metadata | `amprealize/cli.py` dry run (`record-action`/`replay-actions`) | Add manual device-flow transcript during Milestone 1 rehearsal.
| Retry with cached grant | VS Code | ⚠️ Pending manual IDE validation | Telemetry fields present in SDK stub | Schedule IDE smoke test once extension preview branch opens.
| Forced re-prompt after snooze cap | Web | ⚠️ Pending policy bundle change | Synthetic event emitted, no UI macro yet | Implement snooze counter in modal before live run.
| Offline CLI | CLI | ✅ Timeout path exercised by telemetry stub | `tests/test_telemetry_integration.py` mocked payload | Capture manual copy review for offline instructions.
| API parity smoke | API | ✅ REST schema validated | `tests/test_agent_auth_contracts.py` | Add Postman collection to appendix for partner teams.
| MCP/Extension | MCP | ⚠️ Pending MCP tool validation | `mcp/tools/auth.*.json` schema synced | Coordinate with IDE parity owners for live verification.

### Observations
- All automated hooks confirmed required telemetry fields; no schema regressions detected.
- Need staged UI walkthroughs for Web/VS Code to measure actual MFA latency and snooze behavior.
- CLI output remains concise after the new action commands; ensure documentation references the MFA denial copy once finalized.

### Next Steps
1. Schedule manual surface walkthroughs (Web, VS Code, MCP) once consent modal updates land.
2. Export updated latency snapshots from dashboard post-manual run and attach to `docs/analytics/consent_mfa_snapshot.md`.
3. File follow-up issue for snooze-cap escalation logic (`MFA-VALIDATION-04`).

## Appendices
- **Run Scripts**: Provide CLI command templates and API calls in shared internal wiki (link TBD) to avoid duplicating credentials here.
- **Telemetry Queries**: Saved queries in analytics workspace (`consent_mfa_latency_p95`, `mfa_failure_rate_by_surface`).
- **Issue Tags**: File tickets under `MFA-VALIDATION` label for tracking.

_Last updated: 2025-10-15_
