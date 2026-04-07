# Action Registry Specification

## 1. Purpose
Provide a contract-first specification for recording, listing, and replaying platform build actions across API, CLI, platform UI, and MCP tools. This ensures every action taken while constructing the platform can be reproduced by any user or automated agent.

## 2. Domain Model
| Field | Type | Description |
| --- | --- | --- |
| `action_id` | UUID | Unique identifier for the recorded action. |
| `timestamp` | RFC3339 datetime | When the action was executed. |
| `actor_id` | UUID | User or agent identifier. |
| `actor_role` | enum(`Strategist`,`Teacher`,`Student`,`Admin`) | Role in the behavior model. |
| `artifact_path` | string | Path or URI of the artifact affected (e.g., `PRD.md`). |
| `summary` | string | Concise description of the action (≤ 160 chars). |
| `behaviors_cited` | string[] | List of behavior IDs referenced during the action. |
| `related_run_id` | UUID? | Optional run/execution identifier. |
| `metadata` | object | Arbitrary key/value context (commands run, validation results). |
| `replay_status` | enum(`not_started`,`queued`,`running`,`succeeded`,`failed`) | Status when replaying. |
| `checksum` | string | Hash of resulting artifact for verification. |

## 3. API Endpoints (REST)
Base path: `/v1/actions`

| Method & Path | Description | Request Body | Response |
| --- | --- | --- | --- |
| `POST /` | Create a new action record. | `ActionCreateRequest` | `ActionResponse` |
| `GET /` | List actions with filters (`actor_id`, `artifact_path`, `date_range`, `role`). | — | `ActionListResponse` |
| `GET /{action_id}` | Retrieve full details including metadata and replay history. | — | `ActionResponse` |
| `POST /replay` | Start a replay job for a set of actions (ordered list). | `ReplayRequest` | `ReplayResponse` |
| `GET /replay/{replay_id}` | Inspect status, logs, parity checks. | — | `ReplayResponse` |
| `POST /v1/tasks:listAssignments` | List remaining milestone tasks mapped to functions and agents. | `TaskAssignmentRequest` | `TaskAssignmentListResponse` |

### Request Schemas
- **ActionCreateRequest**
```json
{
  "artifact_path": "PRD.md",
  "summary": "Draft PRD vision section",
  "behaviors_cited": ["behavior_handbook_compliance_prompt"],
  "metadata": {
    "commands": ["n/a"],
    "validation": ["documentation review"]
  },
  "related_run_id": "UUID-optional"
}
```
- **ReplayRequest**
```json
{
  "action_ids": ["UUID1", "UUID2"],
  "strategy": "sequential|parallel",
  "options": {
    "skip_existing": true,
    "dry_run": false
  }
}
```

- **SecretScanRequest**
```json
{
  "surface": "CLI|CI|MCP",
  "paths": ["."],
  "fail_on_findings": true,
  "report_format": "json|table"
}
```

- **SecretScanResponse**
```json
{
  "scan_id": "UUID",
  "started_at": "2025-10-15T22:02:00Z",
  "finished_at": "2025-10-15T22:02:03Z",
  "findings": [
    {
      "rule": "Generic Credential",
      "file": "docs/example.md",
      "line": 42,
      "excerpt": "***REDACTED***"
    }
  ],
  "status": "PASSED|FAILED"
}
```

- **TaskAssignmentRequest**
```json
{
  "function": "engineering"
}
```

- **TaskAssignmentListResponse**
```json
{
  "tasks": [
    {
      "task_id": "milestone1.vscode_extension",
      "title": "VS Code Extension Preview",
      "milestone": "Milestone 1",
      "status": "PLANNED",
      "function": "Developer Experience",
      "primary_agent": "Agent Developer Experience",
      "agent_playbook": "AGENT_DX.md",
      "supporting_agents": [
        {"function": "Engineering", "primary_agent": "Agent Engineering", "agent_playbook": "AGENT_ENGINEERING.md"}
      ],
      "surfaces": ["platform", "cli", "api", "mcp"],
      "dependencies": ["sdk-authentication", "behavior-retrieval-api"],
      "evidence_targets": ["Extension bundle", "Capability matrix update"]
    }
  ]
}
```

## 4. MCP Tool Definitions
| Tool Name | Type | Input Schema | Output |
| --- | --- | --- | --- |
| `actions.create` | `command` | `ActionCreateRequest` | `ActionResponse` |
| `actions.list` | `query` | Filters object | Array of `ActionResponse` |
| `actions.get` | `query` | `{ action_id: UUID }` | `ActionResponse` |
| `actions.replay` | `command` | `ReplayRequest` | `ReplayResponse` |
| `actions.replayStatus` | `query` | `{ replay_id: UUID }` | `ReplayResponse` |
| `reviews.run` | `command` | `{ artifact: string, scope: string[], behaviors?: string[] }` | `ReviewResponse` (aggregated feedback, action ids) |
| `security.scanSecrets` | `command` | `SecretScanRequest` | `SecretScanResponse` |
| `tasks.listAssignments` | `query` | `{ function?: string }` | `TaskAssignmentListResponse` |

> AgentAuth MCP tools that gate these operations are defined under `mcp/tools/auth.*.json` and share schema definitions with `proto/agentauth/v1/agent_auth.proto`.

**Capability Negotiation:** During MCP handshake, clients declare support for `action-registry` feature flag; server returns available tools and schemas version.

