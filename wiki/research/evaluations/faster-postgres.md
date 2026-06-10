---
title: 'Evaluation: Faster postgres'
type: evaluation-summary
last_updated: '2026-05-14'
sources:
- paper_0d13c7d42af6
confidence: medium
tags:
- defer
---

# Faster postgres

**Verdict**: DEFER | **Score**: 5.3/10

## Full evaluation report

## Paper

- **Paper ID:** `paper_0d13c7d42af6`
- **Source:** https://www.databricks.com/blog/how-lakebase-architecture-delivers-5x-faster-postgres-writes
- **Words:** 2,485
- **Extraction confidence:** 100%

### Abstract

(no abstract)

## Comprehension

**Core idea:** Databricks' lakebase architecture achieves 5x faster Postgres write performance by eliminating the traditional Full Page Write (FPW) bottleneck. By separating compute and storage layers, they can offload crash-recovery tasks from compute nodes to distributed storage, dramatically reducing WAL traffic and improving both write throughput and read latency.

**Problem addressed:** Traditional Postgres suffers from a performance bottleneck where Full Page Writes inflate WAL volume by up to 15x to prevent torn pages during crashes, becoming the biggest bottleneck for write-heavy applications

**Proposed solution:** Move full page image generation from the compute layer to the distributed storage layer ('image generation pushdown'), eliminating FPW overhead while maintaining durability and bounded read performance

- **Novelty:** 7.0/10 — While storage-compute separation isn't new, applying it to eliminate Postgres's decades-old FPW bottleneck through intelligent pushdown represents a clever architectural exploitation with significant practical impact.
- **Comprehension confidence:** 95%

### Key contributions

- Achieved 4.5x write throughput improvement on 32 vCPU instances and 94% reduction in WAL traffic
- Reduced p99 read latencies by 30-50% through optimized delta chain management
- Seamless production rollout across entire fleet without requiring restarts or interruptions

### Claimed results

- **Write throughput (32 vCPU):** 4.5x increase (95,686 to 439,300 NOPM) (_HammerDB TPROC-C benchmark_)
- **WAL generation per transaction:** 94% reduction (58KB to 4KB) (_OLTP workload measurements_)
- **Production WAL rate:** 30x reduction (30 MB/s to 1 MB/s) (_56 vCPU production environment_)
- **Synced Tables ingestion:** 3x increase (17k to 62k rows/second) (_Customer data-intensive workload_)

## Evaluation (Amprealize fit)

| Dimension | Score | Notes |
|-----------|------:|-------|
| Relevance | 5.0 | Amprealize is an AI agent platform focused on behavior management, not a database company. While we use Postgres for BehaviorService and other components, our performance bottlenecks are in embedding… |
| Feasibility | 5.0 | Implementing lakebase would require deep Postgres internals expertise we likely lack, plus significant infrastructure changes to adopt their storage-compute separation model. The engineering effort w… |
| Novelty | 5.0 |  |
| ROI | 5.0 |  |
| Safety | 8.0 |  |

**Overall score:** 5.30/10

### Honest assessment

Databricks solved a real Postgres bottleneck with clever architecture, achieving impressive 5x write gains. But for Amprealize's AI agent platform, this is solving the wrong problem. We're bottlenecked on LLM inference and vector search, not database writes. Investing 6-12 months here would be engineering malpractice when we could just use managed Postgres or focus on our actual bottlenecks.

### Potential benefits

- Could improve ActionService and audit log write performance
- Might reduce infrastructure costs through better resource utilization
- Could enable higher-throughput telemetry ingestion

### Concerns

- No mention of how this affects Postgres extensions we rely on
- Unclear licensing or if this is Databricks-proprietary
- Migration complexity for existing Postgres deployments
- Operational complexity of managing safekeepers and pageservers

## Recommendation

- **Verdict:** **DEFER**
- **Priority:** P4

### Rationale

This is a classic case of solving the wrong problem. Amprealize's bottlenecks are in AI agent orchestration, behavior execution, and MCP tool coordination - not Postgres write throughput. The paper describes impressive engineering but for a problem we don't have. Our ActionService and audit logs aren't write-bound; they're complexity-bound. This would be a massive engineering distraction that pulls resources away from our core AI platform work.

### Executive summary

Databricks built a faster Postgres by separating compute and storage, achieving 5x write performance. For Amprealize, this is irrelevant. We're not Databricks - we don't have petabyte-scale OLAP workloads or thousands of concurrent writers. Our actual bottlenecks are in agent coordination, behavior selection algorithms, and MCP tool latency. Adopting this would mean months of Postgres internals work, operational complexity we can't afford, and zero improvement to what actually matters: making AI agents more capable. Use Aurora or AlloyDB if you need managed Postgres performance.
