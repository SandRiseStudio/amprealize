# Agent Authentication & Authorization Architecture

## 0. Database Schema (Consolidated 2026-01-08)

This section documents the actual database tables backing the authentication system.

### Auth Tables (`auth` schema)

| Table | Purpose | Primary Key |
|-------|---------|-------------|
| `auth.users` | Human users authenticated via OAuth | `id` (UUID) |
| `auth.federated_identities` | OAuth provider links (Google, GitHub) | `id` (UUID) |
| `auth.service_principals` | Machine/agent API credentials | `id` (UUID) |

### Auth Model Summary

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           AUTHENTICATION                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  HUMAN USERS                           AGENTS/SERVICES                   │
│  ───────────                           ───────────────                   │
│  OAuth Device Flow                     Client Credentials Flow           │
│  (Google, GitHub)                      (client_id + client_secret)       │
│                                                                          │
│  ┌────────────────┐                    ┌─────────────────────┐          │
│  │  auth.users    │◄──owns─────────────│ auth.service_       │          │
│  │                │                    │ principals          │          │
│  │  - id          │                    │                     │          │
│  │  - email       │                    │  - id               │          │
│  │  - display_name│                    │  - name             │          │
│  │  - is_active   │                    │  - client_id        │          │
│  └───────┬────────┘                    │  - client_secret_   │          │
│          │                             │    hash             │          │
│          │ 1:N                         │  - role             │          │
│          │                             │  - allowed_scopes   │          │
│          ▼                             │  - created_by (FK)  │          │
│  ┌────────────────────┐                └─────────┬───────────┘          │
│  │ auth.federated_    │                          │                       │
│  │ identities         │                          │ optional              │
│  │                    │                          │ 1:1                   │
│  │  - provider        │                          ▼                       │
│  │  - provider_user_id│                ┌─────────────────────┐          │
│  │  - user_id (FK)    │                │  execution.agents   │          │
│  └────────────────────┘                │                     │          │
│                                        │  - owner_id (FK)    │          │
│                                        │  - service_         │          │
│                                        │    principal_id     │          │
│                                        │    (nullable FK)    │          │
│                                        └─────────────────────┘          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Separate tables for humans vs machines**
   - `auth.users` stores human users who authenticate via OAuth device flow
   - `auth.service_principals` stores machine credentials for agents needing API access
   - This keeps the concerns cleanly separated while allowing proper FK relationships

2. **Agent ownership via proper FK**
   - `execution.agents.owner_id` is a proper FK to `auth.users`
   - A system user (`id='system'`) owns builtin agents
   - ON DELETE CASCADE ensures agents are cleaned up when users are removed

3. **Optional agent API identity**
   - `execution.agents.service_principal_id` is nullable
   - Only populated when an agent explicitly needs its own API credentials
   - Follows principle of least privilege - most agents don't need separate auth

4. **Role-based access per AGENTS.md**
   - `service_principals.role` uses enum: STRATEGIST, TEACHER, STUDENT, ADMIN, OBSERVER
   - Maps to capabilities defined in the behavior handbook

### Related Services

| Service | Location | Purpose |
|---------|----------|---------|
| `ServicePrincipalService` | `amprealize/auth/service_principal_service.py` | CRUD for service principals |
| `api.py` OAuth callback | `amprealize/api.py` | Creates `auth.users` on OAuth login |
| AgentRegistryService | `amprealize/actions/agent_registry_service.py` | Agent CRUD with owner_id |

### Deprecated (Removed)

The following tables were removed in the 2026-01-08 consolidation:
- `auth.internal_users` - Replaced by `auth.users`
- `auth.internal_sessions` - Replaced by device flow sessions
- `auth.password_reset_tokens` - OAuth-only, no passwords

---

## 1. Purpose
Provide a centralized framework that secures amprealize agents when they act across internal and third-party services. The architecture extends the MCP control plane by introducing a dedicated AgentAuthService that enforces authentication, authorization, auditability, and least-privilege access for every tool invocation across Web, API, CLI, MCP, and IDE surfaces.

