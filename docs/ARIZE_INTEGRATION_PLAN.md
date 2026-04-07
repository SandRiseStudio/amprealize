# Arize AI Integration Plan for Amprealize

## Document Control
- **Status:** Draft — Discovery & Scoping
- **Date:** 2026-03-11
- **Last Updated:** 2026-03-11
- **Author(s):** Product Team
- **Stakeholders:** Product, Engineering, Data Science, GTM
- **Behaviors Referenced:** `behavior_instrument_metrics_pipeline`, `behavior_prefer_mcp_tools`, `behavior_use_raze_for_logging`

---

## Executive Summary

This document outlines how **Arize AI** (particularly **Arize Phoenix**, their open-source LLM observability platform) can be integrated into Amprealize to provide deep LLM trace observability, behavior evaluation, retrieval quality monitoring, and production model monitoring. The integration targets three personas within Amprealize's customer base and extends Amprealize's existing Raze telemetry pipeline without replacing it.

**Why now:** Amprealize's Behavior-Conditioned Inference (BCI) pipeline already captures token savings, behavior reuse rates, and execution traces — but lacks a purpose-built UI for LLM trace exploration, retrieval debugging, and evaluation workflows. Arize Phoenix fills this gap with minimal integration effort.

---

## Background

### What Is Arize AI?

Arize AI offers two products relevant to Amprealize:

| Product | Type | Description |
|---------|------|-------------|
| **Arize Phoenix** | Open-source (Apache 2.0) | Self-hosted LLM observability: tracing, evals, retrieval analysis, prompt playground |
| **Arize Cloud** | Commercial SaaS | Production model monitoring: drift detection, performance dashboards, alerting |

**Key libraries:**
- `arize-phoenix` — Trace collector, eval framework, and UI server
- `openinference-instrumentation-*` — Auto-instrumentors for OpenAI, Anthropic, LangChain, LlamaIndex, etc.
- `arize-otel` — OpenTelemetry bridge for OTLP-compatible export
- `phoenix.evals` — LLM-as-judge evaluation framework with pre-built templates (hallucination, relevance, toxicity, Q&A correctness)

### Why Arize + Amprealize?

| Amprealize Strength | Gap Arize Fills |
|---|---|
| BCI pipeline tracks token savings, behavior IDs, run correlation | No dedicated UI to **explore individual LLM traces** (prompt → completion → latency) |
| TraceAnalysisService extracts behavior patterns from runs | No **LLM-as-judge quality evaluation** of behavior-conditioned outputs vs. baselines |
| Raze logs structured events to Kafka/TimescaleDB | No **retrieval debugging** (why was behavior X retrieved instead of Y?) |
| Compliance pipeline validates 17+ checks | No **drift detection** to alert when behavior quality degrades over time |
| MetricsService tracks KPIs in fact tables | No **experiment tracking** for A/B testing behavior variants |

---

## Target Personas

### Persona 1: The AI/ML Engineer — "The Builder"

**Who they are:** Engineers building and fine-tuning Amprealize's BCI pipeline, behavior retrieval (BGE-M3 + FAISS), LLM provider integrations, and trace analysis workflows.

**Pain points today:**
- Debugging why a specific LLM call produced a poor response requires grepping JSONL logs or running SQL against TimescaleDB
- No easy way to see the full prompt (with injected behaviors) alongside the completion
- Hard to diagnose retrieval failures — when wrong behaviors are retrieved, the only signal is downstream quality
- Token savings calculations are aggregate; can't drill into individual outliers

**How Arize helps them:**
| Capability | Arize Feature | Impact |
|---|---|---|
| **LLM trace exploration** | Phoenix Trace UI — view full prompt/completion/latency per call | Debug bad outputs in seconds, not minutes |
| **Retrieval debugging** | Phoenix Retrieval Evals — visualize embedding similarity, inspect retrieved documents | Diagnose why wrong behaviors are retrieved |
| **Auto-instrumentation** | OpenInference instrumentors for OpenAI, Anthropic, etc. | Zero-code tracing across all 8 LLM providers |
| **Span waterfall view** | Nested spans: query → retrieval → prompt composition → LLM call → citation validation | Identify latency bottlenecks in the BCI pipeline |
| **Prompt playground** | Test prompt variants with different behavior sets directly in Phoenix UI | Iterate on behavior instructions without redeploying |

