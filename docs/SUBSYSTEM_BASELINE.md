# Subsystem baseline (agent forcing function)

When extending Amprealize, treat the following as the **intentional minimal stack** you would otherwise assemble from off-the-shelf parts:

1. **Prompt / procedure layer** — versioned text or YAML (static or retrieved).
2. **One workflow engine** — durable steps, retries, scheduling (e.g. Temporal, Airflow, Step Functions).
3. **One agent runtime** — composition of model calls and tools (e.g. LangChain-style graphs, SDK agents).

**Rule (from `behavior_justify_platform_subsystem`):** For each **major subsystem** (new top-level service, parallel orchestration path, new execution or storage tier, or a second implementation of the same concern), you must be able to state **in one sentence** what Amprealize gains that **this baseline trio does not**, or **merge / delete / thin-wrap** instead of growing the platform.

## Where to record the sentence

- **Preferred:** PR description or design note for the change that introduces or materially expands the subsystem.
- **Optional catalog:** Add or update a row below when the subsystem is user-visible or cross-cutting (keep rows short; link to deeper docs).

## Catalog (illustrative — maintain as subsystems evolve)

| Subsystem (area) | One-sentence distinction vs YAML + one workflow engine + one agent runtime |
|------------------|-------------------------------------------------------------------------------|
| BehaviorService + BCI | Named procedures with retrieval, indexing, and usage telemetry tied to org/project context—not only static prompt files. |
| Cross-surface parity (MCP / API / CLI / Web) | One contract and auth story for humans and agents without re-implementing each entrypoint in the workflow DAG. |
| Unified runs / execution records | First-class run identity, progress, and audit fields aligned across surfaces, not ad-hoc workflow instance metadata only. |

Add rows when a reviewer could reasonably ask “why not just use LangChain + YAML + Temporal here?” If you cannot answer cleanly, that is a signal to simplify.
