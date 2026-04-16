# Brainstorm Summary: Morning Context & Team Awareness

**Date**: 2026-04-13
**Session type**: Product/Feature
**Problem**: User opens the project board and can't quickly answer: What happened? What matters now? What's stuck? — for themselves or the team.

---

## Core Insight

The board is optimized for **inventory** (everything in one place) when users need a **briefing** (what matters to me right now). The fix isn't changing the board — it's adding layers that provide context, communication, and memory on top of it.

## Design Philosophy

- **AI proposes, human approves, transparency everywhere**
- **Trust is earned over time** — explicit feedback loops, visible improvement metrics
- **Reflection is personal, reporting is shared** — brief for thinking, standup for alignment
- **Everything is a message** — shared messaging infrastructure, rich rendering, different features built on top

---

## Five Features

### 1. Personal Brief (DM from Amprealize)

**What**: A rich chat message delivered as a DM from Amprealize each morning. Contains your recap, focus recommendations, blockers, and momentum context.

**Structure**:
- **Recap**: Items completed and progressed since last visit, with time context
- **Focus**: 2-3 recommended items with one-line reasoning ("Focus on X because it's blocking Y and the goal is slipping")
- **Blockers**: Flagged with what's needed to unblock ("waiting on API review from Maria")
- **Momentum**: Hybrid quantitative + narrative ("Feature Alpha 70% done, your 3 tasks are the remaining 30%. The team shipped auth last week, now focus is the dashboard redesign — here's where you fit.")

**Delivery**: DM with toast notification on board page. Persists in chat history forever (becomes queryable work journal). No panel, CLI command, or email digest.

**Tone**: Factual, data-grounded. Not cheerleader. Example: *"Yesterday you closed 4 items including the migration fix that had been open for a week. You're midway through the API rate limiter. The dashboard feature is 70% complete — your next task gets it to 85%."*

**Timing**: Arrives before standup (e.g., 8:30 if standup is 9:00). Serves as personal reflection/prep.

### 2. Team Standup (Facilitated Group Chat)

**What**: Periodic group chat session facilitated by an Agile Coach agent. Round-robin format with streaming agent updates and pre-drafted human updates.

**Mechanics**:
- Agile Coach opens standup, tags participants in order
- Human users get a pre-populated draft (from brief + activity data), edit and send
- Agents stream their updates in real time (typewriter effect), result persists as rich structured card with expandable details
- Absent humans: AI proxy answers, clearly marked as "based on recent activity"
- After round-robin, room stays open briefly for clarifying questions
- Synthesis message posted ~1 hour after standup (correction window for absent humans)

**Cadence**: User/project configurable (daily, 3x/week, etc.). Sessions are time-bounded, history saved.

**Correction flow**: Absent humans can review and edit the proxy update within 1 hour. Corrections update the synthesis before it finalizes. Correction data feeds back into the User Memory Store.

### 3. Chat (Group + DM)

**What**: Persistent messaging — group chats and 1-on-1 DMs between humans and agents. Conversational, always available.

**Key capability**: Rich message rendering — linked work item cards, progress indicators, interactive elements, structured cards. Same rendering system used by briefs and standups.

**Relationship to standups**: Shared underlying infrastructure (components, real-time messaging, rich rendering). But Chat and Standups are distinct features with their own UX surfaces.

### 4. Agile Coach Agent

**What**: Lightweight dedicated agent that facilitates agile rituals.

**Scope (lean to start)**:
- Standup orchestration (round-robin facilitation, proxy updates, synthesis)
- Retrospectives (same facilitated chat format, different prompts)
- Blocker escalation (notices patterns across standups — "this migration review has blocked Nick for 3 days")

**Not in scope (yet)**: Sprint planning, velocity analysis, strategic recommendations.

### 5. User Memory Store

**What**: New first-class concept — a personal, user-scoped knowledge store that Amprealize builds over time.

**Sources**: Briefs, standup answers, standup corrections, focus recommendation feedback (thumbs up/down), activity data, edits to AI drafts.