**What they'd buy / adopt:**
- Phoenix OSS (free, self-hosted) for local development
- Arize Cloud for shared team dashboards in staging/production

---

### Persona 2: The Platform / Product Manager — "The Measurer"

**Who they are:** PMs responsible for Amprealize's KPIs: token savings rate (target 30%), behavior reuse rate (target 70%), retrieval accuracy (target 90%), completion rate (target 80%).

**Pain points today:**
- KPI dashboards exist in Metabase/TimescaleDB but only show **aggregates** — can't drill into "why did token savings drop 5% this week?"
- No way to **A/B test** behavior variants (e.g., does a rewritten behavior instruction save more tokens?)
- Behavior quality is measured by proxy (reuse rate, token savings) — no direct **quality evaluation** of outputs
- Hard to tell if a newly proposed behavior is actually better than existing ones

**How Arize helps them:**
| Capability | Arize Feature | Impact |
|---|---|---|
| **Quality evaluation** | Phoenix Evals — LLM-as-judge scoring (relevance, correctness, helpfulness) | Move from proxy metrics to direct output quality measurement |
| **A/B experiments** | Phoenix Experiments — compare behavior variants side-by-side with eval scores | Data-driven behavior curation, not gut feel |
| **Drift detection** | Arize Cloud monitors — alert when eval scores or token savings degrade | Catch stale/harmful behaviors before users notice |
| **Dataset management** | Phoenix Datasets — curate golden test sets for behavior regression testing | Prevent behavior regressions when updating the handbook |
| **Cohort analysis** | Filter traces by role (Student/Teacher/Strategist), surface (CLI/API/MCP/Web), time range | Understand behavior impact per user segment |

**What they'd buy / adopt:**
- Phoenix OSS for eval workflows and experiment tracking
- Arize Cloud for production monitoring dashboards and automated alerting

---

### Persona 3: The Compliance / Trust & Safety Lead — "The Auditor"

**Who they are:** Stakeholders responsible for ensuring Amprealize's outputs meet safety, compliance, and quality standards — especially in enterprise deployments where behavior-conditioned outputs must be auditable.

**Pain points today:**
- Compliance pipeline validates structural checks (17/17 passing) but doesn't evaluate **content quality** of LLM outputs
- Audit trail captures inputs/outputs but doesn't flag **hallucinations, toxicity, or off-topic responses**
- No automated way to validate that cited behaviors actually influenced the output (citation integrity)
- Enterprise customers ask "how do you monitor your AI outputs?" — no great answer beyond "we log everything"

**How Arize helps them:**
| Capability | Arize Feature | Impact |
|---|---|---|
| **Hallucination detection** | Phoenix Evals `hallucination` template — LLM-as-judge scores factual grounding | Automated quality gate on BCI outputs |
| **Toxicity screening** | Phoenix Evals `toxicity` template | Flag harmful outputs before they reach users |
| **Citation integrity** | Custom eval: "Does this output actually follow the cited behaviors?" | Validate behavior attribution is real, not fabricated |
| **Audit-ready exports** | Phoenix dataset exports with eval scores, timestamps, model versions | Enterprise compliance evidence packages |
| **Continuous monitoring** | Arize Cloud alerting on eval score degradation | Proactive quality assurance, not reactive firefighting |

**What they'd buy / adopt:**
- Phoenix OSS for eval pipeline in CI/CD (block deployments with failing evals)
- Arize Cloud for production monitoring with alerting and retention policies

---

## PM Sales & Positioning Strategy

### Value Proposition by Buyer

| Buyer | Pitch | Proof Point |
|---|---|---|
| **Engineering Lead** | "See every LLM call your BCI pipeline makes — prompt, completion, latency, token count — in one UI. Debug in seconds, not hours." | Demo: Phoenix trace waterfall showing a full BCI request with behavior injection |
| **VP of Product** | "Move from proxy metrics to direct quality measurement. A/B test behavior variants and prove which ones actually improve output quality." | Demo: Phoenix experiment comparing two behavior versions with LLM-as-judge scores |
| **CISO / Compliance** | "Automated hallucination detection, toxicity screening, and citation integrity checks — continuous monitoring, not spot checks." | Demo: Phoenix eval dashboard showing 98.5% factual grounding across last 30 days |
| **CTO / Budget Holder** | "Start free with Phoenix OSS. Self-hosted, Apache 2.0. Graduate to Arize Cloud when you need production alerting and team dashboards." | Cost: $0 to start, scales with usage |

