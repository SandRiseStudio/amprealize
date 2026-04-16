# Feature Definition: Brainstorm Whiteboard

**Date**: 2026-04-14
**Author**: Nick
**Status**: Approved

---

## Summary

Real-time collaborative whiteboard for brainstorm sessions. Human + AI agent draw on the same live canvas using tldraw SDK with `@tldraw/sync` for multiplayer. Text chat stays primary; the whiteboard is a supplemental scratchpad. Agent interacts via 5 MCP tools; human opens a URL in a browser or the web console. Canvas state persists and flows to downstream agents.

---

## Distribution

| Attribute | Value |
|-----------|-------|
| Edition | OSS (Apache 2.0, available to all) |
| Feature Flag | `ENABLE_WHITEBOARD` (boolean, default off) |
| Rollout Strategy | Ship behind boolean flag, opt-in |
| Starter Tier Cap | N/A (no caps) |
| OSS Stub Pattern | N/A (feature is OSS) |

---

## Surface Coverage

| Surface | Day One | Follow-up | Notes |
|---------|---------|-----------|-------|
| MCP Tools | ✅ | — | 5 tools: `whiteboard.open`, `whiteboard.draw`, `whiteboard.read`, `whiteboard.snapshot`, `whiteboard.close` |
| REST API | ✅ | — | Room CRUD + snapshot export endpoints. Strict parity with MCP. |
| CLI | ❌ | ✅ | Visual feature — CLI has limited utility. Follow-up: basic `whiteboard open/close/status` commands. |
| Web Console | ✅ | — | Embedded tldraw canvas on separate tab/route. |
| VS Code Extension | ❌ | ✅ | Follow-up: command to open whiteboard URL in browser, then webview panel. |

**Cross-Surface Parity**: Strict — MCP and API must support identical operations.
**Real-time Sync**: WebSocket only (`@tldraw/sync` native).
**Offline/Disconnect**: Canvas becomes read-only on disconnect; reconnect resumes.

---

## Architecture & Services

### Services Impacted

| Service | Impact Type | Description |
|---------|------------|-------------|
| WhiteboardService | New | Standalone package at `packages/whiteboard/`. Room lifecycle, tldraw sync, canvas persistence, snapshot export. |
| Brainstorm Agent | Modified | Playbook updated to offer whiteboard when `ENABLE_WHITEBOARD` is on. Session Bridge exports canvas artifacts. |
| FeatureFlagService | Depends | Gate feature behind `ENABLE_WHITEBOARD` flag. |
| Raze | Depends | Structured logging for room lifecycle events. |
| MCP Server | Modified | Register 5 new `whiteboard.*` tool schemas. |
| Web Console | Modified | New route/tab for embedded tldraw canvas. |

### Data Model Changes

| Table/Collection | Change | Migration |
|-----------------|--------|-----------|
| `whiteboard_rooms` | New table | `20260414_add_whiteboard_rooms` |

**Columns for `whiteboard_rooms`:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Room identifier |
| `session_id` | VARCHAR (FK) | Links to parent brainstorm session |
| `title` | VARCHAR | Room title |
| `status` | ENUM | `active`, `closed` |
| `canvas_state` | JSON/JSONB | tldraw `.tldr` format canvas state (max ~10 MB) |
| `created_by` | VARCHAR | User/agent who created |
| `created_at` | TIMESTAMP | Creation time |
| `closed_at` | TIMESTAMP | Close time (nullable) |
| `metadata` | JSON | Additional metadata |

**Storage Backends**: SQLite, Postgres, Neon (all three from day one).

### tldraw Server Hosting

Embedded — tldraw sync server runs inside WhiteboardService process.

### Configuration

| Env Var / Setting | Purpose | Default |
|-------------------|---------|---------|
| `ENABLE_WHITEBOARD` | Feature flag (boolean) | `false` |
| `WHITEBOARD_PORT` | Port for tldraw sync server | `3456` |
| `WHITEBOARD_HOST` | Host for tldraw sync server | `localhost` |

---

## Behavioral Context

**Existing Behaviors**:
- `behavior_facilitate_brainstorm` — Updated to include whiteboard offering
- `behavior_extract_standalone_package` — Followed for `packages/whiteboard/`
- `behavior_design_mcp_tool_schema` — Followed for 5 tool schemas
- `behavior_manage_feature_flags` — Followed for `ENABLE_WHITEBOARD`
- `behavior_design_api_contract` — Followed for REST endpoints

**New Behaviors**:
- `behavior_manage_whiteboard_sessions` — Proposed. Covers room lifecycle, canvas sync, artifact persistence, agent drawing patterns.

**Primary Role**: All three — Student executes whiteboard operations, Teacher creates examples and validates quality, Strategist designs new patterns as the feature evolves.

