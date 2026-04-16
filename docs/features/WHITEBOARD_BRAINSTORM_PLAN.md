# Feature Plan: Collaborative Whiteboarding for Brainstorm Agent

**Status**: Brainstorm Complete → Ready for Feature Definition
**Created**: 2026-04-14
**Origin**: Brainstorm session (Nick + Brainstorm Agent)

---

## Summary

Add an optional, real-time collaborative whiteboard to brainstorm sessions where both human users and AI agents can view, draw, and type on the same live canvas. Text conversation remains primary; the whiteboard is a supplemental scratchpad — think "virtual room with a shared whiteboard."

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Canvas technology | **tldraw SDK** | Built-in multiplayer (@tldraw/sync), Editor API for programmatic control, custom shapes, AI starter kit, presence system. Best SDK for agent integration. |
| Build approach | **Build fresh** | tldraw SDK handles hard parts natively (room sync, element CRUD, screenshots). No existing MCP fork saves meaningful effort. |
| Licensing | **Start with 100-day free trial** | No credit card. Full SDK access. Evaluate commercial terms if concept proves out. Excalidraw (MIT) is the fallback if licensing becomes a blocker. |
| Feature toggle | **Opt-in via config** | Existing text-only brainstorm stays unchanged. Whiteboard enabled per config, then suggested by agent or triggered by user. |
| Interaction model | **Bidirectional, real-time** | Both humans and agents can view AND draw/type. Agent joins as full participant via Editor API. |
| Participant model | **1-on-1 primary**, extensible to multi | Human + agent day one. Multi-human + multi-agent architecture-ready. |
| Cursor strategy | **V1: instant appear + attribution** | Agent shapes appear instantly with 🧠 badge/metadata. V2 (parallel): animated cursor movement, then A/B compare. |
| Whiteboard access | **URL-based** | Agent provides a link; human opens in browser. |
| Aesthetic | **Sketchy/hand-drawn** | tldraw's native aesthetic. Fits brainstorming vibe. |
| Artifact persistence | **Full** | Canvas state saved, embedded in brainstorm summary, flows to downstream agents (NewFeature, WorkItemPlanner, Plan). |

## Architecture

```
┌──────────────────────────────────────────────┐
│              Brainstorm Session               │
│                                               │
│  ┌─────────────┐    ┌─────────────────────┐  │
│  │  Text Chat   │    │   Whiteboard (opt)  │  │
│  │  (existing)  │◄──►│   tldraw canvas     │  │
│  └─────────────┘    └──────────┬──────────┘  │
│                                │              │
└────────────────────────────────┼──────────────┘
                                 │
              ┌──────────────────┼──────────────┐
              │                  ▼              │
              │    WhiteboardService            │
              │    (packages/whiteboard/)        │
              │                                 │
              │  ┌─────────────────────────┐    │
              │  │ tldraw + @tldraw/sync   │    │
              │  │ - Room management       │    │
              │  │ - Real-time sync (WS)   │    │
              │  │ - Presence/cursors      │    │
              │  │ - Custom brainstorm     │    │
              │  │   shapes (Idea Card,    │    │
              │  │   Theme Cluster, etc.)  │    │
              │  └─────────────────────────┘    │
              │                                 │
              │  MCP Tools                      │
              │  - whiteboard.open              │
              │  - whiteboard.draw              │
              │  - whiteboard.read              │
              │  - whiteboard.snapshot          │
              │  - whiteboard.close             │
              │                                 │
              │  Agent Adapter                  │
              │  - Translates agent intentions  │
              │    to Editor API calls          │
              │  - Shape attribution            │
              │  - Viewport management          │
              │                                 │
              │  Session Bridge                 │
              │  - Links to brainstorm memory   │
              │  - Exports for downstream       │
              │    agents (NewFeature, etc.)    │
              └─────────────────────────────────┘
```

**Package location**: `packages/whiteboard/` (follows Raze/BreakerAmp standalone package pattern)

### Components

| Component | Responsibility |
|-----------|----------------|
| **WhiteboardService** | Spins up tldraw rooms, manages lifecycle, returns URLs |
| **MCP Tools** (5) | `whiteboard.open` / `draw` / `read` / `snapshot` / `close` — agent's interface to the canvas |
| **Agent Adapter** | Translates high-level agent intentions ("place idea card at top-left") into tldraw Editor API calls (`editor.createShape(...)`) |
| **Session Bridge** | Connects whiteboard state to brainstorm session memory; exports canvas artifacts for downstream agents |

### MCP Tool Details

| Tool | Purpose | Key Params |
|------|---------|------------|
| `whiteboard.open` | Create room, return URL | `session_id`, `title`, `template?` |
| `whiteboard.draw` | Place or modify shapes | `shape_type`, `text`, `position`, `style` |
| `whiteboard.read` | Get canvas state / describe scene | `format: json \| description \| shapes_list` |
| `whiteboard.snapshot` | Export canvas as PNG or .tldr | `format: png \| tldr \| svg` |
| `whiteboard.close` | End session, persist final state | `session_id` |

## Custom Brainstorm Shapes (Proposed for V2)