### Competitive Positioning

| Alternative | Why Arize Wins for Amprealize |
|---|---|
| **Langfuse** | Phoenix has deeper eval framework (LLM-as-judge templates out of the box); Arize Cloud adds production drift monitoring |
| **LangSmith** | Phoenix is open-source and vendor-neutral; LangSmith locks into LangChain ecosystem |
| **Datadog LLM Monitoring** | Datadog is expensive and generic; Phoenix is purpose-built for LLM traces with retrieval-specific analysis |
| **Custom Raze dashboards** | Raze + Metabase gives aggregates; Phoenix gives per-trace exploration and eval workflows |
| **Weights & Biases** | W&B focuses on training; Phoenix focuses on production inference observability |

### LLM Observability Competitive Landscape

The LLM observability and evaluation space has exploded since 2024, with players spanning open-source tools, venture-backed startups, and incumbent APM giants adding AI modules. Understanding this landscape is critical both for choosing Arize and for positioning Amprealize's own observability story to customers.

#### Market Map

| Category | Players | Positioning |
|---|---|---|
| **OSS-First LLM Observability** | Arize Phoenix, Langfuse, OpenLLMetry (Traceloop), Phoenix Traces | Open-source tracing + evals, self-hosted, OTLP-compatible. Compete on developer experience and community. |
| **Managed LLM Platforms** | Arize Cloud, LangSmith (LangChain), Humanloop, Braintrust, Log10 | SaaS platforms combining tracing, evals, prompt management, and collaboration. Compete on team features and workflow integration. |
| **Incumbent APM + AI Extensions** | Datadog LLM Observability, New Relic AI Monitoring, Dynatrace, Elastic Observability | Traditional APM vendors adding LLM trace support. Compete on "one pane of glass" for infra + AI. |
| **Experiment / Eval Focused** | Weights & Biases (Weave), Patronus AI, Ragas, DeepEval, Promptfoo | Focused on evaluation, benchmarking, and red-teaming. Less emphasis on production tracing. |
| **AI Gateway + Observability** | Portkey, Helicone, Keywords AI, LiteLLM | Proxy-layer tools that sit between app and LLM provider; provide logging, caching, and cost tracking as a byproduct. |

#### Key Players Deep Dive

**Arize AI (Phoenix + Cloud)**
- **Founded:** 2020 | **Funding:** ~$62M (Series B, 2023)
- **Strengths:** Strongest eval framework (LLM-as-judge templates for hallucination, relevance, toxicity, Q&A correctness). Phoenix OSS is genuinely useful standalone. Arize Cloud adds drift detection and production alerting inherited from their original ML monitoring product. Deep OTEL integration.
- **Weaknesses:** Arize Cloud pricing can be opaque at scale. Phoenix UI is functional but less polished than LangSmith. Smaller community than Langfuse.
- **Best for:** Teams that need both tracing AND evaluation AND production monitoring in one stack.

**Langfuse**
- **Founded:** 2023 | **Funding:** ~$14M (Series A, 2024)
- **OSS License:** MIT
- **Strengths:** Excellent developer experience. Clean, fast UI. Strong community (15k+ GitHub stars). Easy self-hosting with Docker. Good prompt management and dataset features. Growing eval capabilities.
- **Weaknesses:** Eval framework less mature than Phoenix (no built-in LLM-as-judge templates — you bring your own). No production drift monitoring equivalent to Arize Cloud. Smaller company, higher vendor risk.
- **Best for:** Teams that prioritize DX and community; primarily need tracing + prompt management.

**LangSmith (LangChain)**
- **Founded:** 2023 (part of LangChain Inc.) | **Funding:** LangChain raised ~$35M (Series A, 2023)
- **License:** Proprietary (closed-source)
- **Strengths:** Tightest integration with LangChain/LangGraph ecosystem. Excellent annotation and human-in-the-loop workflows. Good dataset management. Large user base from LangChain adoption.
- **Weaknesses:** Vendor lock-in to LangChain ecosystem — instrumenting non-LangChain code requires manual work. Closed-source. Pricing increase concerns. Performance issues reported at high trace volumes.
- **Best for:** Teams already deep in LangChain; willing to accept ecosystem lock-in for tight integration.