## 2. Objectives
- **Unified identity model:** Distinguish between human users, autonomous agents, and service integrations while preserving parity across all surfaces.
- **Delegated & direct access:** Support OAuth 2.0 / OIDC flows for agents operating on behalf of users (delegated) and for autonomous background jobs (direct) without compromising security.
- **Just-in-time, least-privileged grants:** Issue scoped credentials only when required, with time-bound policies and contextual rule enforcement.
- **Centralized auditing:** Capture evidence for every grant, token exchange, and tool execution per `AUDIT_LOG_STORAGE.md` requirements.
- **Policy orchestration:** Allow RBAC, attribute-based rules, and consent policies to evolve without redeploying agents.
- **Parity & extensibility:** Expose consistent SDKs and MCP tools so Web, CLI, VS Code extension, and partner integrations rely on the same auth contracts.

## 3. Guiding Requirements
1. **Authentication flows**
   - Device + auth-code flow for interactive human approval (`amprealize auth login`).
   - Client credentials flow for service-to-service automation.
   - On-Behalf-Of (OBO) token exchange for mid-tier APIs complying with delegated access patterns.
2. **Authorization model**
   - RBAC roles (Strategist, Teacher, Student, Admin, Observer) mapped to capabilities in `docs/capability_matrix.md`.
   - Contextual rules (time-bound JIT grants, deny-lists for risky scopes, consent prompts per agent).
   - Resource-scoped policies referencing tool definitions (`ACTION_REGISTRY_SPEC.md`).
3. **Audit & telemetry**
   - Every grant and tool execution must emit structured events linking user ID, agent ID, scope, and rationale to the warehouse metrics defined in `TELEMETRY_SCHEMA.md`.
   - Evidence persisted via `ActionService` for reproducibility (action IDs attached to auth operations).
4. **Secrets & tokens**
   - Align with `SECRETS_MANAGEMENT_PLAN.md`: encrypt refresh tokens, rotate credentials, forbid plaintext storage.
   - Feature detection for runtime support (Python, Node, upcoming Rust SDK) to avoid breaking legacy clients.
5. **Compatibility**
   - Backwards compatible with existing CLI and REST endpoints; clients without AgentAuth support continue using existing PAT/device flows until migrated.
   - Forward-compatible hooks for VS Code extension and arcade.dev-style tool adapters.

## 4. High-Level Architecture
```
+--------------------+        +---------------------+
|  Human User / CLI  |        |  Autonomous Agent   |
+---------+----------+        +----------+----------+
          |                              |
          v                              v
  +-----------------+         +--------------------+
  | Auth Gateway    |         | Service Principals |
  | (OIDC, Device)  |         | Client Credentials |
  +--------+--------+         +---------+----------+
           |                            |
           v                            v
  +-----------------------------------------------+
  |             AgentAuthService                  |
  |  - Token Broker (Auth Code, OBO, Client Cred) |
  |  - Policy Engine (RBAC + contextual rules)    |
  |  - Consent Orchestrator (JIT prompts)         |
  |  - Token Vault (encrypted storage)            |
  |  - Audit Hub (ActionService + WORM logs)      |
  +-----------------+---------------+-------------+
                    |               |
                    v               v
        +------------------+   +--------------------+
        | Tool Execution   |   | External Services  |
        | Gateways (MCP    |<->| (Slack, Google,    |
        | adapters, CLI,   |   |  Jira, Internal)   |
        | VS Code, API)    |   +--------------------+
        +------------------+
```

### Core Components
- **Auth Gateway**: Handles device code and browser redirects, issues ID tokens for human identities, integrates with existing MCP OAuth provider.
- **AgentAuthService** (new): Microservice responsible for token lifecycle, policy enforcement, and audit logging. Exposes gRPC/REST endpoints and MCP tools (`auth.grant`, `auth.revoke`, `auth.status`).
- **Policy Engine**: Evaluates RBAC roles, contextual rules (deny specific scopes, require re-consent per request), and JIT expiration windows.
- **Token Vault**: Stores encrypted access/refresh tokens (per user × agent × service) leveraging the secrets management controls (KMS envelope encryption, rotation hooks).
- **Audit Hub**: Publishes events to telemetry pipeline and persists immutable records referencing action IDs.
- **Tool Execution Gateways**: Wrappers around tool adapters that call AgentAuthService before executing any external action.

## 5. Trust Boundaries
1. **User/Agent ↔ Auth Gateway** – All browser or device flows; tokens exchanged here are short-lived and never exposed to downstream services.
2. **AgentAuthService ↔ Token Vault** – Server-side only; uses KMS-encrypted storage and automatic rotation jobs.
3. **Tool Gateways ↔ External APIs** – Access tokens fetched just-in-time; no token reuse across agents or users.
4. **Telemetry/Audit** – Events emitted over secure channel to MetricsService and WORM storage.

