---
title: "MCP Tool Families"
type: reference
last_updated: 2026-04-14
applies_to:
  - dev
  - test
  - staging
  - prod
tags:
  - mcp
  - tools
  - api
  - copilot
---

# MCP Tool Families

The Amprealize MCP server exposes **64+ tools** across 16 service families. These tools
are callable from VS Code Copilot Chat, the CLI (`amprealize mcp`), or any
MCP-compatible client.

## Tool Families

### actions (5 tools)
Record, retrieve, and replay agent actions.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `actions.create` | action_type, artifact | Record a new action |
| `actions.get` | action_id | Get action by ID |
| `actions.list` | — | List actions (filter by type, actor, date) |
| `actions.replay` | action_id | Start async replay of an action |
| `actions.replayStatus` | replay_id | Check replay job status |

### agents (3 tools)
Manage agent assignments and lifecycle.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `agents.assign` | agent_id, task_id | Assign agent to task |
| `agents.status` | agent_id | Check agent status |
| `agents.switch` | agent_id, role | Switch agent role |

### analytics (4 tools)
Query platform metrics and KPI summaries.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `analytics.behaviorUsage` | — | Behavior usage statistics |
| `analytics.complianceCoverage` | — | Compliance coverage metrics |
| `analytics.kpiSummary` | — | Key performance indicators |
| `analytics.tokenSavings` | — | BCI token savings report |

### auth (8 tools)
Authentication, authorization, and grant management.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `auth.deviceLogin` | — | Start device flow login |
| `auth.authStatus` | — | Check current auth status |
| `auth.refreshToken` | — | Refresh access token |
| `auth.logout` | — | End session |
| `auth.ensureGrant` | scope | Request permission grant |
| `auth.listGrants` | — | List active grants |
| `auth.revoke` | grant_id | Revoke a grant |
| `auth.policy.preview` | — | Preview auth policies |

### bci (11 tools)
Behavior-Conditioned Inference — retrieve, compose, and analyze.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `bci.retrieve` | query | Retrieve relevant behaviors for a task |
| `bci.retrieveHybrid` | query | Hybrid retrieval (keyword + semantic) |
| `bci.composePrompt` | task, behaviors | Compose BCI-enhanced prompt |
| `bci.composeBatchPrompts` | tasks | Batch prompt composition |
| `bci.computeTokenSavings` | original, bci | Compare token usage |
| `bci.detectPatterns` | trace | Detect reusable patterns in trace |
| `bci.parseCitations` | text | Extract behavior citations |
| `bci.validateCitations` | citations | Validate citation accuracy |
| `bci.rebuildIndex` | — | Rebuild retrieval index |
| `bci.scoreReusability` | behavior | Score behavior reuse potential |
| `bci.segmentTrace` | trace | Segment reasoning trace |

### behaviors (9 tools)
Full behavior lifecycle management.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `behaviors.create` | name, description | Create behavior draft |
| `behaviors.get` | behavior_id | Get behavior by ID |
| `behaviors.list` | — | List behaviors (filter by status, tags) |
| `behaviors.search` | query | Semantic search for behaviors |
| `behaviors.update` | behavior_id | Update behavior draft |
| `behaviors.submit` | behavior_id | Submit for review |
| `behaviors.approve` | behavior_id | Approve behavior |
| `behaviors.deprecate` | behavior_id | Mark as deprecated |
| `behaviors.deleteDraft` | behavior_id | Delete draft behavior |

### compliance (5 tools)
Compliance checklists and policy validation.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `compliance.createChecklist` | name, steps | Create compliance checklist |
| `compliance.getChecklist` | checklist_id | Get checklist by ID |
| `compliance.listChecklists` | — | List all checklists |
| `compliance.recordStep` | checklist_id, step | Record step completion |
| `compliance.validateChecklist` | checklist_id | Validate checklist completeness |

### metrics (3 tools)
Telemetry export and subscription.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `metrics.export` | format | Export metrics data |
| `metrics.getSummary` | — | Get metrics summary |
| `metrics.subscribe` | events | Subscribe to metric events |

### patterns (2 tools)
Pattern detection and reusability analysis.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `patterns.detectPatterns` | trace | Detect patterns in execution traces |
| `patterns.scoreReusability` | pattern | Score reuse potential |

### reflection (1 tool)
Metacognitive reflection extraction.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `reflection.extract` | trace | Extract behaviors from reasoning trace |

### runs (6 tools)
Execution run lifecycle management.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `runs.create` | workflow_name | Create a new run |
| `runs.get` | run_id | Get run by ID |
| `runs.list` | — | List runs (filter by status, workflow) |
| `runs.updateProgress` | run_id, progress | Update run progress |
| `runs.complete` | run_id | Mark run complete |
| `runs.cancel` | run_id | Cancel a run |

### security (1 tool)
Secret scanning and leak detection.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `security.scanSecrets` | — | Scan repo for leaked secrets |

### tasks (3 tools)
Task assignment and tracking.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `tasks.listAssignments` | — | List task assignments |
| `tasks.create` | title | Create task |
| `tasks.updateStatus` | task_id, status | Update task status |

### workitems (6 tools)
Work item CRUD with GWS-compliant naming.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `workitems.create` | title, type | Create work item (goal/feature/task/bug) |
| `workitems.get` | item_id | Get work item by ID |
| `workitems.list` | — | List work items (filter by type, status) |
| `workitems.update` | item_id | Update work item fields |
| `workitems.delete` | item_id | Delete work item |
| `workitems.move` | item_id | Move work item (deprecated) |

### workflow (5 tools)
Workflow templates and execution.

| Tool | Required Params | Description |
|------|-----------------|-------------|
| `workflow.run.start` | template_id | Start workflow from template |
| `workflow.run.status` | run_id | Check workflow run status |
| `workflow.template.create` | name, steps | Create workflow template |
| `workflow.template.get` | template_id | Get template by ID |
| `workflow.template.list` | — | List workflow templates |

## Using MCP Tools

### In VS Code Copilot Chat
Tools are available natively — invoke by name (e.g., `mcp_amprealize_behaviors_list`).

### Via CLI
```bash
amprealize mcp init      # Initialize MCP server
amprealize mcp doctor    # Check MCP health
```

### Tool Schema Location
Tool JSON schemas are in `mcp/tools/`. Each tool has a `.json` file defining its
`inputSchema` with parameter types, descriptions, and required fields.
