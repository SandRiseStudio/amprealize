---
title: 'Evaluation: Pause agent context'
type: evaluation-summary
last_updated: '2026-05-14'
sources:
- paper_6f5fd548969e
confidence: medium
tags:
- defer
---

# Pause agent context

**Verdict**: DEFER | **Score**: 5.3/10

## Full evaluation report

## Paper

- **Paper ID:** `paper_6f5fd548969e`
- **Source:** https://developers.googleblog.com/build-long-running-ai-agents-that-pause-resume-and-never-lose-context-with-adk/
- **Words:** 2,871
- **Extraction confidence:** 100%

### Abstract

(no abstract)

## Comprehension

**Core idea:** Google's Agent Development Kit (ADK) enables building AI agents that can run for weeks or months by implementing durable state machines, persistent sessions, and event-driven resumption. The tutorial demonstrates building an HR onboarding agent that survives container restarts, handles multi-day idle periods waiting for human actions, and delegates tasks to specialized sub-agents without losing context.

**Problem addressed:** Stateless AI agents fail in real enterprise workflows that span days or weeks because they lose context during restarts, accumulate irrelevant conversation history, and hallucinate progress after idle periods

**Proposed solution:** Use ADK's architecture with explicit state machines instead of conversation history, persistent SQLite/Cloud SQL sessions, webhook-triggered resumption from dormancy, and multi-agent delegation for specialized tasks

- **Novelty:** 6.0/10 — While state machines and persistent storage are established patterns, applying them systematically to long-running AI agents with ADK's specific implementation is a practical advancement over typical stateless chatbot architectures.
- **Comprehension confidence:** 95%

### Key contributions

- Durable memory schemas that replace raw JSON dumps with explicit state tracking
- Event-driven dormancy gates that allow agents to sleep for days and resume via webhooks
- Multi-agent delegation pattern that keeps individual agent prompts focused
- Checkpoint-and-resume architecture that survives container restarts and scale-to-zero events

### Claimed results

- **Context retention:** 100% context preservation across multi-day workflows (_Using persistent sessions vs stateless agents that lose everything on restart_)
- **Token cost:** Significant reduction by avoiding full conversation history replay (_Compared to standard stateless pattern that feeds entire history on each call_)

## Evaluation (Amprealize fit)

| Dimension | Score | Notes |
|-----------|------:|-------|
| Relevance | 5.0 |  |
| Feasibility | 5.0 |  |
| Novelty | 5.0 |  |
| ROI | 5.0 |  |
| Safety | 8.0 |  |

**Overall score:** 5.30/10

### Honest assessment

Google's ADK tutorial presents a pragmatic solution to a real problem - AI agents that lose context during long-running workflows. While the core ideas (state machines, persistent storage, webhooks) aren't novel, packaging them specifically for AI agents with clear patterns is valuable. For Amprealize, this isn't about adopting ADK wholesale but rather incorporating these proven patterns into our existing behavior/MCP framework to enable multi-day agent workflows.

### Potential benefits

- Enable true multi-day agent workflows for complex tasks like onboarding, compliance reviews, and release cycles
- Significant token cost reduction by avoiding full conversation replay on each resumption
- Better fault tolerance - agents can resume exactly where they left off after crashes or deployments
- Cleaner separation of concerns with explicit state machines instead of implicit conversation parsing

### Concerns

- ADK examples use Google Cloud SQL - need to ensure our PostgreSQL setup can handle the state persistence patterns efficiently
- The multi-agent delegation pattern might conflict with our existing agent orchestration service's role assignment logic
- Need to carefully manage state schema evolution as behaviors change over time

## Recommendation

- **Verdict:** **DEFER**
- **Priority:** P3

### Rationale

Google's ADK is a production-ready framework that solves a real problem we have - agents losing context across restarts. However, our current architecture assumes stateless conversation replays, so adopting ADK requires non-trivial changes to conversation_service and agent orchestration. The 5.3/10 score reflects that this is useful but not transformative - it's essentially durable workflow orchestration, which tools like Temporal already do well.

### Executive summary

Google ADK enables pause/resume for long-running agents via state persistence. This directly addresses our token costs from replaying full conversations and would enable multi-day workflows. However, it's not revolutionary - it's workflow orchestration with LLM-friendly APIs. The real question is whether ADK's patterns are worth adopting over alternatives like Temporal or even just adding checkpoint tables to our existing PostgreSQL setup. Given our stateless architecture, this is a medium-priority architectural decision rather than an urgent need.