## 6. Authorization Policies
- **Role-based policies**: Stored in Postgres and exposed via MCP; e.g., Strategist can approve new OAuth scopes, Student cannot.
- **Contextual rules**: JSON policy language supporting conditions (time of day, triggering tool, resource path). Example: "Agent `support-bot` cannot request `files.write` in Slack".
- **Just-in-time flow**: When a tool invocation lacks valid credentials, the gateway requests AgentAuthService to initiate consent. User receives prompt (web UI modal or CLI link) describing requested scopes. Consent decisions stored with expiry timestamp.
- **Revocation & anomaly**: On suspicious activity, Compliance agent can revoke tokens (via `auth.revoke`) and flag `behavior_lock_down_security_surface` checklist item.
- **High-risk scope MFA**: Destructive scopes (`actions.replay`, `agentauth.manage`) require a completed MFA challenge before consent. Requests without `mfa_verified=true` are held with `SECURITY_HOLD` responses and logged to telemetry.

## 7. Token Flows
### 7.1 Delegated Access (Auth Code + OBO)
1. User authenticates via Auth Gateway → receives ID token.
2. Agent calls AgentAuthService `auth.ensureGrant` (tool, scope, user context).
3. Service checks Token Vault; if absent/expired, initiates Auth Code flow with PKCE.
4. Upon completion, Token Broker stores access + refresh token keyed by user × agent × tool.
5. Tool gateway obtains access token via OBO when acting as mid-tier service operations.
6. Audit Hub records grant with action ID referencing `amprealize record-action` entry.

### 7.2 Direct Access (Client Credentials)
1. Autonomous agent registers service principal via `auth.registerClient` (admin only).
2. Token Broker issues short-lived tokens using client credentials; scopes limited to non-user-specific operations.
3. Policy Engine enforces rate limits, resource constraints.

### 7.3 JIT Consent Refresh
- Token expiration and scope expansions trigger `auth.promptConsent` events to UI/CLI, requiring user confirmation per request.
- Leverages push notifications in dashboard, CLI prompts, or IDE popups.

## 8. Integration with Tool Execution
- **Pre-execution hook**: All tool adapters must call `auth.verifyAction(agentId, userId, toolName, parameters)`.
- **Decision outcomes**:
  - **ALLOW** – returns signed access token, obligation metadata (expiry, audit ID).
  - **CONSENT_REQUIRED** – instructs UI/CLI to present consent URL; holds execution until approved.
  - **DENY** – includes reason code, logged to audit.
- **Post-execution**: Tool reports execution result to AgentAuthService for anomaly detection and to close the audit record.

## 9. Data Model Overview
- **Users** (`users`) – human identities with role assignments.
- **Agents** (`agents`) – registered applications with metadata (surface, owner, default scopes).
- **Tools** (`tools`) – reference `ACTION_REGISTRY_SPEC.md` entries, including required scopes per provider.
- **Grants** (`grants`) – mapping of user × agent × tool × scope with status (active, expired, revoked) and expiry.
- **Tokens** (vault) – encrypted envelope storing provider-specific refresh/access tokens and metadata.
- **Audit Events** – persisted via ActionService (`auth.grant.created`, `auth.grant.revoked`, `auth.tool.execution`).

## 10. Observability & Compliance
- Emit metrics: `auth_grant_success_total`, `auth_grant_denied_total`, `auth_scope_expansion_requests_total`, `auth_jit_consent_latency_ms`.
- Dashboards correlate auth events with tool executions to detect anomalies.
- Compliance checklist additions: ensure every new tool includes scope mapping and consent UX.
- Quarterly access review: export `grants` table, verify least-privilege adherence, log in `PRD_ALIGNMENT_LOG.md`.

### Consent Telemetry Instrumentation
- Capture consent prompt impressions, approvals, and denials per surface with events `auth_consent_prompt_shown`, `auth_consent_approved`, `auth_consent_denied`.
- Record decision latency buckets (p50/p90) and correlate with tool invocation outcomes for anomaly detection.
- Include `mfa_required` and `mfa_verified` flags in consent telemetry payloads so analytics can track MFA completion rates for high-risk scopes.
- Attach AgentAuthService action IDs and scope metadata so analytics can calculate consent completion rates against PRD targets (70% behavior reuse, 30% token savings, 80% task completion, 95% compliance coverage).
- Emit consent telemetry into the MetricsService pipeline with partition keys `(surface, tool, scope)` to keep dashboard filters consistent across Web, CLI, VS Code, and MCP surfaces.