**AGENTS.md Updates**:
- Quick Triggers: Add keywords `whiteboard`, `canvas`, `brainstorm canvas`, `shared drawing`, `collaborative canvas`
- New behavior definition: `behavior_manage_whiteboard_sessions`

---

## Feature Interactions

**Depends On**:
- Brainstorm Agent (playbook + session memory)
- FeatureFlagService (`ENABLE_WHITEBOARD` gate)
- Raze (structured logging)
- Web Console infrastructure (React, routing)
- MCP server framework (tool registration)

**Impacts**:
- Brainstorm summary output (canvas artifacts embedded in summary)
- Downstream agents (NewFeature, WorkItemPlanner, Plan receive canvas context)

**Breaking Changes**: None — all additive. New endpoints and tools only.
**Backward Compatibility**: Fully backward compatible. Feature is opt-in. Text-only brainstorm is unchanged.
**Migration Path**: None needed — no existing whiteboard data.

---

## Security & Compliance

| Attribute | Value |
|-----------|-------|
| Auth Level | Authenticated (bearer token required) |
| New Permissions | `whiteboard:create`, `whiteboard:read`, `whiteboard:write` |
| Audit Logging | Room create/close events (append-only) |
| Data Sensitivity | Internal |
| Rate Limiting | Default API rate limits |
| CORS/Security | Standard CORS + CSP headers for embedded tldraw |
| Compliance Items | None |

---

## Success Criteria

### Acceptance Criteria

1. Agent can open a whiteboard room via MCP `whiteboard.open` and receive a shareable URL
2. Human opens URL in browser and sees a live tldraw canvas with sketchy/hand-drawn aesthetic
3. Agent draws shapes via MCP `whiteboard.draw`; human sees them appear in real-time with 🧠 agent attribution
4. Human draws shapes on canvas; agent reads current canvas state via MCP `whiteboard.read`
5. `whiteboard.snapshot` exports canvas as PNG
6. Canvas state persists in `whiteboard_rooms` table and is embedded in brainstorm summary for downstream agents
7. Feature is gated behind `ENABLE_WHITEBOARD` boolean flag; text-only brainstorm is completely unchanged when disabled
8. Canvas becomes read-only on WebSocket disconnect; reconnection resumes editing

### Metrics

| Metric | Target | Telemetry Event |
|--------|--------|-----------------|
| Room creation | Track count | `whiteboard.room.created` |
| Session duration | Track average | `whiteboard.room.closed` (includes duration) |
| Snapshot exports | Track count by format | `whiteboard.snapshot.exported` |

### Testing Requirements

| Type | Scope | Target |
|------|-------|--------|
| Parity | MCP + API + Web | 100% operation coverage |
| Unit | WhiteboardService core logic | >90% coverage |
| Integration | Room lifecycle, canvas sync, artifact export | Key paths |
| Performance | Room creation latency, draw/type/cursor sync latency | TBD (benchmarked during implementation) |

### Documentation Updates

- [ ] `docs/capability_matrix.md` — Add Brainstorm Whiteboard row
- [ ] `README.md` — Mention whiteboard feature
- [ ] `docs/contracts/MCP_SERVER_DESIGN.md` — Document 5 new `whiteboard.*` tools
- [ ] `AGENTS.md` — New Quick Triggers + `behavior_manage_whiteboard_sessions`
- [ ] `amprealize/agents/playbooks/AGENT_BRAINSTORM.md` — Update playbook with whiteboard offering

---

## V2 / Future Enhancements

- **Canvas elements as structured data**: Individual shapes/cards become building blocks that downstream agents can parse and manipulate (beyond PNG snapshots)
- **Agent presence cursor**: Named "Brainstorm Agent 🧠" via tldraw CollaboratorCursor with animated movement
- **Custom brainstorm shapes**: Idea Card, Theme Cluster, Connection Arrow, Decision Marker
- **Multi-agent support**: Multiple agents in same whiteboard room
- **Template canvases**: Pre-built layouts (2×2 matrix, fishbone diagram, sprint retro, etc.)
- **Whiteboard replay**: Animate the brainstorm session as a timelapse
- **Voice-to-sketch**: Speech input → agent draws what you describe
- **Universal whiteboard**: Beyond brainstorms — architecture reviews, incident postmortems, sprint retros
- **CLI commands**: `amprealize whiteboard open/close/status`
- **VS Code extension**: Webview panel with embedded tldraw canvas

---

## Open Questions

*All resolved during review.*

1. ~~tldraw licensing~~: **90-day free trial** active. Start commercial negotiation at day 60.
2. ~~Firestore adapter~~: **Replaced with Neon adapter** (Neon Postgres). Day-one backends: SQLite, Postgres, Neon.
3. ~~Canvas size limits~~: **Start with a reasonable limit** (e.g., 10 MB per canvas state JSON blob). Validate during implementation.
4. ~~Room cleanup policy~~: **Reasonable archival policy** — closed rooms retained for 90 days, then archived/purged. Active rooms have no expiry.