**Datadog LLM Observability**
- **Launched:** 2024 (extension of existing Datadog APM)
- **Strengths:** Unified view: infra metrics, APM traces, logs, AND LLM traces in one dashboard. Massive existing customer base. Strong alerting and incident management. Enterprise sales motion.
- **Weaknesses:** Expensive (Datadog pricing is per-host + per-trace + per-log). LLM-specific features are shallow compared to purpose-built tools (basic trace view, limited eval support). Generalist tool trying to serve specialist needs.
- **Best for:** Enterprise teams already paying for Datadog who want "good enough" LLM visibility without adding another vendor.

**Weights & Biases (Weave)**
- **Founded:** 2018 | **Funding:** ~$250M (Series C, 2023)
- **Strengths:** Dominant in ML experiment tracking and model training. Weave product extends into LLM app tracing and evals. Large community. Strong enterprise relationships.
- **Weaknesses:** Weave is newer and less mature than their training tools. Primary mindshare is still training/fine-tuning, not production inference. Tracing capabilities are behind Arize/Langfuse.
- **Best for:** Teams already using W&B for training who want to extend into production LLM monitoring.

**Promptfoo**
- **License:** MIT (open-source)
- **Strengths:** Best-in-class for prompt testing and red-teaming. CLI-first workflow integrates well with CI/CD. Supports 100+ assertion types. Lightweight — no server needed for basic usage.
- **Weaknesses:** Not a production observability tool — designed for pre-deployment testing. No trace collection or production monitoring.
- **Best for:** Teams that want rigorous prompt testing in CI/CD; complementary to (not a replacement for) Arize/Langfuse.

#### Market Trends Relevant to Amprealize

1. **Convergence of tracing + evals:** The market is consolidating around platforms that do both. Standalone tracing (without evals) or standalone evals (without tracing) are becoming less competitive. Arize Phoenix is well-positioned here.

2. **OpenTelemetry as the standard:** OTEL/OTLP is emerging as the wire protocol for LLM traces (via the OpenInference semantic conventions). This means Amprealize's Raze telemetry can export to *any* OTEL-compatible backend, not just Phoenix — reducing lock-in risk.

3. **Eval-driven development:** Teams are shifting from "log everything, analyze later" to "eval continuously, fail fast." The eval framework quality is becoming the key differentiator — favoring Arize Phoenix and Braintrust over pure tracing tools.

4. **OSS + Cloud hybrid:** The winning go-to-market model is free OSS for developers → paid Cloud for teams. Arize (Phoenix → Cloud), Langfuse (OSS → Cloud), and LangSmith all follow this. Amprealize should leverage the same motion for its own observability features.

5. **AI gateway commoditization:** Proxy-layer tools (Portkey, Helicone, LiteLLM) are commoditizing basic LLM call logging and cost tracking. The value is moving up-stack to evals, experiments, and production monitoring — where Arize is strong.

#### Why Arize Over Alternatives — Summary

| Decision Factor | Arize Phoenix | Langfuse | LangSmith | Datadog |
|---|---|---|---|---|
| **Open source** | Yes (Apache 2.0) | Yes (MIT) | No | No |
| **Eval framework** | Best-in-class (built-in templates) | Basic (BYO evals) | Good | Minimal |
| **Production monitoring** | Yes (via Arize Cloud) | Limited | Limited | Yes (but expensive) |
| **Vendor lock-in** | Low (OTEL-native) | Low | High (LangChain) | Medium (Datadog ecosystem) |
| **Self-hosted** | Yes | Yes | No (paid self-hosted) | No |
| **Retrieval-specific analysis** | Yes (embedding viz, retrieval evals) | Basic | Basic | No |
| **Cost to start** | Free | Free | Free tier, then paid | Expensive |
| **Amprealize fit** | **Best** — evals + tracing + retrieval + production monitoring | Good — strong DX but weaker evals | Poor — ecosystem lock-in | Poor — expensive, shallow LLM features |

### Objection Handling

| Objection | Response |
|---|---|
| "We already have Raze logging" | Raze captures events; Phoenix interprets them. Raze is your data plane, Phoenix is your analysis plane. They're complementary — Phoenix reads from Raze via a custom sink. |
| "Another tool to maintain" | Phoenix is a single `pip install` + `phoenix serve`. No Kafka, no DB — it has an embedded SQLite store. Deploy alongside your backend with zero infra changes. |
| "Does it work with our LLM providers?" | OpenInference has instrumentors for OpenAI, Anthropic, and generic OTEL adapters. All 8 Amprealize providers are covered. |
| "We need on-prem / self-hosted" | Phoenix is Apache 2.0 open-source. Self-host anywhere. No data leaves your infra. |
| "What about cost?" | Phoenix OSS is free. Arize Cloud pricing is usage-based (per trace). Start free, upgrade when you need team features + alerting. |

