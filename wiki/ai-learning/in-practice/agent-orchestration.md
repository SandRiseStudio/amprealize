---
title: "Agent Orchestration in Amprealize"
type: in-practice
difficulty: advanced
prerequisites:
  - concepts/multi-agent.md
  - in-practice/bci-in-amprealize.md
  - in-practice/context-composition.md
tags:
  - amprealize
  - agents
  - orchestration
last_updated: "2026-05-04"
sources:
  - "amprealize/agent_orchestrator_service.py"
  - "amprealize/agent_execution_loop.py"
  - "amprealize/session_audit.py"
  - "amprealize/agent_registry_service.py"
  - "amprealize/execution_gateway.py"
  - "amprealize/execution_gateway_contracts.py"
  - "amprealize/policy_composition.py"
  - "amprealize/execution_gateway_adapter.py"
  - "amprealize/services/work_item_execution_api.py"
  - "amprealize/work_item_execution_service.py"
  - "amprealize/work_item_execution_contracts.py"
  - "amprealize/plan_artifact_contracts.py"
  - "amprealize/plan_approval_service.py"
  - "amprealize/chat_action_router.py"
  - "amprealize/agent_lifecycle_actions.py"
  - "amprealize/platform_management_actions.py"
  - "web-console/src/components/conversations/MessageBubble.tsx"
  - "web-console/src/components/conversations/ConversationPanel.css"
  - "web-console/src/lib/executionControls.ts"
  - "web-console/src/components/boards/BoardPage.tsx"
  - "web-console/src/components/boards/WorkItemDrawer.tsx"
  - "tests/test_execution_gateway_adapter.py"
  - "tests/test_chat_governance_boundaries.py"
  - "tests/test_chat_action_router.py"
  - "amprealize/conversation_contracts.py"
  - "amprealize/services/conversation_service.py"
  - "amprealize/services/conversation_reply_service.py"
  - "amprealize/conversation_event_hub.py"
  - "amprealize/conversation_realtime_redis.py"
  - "amprealize/global_chat_context.py"
  - "amprealize/context_composer.py"
  - "web-console/src/components/conversations/StreamingMessage.tsx"
  - "web-console/src/api/conversations.ts"
  - "migrations/versions/20260424_expand_conversation_workspace_scopes.py"
  - "docs/CONVERSATION_SYSTEM_PLAN.md"
  - "amprealize/research_service.py"
  - "amprealize/research/ingesters/url_ingester.py"
  - "tests/test_research_work_items.py"
  - "amprealize/resource_analysis.py"
  - "amprealize/tool_executor.py"
  - "docs/contracts/LOCAL_CONNECTOR_TOOL_PROTOCOL.md"
  - "amprealize/local_execution_connector_hub.py"
  - "amprealize/local_connector_tool_delegate.py"
  - "amprealize/mode_executors.py"
  - "amprealize/services/resource_analysis_api.py"
  - "amprealize/mcp_server.py"
  - "web-console/src/api/resources.ts"
  - "mcp/tools/resources.analyze.json"
  - "tests/test_resource_analysis.py"
  - "tests/test_resource_analysis_api.py"
  - "tests/test_mcp_resource_analysis_tool.py"
amprealize_relevance: "Direct walkthrough of Amprealize's multi-agent system — role-based dispatch, behavior-conditioned execution, and handoff patterns."
visibility: internal
---

# Agent Orchestration in Amprealize

## What It Is

Amprealize implements a supervisor-pattern multi-agent system where the orchestrator routes tasks to specialized agents based on role declarations, behavior conditions, and task requirements.

## How It Maps to Concepts

| AI/ML Concept | Amprealize Implementation |
|--------------|--------------------------|
| [Multi-Agent Orchestration](../concepts/multi-agent.md) | `agent_orchestrator_service.py` — supervisor pattern |
| [Prompt Engineering](../concepts/prompt-engineering.md) | Per-agent system prompts with role-specific instructions |
| [RAG](../concepts/rag.md) | Each agent call includes BCI-retrieved behaviors |

## Architecture

```
Task Request
    ↓
[Agent Orchestrator]
    ├── Role Detection (Student/Teacher/Strategist)
    ├── Behavior Retrieval (BCI)
    ├── Context Composition
    └── Agent Dispatch
         ↓
[Agent Execution Loop]
    ├── Tool Calls (MCP tools)
    ├── Self-Monitoring (adherence tracking)
    └── Result / Handoff
         ↓
[Handoff Work Item] (if ADOPT/ADAPT verdict)
```