## 11. Surface Parity
| Surface | Integration Approach | Notes |
| --- | --- | --- |
| Web Dashboard | React/Vue components consuming `auth.*` REST endpoints; integrates with JIT modals. | Requires session cookies or PAT exchange. |
| CLI (`amprealize`) | Commands `auth login`, `auth status`, `auth revoke`; tool commands automatically call `auth.verify-action`. | Device code flow + keychain storage. |
| MCP / SDKs | New tools: `auth.listGrants`, `auth.ensureGrant`, `auth.revoke`. Generated clients keep parity across languages. | |
| VS Code Extension | Uses MCP tools over WebSocket; prompts user via VS Code notifications. | |
| Partner APIs | Provide signed JWT + capability negotiation; rely on same policy engine. | |

## 12. Implementation Roadmap
1. **Phase A – Contracts (2 weeks)**
   - Publish `proto/agentauth/v1/agent_auth.proto` covering `EnsureGrant`, `RevokeGrant`, `ListGrants`, and `PolicyPreview` RPCs with shared error enums.
   - Generate REST schemas under `schema/agentauth/v1/*.json` mirroring proto types for OpenAPI parity.
   - Create canonical scope catalog (`schema/agentauth/scope_catalog.yaml`) mapping each tool/action to provider scopes and default RBAC roles.
   - Define policy bundle format (`schema/policy/agentauth/bundle.yaml`) encapsulating contextual rules, version metadata, and rollout annotations.
   - Produce MCP tool contracts (`auth.ensureGrant`, `auth.revoke`, `auth.listGrants`, `auth.policy.preview`) with capability notes for CLI, Web, and VS Code clients.
   - Update capability matrix with Agent Auth row.
   - Ship SDK stubs and contract tests (`amprealize/agent_auth.py`, `tests/test_agent_auth_contracts.py`) validating artifact alignment (CMD-006).
   - Reference consent UX prototype plan in `docs/CONSENT_UX_PROTOTYPE.md` for Milestone 1 implementation.
2. **Phase B – Core Service (4 weeks)**
   - Implement AgentAuthService (Token Broker, Policy Engine, Token Vault integration).
   - Integrate with secrets manager, ActionService logging, metrics pipeline.
   - Provide Python/TypeScript SDK updates.
3. **Phase C – Tool Enforcement (3 weeks)**
   - Update CLI, MCP adapters, and web tooling to call `auth.verifyAction` pre-execution.
   - Build consent UI flows (web modal, CLI prompt, VS Code notification).
4. **Phase D – External Providers (3 weeks)**
   - Ship connectors for Slack, Google Workspace, Jira using JIT OAuth.
   - Configure scope templates and tests per provider.
5. **Phase E – Governance & Hardening (2 weeks)**
   - Finalize compliance checklists, telemetry dashboards, and rotation runbooks.
   - Conduct security review, penetration testing, and failover drills.

## 13. Risks & Mitigations
| Risk | Impact | Mitigation |
| --- | --- | --- |
| Token leakage via logs | High | Redact tokens, add automated linting, enforce secrets scanning. |
| Consent fatigue | Medium | Batch scope prompts, provide descriptive tool names, allow admins to pre-approve patterns. |
| Policy misconfiguration | Medium | Versioned policies with staged rollout & dry-run mode; use ActionService to track changes. |
| External provider rate limits | Medium | Cache tokens securely, implement exponential backoff, monitor `auth_provider_error_total`. |
| Legacy clients unable to support JIT flows | Low | Offer compatibility mode with service accounts but gate access to low-risk scopes only. |

## 14. Open Questions
- ~~Do we require multi-factor re-authentication for high-risk scopes (e.g., data deletion)?~~ **Resolved (2025-10-15):** Yes—`actions.replay` and `agentauth.manage` demand MFA verification (`mfa_verified=true`) prior to consent issuance; enforced in scope catalog and policy bundle.
- Should we integrate with arcade.dev or similar providers for managed OAuth flows vs maintaining in-house connectors?
- How do we expose policy editing: internal dashboard only or MCP tool accessible to Strategist role?
- What retention period applies to per-service grant records in WORM storage?

## 15. Next Actions
- Review architecture with Security, Compliance, and DX agents.
- Add tasks to `PRD_NEXT_STEPS.md` and milestone tracker for Phase A deliverables.
- Prepare consent UX requirements for dashboard and CLI teams.
- Align with infrastructure team on using existing KMS/Vault setup for Token Vault.

