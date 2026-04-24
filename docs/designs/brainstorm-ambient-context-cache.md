# Design: Brainstorm Ambient Context Cache

**Date**: 2026-04-23
**Author**: Nick
**Status**: Draft

---

## Problem

Even with the three-tier context loading protocol, Tier 3 (full `Explore` subagent scan) takes 30-90 seconds when it's needed. For users who regularly brainstorm on active areas of the codebase, this wait is repetitive and unnecessary — the relevant context hasn't changed meaningfully since last time.

The ambient context cache pre-computes and stores structured codebase summaries so that brainstorm sessions on familiar areas start with rich context instantly.

---

## Design Philosophy

- **Background, never blocking**: cache refreshes happen outside any active session
- **Topic-indexed, not monolithic**: summaries are organized by area/domain, not a single blob
- **Staleness is acceptable**: a 24-hour-old summary is vastly better than no summary for most brainstorming purposes
- **Transparent to the user**: the agent cites the cache date so the user knows context freshness
- **Complements, doesn't replace**: the cache handles "familiar areas"; Tier 3 live scanning still runs for genuinely novel territory

---

## Cache Structure

The cache lives at `memories/context-cache/` and is structured as a set of topic-indexed markdown files, plus a manifest.

### Directory Layout

```
memories/context-cache/
  manifest.json              # index of all cached areas + last-updated timestamps
  areas/
    auth.md                  # Authentication & user management
    api.md                   # API layer, rate limiting, contracts
    notifications.md         # Notification system
    onboarding.md            # Onboarding flows
    billing.md               # Billing & subscription
    [domain].md              # One file per identified domain
  global.md                  # Cross-cutting: open work items, recent activity, key patterns
```

### Manifest Format

```json
{
  "version": 1,
  "last_full_refresh": "2026-04-22T08:00:00Z",
  "areas": {
    "auth": {
      "file": "areas/auth.md",
      "last_updated": "2026-04-22T08:00:00Z",
      "key_services": ["AuthService", "SessionService", "UserService"],
      "open_work_items": 3,
      "staleness_hours": 16
    },
    "notifications": {
      "file": "areas/notifications.md",
      "last_updated": "2026-04-21T08:00:00Z",
      "key_services": ["NotificationService", "EmailService", "PushService"],
      "open_work_items": 5,
      "staleness_hours": 40
    }
  },
  "global": {
    "file": "global.md",
    "last_updated": "2026-04-22T08:00:00Z"
  }
}
```

### Area Summary Format

Each area summary is a structured markdown file designed for fast agent consumption:

```markdown
# Context Cache: [Area Name]
**Last updated**: 2026-04-22 08:00 UTC (16 hours ago)
**Staleness**: Acceptable for brainstorming; run live scan if you need current state

## Key Services & Components
- **[ServiceName]**: [one-line purpose + location]
- **[ServiceName]**: [one-line purpose + location]

## Current State
- [X] open work items on this area
- Last significant change: [description] ([N days ago])
- Notable open issues: [top 1-2 if any]

## Patterns & Constraints
- [Key design pattern or constraint the agent should know]
- [Anything non-obvious that shapes brainstorming]

## Prior Brainstorm Sessions
- [Date]: [Topic] — [top 2-3 ideas in one line each]

## Related Areas
- Connects to: [other area names]
```

---

## Cache Refresh Strategy

### When to Refresh

| Trigger | Scope | Priority |
|---------|-------|----------|
| Session end (after a brainstorm completes) | Area discussed in session | High — knowledge is fresh from session |
| Morning pre-warm (scheduled, before standup) | `global.md` + top 3 active areas by work item count | Medium |
| After significant git activity in an area | That area only | Medium |
| Manual trigger via `/refresh-context [area]` | Specified area | On-demand |
| Full refresh (weekly, or if manifest is >7 days old) | All areas | Low — background |

### Staleness Thresholds

| Staleness | Brainstorm Use |
|-----------|---------------|
| < 4 hours | Use as primary context, no caveat |
| 4-24 hours | Use with light caveat: "context from earlier today" |
| 1-3 days | Use with clear caveat: "context as of [N days ago]" |
| > 3 days | Use only for structural/pattern knowledge, always offer live scan |