For assigned work item execution, Amprealize is migrating toward a gateway-first path:

```
Board / Chat / REST / MCP / CLI
    ↓
[ExecutionRequest]
    ↓
[ExecutionGateway]
    ├── Resolve agent, model, source, mode, output target
    ├── Compose policy signals before records are created
    ├── Create Run + TaskCycle records
    ├── Preserve compatibility fields for existing clients
    └── Dispatch to queue / worker path
         ↓
[Agent Execution Loop]
```

`ExecutionIntent` separates full execution from plan-only requests. Plan-only is important for governed chat because the agent can draft a durable plan linked to the work item or conversation before a user approves a separate write-capable execution run.

REST and MCP keep the legacy service response contract while using the gateway as the canonical start boundary. Their execution factories accept an `ExecutionGateway` and wrap only the start path through `GatewayWorkItemExecutionAdapter`; `AMPREALIZE_EXECUTION_GATEWAY_ENABLED=false` remains as an explicit legacy fallback. Gateway dispatch then chooses between `background` for local validation and `queue` for worker execution via `AMPREALIZE_EXECUTION_GATEWAY_DISPATCH`.

**Workspace drivers:** `execution_workspace_kind` selects **`cloud_git`** (BreakerAmp / Podman isolated clone; tools via container exec when provisioned) versus **`local_connector`** (hybrid: `AgentExecutionLoop` runs in the API process with **`background` dispatch** only; file/shell tools delegate over the paired connector WebSocket — `tool.invoke` / `tool.result` per `docs/contracts/LOCAL_CONNECTOR_TOOL_PROTOCOL.md`. Starting `local_connector` when `dispatch_mode=queue` and a queue publisher is configured fails fast).

The execution trace surface is also becoming shared product infrastructure. Execution status and step responses now carry the same origin clues that the gateway and worker record: surface, source type, conversation/message/request IDs, queue job metadata, phase timing summaries, token/cost/tool aggregates, and last error. The work item drawer consumes those fields in its activity feed so a chat-triggered run and a board-triggered run can be inspected with the same timeline language even before a standalone run page exists.

Research work items add a specialized orchestration branch. The board item can be assigned to any user or agent for ownership, but `ExecutionGateway` treats `item_type=research` as a governed dispatch case: it validates `metadata.research_url`, resolves the builtin agent registry slug `ai_research`, rejects arbitrary agent overrides, and runs `ResearchService.evaluate()` with `SourceType.URL`. This keeps the task-management model flexible while making the execution identity and URL-fetching boundary explicit and auditable.

Plan-only output is represented by `PlanArtifact` in `amprealize/plan_artifact_contracts.py`. The artifact gives chat and work item cards a stable plan ID, version history, links back to the message/work item/agent/source run, and explicit draft, approved, discarded, and executed states. Approval does not mutate the plan into an execution; it only makes the artifact eligible for a separate execution run that records its own run ID.

`GUIDEAI-1055` turns that contract into a gateway mode. When the request intent is `plan_only`, the gateway still creates auditable Run and TaskCycle records, but it derives a read-only policy, denies write/platform-mutating tools, creates a draft plan artifact, returns a summary card, marks the run as `run_type=plan_only`, and never queues or starts an executor. This makes planning a governed artifact-producing step rather than a disguised execution run.

`GUIDEAI-1056` adds the approval bridge. `PlanApprovalService` lets users revise or discard draft artifacts without starting work, and starts execution only through `approve_and_start_execution()`. That method creates a new gateway `ExecutionRequest` with `intent=execute` and the approved `plan_artifact_id`; the plan artifact is marked executed only after the new run is successfully created. The orchestration pattern is therefore two-step: plan artifact first, approved execution run second.

`GUIDEAI-1057` adds a deterministic chat action router before tool dispatch. `ChatActionRouter` converts user messages and preset commands into typed `ChatActionCandidate` objects for read/synthesis, work management, agent management, execution planning, execution start, MCP tools, attachments, and invite/share. Each candidate carries confidence, permission surface/action, required scopes, risk, and approval/clarification flags, giving governance and UI cards a shared pre-dispatch contract.

