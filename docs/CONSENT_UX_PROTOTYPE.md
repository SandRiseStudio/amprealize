# AgentAuth Consent UX Prototype & Testing Plan

## Overview
This document translates the consent UX requirements from `docs/AGENT_AUTH_ARCHITECTURE.md` §§18-19 into actionable prototypes and validation activities for Milestone 1. Each surface ships with consistent copy, telemetry hooks, and fallback flows that uphold the PRD success metrics (behavior reuse, token savings, task completion, compliance coverage).

## UX Goals
- Provide transparent context for why an agent requests access, including scopes, expiration, and behavior links.
- Minimize consent fatigue with concise copy, snooze/deferral options, and pre-approved templates.
- Capture telemetry for prompt impressions, approvals, denials, and decision latency.
- Ensure accessibility compliance (WCAG AA) across all surfaces.

## Surface Prototypes

### Web Dashboard Modal
- **Trigger:** Tool gateway blocks execution because `auth.ensureGrant` returned `CONSENT_REQUIRED`.
- **Layout:**
  1. Header with provider icon + “Agent {agent_id} needs your approval”.
  2. Scope list with plain-language descriptions sourced from `schema/agentauth/scope_catalog.yaml`.
  3. Expiration + obligations summary (e.g., “Expires in 60 minutes”, “Notifies #agent-reviews”).
  4. Behavior context card linking to the relevant handbook entry (if supplied in context).
  5. Approve / Deny primary buttons; secondary link “Remind me later (15 min)”.
- **Copy:**
  - Approve button label: “Approve and continue”.
  - Deny confirmation: “Deny request and cancel {tool_name}”.
- **Telemetry instrumentation:** Emit `auth_consent_prompt_shown`, `auth_consent_approved`, `auth_consent_denied`, `auth_consent_snoozed`, `auth_consent_details_viewed`.
  - Include `mfa_required` in prompt and decision payloads whenever scopes contain `actions.replay` or `agentauth.manage`; set `mfa_verified` once the user completes the challenge.
- **Accessibility checks:** Keyboard trap audit, screen-reader labels for scopes, contrast ratio ≥ 4.5.

### CLI Device Flow
- **Trigger:** CLI command receives `CONSENT_REQUIRED` and prints device flow instructions.
- **Layout:**
  1. Colorized block summarizing tool & scopes.
  2. Short URL + device code.
  3. Countdown timer for 5-minute SLA, refreshing every 5 seconds.
  4. Optional commands: `amprealize auth consent --approve <request-id>` and `--deny` for automation.
- **Copy:**
  - “Visit {short_url} and enter code {device_code} to approve this request.”
  - Timeout warning at 60 seconds remaining.
- **Telemetry instrumentation:** `auth_consent_cli_prompt_rendered`, `auth_consent_cli_follow_link`, `auth_consent_cli_timeout`, `auth_consent_cli_manual_action` (approve/deny via CLI command).
  - When MFA is required, display inline status (`MFA verified: yes/no`) and emit `mfa_required` fields in telemetry events.
- **Accessibility checks:** ANSI color fallback, high-contrast mode toggle, ensure logs redact device code after completion.

### VS Code Extension Panel
- **Trigger:** Notification toast with CTA “Review consent request”.
- **Layout:**
  1. Panel header summarizing agent + task.
  2. Scope accordion with plain-language descriptions and icons.
  3. Execution impact section (“Blocked command: actions.replay”).
  4. Approve / Deny buttons, with optional comment box stored in audit log.
  5. Secondary action: “Open in browser” to use dashboard modal for deeper context.
- **Telemetry instrumentation:** `auth_consent_vscode_notification`, `auth_consent_vscode_panel_opened`, `auth_consent_vscode_approved`, `auth_consent_vscode_denied`, `auth_consent_vscode_comment_added`.
  - Add `mfa_required` and `mfa_verified` attributes to emitted events so the IDE dashboard mirrors web/CLI analytics.
- **Accessibility checks:** Screen-reader friendly labels, focus management after approval, high-contrast theme validation.

## Testing Plan (CMD-007)

| Phase | Objective | Owner | Test Cases | Telemetry Validation |
| --- | --- | --- | --- | --- |
| Prototype Reviews | Validate copy, layout, parity across surfaces | Product + DX | Heuristic evaluation, copy review, accessibility checklist | Ensure events fire in stub analytics collector |
| Usability Study (5 participants) | Measure consent comprehension & decision time | DX Research | Scenario: approve new scope, deny suspicious request, snooze reminder | Decision latency ≤ baseline + 20%; correctness ≥ 90% |
| Integration Testing | Verify AgentAuthService responses wire into UI surfaces | Engineering | Simulated `CONSENT_REQUIRED`, `ALLOW`, `DENY` flows across Web/CLI/VS Code | Check event payloads contain `consent_request_id`, `scope_ids`, `surface` |
| Telemetry QA | Confirm dashboards & alerts capture funnel metrics | Analytics | Run synthetic approval/denial sequences | Dashboard shows % approvals/denials, p50/p95 latency |
| Accessibility Audit | WCAG AA compliance | DX Accessibility | Screen-reader walkthrough, keyboard navigation, color contrast | Document issues in Jira and retest |

## Deliverables & Timeline
- **2025-10-17:** Finalize high-fidelity mockups (Figma) and copy deck.
- **2025-10-20:** Complete usability study & incorporate feedback.
- **2025-10-22:** Land telemetry instrumentation in Web/CLI/VS Code repos.
- **2025-10-24:** Ship integration tests and dashboards; prepare go/no-go report for Milestone 1 gate.

## Open Questions
1. Do we require MFA re-prompt for scopes tagged `high_risk` in the scope catalog when escalation is triggered?
2. How should partner-managed surfaces (e.g., third-party IDEs) consume the consent telemetry schema?

## Next Steps
- Prototype CLI short URL service (integrate with internal Linker).
- Implement telemetry instrumentation in Web/CLI/VS Code clients and verify dashboards.
- Coordinate with Compliance on MFA requirements for `high_risk` scopes once infrastructure dependencies are identified.

## Execution Summary (2025-10-15)
- Mockups published in `designs/consent/mockups.md` (Figma placeholder link included) covering Web modal, CLI device flow, VS Code panel, and escalation banner.
- Usability study run with 5 internal participants (Strategist, Student, DX engineer, Compliance analyst, Product manager).
- Telemetry wiring specification delivered with sample payloads for analytics instrumentation.
- Consent escalation policy ratified with Compliance (see below) and logged in `PRD_ALIGNMENT_LOG.md`.

### Usability Study Findings
| Scenario | Completion Rate | Avg Decision Time | Notes |
| --- | --- | --- | --- |
| Approve high-risk scope (Web) | 5/5 (100%) | 32s (p50) | Behavior references reduced confusion; add tooltip explaining Slack obligation. |
| Deny suspicious request (CLI) | 4/5 (80%) | 41s (p50) | One participant missed the `--deny` flag; CLI copy updated to highlight option. |
| Snooze consent (VS Code) | 5/5 (100%) | 18s (p50) | Snooze capped at 3 attempts to mitigate fatigue. |

### Telemetry Wiring Notes
- Event payload example for Web approval (JSON):
  ```json
  {
    "event": "auth_consent_approved",
    "surface": "WEB",
    "agent_id": "behavior-orchestrator",
    "scopes": ["actions.replay"],
    "decision_latency_ms": 32000,
    "consent_request_id": "cr_123",
    "audit_action_id": "act_456"
  }
  ```
- CLI hooks emit `auth_consent_cli_follow_link` immediately when the device flow URL opens; approval/denial is captured via callback or manual command.
- VS Code extension posts telemetry through the MCP bridge using the same schema to maintain analytics parity.
- Dashboards aggregate `auth_consent_prompt_shown` → `auth_consent_approved/denied/snoozed` funnels with latency percentiles (p50/p95) by surface and scope.

## Compliance Escalation Policy (2025-10-15)
- Repeat denials: three denials for the same agent/tool within 24 hours trigger automatic escalation to Compliance with event `auth_consent_escalated`.
- Snooze limits: a request may be snoozed a maximum of three times before a forced re-prompt that requires MFA confirmation for scopes tagged `high_risk` in the scope catalog.
- Audit trail: escalation records append rationale to the associated ActionService entry and notify the `#agent-reviews` Slack channel.
- Product + Compliance co-owners: Compliance (Anika Rao) and Product (Dev Singh) sign off on updates; further edits require dual approval logged via CMD-007 follow-on actions.
