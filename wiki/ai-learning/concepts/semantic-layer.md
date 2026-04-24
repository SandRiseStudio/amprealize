---
title: "Semantic Layer & NL-to-Data Architecture"
type: concept
difficulty: intermediate
prerequisites:
  - "[RAG (Retrieval-Augmented Generation)](rag.md)"
  - "[Model Context Protocol (MCP)](mcp.md)"
  - "[Multi-Agent Orchestration](multi-agent.md)"
tags:
  - agents
  - analytics
  - data
  - architecture
  - nlp
last_updated: 2026-04-23
sources:
  - "Reddit r/ProductManagement thread on MCP vs CLI (April 2026)"
  - "Zylos Research — AI Agent Tool-Use Optimization (March 2026): https://zylos.ai/research/2026-03-03-ai-agent-tool-use-optimization"
  - "NefariousnessSad2208 on Reddit — NL to Semantic Layer architecture (2026)"
amprealize_relevance: "Relevant to Amprealize's analytics product direction. The pattern of NL → Agent → MCP tools → Semantic Layer → data source mirrors how Amprealize's own behavior retrieval works: natural language queries go through BCI, not raw SQL, to ensure governance and consistency."
visibility: public
---

# Semantic Layer & NL-to-Data Architecture

## Why This Matters

One of the most common AI product patterns in 2025–2026 is "chat with your data." The naive implementation — point an LLM at a database schema and let it write SQL — works well enough in demos and small internal tools. It breaks at scale. Understanding *why* it breaks, and what to replace it with, is one of the most practically useful architectural lessons for anyone building data-driven AI products.

## The Naive Path: NL → LLM → SQL

The simplest version of natural language data access:

```
User question (natural language)
    │
    ▼
LLM (schema + question → SQL)
    │
    ▼
Database (BigQuery, Postgres, etc.)
    │
    ▼
Results → LLM (interpret) → Answer
```

**Why this works for small tools:**
- Fast to build (no semantic layer infrastructure)
- Fine for internal use with a handful of tables and trusted users
- Acceptable when consistency and governance are not priorities

**Why it breaks at scale:**

| Problem | Impact |
|---------|--------|
| **Schema exposure** | The raw schema is in the LLM prompt — table names, column names, relationships. Any user can extract this if the interface is not tightly controlled. |
| **Inconsistent metric definitions** | "Revenue" might be `orders.total`, `orders.total - returns.amount`, or something else depending on how the LLM interprets the question. Different users get different answers to the same question. |
| **No governance** | There is no enforcement layer. The LLM can write a query that joins any table the DB user has access to, including ones that should be restricted per-user. |
| **Performance unpredictability** | LLM-generated SQL can be inefficient. There is no place to enforce query patterns, caching, or rate limits. |
| **Context limit vs. schema size** | A real enterprise schema has hundreds of tables. You cannot fit all of them in the LLM prompt. You must pre-select, which reintroduces manual logic. |

## What a Semantic Layer Is

A semantic layer sits between raw data and consumers (humans, agents, dashboards). It encodes business logic that would otherwise live in SQL — or in no-one's heads at all.

```
Raw tables (BigQuery, Postgres, Snowflake, ...)
    │
    ▼
Semantic Layer
  • Metric definitions ("Revenue = gross_amount - returns where order_status = 'complete'")
  • Dimension definitions ("Customer Segment by LTV bucket")
  • Access controls ("this user can only see their own region's data")
  • Pre-aggregated views (cached results for common queries)
  • Join logic (which tables connect and how)
    │
    ▼
Consumers: dashboards, APIs, agents, NL interfaces
```

Examples of semantic layer tools: dbt Semantic Layer, Cube, LookML (Looker), AtScale, Apache Superset metrics layer.

## The Recommended Path at Scale: NL → Agent → MCP → Semantic Layer → DB

```
User question (natural language)
    │
    ▼
Agent
  (decides which semantic tools to call, with what parameters)
    │
    ▼
MCP Server(s)  ← semantic layer exposed as MCP tools
  • get_metric(name="revenue", filters={region: "APAC"}, time_range="last_30d")
  • list_dimensions(entity="customer")
  • get_segment(name="high_value_customers", definition=True)
    │
    ▼
Semantic Layer
  (applies metric definitions, access controls, pre-aggs)
    │
    ▼
Database
    │
    ▼
Results → Agent → Answer
```

### Why the extra layers help

**MCP as the tool interface:** The agent discovers available data capabilities at runtime through the MCP tool list, not through raw schema. The agent sees `get_metric(name, filters, time_range)` — not `SELECT SUM(o.gross_amount - r.return_amount) FROM orders o LEFT JOIN returns r ...`. This reduces the reasoning burden on the LLM and keeps the SQL complexity inside the MCP server where it can be governed.

**Semantic layer as the source of truth:** Metric definitions are encoded once and reused everywhere. Revenue means the same thing whether the query comes from an agent, a dashboard, or a direct API call.

**Security:** The semantic layer enforces row-level security and column-level permissions. The agent cannot bypass access controls by writing clever SQL because the agent never writes SQL — it calls tools that apply access controls internally.

**Scalability:** Pre-aggregations and query routing in the semantic layer mean agent queries don't always hit raw tables. Caching is transparent to the agent.

## Practical Application: NLP Search and Segmentation

A common use case: building NL-driven segmentation over a dataset (e.g., BigQuery customer data).

**Small-scale / internal:**
NL → LLM → BigQuery SQL is acceptable. The schema is small, users are trusted, and consistency requirements are low.

**B2B SaaS / multi-tenant:**
Move to NL → Agent → MCP tools → Semantic Layer → BigQuery. Key reasons:
- Each tenant must only see their own data (row-level security in the semantic layer)
- Segment definitions must be consistent across tenants (defined once in the semantic layer, not regenerated per query)
- Segmentation rules defined in the product (not by the LLM) should be surfaced alongside LLM-generated segments

**Planet-scale / multi-region:**
Add caching, pre-aggregations, and per-region routing at the semantic layer. The agent interface remains unchanged — complexity is absorbed by infrastructure, not by the LLM.

## Connection to Amprealize's Architecture

Amprealize's own BCI (Behavior-Conditioned Inference) is an application of this principle:

Instead of: User query → LLM → raw behavior database SQL

Amprealize uses: User query → Agent → BCI tool → behavior retrieval layer (FAISS + keyword index) → behavior store

The retrieval layer encodes the "semantic" knowledge of how behaviors relate to each other and to the current learner context. The agent never writes raw database queries for behavior retrieval.

## When Not to Add the Semantic Layer

The semantic layer is infrastructure investment. Don't add it if:
- The project is a prototype or internal tool with < 10 users
- The schema is small (< 20 tables) and stable
- Consistency requirements are low (exploratory analysis, not business reporting)
- No compliance or access control requirements exist

Start simple, add the semantic layer when one of the scaling problems listed above actually appears in production.

## See Also

- [Model Context Protocol (MCP)](mcp.md) — the protocol that exposes semantic layer tools to agents
- [RAG (Retrieval-Augmented Generation)](rag.md) — similar principle applied to document retrieval
- [Multi-Agent Orchestration](multi-agent.md) — the agent layer that calls semantic tools
- [6 Agent Design Patterns](../patterns/agent-design-patterns.md) — patterns for structuring the agent layer
- [BCI in Amprealize](../in-practice/bci-in-amprealize.md) — Amprealize's own semantic retrieval layer
