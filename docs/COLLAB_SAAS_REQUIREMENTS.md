# Amprealize SaaS Web Console & Real-Time Collaboration Requirements

> **Status**: Active
> **Created**: December 12, 2025
> **Updated**: December 15, 2025
> **Purpose**: Canonical requirements document for AI agents and human developers implementing the Amprealize SaaS platform and collaboration features.

---

## 🎯 Executive Vision

Amprealize's SaaS platform must be **the fastest, most responsive collaborative platform ever built**—surpassing Figma, Linear, and other industry leaders in perceived performance and user delight. This is a core differentiator, not a nice-to-have.

The platform serves **both AI agents and human users simultaneously**, potentially thousands of agents collaborating in real-time. This dual-user paradigm fundamentally shapes every architectural and UX decision.

The platform core is designed to use AI agents to advance a user's development of their project.  AI agents using existing behaviors and creating new behaviors as different roles and agents is at the core of achieving this on the platform.

### User-Facing Information Architecture

Amprealize's user-facing mental model is:

**Scope → Projects → Boards / Items / Runs / Agents**

- **Scope** means either **Personal** or an **Organization**.
- **Projects** are the primary containers where work happens.
- **Boards**, **items**, **runs**, and **agents** are anchored to a project or to the currently selected scope.
- The term **workspace** should remain internal or implementation-focused unless Amprealize later promotes it to a first-class product object with a distinct user-facing meaning.

When updating UI copy, prefer:

- **Personal** over **Personal workspace**
- **Organization** over **workspace** when referring to a shared team context
- **Scope** when the choice is between Personal and Organization

Implementation note:

- Internal component names such as `WorkspaceShell` may remain in code for compatibility during staged IA migrations.
- User-facing copy should be centralized in shared copy helpers/constants when terminology must stay consistent across routes.

---

## 🚫 Non-Negotiable Constraints

### Technology Constraints

| Constraint | Rationale |
|------------|-----------|
| **Never use Next.js** | Explicit requirement. Use cutting-edge alternatives that maximize speed and flexibility. |
| **Cross-surface parity from day one** | Web console, VS Code extension, and any future surfaces must share collaboration primitives and maintain identical real-time behavior. |
| **Strong consistency for collaborative artifacts** | No eventual consistency compromises on documents that matter. Users (human and AI) must see the same state. |

### Current Technology Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| **Web Framework** | Vite + React 19 + rolldown-vite | Fastest build times, native ESM, React 19's concurrent features |
| **Shared Package** | `@amprealize/collab-client` | Cross-surface TypeScript library for WebSocket + REST collaboration |
| **Build Tooling** | tsup (ESM + CJS + DTS) | Fast bundling with full type support for package distribution |
| **Animation** | CSS-first with GPU acceleration | Spring physics via `cubic-bezier`, hardware-accelerated transforms |
| **State Management** | Zustand-like pattern (no external deps) | Minimal overhead, maximum performance |
| **Backend** | FastAPI with WebSocket support | Python ecosystem integration, high-performance async |

---

## ✨ User Experience Requirements

### Performance Targets

| Metric | Target | Industry Benchmark |
|--------|--------|-------------------|
| **Time to Interactive (TTI)** | < 1.5s | Figma: ~2.5s |
| **First Input Delay (FID)** | < 50ms | Linear: ~80ms |
| **Animation Frame Rate** | 60fps constant | Non-negotiable |
| **Collaboration Latency** | < 100ms perceived | Figma: ~150ms |
| **WebSocket Reconnection** | < 500ms | Transparent to user |

### UX Qualities (The "Feel")

The platform must embody these qualities in every interaction:

1. **Extremely Fast** — No perceptible lag. Optimistic updates everywhere. Users should feel the UI responds before they finish their action.

2. **Floaty** — Smooth spring animations on state transitions. Elements should feel like they have physical weight but move through a low-friction medium.

3. **Smooth** — 60fps animations, no jank, no layout shifts. GPU-accelerated transforms only.

4. **Responsive** — Instant feedback on every interaction. Hover states, press states, focus rings—all immediate.