---

## Integration Architecture

### Phase 1: LLM Trace Observability (Quick Win)

**Effort:** 1-2 days | **Impact:** High

```
┌─────────────────────────────────────────────────────────┐
│                  Amprealize Backend                        │
│                                                         │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────┐ │
│  │ LLM Provider│──▶│ OpenInference│──▶│   Phoenix    │ │
│  │  (OpenAI,   │   │ Instrumentor │   │  Collector   │ │
│  │  Anthropic) │   │ (auto-trace) │   │  (OTLP)     │ │
│  └─────────────┘   └──────────────┘   └──────┬──────┘ │
│                                                │        │
│  ┌─────────────┐                               │        │
│  │ BCI Service │───── run_id, behavior_ids ────┘        │
│  └─────────────┘                                        │
└─────────────────────────────────────────────────────────┘
                                                  │
                                    ┌─────────────▼──────────────┐
                                    │     Phoenix Server         │
                                    │  http://localhost:6006     │
                                    │                            │
                                    │  • Trace waterfall view    │
                                    │  • Token count analytics   │
                                    │  • Latency breakdown       │
                                    │  • Prompt/completion viewer│
                                    └────────────────────────────┘
```

**Implementation:**
1. `pip install arize-phoenix openinference-instrumentation-openai openinference-instrumentation-anthropic`
2. Add instrumentors in `amprealize/llm_provider.py` startup
3. Enrich spans with Amprealize-specific attributes: `run_id`, `behavior_ids`, `token_savings_pct`, `actor_role`, `actor_surface`
4. Run `phoenix serve` as a companion service (or add to `docker-compose.yml`)

### Phase 2: Behavior Evaluation Pipeline

**Effort:** 3-5 days | **Impact:** High

```
┌──────────────────────────────────────────────────────────┐
│                   Evaluation Pipeline                     │
│                                                           │
│  ┌──────────────┐    ┌───────────────┐    ┌───────────┐ │
│  │ fact_token_  │───▶│ Phoenix       │───▶│ Eval      │ │
│  │ savings      │    │ Datasets      │    │ Results   │ │
│  │ (TimescaleDB)│    │ (golden sets) │    │ (scored)  │ │
│  └──────────────┘    └───────────────┘    └───────────┘ │
│                                                           │
│  Eval Templates:                                          │
│  • relevance    — Is the output relevant to the query?    │
│  • correctness  — Does the output follow the behaviors?   │
│  • hallucination — Is the output factually grounded?      │
│  • token_efficiency — Did behaviors reduce tokens?        │
│  • citation_integrity — Are cited behaviors real?         │
└──────────────────────────────────────────────────────────┘
```

**Implementation:**
1. Export BCI runs from `fact_token_savings` / `fact_behavior_usage` to Phoenix Datasets
2. Define custom eval templates for behavior-specific quality dimensions
3. Schedule nightly eval runs via TraceAnalysisService integration
4. Surface eval scores in MetricsService dashboards

### Phase 3: Raze → Phoenix Sink

**Effort:** 1-2 days | **Impact:** Medium

```python
# packages/raze/src/raze/sinks/phoenix_sink.py
class PhoenixSink(RazeSink):
    """Forward Amprealize telemetry to Arize Phoenix as dataset entries."""

    def __init__(self, phoenix_url: str = "http://localhost:6006"):
        self.client = px.Client(endpoint=phoenix_url)

    async def write(self, event: TelemetryEvent):
        # Map Raze events to Phoenix spans/dataset entries
        ...

    async def write_batch(self, events: list[TelemetryEvent]):
        # Batch upload for efficiency
        ...
```

### Phase 4: Production Monitoring (Arize Cloud)

**Effort:** 1-2 weeks | **Impact:** High (enterprise customers)

- Kafka consumer that forwards `telemetry.events` topic to Arize Cloud
- Drift monitors on eval scores, token savings, retrieval accuracy
- Automated alerts when behavior quality degrades
- Enterprise compliance dashboards with 90-day retention

---

## Feature Ideas

### Near-Term (integrate existing Arize capabilities)