## 5. CLI Commands
| Command | Description | Options |
| --- | --- | --- |
| `amprealize record-action` | Create action entry. | `--artifact <path>`, `--summary <text>`, `--behaviors <csv>`, `--metadata <json|path>`, `--run-id <uuid>` |
| `amprealize list-actions` | List or search actions. | `--actor`, `--role`, `--artifact`, `--from`, `--to`, `--limit` |
| `amprealize show-action <id>` | Display full details plus diff/checksum. | `--format (json|table)` |
| `amprealize replay` | Replay a set of actions. | `--actions <ids|path>`, `--strategy`, `--dry-run`, `--skip-existing`, `--watch` |
| `amprealize replay-status <id>` | Stream replay progress/logs. | `--follow` |
| `amprealize tasks` | List remaining tasks mapped to functions/agents. | `--function <owner>`, `--format (json|table)` |
| `amprealize agents review` | Schedule cross-functional agent reviews (Engineering, DX, Compliance, Product) and fetch feedback. | `--artifact <path>` `--scope <csv>` `--behaviors <csv>` `--wait` |
| `amprealize scan-secrets` | Run repo-wide secret scan via Gitleaks and log results as an action. | `--format (table|json)` `--fail-on-findings` `--output <path>` |

All CLI commands call MCP tools via generated SDK; parity tests ensure outputs mirror REST responses.

**Example – Progress Tracker Update**
```bash
amprealize record-action \
  --artifact PROGRESS_TRACKER.md \
  --summary "Update Milestone 0 tracker" \
  --behaviors behavior_handbook_compliance_prompt,behavior_update_docs_after_changes \
  --metadata '{"status":"completed","milestone":"m0"}'
```

## 6. Platform UI Workflow
1. **Task Completion Modal:** After finishing a task, UI prompts to log an action with auto-filled artifact path and detected behaviors.
2. **Action Timeline View:** Displays chronological list (mirrors `BUILD_TIMELINE.md`) with filters and replay buttons.
3. **Replay Wizard:** Allows selecting actions/time ranges, previews artifacts to generate, and triggers MCP `actions.replay` tool.
4. **Progress Tracker Guardrail:** When `PROGRESS_TRACKER.md` changes, UI enforces action logging before allowing navigation away (ensures reproducibility of progress reporting).
5. **Agent Review Scheduler:** Strategist can trigger Engineering/DX/Compliance/Product agents from the UI, which records a review action (`reviews.run`). Results summarize in a modal and link to `PRD_AGENT_REVIEWS.md` updates.

## 6.1 VS Code Extension Integration
The VS Code extension (`extension/`) provides full Action Registry parity via MCP:

**Tree View (Action Tracker)**
- Located in Explorer sidebar under "Amprealize" container
- Displays actions grouped by replay status (Not Started, Running, Succeeded, Failed)
- Context menu: Copy Action ID, Filter by Behavior, View Details, Replay Action

**Commands**
| Command ID | Title | Description |
| --- | --- | --- |
| `amprealize.refreshActionTracker` | Refresh Action Tracker | Reload actions from server |
| `amprealize.openActionTimeline` | Open Action Timeline | Open timeline WebView panel |
| `amprealize.recordAction` | Record Action | Quick dialog to record new action |
| `amprealize.listActions` | List Actions | Quick pick to browse actions |
| `amprealize.replayAction` | Replay Action | Start replay with dry-run option |
| `amprealize.viewActionDetail` | View Action Details | Open action in timeline panel |
| `amprealize.actionTracker.copyActionId` | Copy Action ID | Copy ID to clipboard |
| `amprealize.actionTracker.filterByBehavior` | Filter by Behavior | Filter tree by behavior ID |
| `amprealize.actionTracker.clearFilters` | Clear Filters | Remove all filters |

**WebView Panel (Action Timeline)**
- Timeline visualization of actions with status indicators
- Quick replay button with dry-run toggle
- Polling for replay status updates
- Artifact path and behaviors display

**MCP Client Methods**
```typescript
mcpClient.actionCreate({ artifactPath, summary, behaviorsCited, tier? })
mcpClient.actionList({ artifactPathFilter?, behaviorId?, limit? })
mcpClient.actionGet({ actionId })
mcpClient.actionReplay({ actionIds, strategy, options, tier? })
mcpClient.actionReplayStatus({ replayId })
```

**Configuration**
- `amprealize.telemetryActorId`: Actor ID for action recording
- `amprealize.telemetryActorRole`: Actor role (STUDENT/TEACHER/STRATEGIST)

**Files**
- `src/providers/ActionTreeDataProvider.ts`: Tree view provider
- `src/panels/ActionTimelinePanel.ts`: WebView panel
- `src/styles/ActionTimelinePanel.css`: Panel styles
- `src/client/McpClient.ts`: MCP action methods

## 7. Parity & Testing
- Contract tests in CI hit REST endpoints and MCP tools using the same schema fixtures.
- CLI snapshot tests validate command output for create/list/replay/scan flows against golden files.
- UI E2E tests (Playwright) confirm action logging prompts appear for Strategist/Student/Teacher flows.
- Observability: metrics `actions_created_total`, `actions_replayed_total`, `action_parity_failures_total`, `action_secret_scan_failures_total` exported to analytics service.

## 8. Security & Compliance
- Actions inherit RBAC scopes: `action.write`, `action.read`, `action.replay` (replay limited to Strategist/Admin).
- replay jobs include dry-run mode to prevent accidental overwrites; destructive steps require confirmation prompts.
- Audit logs store hash of request+response for tamper detection; align with requirements in `REPRODUCIBILITY_STRATEGY.md`.
- Secret scan outputs redact excerpts before storage; `security.scanSecrets` responses reference follow-up `amprealize record-action` entries when remediation is required.

## 9. Open Items
- Determine policy for redacting sensitive metadata prior to storage.
- Define retry semantics for failed replay steps; consider checkpointing per action.
- Evaluate Git webhook integration to auto-log actions from merges.
- Decide whether to auto-capture derived progress metrics (e.g., milestone completion %) when `PROGRESS_TRACKER.md` is updated.