---

## Integration with Brainstorm Opening Protocol

The ambient cache slots into **Tier 1** of the context loading tiers, making it truly instant:

```
Tier 1 (instant, enhanced):
  1. Read memories/session/ for prior brainstorm sessions
  2. Read memories/context-cache/manifest.json to find relevant cached areas
  3. Read relevant area .md files
  4. Read global.md for cross-cutting context
  → All of this is file reads, sub-second
```

When the agent opens a brainstorm, the opening response can cite cache content immediately:

> "I've got context on the notification system from earlier today —
> 5 open work items, EmailService and PushService are the core components.
> What's the angle you want to explore?"

This is the "magic" experience: the agent already knows the area without having scanned anything in the current session.

---

## Cache Population

### Initial Population

On first run (or after `memories/context-cache/` is empty), trigger a one-time background full scan:

1. Discover all major domains from the codebase structure
2. For each domain, run a focused Explore subagent to generate the area summary
3. Write area files and manifest
4. This is a one-time cost, runs in background, user is not blocked

### Incremental Updates

After each brainstorm session:
1. The agent already has context for the area discussed in that session
2. Write an updated area summary directly from session context (no additional scan)
3. Update manifest with new timestamp

This makes post-session updates near-free — the knowledge is already in context.

### Refresh Agent

For scheduled/triggered refreshes outside of brainstorm sessions, a lightweight `ContextRefreshAgent` is responsible:

```
ContextRefreshAgent responsibilities:
- Read manifest.json, identify stale areas (by staleness threshold)
- For each stale area, run focused Explore subagent → write updated area file
- Update manifest
- Does NOT run during active brainstorm sessions
- Triggered by: schedule, session-end hook, git activity signal
```

---

## Connection to Morning Context Design

The [Morning Context & Team Awareness design](./brainstorm-morning-context-team-awareness.md) already includes a morning pre-warm concept. The ambient context cache is the shared infrastructure that makes both the morning brief and brainstorm sessions fast:

```
Morning pre-warm job:
  1. ContextRefreshAgent refreshes top 3 active areas
  2. Writes updates to memories/context-cache/
  3. Morning Personal Brief reads from cache
  4. Brainstorm sessions read from same cache — already warm
```

---

## Implementation Phases

### Phase 1 — Cache read (immediate value, minimal build)

Add cache-reading logic to the brainstorm opening protocol. If `memories/context-cache/` exists and has fresh data, use it. If not, fall through to existing Tier 2/3 scanning.

**Changes**: Brainstorm playbook update (add cache-read step to Tier 1).

### Phase 2 — Post-session writes (low cost, high leverage)

After each brainstorm session closes, write the session's context knowledge back to the cache for the relevant area. The agent already has this context — it's just a matter of persisting it.

**Changes**: Memory Protocol update, brainstorm close handler.

### Phase 3 — ContextRefreshAgent (scheduled refresh)

Implement the lightweight refresh agent that runs on schedule and on git activity signals.

**Changes**: New agent definition, scheduler hook, manifest management logic.

### Phase 4 — Morning pre-warm integration

Wire ContextRefreshAgent into the morning Personal Brief pipeline so cache is always warm before the workday.

**Changes**: Morning brief pipeline, pre-warm trigger.

---

## Open Questions

1. **Area discovery**: How do we identify "areas" from the codebase? Options: directory structure, service names, existing feature docs, or a one-time manual mapping.
2. **Cache invalidation**: If a service is significantly refactored, how does the cache know the area summary is structurally stale (not just time-stale)?
3. **Area granularity**: Too fine-grained (one file per service) creates too many files; too coarse (one file for everything) makes the cache less useful. Right granularity = one file per major product domain.
4. **Git activity signal**: How does the system know which area saw significant git activity? Possible: parse `git log --oneline -20` at session start and match changed file paths to area domains.
5. **Storage location**: `memories/context-cache/` assumes the memories directory is persistent across sessions. Confirm this is true in the Amprealize runtime.