| # | Feature | Description | Persona | Effort |
|---|---------|-------------|---------|--------|
| 1 | **BCI Trace Explorer** | Phoenix UI embedded or linked from Amprealize web console — click a run to see full LLM trace waterfall | Builder, Measurer | 2-3 days |
| 2 | **Behavior A/B Testing** | Use Phoenix Experiments to compare behavior variants; expose "Test this behavior" button in behavior editor | Measurer | 3-5 days |
| 3 | **Retrieval Debugger** | Phoenix retrieval analysis showing embedding distances, retrieved vs. expected behaviors per query | Builder | 2-3 days |
| 4 | **Hallucination Guard** | Phoenix eval as a quality gate — flag or block BCI outputs with hallucination score < threshold | Auditor | 3-5 days |
| 5 | **Nightly Eval Report** | Scheduled Phoenix eval runs; results posted to Slack / emailed to PMs | Measurer, Auditor | 2-3 days |

### Medium-Term (build on top of Arize foundation)

| # | Feature | Description | Persona | Effort |
|---|---------|-------------|---------|--------|
| 6 | **Behavior Health Score** | Composite score (eval quality + token savings + retrieval frequency) powered by Phoenix evals, surfaced in behavior list | Measurer | 1-2 weeks |
| 7 | **Auto-Deprecation** | When a behavior's eval scores degrade below threshold for 7+ days, auto-propose deprecation via Metacognitive Strategist role | Measurer, Auditor | 1-2 weeks |
| 8 | **Prompt Playground in VS Code** | Phoenix prompt playground accessed from the Amprealize VS Code extension — test behavior variants without leaving the IDE | Builder | 2-3 weeks |
| 9 | **Citation Map** | Visualization showing which behaviors influenced which parts of an output, powered by Phoenix spans | Auditor | 2-3 weeks |
| 10 | **Compliance Evidence Pack** | One-click export from Phoenix: eval scores + traces + behavior citations for a time period, formatted for SOC2/ISO audit | Auditor | 1-2 weeks |

### Long-Term (strategic differentiation)

| # | Feature | Description | Persona | Effort |
|---|---------|-------------|---------|--------|
| 11 | **Behavior Auto-Tuner** | Use Phoenix eval feedback loops to automatically refine behavior instructions — ReflectionService proposes, Phoenix evals validate, auto-approve if quality improves | All | 4-6 weeks |
| 12 | **Multi-Tenant Observability** | Arize Cloud workspaces per customer org — each sees only their traces, evals, and behavior performance | Measurer, Auditor | 4-6 weeks |
| 13 | **Fine-Tuning Data Curator** | Use Phoenix eval scores to select high-quality BCI traces as fine-tuning data for BC-SFT (behavior-conditioned supervised fine-tuning) | Builder | 3-4 weeks |

---

## Success Metrics — What to Focus On

### Primary KPIs (PM Dashboard)

| Metric | Current (Raze-only) | Target (with Arize) | How Arize Enables |
|---|---|---|---|
| **Mean Time to Debug (MTTD)** | ~15 min (grep logs, run SQL) | < 2 min | Phoenix trace UI — click to inspect any LLM call |
| **Behavior Quality Score** | Proxy only (token savings %) | Direct eval score (0-1) | Phoenix LLM-as-judge evals on every BCI output |
| **Retrieval Accuracy** | 90% target, measured manually | 90%+ measured continuously | Phoenix retrieval evals — automated precision@K tracking |
| **Behavior Regression Rate** | Unknown (no systematic testing) | < 5% per release | Phoenix dataset + eval gate in CI/CD |
| **Token Savings Uplift from Experiments** | None (no A/B testing) | +5-10% per quarter | Phoenix Experiments — data-driven behavior optimization |

### Secondary KPIs (Adoption & Engagement)

| Metric | Target | Measurement |
|---|---|---|
| **Phoenix MAU (engineers)** | 80% of eng team uses Phoenix weekly | Phoenix server access logs |
| **Eval Coverage** | 100% of BCI calls have at least 1 eval dimension scored | `eval_results` table row count / `fact_token_savings` row count |
| **Experiment Velocity** | 2+ behavior experiments per sprint | Phoenix experiment count per 2-week period |
| **Alert Response Time** | < 4 hours from drift alert to investigation | Time from Arize Cloud alert to first Phoenix trace view |
| **Compliance Audit Time** | 50% reduction in evidence gathering | Hours spent per audit before vs. after |

### North Star Metric