| Shape | Purpose | Visual |
|-------|---------|--------|
| **Idea Card** | Single idea, labeled | Sticky note (tldraw note shape + metadata) |
| **Theme Cluster** | Group of related ideas | Dashed boundary with label |
| **Connection Arrow** | Relationship between ideas | Arrow with optional label |
| **Decision Marker** | Concluded decisions | Checkmark badge on shape |

## tldraw Technical Details

| Feature | tldraw Capability |
|---------|-------------------|
| Real-time sync | `@tldraw/sync` — self-hostable, WebSocket-based |
| Agent drawing | `Editor.createShape()`, `updateShape()`, `deleteShapes()` |
| Presence/cursors | `CollaboratorCursor` component, customizable per participant |
| Text input | Text shape, Note shape (sticky note), Geo shape with labels, Rich text |
| Custom shapes | `ShapeUtil` class — define render, bounds, migration |
| Snapshots | `editor.getSvg()`, `editor.getSnapshot()`, PNG export |
| Animation | `editor.animateShape()`, camera animations |
| Starter kit | `npx create-tldraw@latest` (includes agent template) |

### Licensing

| Tier | Cost | Notes |
|------|------|-------|
| Development | Free | No key needed |
| Trial | Free, 100 days | No credit card. Full access. Analytics ping. |
| Hobby | Free | Non-commercial. "Made with tldraw" watermark required. |
| Startup | Discounted | Apply via tldraw.dev/get-a-license/startup |
| Commercial | Value-based | Contact sales |

**Decision**: Start with 100-day trial. If feature proves valuable, negotiate commercial/startup terms. Excalidraw (MIT) is architecture-compatible fallback.

## Phasing

### V1 — Ship and Start Using

**Goal**: Humans and agents brainstorming on the same live canvas.

- WhiteboardService spins up tldraw room, returns URL
- Human opens URL in browser, draws/types normally
- Agent creates shapes programmatically via MCP tools (instant appear)
- Agent-created shapes have visual attribution (🧠 badge or colored border)
- 5 MCP tools: open, draw, read, snapshot, close
- Canvas state persists and exports to brainstorm summary
- Opt-in via config flag
- tldraw note shapes as brainstorm idea cards (using built-in shapes)

### V2 — Build in Parallel

- Agent presence cursor (named "Brainstorm Agent 🧠" via CollaboratorCursor)
- Animated cursor movement before shape placement
- Side-by-side comparison with V1 to determine which feels better
- Custom brainstorm shapes (Idea Card, Theme Cluster, etc.)
- Multi-agent support (multiple agents in same room)
- Template canvases (2×2 matrix, fishbone, etc.)

### Future / Sleeper Ideas

- **Whiteboard replay** — animate the brainstorm session as a timelapse
- **Voice-to-sketch** — speech input → agent draws what you describe
- **Universal whiteboard** — not just brainstorms: architecture reviews, incident postmortems, sprint retros
- **Whiteboard as first-class artifact** — version controlled, diffable, searchable

## Risk & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| tldraw license cost at scale | Medium | High | MCP tool surface is canvas-agnostic; Excalidraw (MIT) is drop-in fallback |
| SDK is source-available, not OSS | Low | Medium | License keys are client-validated, offline-capable. Manageable restriction. |
| Trial expires before commercial terms | Low | Medium | Start negotiation at day 60 |
| Feature complexity creep | Medium | Medium | V1 is intentionally minimal; custom shapes and animated cursors deferred to V2 |
| WebSocket infra for sync | Low | Low | @tldraw/sync is self-contained; can run alongside existing services |

## Alternatives Considered

| Tool | Why Not |
|------|---------|
| **Excalidraw** | MIT licensed (pro), but SDK lacks built-in multiplayer and programmatic Editor API. More assembly required. Remains fallback. |
| **Miro** | Enterprise-ready but SaaS-only. Can't self-host. Overkill for brainstorm scratchpad. |
| **Draw.io** | Good for structured diagrams, not freeform brainstorming. No real-time collab SDK. |
| **Whimsical** | URL-based only (Mermaid→image). No live canvas SDK. |
| **Napkin (existing skill)** | One-directional (human draws, agent reads via screenshot). No agent drawing. |

## Research Sources

- tldraw SDK docs: tldraw.dev/docs
- tldraw collaboration: tldraw.dev/docs/collaboration
- tldraw AI integrations: tldraw.dev/docs/ai
- tldraw pricing: tldraw.dev/pricing
- tldraw license: tldraw.dev/community/license
- tldraw GitHub: github.com/tldraw/tldraw (46.3k stars)
- Existing MCP tools surveyed: yctimlin/mcp_excalidraw, excalidraw/excalidraw-mcp, talhaorak/tldraw-mcp, miroapp/miro-ai, and others

## Next Steps

1. ☐ Apply for tldraw 100-day trial at tldraw.dev/get-a-license/trial
2. ☐ Run through NewFeature agent for formal Feature Definition
3. ☐ Scaffold `packages/whiteboard/` following standalone package pattern
4. ☐ Prototype: tldraw room + @tldraw/sync + basic MCP tools
5. ☐ Agent adapter: wire Editor API calls to MCP tool handlers
6. ☐ Integration: connect to brainstorm skill config toggle + session memory
7. ☐ Test: human + agent on same canvas, real-time
8. ☐ Iterate: use it in actual brainstorm sessions, refine