## 16. Token Vault SLOs & Operational Targets
- **Availability SLO**: 99.95% monthly availability for token issuance and retrieval endpoints; alerts trigger when error budget consumption exceeds 25%.
- **Recovery Objectives**: RPO 0 minutes (token vault replicas in sync via multi-AZ replication) and RTO 15 minutes through automated failover runbooks.
- **Latency Targets**: `auth.ensureGrant` P95 latency ≤ 250 ms for cached grants; ≤ 750 ms when vault decryption is required.
- **Rotation Cadence**: Refresh tokens rotated every 30 days or immediately upon provider revocation signals; rotation jobs must finish within 4 hours.
- **Integrity Checks**: Daily checksum verification of encrypted blobs with discrepancies escalated to Security and recorded via `amprealize record-action`.

## 17. Policy Deployment & Change Management
- **Version Control**: Policies authored in declarative YAML, stored in Git with semantic version tags (`policy-major.minor.patch`).
- **Review Workflow**: Every policy change requires dual approval (Security + Product) and a dry-run report attached to the pull request.
- **Staged Rollout**: Deploy policy bundles to staging via GitOps; production promotion waits for automated integration tests (`tests/test_policy_contracts.py`, to be added in Phase B) and manual sign-off recorded in `PRD_ALIGNMENT_LOG.md`.
- **Telemetry Hooks**: Policy engine emits `auth.policy.evaluate` events with version hash and decision outcome to support post-deployment audits.
- **Rollback**: Maintain last-known-good bundle; `amprealize auth policy rollback` CLI command (Phase B) reverts production to prior version, logging action ID and approvers.

## 18. Consent Telemetry Instrumentation Rollout Plan
- **Instrumentation Tasks**: DX team adds consent analytics hooks to Web modal, CLI device flow, and VS Code notification surfaces; SDKs expose helper to emit standard events.
- **Dashboard Views**: Analytics builds consent funnel dashboard showing prompt→approve/deny conversion and latency distributions per surface.
- **Alerts**: Configure anomaly detection on spike in denials or latency > 2× baseline; notify Security/DX Slack channels.
- **Data Retention**: Consent telemetry retained for 400 days to support compliance audits, aligning with `AUDIT_LOG_STORAGE.md` requirements.

## 19. Consent UX Plans by Surface

### Web Dashboard
- **Entry Point**: Inline modal triggered from tool execution or settings panel when strategic plans request new scopes.
- **Experience**: Display provider icon, requested scopes, purpose statement (<160 chars), expiration window, and auditor note link. Include `Need more context?` accordion linking to behavior handbook references.
- **Fallback**: Offer "Remind me later" (snooze 15 minutes) while pausing execution; log deferral as `auth_consent_snoozed` event.
- **Accessibility**: Support keyboard navigation and screen-reader labels; ensure contrast ratio ≥ 4.5.
- **Telemetry Hooks**: Emit `auth_consent_prompt_shown`, `auth_consent_approved/denied/snoozed`, plus `auth_consent_details_viewed` when accordion expands.

### CLI (`amprealize`)
- **Entry Point**: Device-code flow surfaces consent message in terminal with short URL and code; CLI polls `auth.consentStatus`.
- **Experience**: Provide concise summary, reason for request, and safety note referencing policy version. Use colorized output (yellow pending, green approved, red denied) with ASCII fallback for non-color terminals.
- **Fallback**: Offer `amprealize auth consent --approve <request-id>` and `--deny` for headless automation; default SLA is 5-minute timeout before request expires.
- **Telemetry Hooks**: Record `auth_consent_cli_prompt_rendered`, `auth_consent_cli_follow_link`, `auth_consent_cli_timeout`, including shell type and OS metadata.

### VS Code Extension
- **Entry Point**: VS Code notification with "Review consent" CTA opening a WebView panel showing scope details and sample commands affected.
- **Experience**: Provide context of triggering task, highlight execution blocker, allow quick approve/deny with rationale notes stored in audit log.
- **Fallback**: If user dismisses notification, schedule reminder toast after 10 minutes and update activity bar icon badge count.
- **Telemetry Hooks**: Emit `auth_consent_vscode_notification`, `auth_consent_vscode_panel_opened`, `auth_consent_vscode_approved/denied`, and capture time-to-decision metrics.
