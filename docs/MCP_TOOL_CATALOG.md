# MCP Tool Catalog

This document catalogs all available MCP tools for the amprealize platform.
**Total tools**: 64

## Table of Contents

- [Actions Service](#service-actions) (5 tools)
- [Agents Service](#service-agents) (3 tools)
- [Analytics Service](#service-analytics) (4 tools)
- [Auth Service](#service-auth) (8 tools)
- [Bci Service](#service-bci) (11 tools)
- [Behaviors Service](#service-behaviors) (9 tools)
- [Compliance Service](#service-compliance) (5 tools)
- [Metrics Service](#service-metrics) (3 tools)
- [Patterns Service](#service-patterns) (2 tools)
- [Reflection Service](#service-reflection) (1 tools)
- [Runs Service](#service-runs) (6 tools)
- [Security Service](#service-security) (1 tools)
- [Tasks Service](#service-tasks) (1 tools)
- [Work Items Service](#service-workitems) (6 tools) ⚠️ **Board tasks**
- [Workflow Service](#service-workflow) (5 tools)

---

## Service: actions

**Tool count**: 5

### `actions.create`

Record a new build action for reproducibility tracking. Automatically calculates artifact checksum if not provided and creates an immutable audit log entry.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `artifact_path` | string | **required** | Path or URI of the artifact impacted (file, directory, deployment URL) |
| `summary` | string | **required** | Human-readable action summary (e.g., 'Refactored BehaviorService to add versioning') |
| `behaviors_cited` | array<string> | **required** | Behavior IDs referenced during this action (enables behavior reuse tracking) |
| `metadata` | object | optional | Additional action metadata |
| `related_run_id` | string | optional | Optional RunService workflow run association |
| `checksum` | string | optional | SHA-256 checksum of artifact (calculated by server if omitted) |
| `actor` | object | **required** | Actor recording the action |

---

### `actions.get`

Retrieve a single action by ID with full metadata, commands, validation output, and audit log linkage.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `action_id` | string | **required** | Action identifier to retrieve |
| `actor` | object | **required** | Actor requesting the action |

---

### `actions.list`

List recorded build actions with optional filtering by artifact path, behaviors, or related workflow runs. Returns actions in reverse chronological order.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `artifact_path_filter` | string | optional | Filter actions by artifact path prefix (e.g., 'amprealize/', 'docs/') |
| `behavior_id` | string | optional | Filter actions that cite a specific behavior ID |
| `related_run_id` | string | optional | Filter actions associated with a specific workflow run |
| `limit` | integer | optional | Maximum number of actions to return |
| `actor` | object | **required** | Actor requesting the list |

---

### `actions.replay`

Launch a replay job to reproduce one or more actions sequentially or in parallel. Requires action.replay RBAC scope. Returns a replay_id for status tracking.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `action_ids` | array<string> | **required** | Action IDs to replay |
| `strategy` | string (`SEQUENTIAL`, `PARALLEL`) | optional | Replay execution strategy (SEQUENTIAL = one at a time, PARALLEL = concurrent) |
| `options` | object | optional | Replay execution options |
| `actor` | object | **required** | Actor launching replay (requires action.replay scope) |

---

### `actions.replayStatus`

Check the status of a replay job including progress, logs, and failed action details. Use this to monitor long-running replays.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `replay_id` | string | **required** | Replay job identifier |
| `actor` | object | **required** | Actor requesting replay status |

---

## Service: agents

**Tool count**: 3

### `agents.assign`

Request initial agent assignment for a run. Evaluates policy heuristics (task type, compliance tags, telemetry) and returns the chosen agent persona. Requires agents.assign scope.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `run_id` | string | optional | Run identifier to associate with this assignment (optional, will generate if not provided) |
| `requested_agent_id` | string | optional | Specific agent ID to request (e.g., 'compliance', 'product', 'engineering'). If omitted, service selects agent via heuristics. |
| `stage` | string | **required** | Workflow stage (e.g., 'PLANNING', 'EXECUTION', 'REVIEW') |
| `context` | object | optional | Task context for heuristic evaluation |
| `requested_by` | object | **required** | Requester identity |

---

### `agents.status`

Retrieve current agent assignment status, including active agent, assignment history, heuristics applied, and recommended next agent based on run context. Requires agents.read scope.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `assignment_id` | string | optional | Agent assignment identifier to look up (exclusive with run_id) |
| `run_id` | string | optional | Run identifier to find assignment for (exclusive with assignment_id) |

---

### `agents.switch`

Switch the active agent for an existing assignment. Triggers agent change, logs AgentSwitchEvent, updates RunService metadata, and emits telemetry. Requires agents.switch scope.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `assignment_id` | string | **required** | Agent assignment identifier to update |
| `target_agent_id` | string | **required** | Agent ID to switch to (e.g., 'compliance', 'product', 'engineering') |
| `reason` | string | optional | Reason for the switch (e.g., 'manual_override', 'heuristic_recommendation', 'escalation') |
| `allow_downgrade` | boolean | optional | Whether to allow switching to an agent with lower privilege level |
| `stage` | string | optional | Optional stage update to accompany the switch |
| `issued_by` | object | optional | Identity of user/system issuing the switch |

---

## Service: analytics

**Tool count**: 4

### `analytics.behaviorUsage`

Query behavior usage facts from analytics warehouse showing per-run behavior citations, token counts, and actor context.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `start_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter results from this date forward |
| `end_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter results up to this date |
| `limit` | integer | optional | Maximum number of records to return (1-1000, default: 100) |

---

### `analytics.complianceCoverage`

Query compliance coverage facts from analytics warehouse showing checklist completion status, evidence tracking, and coverage scores per run.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `start_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter results from this date forward |
| `end_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter results up to this date |
| `limit` | integer | optional | Maximum number of records to return (1-1000, default: 100) |

---

### `analytics.kpiSummary`

Query aggregated KPI summary from analytics warehouse showing PRD success metrics: behavior reuse %, token savings %, task completion rate, and compliance coverage %.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `start_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter results from this date forward |
| `end_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter results up to this date |

---

### `analytics.tokenSavings`

Query token savings facts from analytics warehouse showing per-run token consumption, baseline comparisons, and efficiency metrics.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `start_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter results from this date forward |
| `end_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter results up to this date |
| `limit` | integer | optional | Maximum number of records to return (1-1000, default: 100) |

---

## Service: auth

**Tool count**: 8

### `auth.authStatus`

Check current authentication status, including token validity, granted scopes, and expiry information. Validates stored tokens against the authorization server.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `client_id` | string | optional | OAuth client identifier to check tokens for. Defaults to amprealize-mcp-client. |
| `validate_remote` | boolean | optional | Whether to validate access token with authorization server (vs. checking local expiry only). |

---

### `auth.deviceLogin`

Initiate OAuth 2.0 device authorization flow (RFC 8628) for CLI/IDE authentication. Returns device code and user code for browser-based consent, then polls until user approves or denies access.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `client_id` | string | optional | OAuth client identifier for the requesting application. |
| `scopes` | array<string> | optional | Requested OAuth scopes (e.g., ['behaviors.read', 'runs.create']). |
| `poll_interval` | integer | optional | Polling interval in seconds. Server may enforce minimum (default 5s per RFC 8628). |
| `timeout` | integer | optional | Maximum time in seconds to wait for user authorization before giving up. |
| `store_tokens` | boolean | optional | Whether to persist tokens in system keychain (or file fallback). Recommended for persistent authentication. |

---

### `auth.ensureGrant`

Perform a just-in-time authorization check for a tool invocation and return consent details or grant metadata.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `agent_id` | string | **required** | Registered agent identifier. |
| `user_id` | string | optional | Human user id when acting on behalf of a person. |
| `surface` | string (`WEB`, `CLI`, `API`, `VS_CODE`, `MCP`) | **required** |  |
| `tool_name` | string | **required** | Tool/action identifier. Must match ACTION_REGISTRY_SPEC. |
| `scopes` | array<string> | **required** |  |
| `context` | object | optional | Optional context such as run_id or resource identifiers. |

---

### `auth.listGrants`

List active and historical grants for an agent and optional user scope.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `agent_id` | string | **required** | Registered agent identifier. |
| `user_id` | string | optional | Filter by human user id. |
| `tool_name` | string | optional | Filter by tool/action identifier. |
| `include_expired` | boolean | optional |  |
| `page_size` | integer | optional |  |
| `page_token` | string | optional |  |

---

### `auth.logout`

Revoke OAuth tokens and remove them from storage. Optionally revokes tokens with authorization server (requires network connectivity) or clears local storage only.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `client_id` | string | optional | OAuth client identifier for which to clear tokens. Defaults to amprealize-mcp-client. |
| `revoke_remote` | boolean | optional | Whether to revoke tokens with authorization server (RFC 7009) before clearing local storage. Recommended true for security. |

---

### `auth.policy.preview`

Evaluate a potential tool invocation against the current policy bundle without mutating state.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `agent_id` | string | **required** |  |
| `user_id` | string | optional |  |
| `tool_name` | string | **required** |  |
| `scopes` | array<string> | **required** |  |
| `context` | object | optional |  |
| `bundle_version` | string | optional | Optional policy bundle hash; defaults to latest. |

---

### `auth.refreshToken`

Refresh an expired access token using a stored refresh token. Follows OAuth 2.0 refresh token grant (RFC 6749 §6). Returns new access token without requiring user interaction.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `client_id` | string | optional | OAuth client identifier for which to refresh tokens. Defaults to amprealize-mcp-client. |
| `store_tokens` | boolean | optional | Whether to persist refreshed tokens in system keychain (or file fallback). Recommended true. |

---

### `auth.revoke`

Revoke an existing grant and invalidate cached credentials for an agent/user/tool combination.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `grant_id` | string | **required** | Identifier of the grant to revoke. |
| `revoked_by` | string | **required** | Actor (user id or system principal) performing the revocation. |
| `reason` | string | optional | Optional explanation logged to audit trail. |

---

## Service: bci

**Tool count**: 11

### `bci.composeBatchPrompts`

Compose prompts for multiple query/behavior pairs in a single request to optimize batching.

**Parameters:** None

---

### `bci.composePrompt`

Compose a behavior-conditioned prompt using retrieved behavior snippets and citation controls.

**Parameters:** None

---

### `bci.computeTokenSavings`

Calculate token savings achieved by behavior-conditioned prompting versus a baseline.

**Parameters:** None

---

### `bci.detectPatterns`

Detect reusable reasoning patterns across traces to seed new behaviors.

**Parameters:** None

---

### `bci.parseCitations`

Extract behavior citations from model output to support compliance validation.

**Parameters:** None

---

### `bci.rebuildIndex`

Rebuild the BehaviorRetriever semantic index from all approved behaviors. This creates fresh embeddings using the BGE-M3 model and updates the FAISS index for semantic retrieval. The index is automatically rebuilt when behaviors are approved, but this tool allows manual triggering for operational tasks.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `force` | boolean | optional | Force rebuild even if index is current (default: false) |

---

### `bci.retrieve`

Retrieve top-K behaviors using hybrid embedding/keyword scoring for behavior-conditioned inference.

**Parameters:** None

---

### `bci.retrieveHybrid`

Retrieve behaviors with explicit hybrid weighting configuration for embedding and keyword scores.

**Parameters:** None

---

### `bci.scoreReusability`

Score a candidate behavior's reusability using weighted evaluation dimensions.

**Parameters:** None

---

### `bci.segmentTrace`

Segment chain-of-thought or structured traces into indexed steps for downstream pattern detection.

**Parameters:** None

---

### `bci.validateCitations`

Validate that model output cites prepended behaviors according to compliance rules.

**Parameters:** None

---

## Service: behaviors

**Tool count**: 9

### `behaviors.approve`

Approve a behavior for production use. Changes status from PENDING_REVIEW to APPROVED. Requires approval authority. Returns the approved behavior.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `behavior_id` | string | **required** | Behavior ID to approve |
| `version` | string | **required** | Version to approve (must be PENDING_REVIEW) |
| `effective_from` | string | **required** | ISO8601 timestamp when behavior becomes active (defaults to now) |
| `approval_action_id` | string | optional | Optional ActionService action ID recording the approval decision |
| `actor` | object | **required** | Actor must have approval authority (behaviors:approve scope) |

---

### `behaviors.create`

Create a new behavior draft in the handbook. Returns the created behavior with status=DRAFT and version=0.1.0.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | **required** | Behavior name (concise, action-oriented) |
| `description` | string | **required** | Brief description of what the behavior does |
| `instruction` | string | **required** | Procedural instruction defining how to apply the behavior |
| `role_focus` | string (`STRATEGIST`, `TEACHER`, `STUDENT`) | **required** | Primary role that uses this behavior |
| `trigger_keywords` | array<string> | optional | Keywords that suggest when this behavior applies |
| `tags` | array<string> | optional | Tags for categorization and filtering |
| `examples` | array<object> | optional | Usage examples demonstrating the behavior |
| `metadata` | object | optional | Additional metadata (source, references, etc.) |
| `embedding` | array<number> | optional | Optional pre-computed embedding vector for semantic search |
| `base_version` | string | optional | Optional base version if creating a revision of an existing behavior |
| `actor` | object | **required** |  |

---

### `behaviors.deleteDraft`

Permanently delete a behavior draft. Only DRAFT behaviors can be deleted. This operation cannot be undone.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `behavior_id` | string | **required** | Behavior ID to delete |
| `version` | string | **required** | Version to delete (must be DRAFT) |
| `actor` | object | **required** |  |

---

### `behaviors.deprecate`

Deprecate an approved behavior. Changes status from APPROVED to DEPRECATED. Optionally specify a successor behavior. Returns the deprecated behavior.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `behavior_id` | string | **required** | Behavior ID to deprecate |
| `version` | string | **required** | Version to deprecate (must be APPROVED) |
| `effective_to` | string | **required** | ISO8601 timestamp when deprecation takes effect (defaults to now) |
| `successor_behavior_id` | string | optional | Optional ID of the behavior that replaces this one |
| `actor` | object | **required** | Actor must have deprecation authority |

---

### `behaviors.get`

Retrieve a specific behavior by ID with full details including instruction, examples, and metadata. Optionally specify a version.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `behavior_id` | string | **required** | Unique behavior identifier (bhv-<12-char-hex>) |
| `version` | string | optional | Optional semantic version (defaults to latest approved) |

---

### `behaviors.list`

List behaviors from the handbook with optional filters for status, tags, and role focus. Returns an array of behavior summaries.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `status` | string (`DRAFT`, `PENDING_REVIEW`, `APPROVED`, `DEPRECATED`) | optional | Filter behaviors by lifecycle status |
| `tags` | array<string> | optional | Filter behaviors by tags (exact match) |
| `role_focus` | string (`STRATEGIST`, `TEACHER`, `STUDENT`) | optional | Filter behaviors by role focus |

---

### `behaviors.search`

Search behaviors by natural language query using semantic similarity. Returns ranked results with relevance scores.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | **required** | Natural language search query describing the desired behavior |
| `tags` | array<string> | optional | Optional tags filter to narrow search scope |
| `role_focus` | string (`STRATEGIST`, `TEACHER`, `STUDENT`) | optional | Optional role filter |
| `status` | string (`DRAFT`, `PENDING_REVIEW`, `APPROVED`, `DEPRECATED`) | optional | Optional status filter (defaults to APPROVED for production searches) |
| `limit` | integer | optional | Maximum number of results to return |
| `actor` | object | optional |  |

---

### `behaviors.submit`

Submit a behavior draft for review. Changes status from DRAFT to PENDING_REVIEW. Returns the updated behavior.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `behavior_id` | string | **required** | Behavior ID to submit |
| `version` | string | **required** | Version to submit (must be DRAFT) |
| `actor` | object | **required** |  |

---

### `behaviors.update`

Update an existing behavior draft. Only DRAFT behaviors can be updated. Returns the updated behavior.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `behavior_id` | string | **required** | Behavior ID to update |
| `version` | string | **required** | Version to update (must be DRAFT) |
| `instruction` | string | optional | Updated procedural instruction |
| `description` | string | optional | Updated description |
| `trigger_keywords` | array<string> | optional | Updated trigger keywords |
| `tags` | array<string> | optional | Updated tags |
| `examples` | array<object> | optional | Updated examples |
| `metadata` | object | optional | Updated metadata |
| `embedding` | array<number> | optional | Updated embedding vector |
| `actor` | object | **required** |  |

---

## Service: compliance

**Tool count**: 5

### `compliance.createChecklist`

Create a new compliance checklist to track required evidence steps for a workflow or milestone. Returns the created checklist with an initial coverage_score of 0.0.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `title` | string | **required** | Checklist name (e.g., 'Milestone 1 Compliance Review') |
| `description` | string | optional | Markdown overview of scope and purpose |
| `template_id` | string | optional | Optional reference to workflow template UUID |
| `milestone` | string | optional | Associated milestone (e.g., 'Milestone 1', 'Milestone 2') |
| `compliance_category` | array<string> | **required** | Compliance categories this checklist addresses |
| `actor` | object | **required** | Actor creating the checklist |

---

### `compliance.getChecklist`

Retrieve a single compliance checklist by ID with all steps, evidence, and validation details.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `checklist_id` | string | **required** | Checklist identifier to retrieve |
| `actor` | object | **required** | Actor requesting the checklist |

---

### `compliance.listChecklists`

List compliance checklists with optional filtering by milestone, compliance category, and status. Returns all checklists accessible to the requesting actor.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `milestone` | string | optional | Filter by milestone (e.g., 'Milestone 1') |
| `compliance_category` | array<string> | optional | Filter by compliance categories (OR match) |
| `status_filter` | string (`ACTIVE`, `COMPLETED`, `FAILED`) | optional | Filter by checklist status (ACTIVE = has incomplete steps, COMPLETED = all steps done, FAILED = any step failed) |
| `actor` | object | **required** | Actor requesting the list |

---

### `compliance.recordStep`

Record a compliance checklist step with status, evidence, and behavior citations. Updates the checklist coverage_score automatically.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `checklist_id` | string | **required** | Parent checklist identifier |
| `title` | string | **required** | Actionable step description (e.g., 'Run parity tests') |
| `status` | string (`PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `SKIPPED`) | **required** | Current step status |
| `evidence` | object | optional | Optional evidence payload |
| `behaviors_cited` | array<string> | optional | Behavior IDs referenced during step execution |
| `related_run_id` | string | optional | Optional RunService association |
| `actor` | object | **required** | Actor recording the step |

---

### `compliance.validateChecklist`

Validate a compliance checklist against completion requirements and return coverage score, missing steps, failed steps, and warnings. Requires compliance.validate RBAC scope.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `checklist_id` | string | **required** | Checklist identifier to validate |
| `actor` | object | **required** | Actor requesting validation (requires compliance.validate scope) |

---

## Service: metrics

**Tool count**: 3

### `metrics.export`

Export metrics data to JSON, CSV, or Parquet format for offline analysis. Supports filtering by date range, specific metrics, and optional inclusion of raw telemetry events.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `format` | string (`json`, `csv`, `parquet`) | **required** | Export file format |
| `start_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter from this date |
| `end_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter up to this date |
| `metrics` | array<string> | optional | Optional list of specific metrics to include (empty = all metrics) |
| `include_raw_events` | boolean | optional | Whether to include raw telemetry events in export |

---

### `metrics.getSummary`

Get real-time metrics summary with 30s cache TTL, providing PRD KPI targets: behavior reuse (70%), token savings (30%), task completion (80%), compliance coverage (95%). Faster than analytics.kpiSummary for dashboard updates.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `start_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter results from this date forward |
| `end_date` | string | optional | Optional ISO format date (YYYY-MM-DD) to filter results up to this date |
| `use_cache` | boolean | optional | Whether to use cached data (default: true). Set false to force fresh query. |

---

### `metrics.subscribe`

Create a real-time metrics subscription for SSE streaming. Returns subscription metadata; use the subscription_id to establish an SSE connection for continuous metric updates.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `metrics` | array<string> | optional | Optional list of specific metrics to stream (empty = all metrics) |
| `refresh_interval_seconds` | integer | optional | How often to push metric updates in seconds |

---

## Service: patterns

**Tool count**: 2

### `patterns.detectPatterns`

Detect recurring patterns across multiple execution traces. Analyzes run_ids to identify repeated reasoning sequences using sliding window extraction, similarity grouping, and frequency counting per PRD Component B (TraceAnalysisService). Returns patterns ordered by frequency with occurrence metadata.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `run_ids` | array<string> | **required** | List of run IDs to analyze for pattern detection. |
| `min_frequency` | integer | optional | Minimum occurrences required to consider a pattern (filters rare sequences). |
| `min_similarity` | number | optional | Minimum sequence similarity threshold (0-1) for grouping related patterns using SequenceMatcher. |
| `max_patterns` | integer | optional | Maximum number of patterns to return (limits response size). |
| `include_context` | boolean | optional | Whether to capture before/after steps for each pattern occurrence (enables richer analysis but increases payload size). |

---

### `patterns.scoreReusability`

Score a pattern's reusability using PRD formula (0.4*frequency + 0.3*savings + 0.3*applicability). Evaluates frequency score (pattern_frequency/total_runs), token savings score (tokens_saved*frequency / total_corpus_tokens), and applicability score (unique_task_types/total_task_types). Returns overall_score with approval threshold check (>0.7).

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `pattern_id` | string | **required** | Pattern identifier to score (from detectPatterns output). |
| `total_runs` | integer | **required** | Total runs in analysis period (for frequency normalization). |
| `avg_trace_tokens` | number | **required** | Average tokens per trace in corpus (for savings calculation). |
| `unique_task_types` | integer | **required** | Number of distinct task types where pattern occurred (e.g., debugging, refactoring, testing). |
| `total_task_types` | integer | **required** | Total task types in corpus (for applicability score). |

---

## Service: reflection

**Tool count**: 1

### `reflection.extract`

Extract reusable behavior candidates from a workflow trace via automated reflection.

**Parameters:** None

---

## Service: runs

**Tool count**: 6

### `runs.cancel`

Cancel a running job. Sets status to CANCELLED and records cancellation reason. Returns cancelled run.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `run_id` | string | **required** | Run identifier |
| `reason` | string | optional | Cancellation reason |

---

### `runs.complete`

Complete a run with final status, outputs, and results. Returns completed run.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `run_id` | string | **required** | Run identifier |
| `status` | string (`COMPLETED`, `FAILED`) | **required** | Final run status |
| `outputs` | object | optional | Run outputs and results |
| `message` | string | optional | Completion message |
| `error` | string | optional | Error message (for FAILED status) |
| `metadata` | object | optional | Final metadata updates |

---

### `runs.create`

Create a new workflow execution run. Returns the created run with status=PENDING.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `workflow_id` | string | optional | Workflow identifier |
| `workflow_name` | string | optional | Workflow name for display |
| `template_id` | string | optional | Template identifier |
| `template_name` | string | optional | Template name for display |
| `behavior_ids` | array<string> | optional | List of behavior IDs to use in this run |
| `metadata` | object | optional | Additional run metadata |
| `initial_message` | string | optional | Initial message or description for the run |
| `total_steps` | integer | optional | Total number of steps expected in this run |
| `actor` | object | **required** |  |

---

### `runs.get`

Get run details by ID. Returns the complete run with all steps.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `run_id` | string | **required** | Run identifier |

---

### `runs.list`

List runs with optional filters. Returns array of runs matching criteria.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `status` | string (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`) | optional | Filter by run status |
| `workflow_id` | string | optional | Filter by workflow ID |
| `template_id` | string | optional | Filter by template ID |
| `limit` | integer | optional | Maximum number of runs to return |

---

### `runs.updateProgress`

Update run progress with status, step information, and metadata. Returns updated run.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `run_id` | string | **required** | Run identifier |
| `status` | string (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`) | optional | Updated run status |
| `progress_pct` | number | optional | Progress percentage (0-100) |
| `message` | string | optional | Progress message |
| `step_id` | string | optional | Current step identifier |
| `step_name` | string | optional | Current step name |
| `step_status` | string | optional | Current step status |
| `tokens_generated` | integer | optional | Tokens generated in this run |
| `tokens_baseline` | integer | optional | Baseline tokens for comparison |
| `metadata` | object | optional | Additional metadata to merge |

---

## Service: security

**Tool count**: 1

### `security.scanSecrets`

Execute the Amprealize secret scanning workflow (Gitleaks via pre-commit) and return structured findings for downstream remediation and action logging.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `surface` | string (`CLI`, `CI`, `MCP`) | **required** | Surface invoking the scan. Used for telemetry attribution and guardrail routing. |
| `paths` | array<string> | optional | Relative paths to include in the scan. Defaults to repository root. |
| `fail_on_findings` | boolean | optional | Return a non-zero exit code when findings are detected so callers can block merges/deploys. |
| `report_format` | string (`json`, `table`) | optional | Preferred output style for findings. JSON is recommended for automation. |
| `report_path` | string | optional | Optional path (relative or absolute) where the JSON report should be written for archive/audit purposes. |

---

## Service: tasks

**Tool count**: 3

> ⚠️ **Important**: `tasks` tools are for **agent task assignments** (mapping agents to milestones).
> For **board/kanban tasks** (user-facing work items), use [`workitems.*`](#service-workitems) tools instead.

### `tasks.listAssignments`

List remaining milestone tasks mapped to functions and agents for planning parity.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `function` | string | optional | Optional function filter (engineering, developer-experience, devops, product, pm, product-analytics, copywriting, compliance). |

---

### `tasks.create`

Create an agent task assignment. **Note**: This assigns a task to an agent for milestone tracking. For board/kanban tasks, use `workitems.create` instead.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `agent_id` | string | **required** | Agent ID to assign the task to |
| `title` | string | **required** | Task title |
| `description` | string | optional | Task description |
| `milestone_id` | string | optional | Associated milestone ID |

---

### `tasks.updateStatus`

Update the status of an agent task assignment.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `task_id` | string | **required** | Task ID to update |
| `status` | string | **required** | New status (pending, in_progress, completed, blocked) |

---

### `tasks.getStats`

Get statistics about agent task assignments.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `agent_id` | string | optional | Filter by agent ID |

---

## Service: workitems

**Tool count**: 6

> ✅ **Use these tools for board/kanban tasks** - user-facing work items on project boards.
> For agent task assignments (milestone tracking), use [`tasks.*`](#service-tasks) tools instead.

### `workitems.create`

Create a new work item (task, story, epic, bug) on a board.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `board_id` | string | **required** | Board ID to create the item on |
| `title` | string | **required** | Work item title |
| `item_type` | string | optional | Type: task, story, epic, bug (default: task) |
| `description` | string | optional | Work item description |
| `status` | string | optional | Status: todo, in_progress, done (default: todo) |
| `priority` | string | optional | Priority: low, medium, high, critical (default: medium) |
| `assignee_id` | string | optional | User or agent ID to assign |
| `labels` | array | optional | Array of label strings |

---

### `workitems.get`

Retrieve a work item by ID.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `item_id` | string | **required** | Work item ID |

---

### `workitems.list`

List work items on a board with optional filters.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `board_id` | string | **required** | Board ID to list items from |
| `status` | string | optional | Filter by status |
| `item_type` | string | optional | Filter by type |
| `assignee_id` | string | optional | Filter by assignee |
| `limit` | integer | optional | Max items to return (default: 100) |
| `offset` | integer | optional | Pagination offset |

---

### `workitems.update`

Update an existing work item.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `item_id` | string | **required** | Work item ID to update |
| `title` | string | optional | New title |
| `description` | string | optional | New description |
| `status` | string | optional | New status |
| `priority` | string | optional | New priority |
| `assignee_id` | string | optional | New assignee |
| `labels` | array | optional | New labels (replaces existing) |

---

### `workitems.delete`

Delete a work item.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `item_id` | string | **required** | Work item ID to delete |

---

### `workitems.move` *(DEPRECATED)*

> **Deprecated**: Use `workItems.moveToColumn` instead, which is a strict superset supporting both `column_id` and `status_mapping` parameters plus audit fields.

Move a work item to a different column. Calls through to `workItems.moveToColumn` internally.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `item_id` | string | **required** | Work item ID to move (mapped to `work_item_id`) |
| `column_id` | string | optional | Target column ID |
| `position` | integer | optional | Position in target column |

---

## Service: workflow

**Tool count**: 5

### `workflow.run.start`

Execute a workflow template with behavior-conditioned inference, injecting retrieved behaviors into prompts at runtime.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `template_id` | string | **required** | Template identifier to execute |
| `behavior_ids` | array<string> | optional | Behavior IDs to inject (auto-retrieves from template if omitted) |
| `metadata` | object | optional | Run metadata |
| `actor` | object | **required** |  |

---

### `workflow.run.status`

Check the status of a workflow run, including step progress, token usage, and behavior citations.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `run_id` | string | **required** | Run identifier (e.g., run-<12-char-hex>) |

---

### `workflow.template.create`

Create a new workflow template with role-specific steps and behavior injection points for Strategist/Teacher/Student execution patterns.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | **required** | Template name (max 200 characters) |
| `description` | string | **required** | Template description (max 1000 characters) |
| `role_focus` | string (`STRATEGIST`, `TEACHER`, `STUDENT`, `MULTI_ROLE`) | **required** | Primary role this template targets |
| `steps` | array<object> | **required** | Array of template steps (1-50 steps) |
| `tags` | array<string> | optional | Tags for categorization |
| `metadata` | object | optional | Additional template metadata |
| `actor` | object | **required** |  |

---

### `workflow.template.get`

Retrieve a workflow template by ID with full step definitions.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `template_id` | string | **required** | Template identifier (e.g., wf-<12-char-hex>) |

---

### `workflow.template.list`

List workflow templates with optional filters by role and tags.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `role_focus` | string (`STRATEGIST`, `TEACHER`, `STUDENT`, `MULTI_ROLE`) | optional | Filter templates by primary role |
| `tags` | array<string> | optional | Filter templates containing these tags |

---


## Usage

To call any tool via MCP:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "behaviors.list",
    "arguments": {}
  }
}
```

## Batch Requests

The MCP server supports batch requests per JSON-RPC 2.0 spec:

```json
[
  {"jsonrpc":"2.0", "id":1, "method":"tools/call", "params":{"name":"behaviors.list"}},
  {"jsonrpc":"2.0", "id":2, "method":"tools/call", "params":{"name":"runs.list"}}
]
```

## Common Confusion: Tasks vs Work Items

| If you want to... | Use this tool | Why |
|-------------------|---------------|-----|
| Create a kanban/board task | `workitems.create` | Board tasks are user-facing work items |
| List tasks on a project board | `workitems.list` | Board items have board_id, columns, etc. |
| Assign an agent to a milestone | `tasks.create` | Agent task assignments require agent_id |
| Check agent workload | `tasks.listAssignments` | Shows milestone→agent mappings |

### Quick Reference

```json
// ✅ Create a board task (user work item)
{"name": "workitems_create", "arguments": {"board_id": "...", "title": "My Task"}}

// ❌ WRONG - tasks.create needs agent_id (it's for agent assignments)
{"name": "tasks_create", "arguments": {"title": "My Task"}}  // Missing agent_id!
```

---

*Generated from 64 tool manifests*