`GUIDEAI-1058` adds the first governed platform-action boundary behind those candidates. `AgentLifecycleActionService` handles agent discovery, project assignment, custom-agent creation, tool/policy modification, publishing, and archive/delete requests. Before it dispatches to registry/project services, it evaluates `PolicyCompositionEngine`; sensitive operations require approval and every attempt emits a `GovernedChatAuditLogger` platform-action record.

`GUIDEAI-1059` extends the pattern to platform management. `PlatformManagementActionService` handles project, org, board, work item, invite/share, file, upload, image, and MCP-tool access actions. It validates target and scope before policy evaluation, requires approval for invites/shares and tool access changes, and dispatches only through configured typed services.

`GUIDEAI-1061` makes those governed moments visible as live chat artifacts. `MessageBubble` now recognizes `structured_payload.card_kind` values for work items, runs, plan artifacts, and recovery prompts, so the same transcript can show assignment state, execution queue/phase, plan review actions, progress, and blocked-run recovery without creating a separate message type for each artifact.

`GUIDEAI-1062` keeps the board, drawer, and chat controls aligned with a shared execution-control model. `executionControls.ts` normalizes gateway states such as queued, running, paused, clarification-needed, failed, completed, and cancelled, then derives the same active-run gating and action labels for board cards, `WorkItemDrawer`, and chat run artifact cards. This prevents the orchestration UI from telling users different stories about the same run depending on where they look.

`GUIDEAI-1063` and `GUIDEAI-1064` add validation around those boundaries. Gateway parity tests now compare REST, MCP, CLI-shaped, and chat-shaped start requests against the same `ExecutionRequest` signature, while chat governance tests prove global chat withholds inaccessible resources, group-chat execution uses conversation/project/agent scopes, MCP tool grants require approval, attachments require scope, and agent lifecycle mutations can be blocked before registry dispatch.

`GUIDEAI-1065` closes the global chat grounding loop. `WorkspaceInventoryProvider` gathers the user's accessible projects, project-agent assignments, boards, recent work items, recent runs, relevant behaviors, and AI/platform wiki hits before the model is called. It uses in-process service calls instead of loopback HTTP, fetches independent resource groups concurrently, and keeps a short deterministic inventory cache so global questions like "what projects do I have?" or "what agents are assigned to GuideAI?" are answered from platform state rather than model memory.

The reply path now emits a durable lifecycle around that context work. `ConversationReplyService` uses one `stream_message_id` from scheduling through persistence and publishes `reply.started`, `reply.step`, `reply.token`, `reply.complete`, and `reply.error` alongside the legacy token stream. The chat UI uses those labels for visible progress, then typewriter-reveals the generated response while respecting reduced-motion preferences.

Realtime delivery is now split from durable memory. `ConversationEventHub` remains the orchestration-facing facade, but it can use Redis as a hot path: Pub/Sub fans out current `reply.*` and token events across API workers, while Redis Streams keep a short replay window for late or reconnecting SSE subscribers. Local OSS and tests can still use the in-memory hub; local Postgres, Neon, and enterprise Postgres stay responsible for the durable transcript, permissions, search, and context reads.

Some global-chat questions now use deterministic orchestration instead of model generation. After `ContextComposer` returns the workspace inventory, `ConversationReplyService` delegates simple factual questions to `InventoryAnswerService`: project lists, available agents, project-agent assignments, active runs, and recent or blocked work items can all be answered directly from accessible platform state. The reply still uses the same lifecycle events and durable message persistence, but skips the LLM round trip that would otherwise dominate latency for factual lookups. Those replies also carry cited source rows, structured artifact payloads, and fast-path telemetry so the UI can show a Hex-style "Show work" trace and admins can see context misses.

The context layer is becoming a product surface instead of a hidden prompt implementation detail. `WorkspaceInventoryProvider` can include always-on workspace rules, retrieved guide/wiki hits, endorsed project IDs, and admin-visible `context_sources` metadata. This mirrors the same orchestration pattern used elsewhere in Amprealize: fast deterministic facts first, curated context second, and agentic synthesis only when the request needs it.

The natural-language analyst path generalizes that pattern beyond a handful of inventory questions. `ResourceAnalysisService` builds an auditable `ResourceQueryPlan`, answers factual count/list/group questions from access-checked rows, and allows LLM assistance only for plan refinement or concise synthesis. Chat uses it through `InventoryAnswerService`, work-item agents use the governed read-only `resource_analyze` tool, MCP clients can call `resources.analyze`, and REST clients can call `POST /api/v1/resources:analyze` with the same response shape. The important orchestration boundary is that the LLM may help interpret the question, but row retrieval, filtering, grouping, and mutation gates remain deterministic.

