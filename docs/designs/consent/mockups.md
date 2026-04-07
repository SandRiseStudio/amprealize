# AgentAuth Consent Mockups (Milestone 1)

These mockups accompany `docs/CONSENT_UX_PROTOTYPE.md` and translate the UX requirements into annotated frames. Each frame references event names and consent telemetry targets so engineering and analytics teams can implement instrumentation consistently.

## Frame A – Web Dashboard Modal
- **Trigger:** `auth.ensureGrant` returns `CONSENT_REQUIRED` for `actions.replay`.
- **Layout Notes:**
  - Header: “Agent `behavior-orchestrator` needs approval to continue.”
  - Scope list uses friendly labels from `schema/agentauth/scope_catalog.yaml`.
  - Obligations pill shows Slack notification target `#agent-reviews`.
  - Action buttons: primary “Approve and continue”, secondary “Deny and cancel run”.
  - Snooze link below buttons with 15-minute timeout indicator.
- **Telemetry tags:**
  - `auth_consent_prompt_shown` (surface=`WEB`, scopes=`actions.replay`).
  - `auth_consent_details_viewed` when the “Need more context?” accordion expands.

## Frame B – CLI Device Flow
- **Trigger:** CLI run tries to execute `actions.replay` without grant.
- **Layout Notes:**
  - ANSI-styled box summarizing tool + scopes.
  - Short URL `https://gai.dev/c/{code}` with countdown timer.
  - Tip banner: “Tip: approve via `amprealize auth consent --approve <id>`”.
- **Telemetry tags:**
  - `auth_consent_cli_prompt_rendered`.
  - `auth_consent_cli_follow_link` recorded when user opens the URL (instrumented via CLI callback).

## Frame C – VS Code Panel
- **Trigger:** Notification toast inside VS Code extension.
- **Layout Notes:**
  - Left column: agent avatar + run name.
  - Right column: scope list, obligations, and behavior references.
  - Text field for optional justification stored in audit log.
  - Secondary link opens dashboard modal for advanced review.
- **Telemetry tags:**
  - `auth_consent_vscode_panel_opened`.
  - `auth_consent_vscode_comment_added` when user submits rationale.

## Frame D – Denial Escalation Banner
- **Trigger:** Consent denied three times within 24 hours for same agent/tool.
- **Layout Notes:**
  - Banner surfaces compliance guidance and provides link to SOC2 control.
  - CTA “Escalate to Compliance” opens a pre-filled Slack message template.
- **Telemetry tags:**
  - `auth_consent_escalated` emitted with `escalation_reason=repeat_denial`.

## Assets
- Figma file: `https://www.figma.com/file/xyz123/amprealize-consent?node-id=42%3A910` (placeholder link for engineering reference).
- Icon set: `designs/consent/icons/` (to be added when visual assets are finalized).

## Next Revision Checklist
- Validate copy with Product Marketing.
- Incorporate accessibility feedback (screen-reader order, color contrast adjustments).
- Sync with Compliance on escalation copy updates when new scopes are introduced.