5. **Beautiful** — Polished visual design with attention to typography, spacing, color harmony.  No gradients or shadows but visual effects that adds depth.  A tiny bit of glassmorphism as well.  Not too much white or too much black.

6. **Delightful** — Micro-interactions that surprise and please. Success states that celebrate. Error states that guide.

7. **Haptic-Ready** — Design interactions as if haptic feedback exists. Press-and-hold, drag thresholds, momentum scrolling.

8. **Animated** — State changes are animated, not instant. But animations are fast (150-300ms max) and purposeful.

9.  **Not too SaaS(y)** - Don't want it too look like every old school SaaS plaftorm.  I want this to be very modern and have some consumer app type look & feel.

10. **Never use purple, Gradients, or shadows** - Explicit requirement. Never use the color purple (or similar colors), gradients, or shadows.

### Animation & Motion Design System

```css
/* Core timing functions - Spring physics via cubic-bezier */
--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);        /* Overshoot bounce */
--ease-spring-gentle: cubic-bezier(0.34, 1.2, 0.64, 1);  /* Subtle bounce */
--ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);          /* Fast out, smooth stop */
--ease-in-out-expo: cubic-bezier(0.87, 0, 0.13, 1);      /* Symmetric acceleration */

/* Duration scale */
--duration-instant: 100ms;   /* Micro-interactions */
--duration-fast: 150ms;      /* State changes */
--duration-normal: 250ms;    /* Transitions */
--duration-slow: 400ms;      /* Complex animations */

/* GPU-accelerated properties ONLY */
/* ✅ Use: transform, opacity, filter */
/* ❌ Avoid: width, height, top, left, margin, padding */
```

---

## 🤖 Dual-User Paradigm: Agents + Humans

### Scale Requirements

- **Concurrent agents per active scope**: 1,000+
- **Concurrent human users per active scope**: 100+
- **Operations per second (active scope)**: 10,000+
- **Total platform concurrent connections**: 100,000+

### Agent-Specific Considerations

1. **Batch Operations** — Agents may send many edits rapidly. The system must coalesce and optimize.

2. **Presence at Scale** — With 1,000 agents, traditional cursor presence UI breaks down. Need hierarchical/aggregated views.

3. **Programmatic Access** — Every UI action must have an equivalent API/MCP call for agent automation.

4. **Rate Limiting** — Fair scheduling between agents and humans. Humans get priority for interactive latency.

5. **Audit Trail** — Every agent action must be traceable for compliance and debugging.

### Human-Specific Considerations

1. **Visual Presence** — Humans need to see who's working where (cursors, avatars, focus indicators).

2. **Conflict Resolution** — When human and agent edits collide, humans need clear resolution UI.

3. **Agent Activity Awareness** — Humans should see agent activity without being overwhelmed.

4. **Override Controls** — Humans can pause/stop agent actions on their artifacts.

---

## 🔄 Real-Time Collaboration Architecture

### Consistency Model

**Strong Consistency** for all collaborative artifacts:
- Plans
- Workflows
- Agent configurations
- Shared documents

**Eventual Consistency** acceptable for:
- Presence/cursor positions
- Read-only dashboards
- Analytics/metrics

### Conflict Resolution Strategy

1. **Optimistic Updates** — Apply locally immediately, reconcile with server.
2. **Operational Transformation (OT)** or **CRDTs** — For text/document content.
3. **Last-Write-Wins with Merge** — For structured data (JSON objects).
4. **Human Override** — When conflicts can't auto-resolve, human decision wins.

### WebSocket Protocol

```typescript
// Client → Server
type ClientMessage =
  | { type: 'ping' }
  | { type: 'edit'; operation: EditOperation }
  | { type: 'cursor'; position: number; selectionEnd?: number }
  | { type: 'presence'; status: 'active' | 'idle' | 'away' };

// Server → Client
type ServerMessage =
  | { type: 'pong' }
  | { type: 'ack'; operationId: string; version: number }
  | { type: 'operation'; operation: EditOperation; fromUser: string }
  | { type: 'cursor'; userId: string; position: number; selectionEnd?: number }
  | { type: 'presence'; userId: string; status: string }
  | { type: 'sync'; document: Document }
  | { type: 'conflict'; expectedVersion: number; actualVersion: number; serverDocument: Document }
  | { type: 'error'; code: string; message: string };
```