Amprealize Chat is the user-facing coordination surface for this gateway path. Its target workspace model separates global user chat from project spaces:

```
Global User Chat
    ├── Links to accessible projects / work items / runs / plans / files / tools
    └── Re-checks access per linked resource

Project Space
    ├── Project room
    ├── Direct messages
    ├── Mixed user/agent group chats
    ├── Work item threads
    └── Run threads
```

`conversation_contracts.py` keeps legacy `project_room` and `agent_dm` scopes available while defining target scopes such as `global_user_home`, `project_space`, `dm`, `group_chat`, `work_item_thread`, and `run_thread`. The runtime now follows that model: `global_user_home` persists with `project_id = null`, project-space scopes require `project_id`, and legacy `agent_dm` input normalizes to target `dm` while old `agent_dm` rows remain readable.

The product experience for this orchestration path is a bottom-first Amprealize Chat surface. Global chat starts as a frosted dock, expands into a peek sheet, opens into a full glass chat window, and can be dragged once expanded. Work item and run cards should render inline as live objects in the transcript, while the composer behaves like natural-language chat plus `@` agent/user mentions, `#` resource references, contextual quick chips, and attachment intelligence. Agent presence stays subtle by default and becomes more expressive during active planning, execution, tool use, and handoffs.

This UX matters to orchestration because governance events are user-facing moments: plan approvals, tool-risk decisions, run progress, blocked actions, and handoffs should appear as clear chat artifacts rather than detached logs.

The chat permission matrix makes those governance moments explicit. `CHAT_PERMISSION_MATRIX` in `conversation_contracts.py` maps global chat, project spaces, group chats, work item threads, run threads, agent lifecycle actions, MCP tools, attachments, and platform actions across `read`, `create`, `update`, `delete`, `invite_share`, `execute`, `publish`, and `administer`. Execution-style cells are approval-gated, and ambiguous or missing scope combinations are deny-by-default.

`PolicyCompositionEngine` is the runtime composition boundary. Before the gateway creates Run or TaskCycle records, it gathers user, org, project, conversation, agent, MCP/tool, attachment, chat-matrix, and action-risk policy signals, then applies most-restrictive-wins semantics: `deny` beats `review`, and `review` beats `allow`. Review decisions gate sensitive operations until an `approved_by` actor is present. If policy evaluation itself fails, the engine fails closed to `deny` and returns audit events for telemetry.

`GovernedChatAuditLogger` turns those governance moments into append-only, sanitized audit records. The gateway records intent classification, chat scope resolution, policy decisions, approvals or denials, and execution starts with user, target resource, work item, run, conversation, action, decision, and policy-source fields. Session-mode tool calls can also write governed chat audit records, and denied or review-required records are queryable for operator follow-up without exposing secrets or raw sensitive payloads.

## Key Components

- `agent_orchestrator_service.py` — Routes tasks to agents
- `agent_execution_loop.py` — Runs the agent cycle (think → act → observe)
- `agent_registry_service.py` — Registers available agents and their capabilities
- `adherence_tracker.py` — Monitors whether agents follow their behaviors
- `execution_gateway.py` — Canonical start boundary for assigned work item execution
- `execution_gateway_contracts.py` — Shared request/result contract for board, chat, REST, MCP, and CLI
- `policy_composition.py` — Most-restrictive-wins policy evaluator for runtime execution governance
- `session_audit.py` — Session-mode tool audit logging plus governed chat audit records for policy and execution decisions
- `execution_gateway_adapter.py` — Compatibility adapter that lets legacy REST/MCP execution handlers call the gateway-shaped contract
- `conversation_contracts.py` — Shared chat workspace scopes, resource-link contracts, and permission matrix for global chat, project spaces, work item threads, run threads, tools, attachments, and platform actions
- `conversation_service.py` — Runtime persistence boundary that validates project/global scope binding, normalizes legacy scopes, and stores message resource links

## Handoff Pattern

When an agent's work produces an actionable verdict (e.g., research evaluation yields ADOPT), the orchestrator creates a work item for the next agent. This is the sequential pipeline pattern from [Multi-Agent Orchestration](../concepts/multi-agent.md).

## See Also

- [BCI In Practice](bci-in-amprealize.md) — How agents get their behaviors
- [Context Composition In Practice](context-composition.md) — How agent prompts are built
