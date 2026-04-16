# NewFeature Prompt: Personal Brief

> Copy everything below the line and paste as your first message to `@NewFeature` in a new session.

---

Design the **Personal Brief** feature for Amprealize.

## Feature Idea

A rich DM delivered by Amprealize to each user every morning containing their personal recap, focus recommendations, blockers, and momentum context. It's the answer to "I opened the board and have no idea what I've been doing or what to work on."

## Brainstorm Context

This feature was designed as part of a 5-feature system (Personal Brief, Team Standup, Chat, Agile Coach Agent, User Memory Store). The brainstorm summary is at `docs/designs/brainstorm-morning-context-team-awareness.md`. The Personal Brief is the **first to ship** because it's the most concrete and forces building the Rich Messaging Layer that all 5 features share.

## Design Decisions Already Made

These were decided during brainstorming — treat them as constraints, not open questions:

- **Delivery mechanism**: Rich DM in the chat system, not a board panel, CLI command, or email digest. "Everything is a message."
- **Toast notification** on the board page when it arrives.
- **Persists forever** in chat history — becomes a queryable personal work journal.
- **Timing**: Arrives before standup (e.g., 8:30 if standup is 9:00). Serves as personal reflection/prep time.
- **Tone**: Factual, data-grounded, concise. Not a cheerleader. Example: *"Yesterday you closed 4 items including the migration fix that had been open for a week. You're midway through the API rate limiter. The dashboard feature is 70% complete — your next task gets it to 85%."*
- **Trust model**: AI proposes, human approves, transparency everywhere. Trust earned over time via explicit feedback loops and visible improvement metrics ("Last week you agreed with 4/5 of my suggestions").
- **Reflection is personal**: The brief is for personal thinking/prep. Reporting happens later in the standup.
- **Privacy**: Brief content feeds the User Memory Store, which only the user + Amprealize can see. No manager/admin visibility.

## Brief Structure (4 sections)

1. **Recap** — Items completed and progressed since last visit, with time context
2. **Focus** — 2-3 recommended items with one-line reasoning ("Focus on X because it's blocking Y and the goal is slipping")
3. **Blockers** — Flagged with what's needed to unblock ("waiting on API review from Maria")
4. **Momentum** — Hybrid quantitative + narrative ("Feature Alpha 70% — your 3 tasks are the remaining 30%. The team shipped auth last week, now the focus is the dashboard redesign — here's where you fit.")

## End-of-Day Feedback Loop

At end of day, the brief asks: "Did my focus recs feel right today?" with thumbs up/down. This feeds the User Memory Store and improves tomorrow's brief.

## Dependencies on Other Features

- **Rich Messaging Layer** (shared foundation): The brief is a rich message — it needs linked work item cards, progress indicators, interactive elements (thumbs up/down), and structured sections. This rendering system is shared with Chat and Standups.
- **User Memory Store**: The brief reads from it (to personalize recommendations) and writes to it (user feedback, which items were actually worked on). This is a new first-class concept — user-scoped, private, queryable.
- **Chat system**: The brief is delivered as a DM, so the DM/chat infrastructure must exist.

## Architecture Context

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
        └───────────┬────────────┘
                    │
        ┌───────────▼────────────┐
        │   User Memory Store    │
        └────────────────────────┘
```

## Open Questions for the Interview

These are the things NOT yet decided — the NewFeature interview should resolve them:

- **Edition**: OSS or enterprise? Feature-flagged for gradual rollout?
- **Surfaces**: Web console first? Does MCP/CLI/Extension get a brief equivalent?
- **Scheduling details**: User-configurable timing? Timezone handling? What if there's no standup configured?
- **Data sources**: What specific data feeds the brief? Work item state changes, git commits, PR activity, agent execution logs?
- **Generation service**: Does Amprealize generate the brief via LLM, or is it template-driven with LLM polish?
- **Rich message format**: Adaptive Cards? Custom components? This decision affects all 5 features.
- **User Memory Store schema**: What's stored from brief interactions? How indexed?
- **Frequency**: Always daily? Configurable? Skip weekends? Skip if nothing changed?
- **Brief length limits**: How long before it becomes a wall of text? Progressive disclosure?
- **Feedback fatigue mitigation**: Will users tire of daily thumbs-up/down? Adaptive frequency?
- **New service or existing**: New `BriefService`? Part of existing service?
- **Acceptance criteria**: What makes a brief "good"? How do we test quality?