### Cross-Surface Parity

The `@amprealize/collab-client` package provides identical APIs for:

| Surface | Entry Point | Notes |
|---------|-------------|-------|
| **Web Console** | React hooks (`useCollaboration`) | Full feature set |
| **VS Code Webview** | React hooks (same) | Identical to web |
| **VS Code Extension** | Core client (`CollabClient`) | Non-React contexts |
| **CLI** | Core client | Scripting/automation |
| **MCP Tools** | REST API (`CollabApi`) | Stateless operations |

---

## 🧪 Testing Requirements

### Performance Testing

```bash
# Lighthouse CI targets
lighthouse --performance=95 --accessibility=90 --best-practices=95

# WebSocket load test
k6 run --vus 1000 --duration 60s collab-load-test.js

# Animation frame analysis
# Must maintain 60fps with 100 concurrent presence indicators
```

### Cross-Surface Parity Testing

Every feature must pass identical tests on:
1. Chrome/Firefox/Safari (web console)
2. VS Code webview (Electron)
3. Node.js (CLI/MCP)

### Collaboration Scenarios

1. **Two humans editing same document** — No conflicts, smooth merging
2. **Human + 10 agents on same plan** — Human edits take priority
3. **100 agents updating dashboard** — Coalesced updates, no UI thrashing
4. **Network partition recovery** — Graceful reconnect, state reconciliation

---

## 📐 Code Quality Standards

### TypeScript

```typescript
// Strict mode always
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true
  }
}
```

### React

- Functional components only
- Hooks for all state management
- `memo()` for list items and heavy components
- No inline object/array literals in JSX props

### CSS

- CSS Modules or scoped CSS files (no global styles)
- CSS custom properties for theming
- GPU-accelerated properties only for animations
- Mobile-first responsive design

### Bundle Size

| Target | Limit |
|--------|-------|
| Initial JS | < 150KB gzipped |
| Initial CSS | < 20KB gzipped |
| Collab client | < 20KB gzipped |

---

## 🔗 Related Documents

- `PRD.md` — Product requirements (business context)
- `contracts/MCP_SERVER_DESIGN.md` — MCP tool specifications
- `contracts/ACTION_SERVICE_CONTRACT.md` — Backend API contracts
- `contracts/BEHAVIOR_SERVICE_CONTRACT.md` — Agent behavior system
- `packages/collab-client/README.md` — Collaboration client docs
- `web-console/src/styles/design-system.css` — CSS design tokens

---

## ⚠️ Common Pitfalls to Avoid

1. **Don't use Next.js** — Explicit requirement. No SSR framework lock-in.

2. **Don't animate layout properties** — Only `transform`, `opacity`, `filter`. Never `width`, `height`, `top`, `left`.

3. **Don't skip optimistic updates** — Every mutation must update UI immediately, then reconcile.

4. **Don't treat agents like humans** — Agents generate far more traffic. Design for 1000:1 agent:human ratio.

5. **Don't break cross-surface parity** — If it works in web, it must work in VS Code. Test both.

6. **Don't forget accessibility** — Fast and beautiful is useless if inaccessible. Keyboard nav, screen readers, color contrast.

7. **Don't hardcode WebSocket URLs** — All endpoints configurable. Multiple environments.

8. **Don't ignore reconnection** — Users will have flaky networks. Reconnection must be seamless.

9. **Don't duplicate shared code** — If code is needed by both web console AND VS Code extension, it MUST go in `@amprealize/collab-client`. Never implement the same logic twice in surface-specific locations.
10. **Don't assume orgs exist** — Personal projects must support agent assignment with the same UX parity as org-backed projects.

---

## 📝 Changelog

| Date | Change | Author |
|------|--------|--------|
| 2025-12-13 | Added AI Agent Implementation Guidelines section with shared code mandate | AI Agent |
| 2025-12-12 | Initial requirements document | AI Agent |

---

*This document is the source of truth for Amprealize SaaS and collaboration implementation. All PRs affecting these systems should reference this document and update it if requirements evolve.*
