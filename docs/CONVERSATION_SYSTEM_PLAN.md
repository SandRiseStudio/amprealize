# AMPREALIZE-361: Agent Conversation System — Implementation Plan

> **Goal**: Enable users and agents to communicate in real-time within project scope, with built-in group chat, direct messages, context-aware agent replies, and Slack bridge integration.

**Status**: Gateway-era workspace model implemented across contracts, persistence, runtime surfaces, live reply progress, and global workspace grounding
**Date**: 2026-03-30
**Last Updated**: 2026-05-01
**Display ID**: AMPREALIZE-361

---

## Table of Contents

1. [Overview](#overview)
2. [Domain Schema](#domain-schema)
3. [ConversationService API](#conversationservice-api)
4. [ContextComposer](#contextcomposer)
5. [Event Protocol](#event-protocol)
6. [Rate Limiting](#rate-limiting)
7. [Full-Text Search](#full-text-search)
8. [Retention Policy](#retention-policy)
9. [Agent-Initiated Messages](#agent-initiated-messages)
10. [Web Console UX](#web-console-ux)
11. [Slack Bridge](#slack-bridge)
12. [VS Code Extension (v2)](#vs-code-extension-v2)
13. [OSS / Enterprise Boundary](#oss--enterprise-boundary)
14. [Open Questions (Resolved)](#open-questions-resolved)
15. [Phase Sequence](#phase-sequence)
16. [Debugging global prioritization chat](#debugging-global-prioritization-chat)

---

## Overview

The conversation system introduces real-time messaging between users and agents. The original design was project-scoped with two conversation scopes:

| Scope | Description |
|-------|-------------|
| **project_room** | Group conversation per project. All project members (users + agents) participate. Agent-to-agent messages are visible. System messages announce status changes. |
| **agent_dm** | 1:1 direct message between a user and an agent. Private to the pair. Focused work discussions. |

**Key Principles**:
- Project-space conversations remain project-scoped unless explicitly linked from global chat
- Agents respond with full project context via ContextComposer
- Messages stream token-by-token for agent replies
- Structured message types (status cards, blocker cards, code blocks) alongside plain text
- Built-in chat is the canonical store; Slack is a bridge

### Target Chat Workspace Model

`guideai-1039` expands the conversation system into a Slack-like Amprealize Chat model with two workspace kinds:

| Workspace kind | Scope boundary | Purpose |
| --- | --- | --- |
| `global` | User home across all orgs, projects, boards, work items, runs, files, agents, and MCP tools the user can access | A personal assistant chat that can synthesize across accessible resources without changing the underlying resource permissions. |
| `project` | One Amprealize project and its assigned users, agents, work items, runs, files, uploads, images, and tools | The collaboration space for project-room messages, DMs, group chats, work item threads, and run threads. |

Target conversation scopes are defined in `amprealize/conversation_contracts.py`:

| Scope | Workspace kind | Description |
| --- | --- | --- |
| `global_user_home` | `global` | The user's global Amprealize chat. It is not bound to a single `project_id`; every linked project resource must still pass access checks. |
| `project_space` | `project` | The root container for project-space navigation and participant discovery. |
| `project_room` | `project` | Existing automatic project room. Retained as the canonical room inside a project space. |
| `dm` | `project` | Target direct-message primitive for user-to-user, user-to-agent, and agent-to-agent DMs when policy allows. |
| `agent_dm` | `project` | Legacy 1:1 user-agent DM scope. Kept for compatibility and normalized to `dm` in the target model. |
| `group_chat` | `project` | Arbitrary mixed user/agent group chat within a project space. |
| `work_item_thread` | `project` | Conversation centered on a work item, linkable from the project room or any group chat. |
| `run_thread` | `project` | Conversation centered on an execution run, linkable from run cards and execution events. |

Scope resolution follows these rules:

- `global_user_home` conversations have `project_id = null` and resolve access per linked resource at read/action time.
- Every project-space scope requires `project_id`; no cross-project participant discovery is allowed through a project conversation.
- Global chat can include typed `resource_links` to project-scoped resources, but links are navigation/context hints, not permission grants.
- Global chat inventory includes project-agent assignments from the user-accessible project service so questions like "what agents are assigned to GuideAI?" are answerable from platform state.
- Most-restrictive-wins policy composition for tools, files, and platform actions is handled by the chat governance feature (`guideai-1040`).

Runtime support now matches the target model:

- migration `20260424_conv_scopes` makes `messaging.conversations.project_id` nullable for `global_user_home`, expands the database scope constraint, and indexes global/user scope lookups
- `ConversationService` normalizes legacy `agent_dm` requests to the target `dm` scope for new rows while still matching existing `agent_dm` rows during DM lookup/listing
- REST, CLI, and MCP conversation create/list surfaces accept the full target scope set; project-scoped creates require `project_id`, while global home creates reject it
- message sends can persist `resource_links` in metadata so global chat can point at project resources without granting access

### Chat Permission Matrix

`guideai-1051` locks the permission contract for chat and chat-adjacent actions in `amprealize/conversation_contracts.py` and `docs/contracts/CHAT_PERMISSION_MATRIX.md`. This is intentionally a contract and documentation change only; the full policy engine will consume it later.

The matrix covers these surfaces:

| Surface | Boundary |
| --- | --- |
| `global_chat` | Personal user home across accessible resources; never grants project access by itself. |
| `project_space` | Project-level collaboration root. |
| `group_chat` | Explicit participant conversation inside one project. |
| `work_item_thread` | Work-item-centered thread linked to a project work item. |
| `run_thread` | Run-centered thread linked to execution status, logs, and controls. |
| `agent_lifecycle` | Agent draft, activation, assignment, deprecation, and publishing actions. |
| `mcp_tool` | MCP tool discovery, grants, invocation, and administration. |
| `attachment` | Files, uploads, images, links, and derived artifacts attached to chat. |
| `platform_action` | Cross-surface platform mutations triggered from chat. |

It covers `read`, `create`, `update`, `delete`, `invite_share`, `execute`, `publish`, and `administer`, and distinguishes `user`, `org`, `project`, `conversation`, and `agent` scopes. Any missing, ambiguous, or conflicting scope combination is deny-by-default; execution-style actions require an explicit approval, grant, or gate decision before runtime enforcement may proceed.

### Chat Action Router

`guideai-1057` adds a deterministic typed action router in `amprealize/chat_action_router.py`. It maps natural-language chat requests and preset commands to `ChatActionCandidate` objects so policy, approval, cards, and service dispatch can share the same typed contract before any tool or platform mutation happens.

The first router slice covers these action families: read/synthesis, work management, agent management, execution planning, execution start, MCP tool invocation, attachment handling, and invite/share. Each candidate includes confidence, permission surface/action, required scopes from `CHAT_PERMISSION_MATRIX`, risk level, approval requirement, clarification requirement, target resource type, and policy-context serialization. Ambiguous requests such as "plan and execute" ask for clarification, while high-risk actions such as execution, agent lifecycle changes, MCP tool invocation, and invites require approval before dispatch.

Work-management create requests can execute directly when the message and accessible workspace inventory identify a project, board, work item type, and title. For example, "create a new work item called 'Ephemeral agents' (work type goal) on the GuideAI project board" routes to `work_item.manage`, resolves the GuideAI project board from the inventory context, and dispatches through `PlatformManagementActionService`/`BoardPlatformManagementAdapter` with `PolicyCompositionEngine` and `GovernedChatAuditLogger` still in the path. Ambiguous requests ask for clarification instead of silently falling back to read-only inventory answers.

Chat-internal dispatch is intentionally **not** a loopback REST or MCP call. The invariant is:

`chat message -> ChatActionRouter -> ChatResourceActionRegistry -> PolicyCompositionEngine / approval / audit -> governed action service -> typed domain service`

`amprealize/chat_resource_actions.py` is the dispatch table for chat-originated resource mutations. It defines stable action IDs for work items, boards, projects, orgs, agents, wiki pages/content, behaviors, runs, attachments, and MCP tool invocation. Implemented actions bind to governed in-process services such as `PlatformManagementActionService` and `AgentLifecycleActionService`; registered-but-not-yet-wired backends (wiki, behavior, execution) fail closed until a typed executor is configured. REST and MCP are parity surfaces for external clients and external agents. They should share request/response schemas and permission semantics with chat, but chat should not call `localhost` APIs or MCP handlers for first-party platform mutations. New chat mutation families should add a registry action and a typed adapter around the domain service, then expose the same capability through REST and MCP separately.

Board inventory has a dedicated direct-answer path. Questions such as "what boards exist on the GuideAI project?" return `board_list` structured payloads rather than falling through to the project-list answer just because the query contains the word "project." If a create-work-item request resolves the project but the workspace inventory has no board rows, chat may perform a governed `board.discover` action through `PlatformManagementActionService` before creating the item; if discovery also returns no boards, chat asks for clarification.

### Agent Lifecycle Actions

`guideai-1058` adds `AgentLifecycleActionService` in `amprealize/agent_lifecycle_actions.py` as the governed action boundary for chat-originated agent registry operations. It supports discover, assign-to-project, create custom agent, modify tools, modify policy, publish, and archive/delete actions.

Every lifecycle action builds a `PolicyCompositionEngine` request with `agent_lifecycle` chat surface metadata and writes a `GovernedChatAuditLogger` platform-action record. Mutating tool/policy edits, publish, and archive/delete actions require explicit approval before registry dispatch. Approved actions call the existing typed registry/project services rather than ad hoc tool calls, preserving the same audit and policy envelope for chat, MCP, REST, and future UI cards.

### Platform Management Actions

`guideai-1059` adds `PlatformManagementActionService` in `amprealize/platform_management_actions.py` as the governed action boundary for chat-originated project, org, board, work item, invite/share, file, upload, image, and MCP-tool access changes.

The service validates that sensitive actions include an explicit target, requires file/upload/image actions to carry project or conversation scope, evaluates `PolicyCompositionEngine`, and emits `GovernedChatAuditLogger` platform-action records. Approved actions dispatch to configured typed services by resource family instead of issuing ad hoc MCP/tool calls. Invite/share and MCP tool access changes require explicit approval before dispatch.

### Live Plan And Run Cards

`guideai-1061` extends `MessageBubble` so `structured_payload.card_kind` can render live chat artifacts without adding new message types. The first supported card kinds are `work_item`, `run`, `plan`, and `recovery`.

These cards keep the existing structured-message contract while adding fields for work item status, priority, assignee, agent, branch, run queue state, execution phase, progress percentage, plan artifact ID, completion summaries, and primary/secondary actions. That gives global and project chat a shared inline artifact shape for plan approval, execution progress, blocked recovery, and work-item handoff moments.

### Unified Execution Controls

`guideai-1062` centralizes board, drawer, and chat execution-control semantics in `web-console/src/lib/executionControls.ts`. The shared model normalizes `pending`, `queued`, `running`, `paused`, `needs_clarification`, `failed`, `completed`, and `cancelled` states and derives the same start/cancel/open/refresh labels, disabled-state titles, active-run semantics, and missing-agent/unavailable copy across surfaces.

Board cards and `WorkItemDrawer` now both use that model for start/cancel gating and status copy. Chat run artifact cards use the same action language, so execution controls read consistently whether a user starts from the board, opens the drawer, or sees the run inline in Amprealize Chat.

### Cross-Surface Validation And Migration Evidence

`guideai-1063` validates that gateway starts from REST, MCP, CLI-shaped requests, and chat-shaped requests share equivalent canonical request metadata while retaining their source labels. `tests/test_execution_gateway_adapter.py` also checks that REST and MCP cancel/clarification controls remain consistent while non-start routes finish migrating.

`guideai-1064` validates the chat governance boundary. `tests/test_chat_governance_boundaries.py` covers global chat denial for inaccessible links, mixed human/agent group-chat execution scopes, project-space work item mutations, attachment scope requirements, MCP tool approval flow, agent lifecycle policy denial, and execution-policy tool denial.

The current migration path is therefore gateway-first for starts, compatibility-preserving for deployed REST/MCP response shapes, and policy-first for chat-originated actions. Deferred work should add dedicated CLI UX where absent and continue moving legacy non-start controls from `WorkItemExecutionService` delegation to gateway-native status/control contracts.

### Existing Primitive Mapping

| Existing primitive | Target model | Migration note |
| --- | --- | --- |
| `project_room` | `project_space` root room | Keep the existing row shape and uniqueness rule for one room per project. Add workspace metadata in a later migration rather than rewriting message history. |
| `agent_dm` | `dm` | Preserve existing rows and normalize in contracts. A later migration can backfill `metadata.dm_kind = "agent"` or a dedicated scope once API clients no longer depend on `agent_dm`. |
| Message `run_id`, `work_item_id`, `behavior_id` fields | `resource_links` plus existing columns | Keep existing columns for fast filters and backward compatibility. Store additional links such as plans, files, uploads, images, MCP tools, and platform actions in `resource_links`/`metadata` until schema columns are justified. |

---

## Domain Schema

New `messaging` Postgres schema with 5 tables.

### `messaging.conversations`

```sql
CREATE TABLE messaging.conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      TEXT NOT NULL,
    org_id          TEXT,
    scope           TEXT NOT NULL CHECK (scope IN ('project_room', 'agent_dm')),
    title           TEXT,                          -- nullable; auto-generated for DMs
    created_by      TEXT NOT NULL,                  -- user_id
    pinned_message_id UUID,                        -- single pinned message (v1)
    is_archived     BOOLEAN NOT NULL DEFAULT FALSE,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_project_room UNIQUE (project_id, scope)
        WHERE scope = 'project_room'              -- one room per project
);

CREATE INDEX idx_conversations_project ON messaging.conversations (project_id);
```

**Notes**:
- Partial unique index ensures exactly one `project_room` per project.
- `agent_dm` conversations have no uniqueness constraint (a user can have multiple DM threads with the same agent over time, though typically one active).
- `pinned_message_id` is a single FK for v1 pinning. Multi-pin can be added later via a junction table.

### `messaging.participants`

```sql
CREATE TABLE messaging.participants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES messaging.conversations(id) ON DELETE CASCADE,
    actor_id        TEXT NOT NULL,                  -- user_id or agent_id
    actor_type      TEXT NOT NULL CHECK (actor_type IN ('user', 'agent', 'system')),
    role            TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
    joined_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    left_at         TIMESTAMPTZ,
    last_read_at    TIMESTAMPTZ,                   -- for unread badge calculation
    is_muted        BOOLEAN NOT NULL DEFAULT FALSE,
    notification_preference TEXT NOT NULL DEFAULT 'mentions'
        CHECK (notification_preference IN ('all', 'mentions', 'none')),

    CONSTRAINT uq_conversation_actor UNIQUE (conversation_id, actor_id)
);

CREATE INDEX idx_participants_actor ON messaging.participants (actor_id, actor_type);
CREATE INDEX idx_participants_conversation ON messaging.participants (conversation_id);
```

**Notes**:
- `last_read_at` enables unread message count without a separate read-receipts table.
- `notification_preference` is per-conversation, per-participant. `'mentions'` is the default — user only gets notified on @mentions and blocker cards.

### `messaging.messages`

```sql
CREATE TABLE messaging.messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES messaging.conversations(id) ON DELETE CASCADE,
    sender_id       TEXT NOT NULL,
    sender_type     TEXT NOT NULL CHECK (sender_type IN ('user', 'agent', 'system')),
    content         TEXT,                           -- plain text / markdown
    message_type    TEXT NOT NULL DEFAULT 'text'
        CHECK (message_type IN (
            'text', 'status_card', 'blocker_card', 'progress_card',
            'code_block', 'run_summary', 'system'
        )),
    structured_payload JSONB,                      -- type-specific structured data
    parent_id       UUID REFERENCES messaging.messages(id) ON DELETE SET NULL,  -- thread reply
    run_id          TEXT,                           -- link to execution run
    behavior_id     TEXT,                           -- link to behavior
    work_item_id    TEXT,                           -- link to work item
    is_edited       BOOLEAN NOT NULL DEFAULT FALSE,
    edited_at       TIMESTAMPTZ,
    is_deleted      BOOLEAN NOT NULL DEFAULT FALSE, -- soft delete
    deleted_at      TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Full-text search
    search_vector   TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', COALESCE(content, ''))
    ) STORED
);

CREATE INDEX idx_messages_conversation_created
    ON messaging.messages (conversation_id, created_at DESC);
CREATE INDEX idx_messages_parent
    ON messaging.messages (parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX idx_messages_sender
    ON messaging.messages (sender_id, sender_type);
CREATE INDEX idx_messages_run
    ON messaging.messages (run_id) WHERE run_id IS NOT NULL;
CREATE INDEX idx_messages_search
    ON messaging.messages USING GIN (search_vector);
```

**Notes**:
- `parent_id` enables threaded replies. Top-level messages have `parent_id = NULL`.
- `structured_payload` holds type-specific JSON for rich message types (status cards, blocker cards, etc.).
- `search_vector` is auto-maintained by Postgres — no application-layer indexing needed.
- Soft delete preserves message for audit trail; UI shows "This message was deleted."
- Cross-references to `run_id`, `behavior_id`, `work_item_id` enable ContextComposer grounding and click-through navigation.

### `messaging.reactions`

```sql
CREATE TABLE messaging.reactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      UUID NOT NULL REFERENCES messaging.messages(id) ON DELETE CASCADE,
    actor_id        TEXT NOT NULL,
    actor_type      TEXT NOT NULL CHECK (actor_type IN ('user', 'agent')),
    emoji           TEXT NOT NULL,                  -- unicode emoji or shortcode
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_reaction UNIQUE (message_id, actor_id, emoji)
);

CREATE INDEX idx_reactions_message ON messaging.reactions (message_id);
```

### `messaging.external_bindings`

```sql
CREATE TABLE messaging.external_bindings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES messaging.conversations(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL CHECK (provider IN ('slack', 'teams', 'discord')),
    external_channel_id TEXT NOT NULL,              -- Slack channel ID, etc.
    external_workspace_id TEXT,                     -- Slack workspace ID
    config          JSONB NOT NULL DEFAULT '{}',    -- provider-specific config (bot tokens, etc.)
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    bound_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    bound_by        TEXT NOT NULL,                  -- user who set up the bridge

    CONSTRAINT uq_external_binding UNIQUE (conversation_id, provider, external_channel_id)
);

CREATE INDEX idx_external_bindings_conversation ON messaging.external_bindings (conversation_id);
CREATE INDEX idx_external_bindings_external ON messaging.external_bindings (provider, external_channel_id);
```

---

## ConversationService API

The canonical service for all conversation operations. All surfaces (web, CLI, MCP, Slack bridge) route through this service.

### Core Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/projects/{project_id}/conversations` | Create conversation (DM only; project room auto-created) |
| `GET` | `/v1/projects/{project_id}/conversations` | List conversations for project |
| `GET` | `/v1/conversations/{conversation_id}` | Get conversation details |
| `POST` | `/v1/conversations/{conversation_id}/messages` | Send message |
| `GET` | `/v1/conversations/{conversation_id}/messages` | List messages (paginated, cursor-based) |
| `GET` | `/v1/conversations/{conversation_id}/messages/search?q=` | Full-text search |
| `PATCH` | `/v1/messages/{message_id}` | Edit message (own messages only) |
| `DELETE` | `/v1/messages/{message_id}` | Soft-delete message |
| `POST` | `/v1/messages/{message_id}/reactions` | Add reaction |
| `DELETE` | `/v1/messages/{message_id}/reactions/{emoji}` | Remove reaction |
| `PATCH` | `/v1/conversations/{conversation_id}/participants/{actor_id}` | Update read cursor / mute / notification pref |
| `PUT` | `/v1/conversations/{conversation_id}/pin` | Pin a message |

### Access Control

- **project_room**: All project members (users with `ProjectPermission.VIEW_PROJECT` + assigned agents) auto-join.
- **agent_dm**: Only the DM's user and agent can read/write. Project admins can audit.
- **Message editing**: Only `sender_id` can edit their own message, within 15 minutes of creation.
- **Message deletion**: Sender can soft-delete own messages. Project admins can delete any message.
- **Pinning**: Project members with `ProjectPermission.MANAGE_PROJECT` can pin.

---

## ContextComposer

When an agent responds in a conversation, ContextComposer assembles relevant project context to ground the reply. This is the most complex component.

### Token Budget

Total budget: **12,288 tokens** (12k), allocated in 3 tiers:

| Tier | Budget | Sources |
|------|--------|---------|
| **Conversation** | 4,096 tokens | Recent messages in the current conversation (last N that fit) |
| **Project State** | 5,120 tokens | Active work items, recent runs, agent assignments, board state |
| **Behavioral** | 3,072 tokens | Assigned behaviors, relevant BCI results, agent persona instructions |

### Native multi-turn transcript (LLM)

When PostgreSQL-backed `ConversationService` is wired into `ConversationReplyService`, replies use a **Codex/Claude-style** message list:

- `ContextComposer.compose(..., include_conversation_history=False)` so the composed system string carries **workspace, behaviors, profile, runs, etc.** without duplicating the chat transcript.
- `chat_transcript.build_transcript_openai_messages` loads messages with `list_messages(..., include_thread_replies=True)`, maps `ActorType.USER` → `user` and `ActorType.AGENT` → `assistant`, trims to a token budget, and optionally prepends `conversation.metadata["thread_summary"]` for operator-maintained or future automated summaries of older turns.
- Telemetry events: `chat.context.transcript_turns`, `chat.context.duplicate_history_avoided`.

**Repeatability (identical agent text):** Chat streaming uses `LLMClient.astream` with temperature from `AMPREALIZE_LLM_TEMPERATURE` (see `LLMConfig.from_env()`). At temperature **0**, identical composed prompts tend to yield identical completions. **`AMPREALIZE_CHAT_LLM_TEMPERATURE`** (optional) overrides temperature **only** for conversation reply streaming, so you can add mild variation in chat without changing other LLM call sites. Long threads are **not** identical context: `chat.context.transcript_turns` grows with history—compare runs using `user_message_id`, not only the visible user text.

Relevant environment variables:

| Variable | Purpose |
|----------|---------|
| `AMPREALIZE_CONTEXT_COMPOSER_TOTAL_TOKENS` | Composer budget (default `12288`) |
| `AMPREALIZE_CONTEXT_COMPOSER_RESERVED_TOKENS` | Reserved headroom (default `1000`) |
| `AMPREALIZE_CHAT_TRANSCRIPT_MAX_TOKENS` | Max tokens for the message-list transcript (default `8192`, capped by model `context_limit`) |
| `AMPREALIZE_CHAT_TRANSCRIPT_FETCH_CAP` | Max messages fetched while paginating (default `5000`) |
| `AMPREALIZE_CHAT_LLM_TEMPERATURE` | Optional: overrides chat streaming temperature only; unset uses `AMPREALIZE_LLM_TEMPERATURE`. |

### Data Sources

1. **Conversation history**: Last N messages from current conversation (tier 1) — **omitted from the composer blob when native transcript mode is active**; otherwise included as today.
2. **Active work items**: Items assigned to the responding agent + items mentioned in recent messages (tier 2)
3. **Recent runs**: Last 3 runs by the agent in this project, with status/outputs (tier 2)
4. **Agent assignments**: Agent's role (PRIMARY/SECONDARY/TERTIARY) and project config overrides (tier 2)
5. **Board state summary**: Condensed board status — column counts, blockers, overdue items (tier 2)
6. **Behavior instructions**: Agent's assigned behaviors via BCI retrieval (tier 3)
7. **Accessible workspace inventory**: Fast global/project grounding for projects, assigned agents, boards, recent work items, recent runs, relevant behaviors, and wiki hits (tier 2)

Global chat now uses `WorkspaceInventoryProvider` through `build_chat_context_composer()` instead of the default empty composer. The provider calls in-process project/org, board, run, behavior, and wiki services, caches deterministic inventory briefly, and fetches independent groups concurrently. This keeps questions such as "what projects do I have?" grounded in the user's accessible Amprealize data before model generation starts.

### Workspace prioritization ("what should I work on today?")

- **Intent**: `chat_action_router.detect_chat_workspace_intent` maps prioritization phrasing to `chat_query_intent=workspace_prioritize`.
- **Phase B (flag)**: When `feature.chat_workspace_targeted_fetch` is on (`AMPREALIZE_ENABLE_CHAT_WORKSPACE_TARGETED_FETCH=true`), global home chat (no `project_id`) runs a **planner → bounded `BoardService.list_work_items` → synthesis** path in `conversation_reply_service` / `chat_workspace_targeted_fetch.py`. Project IDs in the plan must match the workspace inventory allow-list. While the planner runs, the API emits **`reply.step`** SSE events (`planning`, `planning_ready`, `fetching`, `fetch_ready`, or `planning_fallback`) so the web UI can show progress instead of a silent multi-minute wait.
- **Fallback (flag off)**: `ConversationReplyService` adds composer **`extra_context.workspace_prioritization`** guidance and slightly raises the **workspace inventory token ceiling** so single-shot replies keep more inventory text. Large inventories still use a **round-robin compact digest** across projects (not only the first project’s items).

| Variable | Purpose |
|----------|---------|
| `AMPREALIZE_ENABLE_CHAT_WORKSPACE_TARGETED_FETCH` | Enable Phase B targeted fetch (default off). |
| `AMPREALIZE_TARGETED_FETCH_PLANNER_TIMEOUT_SEC` | HTTP timeout for the **first** planner-only LLM call (default `75`). Keep **below** `AMPREALIZE_LLM_TIMEOUT` so the main answer model does not wait for a full provider timeout after planner failure. |
| `AMPREALIZE_TARGETED_FETCH_PLANNER_RETRY_COUNT` | Extra planner attempts after **`planner_timeout`** only (default `1`). Set `0` to disable retries. |
| `AMPREALIZE_TARGETED_FETCH_PLANNER_RETRY_TIMEOUT_SEC` | Optional override for **second and later** planner attempts; if unset, uses `max(first_timeout, min(first×1.25, 110))`. |
| `AMPREALIZE_TARGETED_FETCH_PLANNER_MODEL_ID` | Optional model id **only** for the planner JSON call; when unset, uses chat `metadata.llm_model_id`. Prefer a small/fast model to cut Phase B latency. |
| `AMPREALIZE_WORKSPACE_ACTIVITY_RECENCY_DAYS` | Window in days for **active** vs **quiet** from inventory work-item snapshots (default `14`). Sets `fairness_mode` and synthesis disclosure instructions. |
| `AMPREALIZE_TARGETED_FETCH_MAX_QUERIES` | Max planned `list_work_items` queries (default `6`). |
| `AMPREALIZE_TARGETED_FETCH_MAX_LIMIT` | Max `limit` per planned query (default `50`). |
| `AMPREALIZE_TARGETED_FETCH_MAX_TOTAL_ROWS` | Cap on merged rows from execution (default `200`). |
| `AMPREALIZE_TARGETED_FETCH_PLANNER_MAX_TOKENS` | Max completion tokens for planner JSON (default `1200`). |
| `AMPREALIZE_WORKSPACE_INVENTORY_MAX_CONTENT_TOKENS` | Token threshold before swapping inventory body for compact digest (default `2048`). |
| `AMPREALIZE_WORKSPACE_INVENTORY_COMPACT_MAX_ITEMS` | Max work items listed in compact digest text (default `24`). |

### Relevance Scoring

Each context chunk is scored:

```
score = (recency × 0.5) + (query_relevance × 0.3) + (ownership × 0.2)
```

- **recency**: Exponential decay from creation time. Messages < 1hr = 1.0, < 24hr = 0.7, < 7d = 0.3, older = 0.1
- **query_relevance**: Cosine similarity between the user's message embedding and the context chunk
- **ownership**: 1.0 if the context is about the responding agent, 0.5 if about the project, 0.0 otherwise

### Token Counting

Uses `tiktoken` (already a dependency in BCI service) with the `cl100k_base` encoding.

### Assembly Flow

```
User message arrives
  → ConversationService saves to DB
  → ConversationReplyService emits reply.started with stable stream_message_id
  → ConversationReplyService calls ContextComposer.compose(..., include_conversation_history=…)
      (False when ConversationService supplies a native multi-turn transcript; True otherwise)
  → ContextComposer queries configured sources in parallel (asyncio.gather)
  → Scores and ranks chunks (conversation history fragments are packed in chronological order)
  → Greedy-packs into budget
  → ConversationReplyService builds OpenAI-style messages: system (composed groundings) + user/assistant transcript turns
  → Direct workspace lookup answers simple inventory questions without LLM latency when possible
  → ConversationReplyService emits reply.step for context and generation phases
  → Agent execution produces streaming response
  → ConversationEventHub broadcasts reply/token events locally and through Redis when configured
  → SSE/WebSocket clients receive reply.token and legacy token once, with short replay for late stream subscribers
  → Persisted answer emits reply.complete and legacy complete
```

---

## Event Protocol

Dual-transport: **WebSocket** for bidirectional room events, **SSE** for agent token streaming.

### WebSocket Events

Connection: `ws://host/api/v1/conversations/{conversation_id}/ws`

**Client → Server**:

| Event | Payload |
|-------|---------|
| `message.send` | `{ content, message_type, parent_id?, structured_payload? }` |
| `message.edit` | `{ message_id, content }` |
| `message.delete` | `{ message_id }` |
| `reaction.add` | `{ message_id, emoji }` |
| `reaction.remove` | `{ message_id, emoji }` |
| `typing.start` | `{ }` |
| `typing.stop` | `{ }` |
| `read.update` | `{ last_read_message_id }` |

**Server → Client**:

| Event | Payload |
|-------|---------|
| `message.new` | Full message object |
| `message.updated` | `{ message_id, content, edited_at }` |
| `message.deleted` | `{ message_id, deleted_at }` |
| `reaction.added` | `{ message_id, actor_id, actor_type, emoji }` |
| `reaction.removed` | `{ message_id, actor_id, emoji }` |
| `typing.indicator` | `{ actor_id, actor_type, is_typing }` |
| `read.receipt` | `{ actor_id, last_read_at }` |
| `participant.joined` | `{ actor_id, actor_type }` |
| `participant.left` | `{ actor_id }` |
| `presence.update` | `{ actor_id, presence_status }` |
| `pin.updated` | `{ message_id }` |
| `system.announcement` | `{ content, announcement_type }` |
| `reply.started` | `{ stream_message_id, user_message_id, conversation_id, phase, label }` |
| `reply.step` | `{ stream_message_id, user_message_id, conversation_id, phase, label, source_counts?, trace_steps?, source_rows?, badge? }` |
| `reply.token` | `{ stream_message_id, conversation_id, phase, label, token }` |
| `reply.complete` | `{ stream_message_id, user_message_id, conversation_id, phase, label, content, source_counts?, trace_steps?, source_rows?, badge? }` |
| `reply.error` | `{ stream_message_id, user_message_id, conversation_id, phase, label, error }` |

### SSE Stream (Agent Token Streaming)

Endpoint: `GET /v1/conversations/{conversation_id}/stream/{message_id}`

| Event | Payload |
|-------|---------|
| `token` | `{ text, index }` |
| `structured_start` | `{ message_type, partial_payload }` |
| `structured_update` | `{ field, value }` |
| `complete` | `{ final_content, structured_payload?, usage }` |
| `error` | `{ code, message }` |
| `heartbeat` | `{ ts }` |

**Design**: Each scheduled assistant reply uses one stable `stream_message_id`, supplied by the client when possible and generated server-side otherwise. The user message also carries that ID as scheduling metadata, but the web console only treats a matching assistant/agent message as the persisted streamed reply. The SSE stream exposes rich `reply.*` lifecycle events for progress UI while preserving legacy `token`, `complete`, and `error` event names. The web console shows an immediate progress row, updates labels such as "Gathering workspace context" and "Generating answer", typewriter-reveals streamed text when motion is allowed, and shows a collapsible trace with phases, source counts, cited rows, and deterministic answer badges.

### Realtime Hot Path

`ConversationEventHub` is the app-facing facade for both local and distributed realtime delivery. Its public API remains stable (`publish`, `publish_token`, `subscribe_queue`, `connect`, `disconnect`, `set_typing`), but it can now attach a pluggable realtime backend:

- `memory`: process-local WebSocket/SSE fanout for lightweight OSS and tests.
- `redis`: Redis Pub/Sub for current fanout plus Redis Streams for short best-effort replay.
- `auto`: use Redis when `AMPREALIZE_REDIS_URL` or `REDIS_URL` is present; otherwise use memory.

Redis stores only ephemeral event envelopes and replay windows. Durable messages, search, permissions, resource links, context reads, and audit-worthy history continue to live in the configured Postgres database, whether that is local Postgres, Neon, or an enterprise Postgres deployment. Redis replay is therefore a UX recovery path for in-flight replies, not a source of truth.

**Replay surfaces:** On `connect`, each WebSocket receives the same **conversation-scoped** short replay as `subscribe_queue` without a `message_id` (envelope shape matches live events). Per-`message_id` SSE streams still call `subscribe_queue(..., message_id=…)` for replay of that agent reply only; WebSocket clients do not open a per-message hub subscription, so token/reply replay for a specific stream remains SSE-first. For gaps longer than the Redis window, clients should reconcile from Postgres (REST/MCP) as today.

Straightforward workspace inventory questions can bypass the LLM after context composition. For example, questions such as "what agents are assigned to the GuideAI project?", "what projects do I have?", "what active runs do I have?", or "what work items are blocked?" are answered directly from accessible inventory, then persisted and streamed through the same reply lifecycle. These replies carry structured artifact payloads (`project_list`, `assignment`, `agent_list`, `run_list`, `work_item_list`) and cited source rows for transcript inspection. This keeps deterministic facts fast while leaving synthesis, explanation, and ambiguous requests on the model path.

### Curated Context Layer

Global chat context now treats context as an explicit product layer. `WorkspaceInventoryProvider` can include always-on workspace rules (`AMPREALIZE_CHAT_WORKSPACE_RULES`), endorsed project IDs (`AMPREALIZE_CHAT_ENDORSED_PROJECT_IDS`), retrieved guide/wiki hits, behavior guidance, and accessible inventory. Fragment metadata includes `context_sources` plus a `source_priority_policy` so admin surfaces can explain what context was included and why.

### Chat Observability

`ConversationReplyService` emits telemetry for `chat.fast_path.hit`, `chat.fast_path.miss`, `chat.context.source_count`, and `chat.phase.latency_ms`. These events are intended to power a Context Studio-style view of slow phases, missing deterministic handlers, and source coverage gaps.

Configuration:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AMPREALIZE_CHAT_REALTIME_BACKEND` | `auto` | `memory`, `redis`, or `auto`. |
| `AMPREALIZE_REDIS_URL` / `REDIS_URL` | unset | Redis connection URL used by the realtime backend. |
| `AMPREALIZE_CHAT_REPLAY_TTL_SECONDS` | `900` | TTL for ephemeral Redis stream replay keys. |
| `AMPREALIZE_CHAT_STREAM_MAXLEN` | `1000` | Approximate max events per replay stream. |
| `AMPREALIZE_CHAT_REALTIME_MAX_REMOTE_CONVERSATIONS` | unset (no cap) | Optional upper bound on concurrent Redis Pub/Sub listeners (one per subscribed conversation). When at capacity, new conversations still get local WS/SSE delivery but cross-worker fan-in is skipped until a listener slot frees. Use `0` or omit for unlimited. |

Every realtime payload carries `_event_id`, `_origin_id`, and for reply streams `_stream_message_id`. The backend uses those IDs to avoid local/Redis loopback duplication, while the web console also ignores duplicate replay/live SSE payloads. When the last local subscriber for a conversation disconnects, the hub closes that conversation’s Redis Pub/Sub listener so workers do not accumulate idle subscriptions.

### Debugging global prioritization chat

Use this when global home chat (“what should I work on?”, cross-project prioritization) feels **single-project** or **non-repeatable**, or when comparing telemetry to user-visible answers.

**Decision tree (read telemetry in order):**

1. **`chat.planning.failed`** (e.g. `reason: invalid_or_empty_plan`) means **Phase B did not run**. Replies use workspace digest + LLM without authoritative fetch—not the same failure mode as “planner assigned every query to one `project_id`.”
2. **`chat.planning.completed`** and **`chat.targeted_fetch.completed`** mean Phase B ran; check `queries_planned`, `queries_run`, `rows_fetched`, and (once emitted) `project_ids_in_plan` / `rows_per_project` for skew across projects.
3. **`conversation_reply.generated`**: check **`answer_path`** (`targeted_fetch`, `llm`, `deterministic`, …) and **`used_targeted_fetch`**. Deterministic shortcuts (counts/lists) differ from synthesis paths.
4. **`chat.context.source_count`** / **`conversation_reply.generated`** payloads include **`source_counts`** (e.g. `workspace.projects`, `workspace.boards`). If **`workspace.projects` > 1** but the narrative still emphasizes one project, combine with step 1–3—inventory breadth does not imply Phase B succeeded.

**Repeat “identical” answers:** Same **`AMPREALIZE_LLM_TEMPERATURE`** (especially `0`) + same composed prompt ⇒ same completion. **`chat.context.transcript_turns`** grows with thread length—repeating the same user sentence later is **not** identical context; correlate by **`user_message_id`** when comparing runs.

**Where to query telemetry (Postgres `telemetry_events`):**

- Column is **`event_type`** (not `event_name`). Filter **`session_id`** = **`conversation_id`** for a thread.
- Example: `SELECT event_timestamp, event_type, payload FROM telemetry_events WHERE session_id = '<conversation_id>' ORDER BY event_timestamp;`

**Local dev (BreakerAmp / Podman):** After `breakeramp apply` (or equivalent runtime readiness), BreakerAmp sets the host default connection from `config/breakeramp/environments.yaml` (development, **cloud-dev**, **neon**, and **test** all use the **`amprealize-dev`** machine). If you manage machines only by hand, use the intended connection explicitly (e.g. `podman --connection amprealize-dev`) or run `podman system connection default <name>`. Telemetry Postgres is often reachable at **`127.0.0.1:5433`** with database **`telemetry`** per local blueprint; credentials match env/secrets for that environment.

**API logs:** Logger namespace `amprealize.services.conversation_reply_service` — `conversation_reply.generate_reply.start` / `done` / `failed` with `conversation_id` / `user_message_id`.

**Note:** Table **`observability_generations`** may be empty in some deployments even when **`telemetry_events`** is populated; prefer **`telemetry_events`** and env (`AMPREALIZE_LLM_TEMPERATURE`, planner timeouts/caps in the **Workspace prioritization** subsection above) for investigations.

---

## Rate Limiting

Adaptive multi-lane token bucket with amplification circuit breaker.

### Priority Lanes

| Lane | Actor Type | Limit | Behavior |
|------|-----------|-------|----------|
| **HUMAN** | Users | Unlimited | No rate limit on human messages |
| **AGENT** | AI agents | 10 messages/minute per agent per conversation | Adaptive — limit decreases if amplification detected |
| **SYSTEM** | System messages | Unlimited | Only templated, event-driven messages |

### Amplification Circuit Breaker

Prevents agent-to-agent feedback loops in project rooms:

```
Monitor: sliding 60-second window per conversation
Threshold: 5 consecutive agent-only messages (no human in between)
Action: OPEN circuit breaker
  → Agents can only respond to human messages
  → System posts: "Agents paused — conversation needs human input"
Recovery: Next human message resets the breaker to CLOSED
```

### Backpressure Signaling

When an agent approaches its rate limit (>80% consumed):
- WebSocket sends `rate_limit.warning` event to the agent's handler
- Agent handler can defer non-urgent responses
- If limit exceeded, message is queued and delivered when budget replenishes

---

## Full-Text Search

### Implementation

- Uses Postgres `tsvector` with `GENERATED ALWAYS AS` stored column (see schema above)
- GIN index on `search_vector` for fast lookup
- English language configuration by default

### Search API

```
GET /v1/conversations/{conversation_id}/messages/search?q=deployment+error&limit=20&offset=0
```

Response includes `ts_rank` score and `ts_headline` with highlighted snippets.

### Cross-Conversation Search (v2)

Future: project-wide search across all conversations. Requires additional index:

```sql
CREATE INDEX idx_messages_project_search
    ON messaging.messages USING GIN (search_vector)
    WHERE is_deleted = FALSE;
```

Query would join through `conversations.project_id`.

---

## Retention Policy

Tiered retention with configurable per-project overrides:

| Phase | Duration | Storage | Access |
|-------|----------|---------|--------|
| **Active** | 0–90 days | Postgres (hot) | Full API access, real-time |
| **Archive** | 91–365 days | Postgres (warm) | Read-only API, no WebSocket |
| **Cold** | 365+ days | S3/GCS export (enterprise only) | Export download only |

### Implementation

- **Active → Archive**: Nightly cron job moves messages older than 90 days:
  - Sets `conversations.is_archived = TRUE` when all messages are archived
  - Archived messages remain in Postgres but are excluded from default queries
  - Add `archived_at TIMESTAMPTZ` column to messages table
- **Archive → Cold** (Enterprise): Weekly job exports archived conversations older than 365 days to object storage as JSONL, then deletes from Postgres
- **Per-project override**: `project.settings.retention_days` (default 365, min 30, max unlimited)
- **Compliance hold**: `conversations.metadata.compliance_hold = true` prevents archival/deletion regardless of policy

---

## Agent-Initiated Messages

Agents can proactively post to **project rooms only** (not DMs) using system-style messages.

### Triggers

| Event | Message Type | Template |
|-------|-------------|----------|
| Run completed | `status_card` | "Completed {work_item.title}: {run.summary}" |
| Run failed | `blocker_card` | "Blocked on {work_item.title}: {error.summary}" |
| Review requested | `status_card` | "Ready for review: {work_item.title}" |
| Capacity reached | `status_card` | "At capacity ({active_count}/{max} items)" |
| Work item assigned | `status_card` | "Picked up {work_item.title}" |
| Handoff | `status_card` | "Handing off {work_item.title} to {target_agent.name}" |

### Constraints

- Posted as `sender_type = 'system'` with `sender_id` = the agent's ID (preserves who triggered it)
- Agent-initiated messages are rate-limited by the SYSTEM lane (unlimited but templated-only)
- Cannot be free-form text — must use one of the defined templates
- Each template has a cooldown (e.g., no more than 1 capacity status per 10 minutes)

---

## Web Console UX

### Magical Amprealize Chat North Star

Amprealize Chat should feel like a premium workspace foundation with magical mission-control moments: Linear-grade precision, Raycast command speed, Figma-like collaboration liveliness, and a restrained frosted-glass visual language. The experience must avoid generic enterprise chat, heavy spectacle, purple, gradients, and shadows. Depth comes from translucent layers, blur, crisp outlines, edge highlights, motion, live objects, and excellent spacing.

The hero surface is **global user chat**. It gives the user a personal cross-project command center that can synthesize across accessible orgs, projects, work items, runs, files, agents, and tools without granting new permissions. Project spaces reuse the same interaction language for project room, DMs, group chats, work item threads, and run threads.

### Surface Model

The current fixed right-rail plan is superseded by a two-state bottom-first glass chat surface:

| State | Behavior | Primary use |
| --- | --- | --- |
| **Resting dock** | A slim frosted bottom dock with an "Amprealize Chat" affordance and active global/project context label. | Always-available global or project chat entry without blocking the app. |
| **Full draggable window** | The dock expands directly into a larger Slack-like chat window with vertical spaces/DMs, message timeline, inline live cards, adaptive agent presence, and the magic composer. | Planning, running work, reviewing status, and chatting with humans or agents. |

There is no intermediate peek sheet. Dragging starts only in the full window so the dock remains stable. Keyboard users must have equivalent controls for moving, expanding, collapsing, and closing the surface.

#### Layout

```
WorkspaceShell
├── Sidebar / app navigation
├── Primary route content
│   ├── Boards / Runs / Agents / Files / Plans
│   └── Route-specific cards and panels
└── AmprealizeChatSurface
    ├── BottomDock
    └── UnifiedConversationWindow
        ├── ConversationSidebar
        ├── MessageList
        ├── LiveObjectCards
        ├── AdaptiveAgentPresence
        └── MagicComposer
```

Likely implementation touchpoints are `WorkspaceShell`, `AmprealizeChatDock`, `UnifiedConversationWindow`, `ConversationPanel.css`, `UnifiedConversationWindow.css`, `MessageBubble`, `MessageComposer`, `StreamingMessage`, and `design-system.css`.

`guideai-1060` implements the first context-aware shell contract in `web-console/src/components/conversations/UnifiedConversationWindow.tsx`. The window now accepts `contextKind="global" | "project"` and an optional `contextLabel`, renders a scope badge and hint in the header, updates its accessible dialog label, and adjusts empty-state copy for global versus project chat. The CSS keeps the disciplined glass style with translucent panes, blur, crisp borders, teal-compatible accents, and no shadows or gradients.

`GUIDEAI-1037` now mounts `AmprealizeChatDock` from `WorkspaceShell` so chat is visible on the dashboard and all protected pages. The dock defaults to global chat outside projects and automatically switches to the active project's project-room chat on project/board routes. Board pages no longer mount the legacy horizontal avatar `ChatHub` dock.

### Inline artifact chips (first-party resources)

Inventory answers, `platform_action_result` payloads (e.g. chat-created work items), and other first-party resource references in `MessageBubble` render as **plain markdown** with **compact chips on the same typographic line** when the body is a single short paragraph (`ConversationPanel.css` / `.msg-artifact-inline`, `.msg-markdown--artifact-inline`). For any **single** inline chip, the UI strips redundant tails: typed phrases like `work item:`, `project:`, `board:`, `agent:`, `run:`, `behavior:`, `wiki page:`, `organization:` / `org:`, then a trailing `: {label}` and a duplicate trailing `{label}` when a phrase or colon strip already fired—so the resource name stays on the chip, not repeated in prose. `platform_action_result.data` is interpreted for chips across work items, boards, projects, orgs (Organizations list), agents, runs, behaviors (`/bci?behavior=`), and wiki pages (`/wiki/{domain}/…` when paths are present). Each chip is a router `Link` when a safe deep link exists (project, board, work item drawer via `/projects/:id/boards/:id/items/:id`, agent, behavior via `/bci?behavior=…`, etc.); otherwise the chip is non-interactive with a tooltip explaining why navigation is unavailable. **Plan** and **recovery** structured cards remain full-width artifact cards; status/blocker/progress cards are unchanged.

### Visual Design

- **Frosted glass, not heavy glass:** use layered translucent panes, `backdrop-filter`, saturation, crisp borders, and subtle highlight overlays.
- **No purple, gradients, or shadows:** comply with `COLLAB_SAAS_REQUIREMENTS.md`; ambient depth uses blur fields and surface stacking, not drop shadows.
- **Premium but fun:** polished typography, generous spacing, fluid curves, friendly empty states, and small celebratory moments only when work completes.
- **Motion as physics:** transform/opacity/filter only, 150-300ms default, spring-like easing, interruptible, and disabled or simplified under `prefers-reduced-motion`.
- **Accessible contrast:** glass effects must preserve text contrast, visible focus rings, screen-reader labels, and keyboard operation.

### Entry Points

1. **Global bottom dock** — persistent hero entry for user-home chat across accessible resources.
2. **Project chat dock state** — same surface contextualized to the active project space.
3. **Agent avatar click** — opens an agent/user conversation with capability and availability context.
4. **Work item / run card action** — opens the related inline thread or seeds the composer with resource context.
5. **Keyboard shortcut** — opens global chat and focuses the composer immediately.
6. **Header or command entry** — secondary visible entry for users who prefer top-level navigation.

### Component Tree

```
AmprealizeChatSurface/
├── ChatDock                    -- bottom frosted entry and collapsed status
├── UnifiedConversationWindow   -- expanded / draggable glass shell
│   ├── ConversationSidebar     -- global/project spaces, rooms, DMs, threads
│   ├── ConversationHeader      -- title, scope, participants, connection state
│   ├── AdaptiveAgentPresence   -- subtle/active agent theater
│   ├── MessageList             -- virtualized timeline with grouped messages
│   │   ├── MessageBubble       -- text, markdown, reactions, actions
│   │   ├── WorkItemCard        -- live status, assignee/agent, quick actions
│   │   ├── RunCard             -- live phase, queue state, progress, cancel/open
│   │   ├── StatusCard / BlockerCard / ProgressCard / CodeBlock / RunSummary
│   │   └── StreamingMessage    -- typewriter/materializing agent responses
│   ├── TieredErrorRecovery     -- cards, explanations, and quiet toasts
│   └── MagicComposer
│       ├── NaturalLanguageInput
│       ├── MentionPicker       -- @users and @agents with capability hints
│       ├── ResourcePicker      -- #work items, runs, files, plans
│       ├── AttachmentBrain     -- files, images, links, contextual use
│       ├── QuickChips          -- "Plan this", "Run it", "Summarize", etc.
│       └── SendButton
└── ChatEmptyStates             -- suggested prompts and setup guidance
```

### Magic Composer

The composer is the command surface, not just a textarea:

- **Natural language first:** users type what they want; the UI suggests typed actions only when helpful.
- **`@` mentions:** users and agents appear with availability, role, and capability hints.
- **`#` references:** work items, runs, plans, files, and project resources can be linked into context.
- **Attachment brain:** dropped files, images, and links become scoped resources with clear permission state and suggested use.
- **Quick chips:** contextual suggestions such as "Plan this", "Run it", "Ask reviewer", "Summarize changes", or "Open related run".
- **Power-user slash commands:** optional later, but not the primary personality.

### Adaptive Agent Presence Theater

Agent presence is quiet by default and more expressive during active work:

- Idle agents show small frosted avatars, calm status dots, and short capability hints.
- Thinking agents use subtle breathing or typing motion with readable status text.
- Tool use appears as compact chips such as "reading board", "checking files", or "drafting plan".
- Handoffs appear as lightweight ribbons, for example "Planner handed off to Builder".
- Completion states resolve crisply with a small settle or shimmer motion, not broad confetti.

Presence events must be available to other platform surfaces through shared collaboration/event primitives so boards, runs, agent pages, and future VS Code panels can render consistent activity.

#### Streaming Effect (Agent Replies)

When an agent is composing a reply:
1. **Thinking indicator**: A subtle pulsing dot animation appears below the last message. Three dots that gently pulse in sequence with Amprealize's blue accent (`#2276d2`). The dots have a softer, more organic animation than iMessage — using `ease-in-out` with slight scale variation rather than bouncing.

```css
.thinking-indicator {
    display: flex;
    gap: 4px;
    padding: 8px 12px;
}

.thinking-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-accent, #2276d2);
    opacity: 0.4;
    animation: think-pulse 1.4s ease-in-out infinite;
}

.thinking-dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes think-pulse {
    0%, 100% { opacity: 0.3; transform: scale(0.85); }
    50% { opacity: 0.85; transform: scale(1.1); }
}
```

2. **Token streaming**: As tokens arrive via SSE, a `StreamingMessage` component renders them with a subtle materializing effect. The glass tint of the message bubble slowly intensifies as content fills in (starts at `rgba(244, 250, 253, 0.3)` and eases to `rgba(244, 250, 253, 0.72)` on completion).

3. **Completion snap**: When the `complete` SSE event fires, the streaming content is replaced with the final rendered message (with structured cards, code highlighting, etc.) in a smooth crossfade (200ms).

#### Live Object Cards

Rich message types render as inline live cards, not static embeds. Cards should feel like living glass artifacts with compact headers, resource identity, live state, primary action, secondary details, and an expand affordance.

**First-version hero cards:**

- **Work Item Card**: status, title, priority, assignee/agent, related branch/run, progress, and quick actions.
- **Run Card**: queue state, current phase, live progress, recent agent activity, cancel/open actions, and completion result.

**Supporting cards:**

- **Status Card**: compact state update with icon/title/summary; navigates to run/work item.
- **Blocker Card**: recoverable blocker with cause, impact, and "Help resolve" CTA.
- **Progress Card**: horizontal progress, step count, ETA, and phase label.
- **Code Block**: syntax-highlighted with copy button, language label, and line anchors where possible.
- **Run Summary**: condensed run output with status badge, duration, key metrics, and "View full run".

### Speed Rituals

Speed is part of the visual language:

- Chat opens instantly from the bottom dock; network loading never blocks the surface opening.
- Messages use optimistic local echo and reconcile with server state.
- Timelines remain virtualized for long histories.
- Skeleton cards are preferred over blocking spinners.
- Connection loss is visible but calm; reconnect attempts do not freeze the UI.
- Every tap/click gets visual feedback within 100ms.
- The composer remains interactive while non-critical data loads.

### Empty States And Error Handling

Empty and error states should be helpful, polished, and recoverable:

- **Global chat empty state:** explains that Amprealize can help plan, run, summarize, and find work across accessible resources.
- **Project chat empty state:** suggests starting with project room, asking an agent, or linking a work item/run.
- **Tiered errors:** resource/action failures use inline recovery cards; normal chat failures use conversational explanations; minor UI issues use quiet toasts.
- **Permission failures:** explain the missing access and offer request/access-review actions where policy allows.
- **Agent/tool failures:** show what failed, what was attempted, and the safest next action.

#### Mobile Responsive

On viewports < 768px, the chat surface stays bottom-first: resting dock and full-height chat sheet only. The draggable desktop behavior becomes a mobile-native sheet with safe-area padding, large touch targets, and no horizontal scrolling.

---

## Slack Bridge

### v1: Single App + Display Overrides

A single Slack app (`Amprealize`) bridges messages between Slack channels and Amprealize conversations.

**Setup**:
1. Admin installs Amprealize Slack app to workspace
2. Admin binds a Slack channel to a Amprealize project room via `/amprealize connect #channel`
3. Creates `external_bindings` record

**Message Flow**:
- **Amprealize → Slack**: Agent messages posted to Slack using `chat.postMessage` with `username` and `icon_url` display overrides to show the agent's name and avatar
- **Slack → Amprealize**: Slack Events API webhook receives messages, ConversationService creates corresponding message with `metadata.slack_ts` for threading correlation
- **Threading**: Slack thread replies map to `parent_id` in Amprealize; top-level Slack messages map to top-level Amprealize messages

**Limitations**:
- Display overrides only work in channels where the app is installed
- All agent messages show as "BOT" in Slack (single app identity)
- No Slack DMs — only channel bridges

### v2: Multi-App Personas (Enterprise)

Each agent persona gets its own Slack bot user for true identity separation.

**Changes**:
- Create Slack apps per agent persona (Engineering Agent, Product Agent, etc.)
- Each has its own `bot_user_id` and avatar
- `external_bindings.config` stores per-persona bot tokens
- Messages appear as unique bot users in Slack

**Timeline**: v2 is enterprise-only and deferred to after v1 stabilization.

### Slack Bridge Phases

| Phase | Scope | Timing |
|-------|-------|--------|
| Phase 1 | Single app, outbound only (Amprealize → Slack) | After web chat stable |
| Phase 2 | Bidirectional (Slack → Amprealize via Events API) | +2 weeks |
| Phase 3 | Thread correlation, reaction sync | +2 weeks |
| Phase 4 | Multi-app personas (enterprise) | v2 |

---

## VS Code Extension (v2)

The VS Code extension will connect to project conversations in v2.

**Approach**:
- Use the existing `@amprealize/collab-client` package (already supports the extension)
- New `ConversationPanel` in `extension/src/panels/` — webview showing conversation UI
- Connects via the same WebSocket endpoint as the web console
- Shows the same conversation data, same real-time events
- Entry point: sidebar tree view item + `amprealize.openConversation` command

**Deferred to v2** because the web console is the primary surface and the collab-client transport layer is already proven.

---

## OSS / Enterprise Boundary

Following the patterns in `AGENT_OSS_ENTERPRISE_GUIDE.md`:

### OSS (Core)

| Component | Description |
|-----------|-------------|
| `messaging` schema + migrations | All 5 tables |
| `ConversationService` | Full CRUD, access control, pagination |
| `ContextComposer` | All 6 data sources, token budget, ranking |
| Rate limiter | Adaptive token bucket + amplification breaker |
| WebSocket + SSE endpoints | Real-time events + token streaming |
| Web console conversation panel | All UI components |
| Full-text search | tsvector + GIN index |
| MCP tools | `conversations.*`, `messages.*` |

### Enterprise

| Component | Gating Pattern | Description |
|-----------|---------------|-------------|
| Slack bridge | Boolean flag (`HAS_ENTERPRISE`) | Single-app + multi-app personas |
| Teams bridge | Boolean flag | Future: Microsoft Teams integration |
| Retention worker | Import guard (`raise ImportError`) | Archive + cold storage jobs |
| Cold storage export | Import guard | S3/GCS JSONL export |
| Conversation analytics | Boolean flag | Message volume, response time, sentiment dashboards |
| Cross-project search | Boolean flag | Search across all project conversations |

### Governed Observability Answers

`GUIDEAI-1114` extends the deterministic reply fast path with chat-powered observability answers. When users ask questions like "which tools fail most?", "why are replies slow?", or "which traces produced behavior candidates?", `ConversationReplyService` calls `ObservabilityChatAnswerService` before LLM generation. The service uses `GovernedObservabilityQueryService`, so chat answers inherit the same viewer/data-analyst/admin/compliance redaction policy as REST observability APIs and store structured cards as `observability_analysis` payloads.

**Stub pattern**: Enterprise components use the `raise ImportError` stub in OSS. The `AmprealizeContainer.__init__()` method conditionally wires enterprise implementations when `HAS_ENTERPRISE` is true.

---

## Open Questions (Resolved)

| Question | Decision |
|----------|----------|
| **Notification sounds** | Only for @mentions and blocker cards. System status updates are silent. Configurable per user via `participants.notification_preference`. |
| **Agent "thinking" indicator** | Subtle pulsing dot animation (3 dots, blue accent, organic ease-in-out). Distinct from iMessage — uses Amprealize's design language with scale variation and translucency. |
| **Message pinning** | Pin per conversation in v1 via `conversations.pinned_message_id`. Multi-pin via junction table in v2. |
| **VS Code extension** | v2 — connect via `@amprealize/collab-client` WebSocket. Same conversation data, same events. |

---

## Phase Sequence

| Phase | Name | Scope | Dependencies |
|-------|------|-------|-------------|
| **1** | Schema + Service | `messaging` schema, migrations, ConversationService CRUD, access control | None |
| **2** | Real-Time | WebSocket endpoint, SSE streaming, ExecutionEventHub integration | Phase 1 |
| **3** | ContextComposer | 6 data sources, token budget, relevance scoring, agent reply pipeline | Phase 1, 2 |
| **4** | Web Console | Conversation panel, message list, composer, streaming, structured cards | Phase 2, 3 |
| **5** | Rate Limiting + Search | Adaptive limiter, amplification breaker, full-text search | Phase 1 |
| **6** | MCP Tools + CLI | Conversation/message MCP tools, CLI commands | Phase 1 |
| **7** | Slack Bridge v1 | Single app, outbound → bidirectional → thread sync | Phase 1, 2 |
| **8** | Retention + Analytics | Archive worker, cold storage export, analytics (enterprise) | Phase 1 |
| **9** | VS Code Extension | Extension conversation panel via collab-client | Phase 2 |
