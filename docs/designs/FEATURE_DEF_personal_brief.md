# Feature Definition: Personal Brief

**Date**: 2026-04-13
**Author**: Nick
**Status**: Draft — Interview Complete

---

## Summary

Daily recap, focus recommendations, blocks, and momentum delivered to you every day — as a rich DM from Amprealize so you never open the board wondering what to work on.

---

## Distribution

| Attribute | Value |
|-----------|-------|
| Edition | Enterprise Starter+ |
| Feature Flag | `feature.personal_brief` (BOOLEAN) |
| Rollout Strategy | Boolean on/off toggle per deployment |
| Starter Tier Cap | None — briefs are lightweight |
| OSS Stub Pattern | `None` assignment — feature absent in OSS, callers check for `None` |

---

## Surface Coverage

| Surface | Day One | Follow-up | Notes |
|---------|---------|-----------|-------|
| Web Console | ✅ | — | Primary surface: DM in chat panel + toast notification on board page. Summary card + "Show full brief" expand. |
| REST API | ✅ | — | Backend for all surfaces: `GET /v1/briefs`, `GET /v1/briefs/:id`, `POST /v1/briefs/:id/feedback` |
| MCP Tools | ✅ | — | `brief.get`, `brief.list`, `brief.feedback` — agents/tools can read and interact with briefs |
| CLI | ✅ | — | `amprealize brief show`, `amprealize brief list`, `amprealize brief feedback` |
| VS Code Extension | ❌ | ✅ | Follow-up: notification + brief panel in IDE sidebar |

**Cross-Surface Parity**: Surface-appropriate variations — Web is the rich DM experience, CLI gets formatted text output, MCP gets structured JSON.

---

## Architecture & Services

### Services Impacted

| Service | Impact Type | Description |
|---------|------------|-------------|
| **BriefService** | **New** | Core brief generation, scheduling (per-user timezone), content assembly, LLM polish, delivery orchestration |
| **Rich Messaging Layer** | **New (foundational)** | Shared Adaptive Card rendering, interactive elements (thumbs up/down), structured sections. Used by Brief, Chat, Standups. |
| **User Memory Store** | **New (foundational)** | User-scoped private knowledge store. Brief reads preferences/patterns, writes feedback + actual-work data. Queryable. |
| **Chat/DM Service** | **New (foundational)** | DM channel infrastructure. Brief is delivered as a system DM. Shared with Chat and Standups features. |
| BoardService | Depends | Query work items for Recap + Focus sections (completed, progressed, blocked items) |
| RunService | Depends | Execution history for Recap section (agent runs completed/failed) |
| FeatureFlagService | Depends | Gate `feature.personal_brief` rollout |
| CollaborationService | Modified | Extend notification settings for brief delivery preferences |
| MetricsService | Depends | Momentum data (goal/feature progress percentages) |
| WorkItemExecutionService | Depends | Agent execution logs for recap context |

### Data Model Changes

| Table/Collection | Change | Description |
|-----------------|--------|-------------|
| `briefs` | New | `brief_id`, `user_id`, `project_id`, `content` (JSONB — Adaptive Card payload), `sections` (JSONB — structured Recap/Focus/Blockers/Momentum), `generated_at`, `delivered_at`, `viewed_at`, `feedback` (enum: null/positive/negative), `feedback_at`, `llm_model`, `generation_metadata` (JSONB) |
| `messages` | New | Unified message table: `message_id`, `channel_id`, `sender_id` (user or system), `content` (JSONB — Adaptive Card), `message_type` (enum: brief/chat/standup/system), `created_at`, `updated_at`, `metadata` (JSONB). Foundation for Rich Messaging Layer. |
| `channels` | New | DM/group channel registry: `channel_id`, `channel_type` (enum: dm/group/system), `project_id`, `created_at`, `metadata` (JSONB). Plus `channel_members` join table. |
| `user_memories` | New | User Memory Store: `memory_id`, `user_id`, `memory_type` (enum: feedback/preference/pattern/activity), `memory_key`, `memory_value` (JSONB), `source` (enum: brief_feedback/manual/inferred), `confidence` (float), `created_at`, `updated_at`, `expires_at`. |
| `user_brief_settings` | New | Per-user brief config: `user_id`, `timezone` (text), `brief_time` (time, default 08:30), `brief_enabled` (bool, default true), `feedback_frequency` (enum: daily/adaptive/manual, default adaptive), `skip_empty` (bool, default true) |