**Purpose**: Powers personalization across all features. Amprealize learns your work patterns, priority preferences, and context. Example: *"Nick usually prefers finishing in-progress work before starting new items."*

**Privacy**: Only the user + Amprealize can access. No manager/admin visibility. Aggregated anonymous patterns can inform team-level insights without exposing individual stores.

**Queryable**: Users can ask "What was I working on the week of March 16?" and get synthesized answers from their memory store.

---

## The Daily Loop

| Time | Event | Feature |
|------|-------|---------|
| 8:30 | Brief arrives as DM + toast notification | Personal Brief |
| 8:30-9:00 | User reads brief, reflects, maybe gives feedback | Brief + Memory Store |
| 9:00 | Standup opens, Agile Coach facilitates round-robin | Standup + Agile Coach |
| 9:00-9:10 | Humans approve/edit drafts, agents stream updates, Q&A | Standup + Chat |
| 10:00 | Synthesis posted (after correction window) | Standup + Agile Coach |
| Throughout day | Chat with humans and agents as needed | Chat |
| End of day | Brief asks: "Did my focus recs feel right?" Thumbs up/down | Brief + Memory Store |
| Next morning | Better brief, informed by feedback and activity | The loop repeats |

---

## Architecture: Shared Foundation

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   Personal   │  │   Standups   │  │    Chat      │
│    Brief     │  │  (periodic)  │  │ (persistent) │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └────────────┬────┴────────────────┘
                    │
        ┌───────────▼────────────┐
        │  Rich Messaging Layer  │
        │  (rendering, cards,    │
        │   streaming, interactive│
        │   elements, work item  │
        │   links)               │
        └───────────┬────────────┘
                    │
        ┌───────────▼────────────┐
        │   User Memory Store    │
        │  (personal, queryable, │
        │   feeds personalization)│
        └────────────────────────┘
```

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Brief delivery | Rich DM, not board panel | "Everything is a message" — simpler architecture, persistent history |
| Standup format | Facilitated round-robin by Agile Coach | Structured but not rigid, clear turn-taking |
| Human standup input | Pre-drafted by AI, edited by human (Level 2) | Eliminates blank-page problem, keeps humans engaged as editors not authors |
| Absent human proxy | AI answers + 1-hour correction window before synthesis | Balances accuracy with velocity; corrections improve future proxies |
| Agent standup format | Streaming presentation → persisted rich card | Feels alive during standup, structured in history |
| Reflection vs. reporting | Brief = reflection (before standup), Standup = reporting | Mirrors real-life prep-then-share pattern |
| Personal memory | User Memory Store (new first-class concept) | More powerful than wiki/behaviors; becomes personal model, not just log |
| Memory privacy | User + Amprealize only | Not surveillance; aggregated anonymous patterns for team insights |
| Board page changes | None (just toast notification) | Brief lives in chat; board stays as-is for now |
| Trust building | Explicit feedback loops + visible improvement metrics | "Last week you agreed with 4/5 of my suggestions" |

---

## Open Questions for Later

- **Rich message format**: What rendering standard? Adaptive Cards? Custom component system? Something like Slack blocks?
- **Standup turn order**: Random? Alphabetical? Based on who's online? Configurable?
- **Brief scheduling**: What time relative to standup? User-configurable? Timezone-aware for distributed teams?
- **Agile Coach personality**: How formal/informal? Should it be configurable per team?
- **User Memory Store schema**: What's the data model? How are entries categorized and indexed?
- **Retrospective format**: Same chat-based approach? What templates/prompts does the Agile Coach use?
- **Team momentum narrative**: Always included in standup synthesis, or a separate periodic message?
- **Feedback fatigue**: Will users tire of daily thumbs-up/down? Should frequency adapt?

---

## Suggested Next Steps

1. **Run through NewFeature** for one of these (probably Personal Brief as the most concrete/shippable first)
2. **Design the rich message rendering system** — this is the shared foundation everything depends on
3. **Plan the User Memory Store data model** — what goes in, how it's indexed, how it's queried
4. **Create work items** via WorkItemPlanner for implementation phases
