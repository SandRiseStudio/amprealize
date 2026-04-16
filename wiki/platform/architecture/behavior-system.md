---
title: "Behavior System"
type: architecture
last_updated: 2026-04-14
applies_to:
  - dev
  - test
  - staging
  - prod
tags:
  - behaviors
  - bci
  - metacognitive-reuse
  - retrieval
  - roles
---

# Behavior System

The behavior system is the core of Amprealize, implementing **Metacognitive Reuse** —
a method that compresses repeated reasoning patterns into short, named procedures
("behaviors") and conditions models to use them at inference time.

Based on [Meta AI's research](https://arxiv.org/pdf/2509.13237), this approach
achieves up to **46% fewer reasoning tokens** while maintaining or improving accuracy.

## Core Concepts

| Concept | Description |
|---------|-------------|
| **Behavior** | A named procedure with triggers, steps, and validation criteria |
| **Version** | Behaviors are versioned; each version has instruction text, role focus, status |
| **BCI** | Behavior-Conditioned Inference — retrieving and injecting behaviors into prompts |
| **Primer** | Compressed text in knowledge packs containing curated behavior summaries |
| **Confidence score** | 0.0–1.0 per behavior version; ≥0.8 qualifies for auto-approval |

## Behavior Data Model

```python
@dataclass(frozen=True)
class Behavior:
    behavior_id: str
    name: str           # behavior_<verb>_<noun>
    description: str
    tags: List[str]
    status: str         # draft → submitted → approved → deprecated
    namespace: str      # default: "core"

@dataclass(frozen=True)
class BehaviorVersion:
    behavior_id: str
    version: int
    instruction: str         # The actual procedure text
    role_focus: str          # student | teacher | strategist
    status: str
    trigger_keywords: List[str]
    examples: List[str]
    confidence_score: float  # 0.0-1.0, ≥0.8 auto-eligible
    historical_validations: List[str]
    embedding: List[float]   # Sentence-transformer vector
```

## Behavior Lifecycle

```
         ┌──────────┐
         │  DRAFT   │  ← behaviors.create
         └────┬─────┘
              │ behaviors.submit
         ┌────▼─────┐
         │ SUBMITTED │  ← Review queue
         └────┬─────┘
              │ behaviors.approve (or auto-approve if confidence ≥ 0.8)
         ┌────▼─────┐
         │ APPROVED  │  ← Active, retrievable via BCI
         └────┬─────┘
              │ behaviors.deprecate
         ┌────▼──────┐
         │ DEPRECATED │  ← 30-day grace period, then removable
         └───────────┘
```

## Three Roles

The behavior system uses three roles from Meta's research:

| Role | Responsibility | Behavior Interaction |
|------|---------------|---------------------|
| **Student** 📖 | Execute tasks using existing behaviors | Retrieves and applies behaviors |
| **Teacher** 🎓 | Create examples, validate proposals | Reviews and approves behaviors |
| **Strategist** 🧠 | Solve → Reflect → Emit new behaviors | Proposes new behaviors from traces |

### Role Escalation

```
Student → Teacher      (creating examples, validating approaches)
Student → Strategist   (pattern observed 3+ times, root cause analysis)
Teacher → Strategist   (behavior gaps discovered, cross-cutting concerns)
```

## BCI (Behavior-Conditioned Inference)

BCIService implements three usage modes:

### 1. Behavior-Conditioned Inference (BCI)
Retrieve K relevant behaviors and prepend to prompt:

```
[Behavior: behavior_use_raze_for_logging]
When: Adding logging to any service...
Steps: 1. Import RazeLogger... 2. Configure sink...

[Behavior: behavior_prevent_secret_leaks]
When: Preparing commits...
Steps: 1. Confirm .gitignore... 2. Run scan_secrets.sh...

---
Task: Add logging to the new payment endpoint
```

### 2. Behavior-Guided Self-Improvement
Extract behaviors from earlier attempts as hints for revision.

### 3. Behavior-Conditioned SFT (BC-SFT)
Fine-tune on teacher outputs that already follow behavior-guided reasoning
(Enterprise Midnighter module).

## Retrieval Pipeline

```
Query ──→ BehaviorRetriever
            ├── Topic-based retrieval (keyword matching on trigger_keywords)
            ├── Embedding-based retrieval (BGE-M3 + cosine similarity)
            └── Hybrid retrieval (combined scoring)
                 │
                 ▼
          Top-K behaviors ──→ BCI prompt composition
```

BCIService tools for retrieval:
- `bci.retrieve` — keyword-based retrieval
- `bci.retrieveHybrid` — combined keyword + semantic
- `bci.composePrompt` — assemble prompt with retrieved behaviors

## Pattern Detection

When an agent solves a task, the trace can be analyzed for reusable patterns:

```
Trace ──→ bci.segmentTrace ──→ Segments
      ──→ bci.detectPatterns ──→ Candidate behaviors
      ──→ bci.scoreReusability ──→ Reuse scores
      ──→ reflection.extract ──→ Proposed behavior
```

Scoring weights:
- Clarity: 0.30
- Generality: 0.30
- Reusability: 0.25
- Correctness: 0.15

## Token Efficiency

The primary metric: how many tokens are saved by using BCI vs. raw reasoning.

```
Token savings = (tokens_without_BCI - tokens_with_BCI) / tokens_without_BCI × 100
```

Target: ≥30% reduction. Tracked per-run via `bci.computeTokenSavings`.

## Storage

- **BehaviorService**: PostgreSQL with pgvector for embedding storage
- **BCIService**: In-memory FAISS index rebuilt from Postgres on startup
- **Redis**: Optional caching layer for frequently-retrieved behaviors
- **Telemetry**: All BCI operations emit events via Raze

## Related

- [Agent Handbook & Conventions](../reference/agent-handbook.md) — full behavior catalog
- [MCP Tool Families](../reference/mcp-tools.md) — BCI and behavior tools
- [Knowledge Packs](../howto/knowledge-packs.md) — how behaviors feed into packs