### Configuration

| Env Var / Setting | Purpose | Default |
|-------------------|---------|---------|
| `BRIEF_LLM_MODEL` | Model for narrative generation | `gpt-4o-mini` |
| `BRIEF_LLM_TEMPERATURE` | LLM temperature for brief text | `0.3` |
| `BRIEF_DEFAULT_TIME` | Default delivery time (local) | `08:30` |
| `BRIEF_DEFAULT_TIMEZONE` | Fallback timezone | `UTC` |
| `BRIEF_MAX_ITEMS_RECAP` | Max items in Recap section | `10` |
| `BRIEF_MAX_FOCUS_ITEMS` | Max focus recommendations | `3` |
| `BRIEF_FEEDBACK_ADAPTIVE_THRESHOLD` | Days of consistent feedback before reducing frequency | `14` |

### Content Generation Strategy

**Hybrid: template structure + LLM polish**

1. **Data Assembly** (template-driven): BriefService queries BoardService, RunService, MetricsService, User Memory Store to collect raw data for all 4 sections.
2. **Section Rendering** (structured): Recap and Blockers sections are rendered from structured data with minimal LLM involvement.
3. **Narrative Generation** (LLM): Focus reasoning and Momentum narrative sections get LLM polish — the model receives structured data and writes concise, factual prose in the established tone.
4. **Adaptive Card Packaging**: All sections assembled into an Adaptive Card JSON payload for the Rich Messaging Layer.

### Data Sources (all 4 sections)

| Source | Sections Fed | Service |
|--------|-------------|---------|
| Work item state changes (completed, progressed, blocked) | Recap, Focus, Blockers | BoardService |
| Agent execution logs (runs completed/failed) | Recap | RunService |
| Goal/feature progress percentages | Momentum | MetricsService + BoardService |
| Sprint/board context (upcoming deadlines) | Focus | BoardService |
| User Memory Store (past preferences, feedback) | Focus (personalization) | UserMemoryStore |
| Git commits / PR activity | Recap, Blockers | External integration |
| Team member interactions (who's blocking whom) | Blockers | BoardService (assignments) |

### Scheduling Architecture

- **Scheduler**: Background asyncio task (following ZombieReaper pattern) that runs on a minute interval
- Each tick: query `user_brief_settings` for users whose `brief_time` matches current time in their `timezone`
- For each eligible user: generate brief → persist to `briefs` + `messages` → deliver via Chat/DM Service → push toast via WebSocket/SSE
- **Skip-if-empty**: If no work item changes, no runs, and no blockers since last brief, skip delivery (respects `skip_empty` setting)
- **Fallback**: If no standup configured, brief still delivers at user-set time (default 8:30 local)

### Progressive Disclosure

- **Summary card**: Short headline ("4 items closed yesterday, 2 focus recommendations, 1 blocker") + "Show full brief" button
- **Full brief**: Expandable 4-section Adaptive Card with Recap, Focus, Blockers, Momentum
- Collapse by default on mobile/narrow viewports

### End-of-Day Feedback Loop

- **Delivery**: At end of work window (configurable, default: brief_time + 9 hours), a follow-up message appears in the DM channel
- **Format**: "Did my focus recs feel right today?" with thumbs up / thumbs down interactive buttons
- **Adaptive frequency**: Ask daily for first 14 days of consistent feedback, then reduce to 2x/week. Re-increase if accuracy drops.
- **Data flow**: Feedback → User Memory Store → next day's brief personalization

---

## Behavioral Context

### Existing Behaviors
- `behavior_define_feature_scope` — This feature definition
- `behavior_design_api_contract` — New REST endpoints + MCP tool schemas
- `behavior_migrate_postgres_schema` — 5 new tables via Alembic
- `behavior_manage_feature_flags` — `feature.personal_brief` gating
- `behavior_use_raze_for_logging` — Structured telemetry for all brief events
- `behavior_validate_cross_surface_parity` — 4 day-one surfaces
- `behavior_design_test_strategy` — Parity + quality testing
- `behavior_update_docs_after_changes` — Doc updates

### Proposed New Behaviors
- **`behavior_generate_personal_brief`** — When: Generating daily brief content for a user. Steps: 1) Collect data from all sources, 2) Assemble structured sections, 3) Apply LLM narrative polish, 4) Package as Adaptive Card, 5) Validate against length limits, 6) Deliver via Rich Messaging Layer.
- **`behavior_deliver_rich_message`** — When: Sending any structured message via the Rich Messaging Layer (brief, standup, chat). Steps: 1) Validate Adaptive Card schema, 2) Resolve channel for recipient, 3) Persist to messages table, 4) Push via WebSocket/SSE, 5) Emit telemetry event, 6) Handle delivery failure with retry.
- **`behavior_manage_user_memory`** — When: Reading from or writing to the User Memory Store. Steps: 1) Validate user ownership, 2) Classify memory type, 3) Set confidence score, 4) Persist with source attribution, 5) Apply TTL/expiration if applicable.

