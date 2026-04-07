# AMPREALIZE-361: Agent Conversation System — Implementation Plan

> **Goal**: Enable users and agents to communicate in real-time within project scope, with built-in group chat, direct messages, context-aware agent replies, and Slack bridge integration.

**Status**: Approved Plan
**Date**: 2026-03-30
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

---

## Overview

The conversation system introduces real-time messaging between users and agents within the scope of a Amprealize project. Two conversation scopes:

| Scope | Description |
|-------|-------------|
| **project_room** | Group conversation per project. All project members (users + agents) participate. Agent-to-agent messages are visible. System messages announce status changes. |
| **agent_dm** | 1:1 direct message between a user and an agent. Private to the pair. Focused work discussions. |

**Key Principles**:
- Conversations are project-scoped (no cross-project messaging)
- Agents respond with full project context via ContextComposer
- Messages stream token-by-token for agent replies
- Structured message types (status cards, blocker cards, code blocks) alongside plain text
- Built-in chat is the canonical store; Slack is a bridge

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

### Data Sources (6)

1. **Conversation history**: Last N messages from current conversation (always included, tier 1)
2. **Active work items**: Items assigned to the responding agent + items mentioned in recent messages (tier 2)
3. **Recent runs**: Last 3 runs by the agent in this project, with status/outputs (tier 2)
4. **Agent assignments**: Agent's role (PRIMARY/SECONDARY/TERTIARY) and project config overrides (tier 2)
5. **Board state summary**: Condensed board status — column counts, blockers, overdue items (tier 2)
6. **Behavior instructions**: Agent's assigned behaviors via BCI retrieval (tier 3)

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
  → ConversationService calls ContextComposer.assemble(conversation_id, message)
  → ContextComposer queries 6 sources in parallel (asyncio.gather)
  → Scores and ranks all chunks
  → Greedy-packs into budget (tier 1 first, then tier 2 sorted by score, then tier 3)
  → Returns structured prompt: system_message + context_blocks + conversation_messages
  → Agent execution produces streaming response
  → Tokens broadcast via SSE to client
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

**Design**: The SSE stream fires concurrently with the WebSocket `message.new` event. The WS event carries the message shell (id, sender, type), and the SSE fills in the content token by token. When `complete` fires, the client replaces the streaming content with the final content.

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

### Panel Design

A **collapsible right panel** (360px width) that slides in from the right side of the board page.

#### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  WorkspaceShell                                                     │
│  ┌──────────┬──────────────────────────────────────────────────────┐│
│  │ Sidebar  │  Board Page Content                    │ Chat Panel  ││
│  │ (240px)  │  ┌────────────────────────────────┐    │  (360px)    ││
│  │          │  │ FilterBar                      │    │             ││
│  │          │  │ AgentPresenceRail              │    │ Sidebar     ││
│  │          │  │ ColumnSummaryStrip             │    │ MessageList ││
│  │          │  │ Board Columns                  │    │ Composer    ││
│  │          │  └────────────────────────────────┘    │             ││
│  └──────────┴──────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

#### Visual Design

- **Glass surface**: `background: rgba(244, 250, 253, 0.72)`, `backdrop-filter: blur(16px) saturate(136%)`
- **Border**: 1px left border `rgba(255, 255, 255, 0.18)` — consistent with existing glass elements
- **No shadows, no gradients, no purple** — follows COLLAB_SAAS_REQUIREMENTS
- **Spring animation**: Panel slides in/out with `cubic-bezier(0.175, 0.885, 0.32, 1.06)` (60fps mandatory)
- **Width**: 360px default, resizable to 280px–480px via drag handle
- **Z-index**: Same layer as board content (not overlay) — board columns compress to make room

#### Entry Points (5)

1. **Chat bubble FAB** — persistent floating action button in bottom-right corner of board page
2. **Agent avatar click** — clicking an agent in `BoardAgentPresenceRail` opens DM with that agent
3. **Keyboard shortcut** — `Cmd+Shift+M` toggles panel
4. **Work item context menu** — "Discuss with agent" opens DM pre-filled with work item context
5. **Header icon** — chat icon in the board page header bar

#### Component Tree

```
ConversationPanel/
├── ConversationSidebar          -- conversation list (rooms + DMs)
│   ├── ConversationSearch       -- search input
│   ├── ConversationListItem[]   -- each conversation with unread badge
│   └── NewConversationButton    -- start DM picker
├── ConversationView             -- active conversation
│   ├── ConversationHeader       -- title, participant avatars, pin indicator
│   ├── MessageList              -- virtualized scrolling (react-window)
│   │   ├── MessageGroup[]       -- grouped by sender + time proximity
│   │   │   ├── MessageBubble    -- individual message
│   │   │   │   ├── TextContent / CodeBlock / StatusCard / BlockerCard
│   │   │   │   ├── ReactionBar  -- emoji reactions
│   │   │   │   └── MessageActions -- edit, delete, reply, react (on hover)
│   │   │   └── StreamingMessage -- agent reply with materializing effect
│   │   ├── TypingIndicator      -- "{agent} is thinking..."
│   │   ├── UnreadDivider        -- "New messages" separator
│   │   └── DateSeparator        -- date headers
│   └── MessageComposer
│       ├── RichTextInput        -- contenteditable with markdown preview
│       ├── MentionPicker        -- @agent / @user autocomplete
│       ├── AttachmentBar        -- work item / run links
│       └── SendButton
└── EmptyState                   -- "Start a conversation" illustration
```

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

#### Structured Message Cards

Rich message types render as styled cards within message bubbles:

- **Status Card**: Green left border, icon + title + summary. Clickable → navigates to run/work item.
- **Blocker Card**: Red/amber left border, icon + title + error summary + "Help resolve" CTA.
- **Progress Card**: Horizontal progress bar with percentage, step count, ETA.
- **Code Block**: Syntax-highlighted with copy button, language label, line numbers.
- **Run Summary**: Condensed run output — status badge, duration, key metrics, "View full run" link.

#### Mobile Responsive

On viewports < 768px, the conversation panel becomes a **bottom sheet** that slides up from the bottom (like iOS Share Sheet), covering the full width. Drag handle at top for dismiss. Accessible via the same chat bubble FAB.

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