> **Behavior-Conditioned Output Quality (BCOQ):** The average Phoenix eval score (relevance + correctness + grounding) across all BCI outputs, tracked weekly.

This is the single metric that proves the entire BCI pipeline is working. Token savings are necessary but not sufficient — an output that saves 50% of tokens but is wrong is worthless. BCOQ measures the thing that actually matters.

**Target trajectory:**
- Month 1: Establish baseline (instrument + eval existing outputs)
- Month 2: 0.75+ BCOQ (fix worst-performing behaviors identified by evals)
- Month 3: 0.85+ BCOQ (A/B test behavior improvements, auto-deprecate poor performers)
- Month 6: 0.90+ BCOQ (fine-tuning data curated from high-quality traces)

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Eval quality depends on judge LLM** | Medium | High | Use GPT-4o as judge; validate with human-labeled golden set (100 examples) |
| **Phoenix adds latency to LLM calls** | Low | Medium | OpenInference instrumentation is async — traces are buffered, not blocking |
| **Team doesn't adopt Phoenix UI** | Medium | Medium | Embed Phoenix link in Amprealize web console; make it the default debug path |
| **Arize Cloud costs scale unpredictably** | Medium | Low | Start with Phoenix OSS; only move high-value production traces to Cloud |
| **Too many eval dimensions overwhelm PMs** | Low | Medium | Start with 1 composite BCOQ score; drill-down available on demand |
| **Stale golden datasets** | Medium | Medium | Schedule quarterly dataset refresh; TraceAnalysisService proposes new examples |

---

## Rollout Plan

| Phase | Timeline | Deliverable | Success Criteria |
|---|---|---|---|
| **0. Spike** | Week 1 | Run Phoenix locally against Amprealize dev, instrument 1 LLM provider | Can view traces in Phoenix UI |
| **1. Instrument** | Weeks 2-3 | All LLM providers instrumented, BCI attributes enriched | 100% of LLM calls appear in Phoenix with run_id + behavior_ids |
| **2. Evaluate** | Weeks 3-5 | Eval pipeline running nightly, BCOQ baseline established | Eval scores for last 7 days visible in Phoenix |
| **3. Experiment** | Weeks 5-8 | Behavior A/B testing workflow, first 3 experiments completed | At least 1 behavior improved via experiment |
| **4. Production** | Weeks 8-12 | Arize Cloud for production monitoring, drift alerts configured | < 4 hour response time on quality degradation alerts |
| **5. Enterprise** | Weeks 12-16 | Multi-tenant observability, compliance evidence packs | First enterprise customer exports audit evidence from Phoenix |

---

## Appendix: Technical Quick-Start

### Minimal Integration (30 minutes)

```bash
# 1. Install
pip install arize-phoenix openinference-instrumentation-openai

# 2. Start Phoenix
phoenix serve  # Runs at http://localhost:6006

# 3. Instrument (add to amprealize startup)
from openinference.instrumentation.openai import OpenAIInstrumentor
from phoenix.otel import register

tracer_provider = register(
    project_name="amprealize-bci",
    endpoint="http://localhost:6006/v1/traces",
)
OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)

# 4. Run Amprealize normally — traces appear in Phoenix automatically
```

### Enriching Spans with Amprealize Context

```python
from opentelemetry import trace

tracer = trace.get_tracer("amprealize.bci")

with tracer.start_as_current_span("bci_inference") as span:
    span.set_attribute("amprealize.run_id", run_id)
    span.set_attribute("amprealize.behavior_ids", json.dumps(behavior_ids))
    span.set_attribute("amprealize.token_savings_pct", savings_pct)
    span.set_attribute("amprealize.actor_role", "Student")
    span.set_attribute("amprealize.actor_surface", "MCP")

    response = llm_provider.complete(prompt_with_behaviors)
```

### Running Behavior Evals

```python
from phoenix.evals import llm_classify, OpenAIModel

# Load BCI outputs from TimescaleDB
bci_outputs = pd.read_sql("SELECT * FROM fact_token_savings WHERE ...", conn)

# Run relevance eval
results = llm_classify(
    dataframe=bci_outputs,
    model=OpenAIModel(model="gpt-4o"),
    template="Given the user query: {query}\nAnd the behavior-conditioned response: {response}\nIs this response relevant and helpful? Answer: relevant or irrelevant",
    rails=["relevant", "irrelevant"],
)
```

---

_Last updated: 2026-03-11_