### Primary Role
**Student** — Routine feature execution following established patterns. The foundational services (Rich Messaging, User Memory Store) may require Teacher-level guidance for initial patterns.

### AGENTS.md Updates
- **New Quick Trigger keywords**: `brief`, `personal brief`, `morning brief`, `daily recap`, `focus recommendations`
- **New behavior definitions**: `behavior_generate_personal_brief`, `behavior_deliver_rich_message`, `behavior_manage_user_memory`

---

## Feature Interactions

### Depends On
- **Rich Messaging Layer** (new, ships with brief) — Rendering engine for Adaptive Cards
- **User Memory Store** (new, ships with brief) — Personalization and feedback storage
- **Chat/DM Service** (new, ships with brief) — Delivery channel
- **BoardService** (existing) — Work item data
- **RunService** (existing) — Execution logs
- **FeatureFlagService** (existing) — Rollout gating
- **MetricsService** (existing) — Progress percentages

### Impacts (downstream features)
- **Team Standup** — Will use Rich Messaging Layer + Chat/DM Service
- **Chat** — Will use Chat/DM Service + Rich Messaging Layer
- **Agile Coach Agent** — May read brief data for standup context

### Breaking Changes
**No** — Purely additive. All new endpoints, tables, and services. No existing API contracts or data models are modified.

### Migration Path
**Greenfield** — No existing brief data to migrate. New tables created via Alembic migration.

---

## Security & Compliance

| Attribute | Value |
|-----------|-------|
| Auth Level | Hybrid: user owns brief (user-scoped), project gates data sources (project membership required) |
| New Permissions | None — uses existing authenticated user context |
| Audit Logging | All brief lifecycle events: `brief.generated`, `brief.delivered`, `brief.viewed`, `brief.feedback_given` |
| Data Sensitivity | Internal |
| Rate Limiting | Natural limit (1 brief/user/day) + standard API rate limits |
| Compliance Items | None specific — standard data protection practices |
| Privacy Model | App-level user_id filtering. Only the brief owner + Amprealize system can access brief content. No manager/admin visibility. User Memory Store is strictly user-private. |

---

## Success Criteria

### Acceptance Criteria

1. Given an enterprise user with `feature.personal_brief` enabled, when their configured brief time arrives, then a brief DM is delivered containing all 4 sections (Recap, Focus, Blockers, Momentum) populated from their actual work item data.
2. Given a brief with work item changes since the last brief, when the Recap section renders, then it lists completed and progressed items with correct time context ("yesterday", "2 days ago").
3. Given a brief Focus section, when recommendations are generated, then each recommendation includes a one-line reasoning statement referencing blocking dependencies or goal progress.
4. Given a user with blocked work items, when the Blockers section renders, then each blocker includes what's needed to unblock (e.g., "waiting on API review from Maria").
5. Given a user viewing a brief on Web Console, when the brief is delivered, then a toast notification appears on the board page, and the full brief is accessible in the DM chat panel.
6. Given a brief viewed via CLI (`amprealize brief show`), when rendered, then it displays a surface-appropriate formatted text version of all 4 sections.
7. Given the MCP tool `brief.get`, when invoked with a valid brief_id, then it returns the structured brief content as JSON.
8. Given no work item changes, no runs, and no blockers since the last brief, when the scheduler runs, then no brief is generated (skip-if-empty behavior).
9. Given an end-of-day feedback prompt, when the user gives thumbs up or down, then the feedback is persisted to the User Memory Store and acknowledged with a confirmation message.
10. Given a user in timezone `America/New_York` with brief_time set to `08:30`, when it is 08:30 ET, then the brief is generated and delivered (not at 08:30 UTC).
11. Given a brief, when any other user (including admins) attempts to access it via API, then a 403 Forbidden response is returned.
12. Given the `feature.personal_brief` flag is disabled, when any brief endpoint is called, then a 404 or feature-disabled response is returned.

### Metrics

| Metric | Target | Telemetry Event |
|--------|--------|-----------------|
| Briefs generated per day | Track baseline | `brief.generated` |
| Delivery success rate | >99% | `brief.delivered` |
| Brief view rate | >70% of delivered | `brief.viewed` |
| Feedback response rate | >30% of viewed (first month) | `brief.feedback` |
| Focus accuracy | >60% of recs worked on | `brief.focus_accuracy` |
| Skip rate (empty days) | Track baseline | `brief.skipped` |

### Testing Requirements

| Type | Scope | Target |
|------|-------|--------|
| Parity | All 4 day-one surfaces (Web/REST/MCP/CLI) | 100% parity coverage |
| Unit | BriefService, UserMemoryStore, scheduling logic | >90% coverage |
| Integration | Brief generation → delivery → feedback pipeline | Key e2e paths |
| Content quality | Golden dataset + LLM-as-judge evaluation | Both approaches |
| Performance | Brief generation latency | <5s per brief |

---

## Documentation Updates

- [ ] README.md
- [ ] MCP_SERVER_DESIGN.md (new tools: `brief.get`, `brief.list`, `brief.feedback`)
- [ ] AGENTS.md (new behaviors + quick triggers)
- [ ] API contract docs (new endpoints)
- [ ] OSS_VS_ENTERPRISE.md (new feature row in matrix)

---

## Resolved Questions

1. **Adaptive Card schema version**: Use Adaptive Cards 1.5+ — needed for `Action.Execute` (interactive thumbs up/down buttons).
2. **Git/PR integration**: GitHub webhook integration (industry best practice — same approach as Linear, Shortcut, and other agent platforms). Receive push/PR events, correlate to work items via commit messages and branch naming.
3. **LLM cost management**: Yes — cache narrative templates for common patterns (e.g., "completed X blocking items" template). Only invoke LLM for novel Focus reasoning and personalized Momentum narrative. Estimated <$0.01/brief with `gpt-4o-mini` + caching.
4. **Offline brief access**: Yes — cache recent briefs client-side (IndexedDB / service worker). Display last-cached brief with "offline" indicator when no connectivity.
5. **Multi-project briefs**: **One combined brief per user**, categorized/separated by project. Each project section contains its own Recap/Focus/Blockers/Momentum. Synthesis/standup features operate per-project, pulling from the relevant project section of the brief.

## Remaining Open Questions

None — all design questions resolved.
