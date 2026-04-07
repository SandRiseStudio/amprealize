# Amprealize: Installation, Onboarding & Repository Optimization Plan

> **Version**: 3.1
>
> **Positioning**: *The behavior engine for AI agents* — define behaviors, execute agents, capture traces, refine behaviors.
>
> **Goal**: Ship an open-core developer tool that makes behavior-driven AI agents accessible to individual developers (OSS, Apache 2.0), then expand to teams and organizations via a 5-layer commercial model: **OSS → Starter (free) → Pro ($29/mo) → Team ($99/seat/mo) → Enterprise (custom)**. Self-hosting is available at all commercial tiers. Simultaneously bring the repository to open-source-ready standards with a clean OSS / enterprise split.
>
> **Primary Audience**: Developers and AI engineers building with AI agents — the adoption funnel starts here.
> **Expansion Audience**: Project managers, business analysts, and enterprise architects who benefit from the core behavior-agent loop via supplementary tools (boards, compliance, reporting).
>
> **Reference Model**: Arize AI (Phoenix OSS + AX commercial) — OSS is a genuinely useful standalone product, commercial adds cloud-native features, self-hosting at all tiers.
>
> **License**: Apache 2.0 (OSS core) + Proprietary (enterprise features)
> **Repository Model**: Split — `SandRiseStudio/amprealize` (OSS) + `SandRiseStudio/amprealize-enterprise` (proprietary)
>
> **Tiers**: OSS (free, self-hosted) → Starter (free commercial) → Pro ($29/mo) → Team ($99/seat/mo) → Enterprise (custom)
> **Deployment Topologies**: Local (SQLite), Cloud SaaS (`breakeramp.ai`), Self-Hosted (all commercial tiers), Hybrid (Team+)
> **Platforms**: macOS, Windows, Linux, Web-only (zero install)
>
> **Date**: 2026-03-13
> **Supersedes**: v3.0 (collaboration-gated billing model)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Product Strategy & Open-Core Model](#2-product-strategy--open-core-model)
3. [User Personas & Entry Points](#3-user-personas--entry-points)
4. [Deployment Topologies](#4-deployment-topologies)
5. [Current State Assessment](#5-current-state-assessment)
6. [Track A — Security & Repository Optimization](#6-track-a--security--repository-optimization)
7. [Track B — Cloud SaaS (breakeramp.ai)](#7-track-b--cloud-saas-breakerampai)
8. [Track C — Web Console Onboarding](#8-track-c--web-console-onboarding)
9. [Track D — CLI & Local Installation](#9-track-d--cli--local-installation)
10. [Track E — Desktop Application](#10-track-e--desktop-application)
11. [Track F — IDE Integration](#11-track-f--ide-integration)
12. [Decisions & Trade-offs](#12-decisions--trade-offs)
13. [Verification Scenarios](#13-verification-scenarios)
14. [Implementation Schedule](#14-implementation-schedule)
15. [Further Considerations](#15-further-considerations)

---

## 1. Executive Summary

### Core Value Loop

Amprealize's primary value proposition is **the behavior engine for AI agents**. The core loop is:

```
Define Behaviors → Execute Agents → Capture Traces → Refine Behaviors → (repeat)
```

Behaviors are reusable procedural strategies ("how-to" recipes) that tell AI agents how to approach tasks. Agents execute against those behaviors, producing traces. Traces are reflected on to improve existing behaviors and discover new ones. This flywheel is the product — everything else supports it.

### Open-Core Model

Amprealize ships as an **open-core** product (Apache 2.0):

- **OSS** (`SandRiseStudio/amprealize`): Behavior engine, agent execution, MCP server (64+ tools), CLI, SQLite storage, single-user — everything a developer needs to run the core loop locally.
- **Enterprise** (`SandRiseStudio/amprealize-enterprise`): Cloud SaaS (`breakeramp.ai`), team collaboration, behavior analytics, compliance, multi-org, SSO, PostgreSQL, billing — everything teams and organizations need.

### Adoption Funnel

The plan sequences work around a developer-first adoption funnel:

| Stage | Who | Entry Point | Tier | What They Get |
|-------|-----|-------------|------|---------------|
| **1. Individual (OSS)** | Solo dev / AI engineer | `pip install amprealize` or VS Code Extension | OSS (free) | Core loop: behaviors + agents + MCP + CLI + SQLite — no account needed |
| **2. Individual (Commercial)** | Solo dev wanting cloud/persistence | `breakeramp.ai` sign-up or self-hosted license | Starter (free) | Everything in OSS + managed PostgreSQL, web console, basic RBAC, 1 board |
| **3. Power User** | Individual or small startup | Upgrade from Starter | Pro ($29/mo) | Audit logs, behavior versioning, cost analytics, webhooks, email support |
| **4. Team** | Dev team / tech lead | Team upgrade or `breakeramp.ai` | Team ($99/seat/mo) | Real-time collab, SSO, BCI pipeline, compliance suite, priority support |
| **5. Organization** | Engineering org / management | Enterprise sales | Enterprise (custom) | Dedicated support, SLA, SOC2/HIPAA, multi-region, HA, air-gapped |
| **6. Cross-Functional** | PM, analyst, legal, marketing | Web console + Desktop App | Any tier | Supplementary tools: boards, reporting, domain workflows |

### Supplementary Tools

Project management (boards, work items), compliance tracking, financial modeling, and reporting are **supplementary domain applications** that expand Amprealize's reach beyond developers. They are enabled by — not the focus of — the core behavior-agent loop.

### Entry Points

| Entry Point | Target User | Install Effort |
|-------------|-------------|---------------|
| **CLI** (`pip` / `pipx` / `brew`) | Developers, AI engineers | One command |
| **VS Code Extension** | Developers already in VS Code | One-click from Marketplace |
| **breakeramp.ai** (Cloud SaaS) | Teams, non-technical users | Zero — just sign up |
| **Desktop App** (.dmg / .exe / .AppImage) | Non-technical users | Download + double-click |
| **Docker Compose** | DevOps / self-hosted teams | `docker compose up` |

### Implementation Tracks

The plan is organized into **six tracks**, sequenced around the adoption funnel:

- **Track A** — Security & Repository: OSS / enterprise repo split, Apache 2.0 license, README, governance, credential rotation
- **Track B** — Cloud SaaS: Deploy to `breakeramp.ai`, landing page, billing tiers, MCP proxy
- **Track C** — Web Console Onboarding: Welcome wizard, role-based setup, contextual help, glossary
- **Track D** — CLI & Local: Config loader, SQLite adapter, `amprealize init/open/doctor/infra/mcp-server`, PyPI/brew/npm
- **Track E** — Desktop Application: Electron wrapper around web console + bundled FastAPI + SQLite
- **Track F** — IDE Integration: Getting Started panel, MCP auto-config, VS Code Marketplace publish

---

---

## 2. Product Strategy & Open-Core Model

### 2.1 The Behavior-Agent Flywheel

Amprealize's competitive moat is the **behavior-agent flywheel** — a self-reinforcing loop where behaviors prescribe how agents work, agents produce execution traces, and traces refine behaviors:

```
┌─────────────────────────────────────────────────────────┐
│                                                           │
│   ┌──────────┐    ┌──────────┐    ┌──────────────┐      │
│   │  DEFINE   │───►│ EXECUTE  │───►│   CAPTURE    │      │
│   │ Behaviors │    │  Agents  │    │   Traces     │      │
│   └─────▲────┘    └──────────┘    └──────┬───────┘      │
│         │                                 │              │
│         │         ┌──────────┐           │              │
│         └─────────│  REFINE  │◄──────────┘              │
│                   │ Behaviors│                           │
│                   └──────────┘                           │
│                                                           │
│   Each cycle: better behaviors → smarter agents → richer │
│   traces → even better behaviors                          │
└─────────────────────────────────────────────────────────┘
```

This flywheel is the product. Behaviors are not standalone — they are only improved and grown through Amprealize's agent management and execution capabilities. Without the execution loop, behaviors are static documents. Without behaviors, agents lack procedural guidance.

### 2.2 Open-Core Boundary & 5-Layer Tier Architecture

Amprealize follows an **open-core model** (like Grafana, GitLab, Sentry) with a 5-layer tier architecture inspired by **Arize AI's Phoenix/AX model**:

- **OSS** = genuinely useful standalone product (like Phoenix). No account needed. Full behavior engine.
- **Commercial** = superset of OSS with cloud-native features, collaboration, governance. Free Starter through Enterprise.
- **Self-hosting** = available at ALL commercial tiers (unlike Arize where self-hosted = Enterprise only).
- **Differentiation** = both **capacity limits** AND **feature gates** (not just one axis).

**Repository structure:**

| Repository | License | Contents |
|------------|---------|----------|
| `SandRiseStudio/amprealize` | Apache 2.0 | Behavior engine, agent runner, MCP server (220+ tools), CLI, SQLite adapter, config loader, VS Code Extension, local web console — everything a developer needs |
| `SandRiseStudio/amprealize-enterprise` | Proprietary | Cloud SaaS (`breakeramp.ai`), multi-tenancy (PostgreSQL RLS), billing (Stripe), SSO/OAuth, compliance service, behavior analytics, real-time collaboration, BCI pipeline, license key validation |

**5-Layer Capability Matrix:**

| Capability | OSS | Starter (Free) | Pro ($29/mo) | Team ($99/seat) | Enterprise |
|-----------|:-:|:-:|:-:|:-:|:-:|
| Behavior engine (define, retrieve, search) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Agent execution loop (run, trace, reflect) | ✅ | ✅ | ✅ | ✅ | ✅ |
| MCP server (220+ tools, stdio) | ✅ | ✅ | ✅ | ✅ | ✅ |
| CLI (`amprealize init/doctor/open/mcp-server`) | ✅ | ✅ | ✅ | ✅ | ✅ |
| VS Code Extension (full) | ✅ | ✅ | ✅ | ✅ | ✅ |
| SQLite storage | ✅ | ✅ | ✅ | ✅ | ✅ |
| Config loader (`~/.amprealize/config.yaml`) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Web console (local, single-user) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Raze structured logging (local sinks) | ✅ | ✅ | ✅ | ✅ | ✅ |
| BreakerAmp local infra | ✅ | ✅ | ✅ | ✅ | ✅ |
| GEP (Generalized Execution Pipeline) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Agent Registry | ✅ | ✅ | ✅ | ✅ | ✅ |
| Managed PostgreSQL | — | ✅ | ✅ | ✅ | ✅ |
| Cloud SaaS hosting (`breakeramp.ai`) | — | ✅ | ✅ | ✅ | ✅ |
| Cloud MCP endpoint | — | ✅ | ✅ | ✅ | ✅ |
| Basic RBAC (owner + member) | — | ✅ | ✅ | ✅ | ✅ |
| Boards & work items | — | 1 board | 5 boards | Unlimited | Unlimited |
| Audit logs | — | — | ✅ | ✅ | ✅ |
| Behavior versioning with diffs | — | — | ✅ | ✅ | ✅ |
| Cost analytics dashboards | — | — | ✅ | ✅ | ✅ |
| Webhook integrations | — | — | ✅ | ✅ | ✅ |
| Behavior accuracy tracking | — | — | ✅ | ✅ | ✅ |
| Real-time collaboration (WebSocket) | — | — | — | ✅ | ✅ |
| SSO / SAML / OAuth enforcement | — | — | — | ✅ | ✅ |
| Full compliance suite | — | — | — | ✅ | ✅ |
| BCI pipeline (automated behavior extraction) | — | — | — | ✅ | ✅ |
| Custom branding | — | — | — | ✅ | ✅ |
| Role-based RBAC (granular) | — | — | — | ✅ | ✅ |
| Hybrid deployment (cloud + self-hosted) | — | — | — | ✅ | ✅ |
| Dedicated support + SLA | — | — | — | — | ✅ |
| SOC2 / HIPAA compliance | — | — | — | — | ✅ |
| Multi-region / data residency | — | — | — | — | ✅ |
| High-availability (HA) deployment | — | — | — | — | ✅ |
| Audit log export (SIEM integration) | — | — | — | — | ✅ |
| Air-gapped deployment | — | — | — | — | ✅ |

**Capacity Limits by Tier:**

| Limit | OSS | Starter | Pro | Team | Enterprise |
|-------|:---:|:-------:|:---:|:----:|:----------:|
| Projects | Unlimited | 3 | 10 | Unlimited | Unlimited |
| Members | Single-user | 5 | 15 | 50 | Unlimited |
| Agents | Unlimited | 1 | 5 | 10 | Unlimited |
| Tokens/mo | Unlimited | 100K | 500K | 2M | Custom |
| API calls/mo | N/A | 10K | 50K | 200K | Custom |
| Storage | Local disk | 1 GB | 10 GB | 100 GB | Custom |
| Retention | Local | 7 days | 30 days | 90 days | Custom |
| Boards | N/A | 1 | 5 | Unlimited | Unlimited |

**Deployment Matrix:**

| | OSS | Starter | Pro | Team | Enterprise |
|-|:---:|:-------:|:---:|:----:|:----------:|
| Cloud SaaS | N/A | ✅ | ✅ | ✅ | ✅ |
| Self-Hosted (single node) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Self-Hosted (HA) | — | — | — | — | ✅ |
| Hybrid (cloud + self-hosted) | — | — | — | ✅ | ✅ |
| Air-gapped | ✅ | — | — | — | ✅ |

> **Key design principle**: OSS is a real, standalone product — not a crippled trial. Commercial tiers add cloud-native features that *don't exist* in OSS (managed persistence, multi-user RBAC, cloud MCP endpoints, compliance). Self-hosting requires a license key for commercial tiers but is available at every level.

### 2.3 Adoption Funnel

The implementation schedule (Section 14) sequences work to match how adoption actually happens:

```
Week 1-2: Developer On-Ramp       → individual dev tries `pip install amprealize` (OSS)
Week 2-3: DX Polish               → dev gets hooked, tells team
Week 3-4: Cloud + Commercial       → dev signs up for Starter (free), upgrades to Pro
Week 4-5: Team + Enterprise        → team signs up ($99/seat), org evaluates Enterprise
Week 5+:  Platform + Distribution → Homebrew, npm, desktop app, marketplace
```

### 2.4 Supplementary Domain Applications

Project management, compliance, finance, legal, and marketing tools are **supplementary** — they demonstrate the breadth of the behavior-agent loop but are not the primary value proposition. They ship in the enterprise tier and are positioned as expansion use cases after developer adoption.

### 2.5 Competitive Positioning

| | Amprealize | Arize AI (Phoenix/AX) | LangSmith | Braintrust |
|---|---|---|---|---|
| **Core primitive** | Behaviors (proactive) | Traces (reactive) | Traces (reactive) | Evals (reactive) |
| **Flywheel** | Behaviors ↔ Agents | Observe → Debug | Log → Evaluate | Test → Improve |
| **OSS component** | Behavior engine + agent runner (full product) | Phoenix tracing library (full product) | — | — |
| **Commercial model** | OSS → Starter (free) → Pro → Team → Enterprise | OSS → AX Free → AX Pro → AX Enterprise | Cloud SaaS only | Cloud SaaS only |
| **Self-hosted** | ✅ All tiers | ✅ Enterprise only | ❌ | ❌ |
| **MCP-native** | ✅ 220+ tools | ❌ | ❌ | ❌ |
| **Multi-surface** | CLI + IDE + Web + Desktop | Web + SDK | Web + SDK | Web + SDK |
| **Non-developer users** | ✅ via supplementary tools | ❌ | ❌ | ❌ |

---

## 3. User Personas & Entry Points

### 3.1 Personas

| Persona | Technical Level | Adoption Stage | Primary Use Case | Entry Point |
|---------|----------------|----------------|-----------------|-------------|
| **Solo Developer** | Comfortable with CLI/IDE | Stage 1: Individual | Full-stack behavior-driven development, MCP tools in Copilot | CLI (`amprealize init`) or VS Code Extension |
| **DevOps Engineer** | Advanced infrastructure | Stage 1–2: Individual/Team | Self-hosted deployment, multi-db setup, CI/CD integration | Docker Compose or CLI with Postgres mode |
| **Enterprise Architect** | Advanced, team-scale | Stage 3: Organization | Multi-org orchestration, audit trails, SSO, billing | Hybrid: Cloud SaaS control plane + self-hosted infra |
| **Non-Technical PM** | No terminal/IDE experience | Stage 4: Cross-functional | Behavior-guided project management, team onboarding, knowledge capture | Cloud SaaS (`breakeramp.ai`) or Desktop App |
| **Business Analyst** | Spreadsheets & web apps | Stage 4: Cross-functional | AI agent orchestration, compliance tracking, reporting | Cloud SaaS or Desktop App |

### 3.2 Entry Point Matrix

| | Non-Technical PM | Business Analyst | Solo Developer | DevOps Engineer | Enterprise Architect |
|---|:---:|:---:|:---:|:---:|:---:|
| **breakeramp.ai** (Cloud) | ✅ Primary | ✅ Primary | ✅ Quick try | ❌ | ✅ Control plane |
| **Desktop App** | ✅ Alternative | ✅ Alternative | ❌ | ❌ | ❌ |
| **VS Code Extension** | ❌ | ❌ | ✅ Primary | ✅ Use | ✅ Use |
| **CLI** | ❌ | ❌ | ✅ Primary | ✅ Primary | ✅ Use |
| **Docker Compose** | ❌ | ❌ | ❌ | ✅ Primary | ✅ Build block |

### 3.3 Supplementary Domain Applications

The following use cases are **enabled by the core behavior-agent loop** but represent expansion beyond the primary developer audience. They ship in the enterprise tier and are positioned as Stage 4 (cross-functional) adoption:

| Domain | Use Case | Key Features |
|--------|----------|-------------|
| **Project Management** | Behavior-guided task orchestration, knowledge capture, team onboarding | Boards, work items, behaviors, agent orchestration |
| **Finance** | Budget tracking, ROI modeling, financial compliance | Compliance service, audit trails, reporting |
| **Legal** | Contract review workflows, compliance tracking, document governance | Behaviors, compliance, audit logs |
| **Marketing** | Campaign planning, messaging frameworks, launch checklists | Boards, behaviors, agent orchestration |
| **HR** | Team onboarding sequences, knowledge base management, process automation | Behaviors, knowledge capture, agent workflows |

---

## 4. Deployment Topologies

### 4.1 Cloud SaaS — `breakeramp.ai`

**Zero-install.** User signs up at `breakeramp.ai`, picks a plan, and starts working.

```
┌──────────────────────────────────────────────────────┐
│                    breakeramp.ai                      │
│  ┌────────────┐  ┌────────────┐  ┌────────────────┐ │
│  │ Web Console │  │  REST API  │  │   MCP Proxy    │ │
│  │ (React 19) │  │  (FastAPI) │  │ (WebSocket/SSE)│ │
│  └──────┬─────┘  └──────┬─────┘  └───────┬────────┘ │
│         │               │                 │          │
│  ┌──────┴───────────────┴─────────────────┴────────┐ │
│  │          PostgreSQL (RLS multi-tenancy)          │ │
│  │  Telemetry (TimescaleDB) │ Behavior (pgvector)  │ │
│  │  Workflow (standard)     │ Redis (caching)      │ │
│  └─────────────────────────────────────────────────┘ │
│  ┌─────────────┐  ┌────────────┐  ┌──────────────┐  │
│  │  Stripe     │  │  OAuth     │  │  CDN/Edge    │  │
│  │  Billing    │  │  (GH/Goog) │  │  (Static)    │  │
│  └─────────────┘  └────────────┘  └──────────────┘  │
└──────────────────────────────────────────────────────┘
```

**What's already built:**
- ✅ React 19 web console (`web-console/`) with 14 routes, full CRUD
- ✅ FastAPI REST API (`amprealize/api.py`) with 20+ services, ServiceContainer pattern
- ✅ Multi-tenancy with PostgreSQL RLS (`amprealize/multi_tenant/`)
- ✅ Device Flow + OAuth authentication (GitHub, Google)
- ✅ Stripe billing integration (`amprealize/billing/`)
- ✅ Real-time collaboration (`@amprealize/collab-client`)

**What needs to be built:**
- ❌ Cloud infrastructure provisioning (managed Postgres, container orchestration)
- ❌ Landing page at `breakeramp.ai` (marketing + signup)
- ❌ Web console Dockerfile / deployment pipeline
- ❌ MCP WebSocket proxy for IDE ↔ cloud server
- ❌ Billing tier configuration and enforcement
- ❌ DNS + TLS + CDN setup

### 4.2 Self-Hosted

**Full local control.** Everything runs on the user's machine or private infrastructure. Available at **all tiers** — OSS runs without an account; commercial tiers (Starter through Enterprise) require a license key that unlocks the corresponding feature set.

```
┌────────────────────────── User's Machine ─────────────────────────┐
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────────┐   │
│  │   Desktop   │  │    CLI     │  │   VS Code + Extension    │   │
│  │   App       │  │            │  │   (MCP → stdio)          │   │
│  └──────┬─────┘  └──────┬─────┘  └───────────┬──────────────┘   │
│         │               │                     │                   │
│  ┌──────┴───────────────┴─────────────────────┴──────────────┐   │
│  │              FastAPI (localhost:8000)                       │   │
│  │              Web Console (localhost:5173 or embedded)       │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                             │                                     │
│  ┌──────────────────────────┴────────────────────────────────┐   │
│  │     Storage: SQLite (~/.amprealize/data/) OR                  │   │
│  │     PostgreSQL (Docker via BreakerAmp)                     │   │
│  └───────────────────────────────────────────────────────────┘   │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │     License: None (OSS) or License Key (commercial)        │   │
│  └───────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

**Two sub-modes:**
- **Lite** (SQLite): `amprealize init --storage sqlite` — zero containers, single file DB
- **Full** (Postgres): `amprealize init --storage postgres` — provisions via BreakerAmp

**License key activation (commercial self-hosted):**
- `amprealize license activate <key>` — validates against `breakeramp.ai/v1/licenses`
- Offline activation via signed JWT for air-gapped deployments (Enterprise only)
- License key determines tier (Starter/Pro/Team/Enterprise) and enforces capacity limits locally

### 4.3 Hybrid (Team+ Tiers)

**Cloud control plane + self-hosted compute.** Team and Enterprise customers manage their own databases and infrastructure but use `breakeramp.ai` for web console, billing, team management, and SSO.

```
┌──────── breakeramp.ai ────────┐     ┌──── Private Infra ────┐
│  Web Console  │  Auth/Billing │◄───►│  FastAPI (private)     │
│  Team Mgmt    │  SSO          │     │  PostgreSQL (private)  │
│  MCP Proxy    │               │     │  Agents (private)      │
└───────────────┘───────────────┘     └────────────────────────┘
```

**Tier availability:** Hybrid requires Team ($99/seat/mo) or Enterprise (custom). Starter and Pro tiers use either full cloud or full self-hosted.

---

## 5. Current State Assessment

### 5.1 What Already Exists (Leverageable)

| Component | Location | Status | Notes |
|-----------|----------|--------|-------|
| Web Console | `web-console/` | ✅ Production-ready | React 19, 14 routes, React Router 7, TanStack Query |
| REST API | `amprealize/api.py` | ✅ Production-ready | 20+ services, ServiceContainer, CORS, WebSocket |
| Multi-tenancy | `amprealize/multi_tenant/` | ✅ Production-ready | PostgreSQL RLS, organizations, org_members |
| Authentication | `amprealize/auth/` | ✅ Production-ready | Device Flow (RFC 8628), OAuth (GitHub, Google), Client Credentials |
| Billing | `amprealize/billing/` | ✅ Production-ready | Stripe subscriptions per org |
| MCP Server | `amprealize/mcp_server.py` | ✅ Production-ready | 64+ tools, MCPServiceRegistry, stdio |
| CLI | `amprealize/cli.py` | ✅ Production-ready | 45+ commands, Click-based |
| VS Code Extension | `extension/` | ✅ Production-ready | 8 WebView panels, 11 tree providers, 3 clients |
| BreakerAmp | `packages/breakeramp/` | ✅ Production-ready | Blueprint-driven infra provisioning |
| Raze Logging | `packages/raze/` | ✅ Production-ready | Structured logging, multiple sinks |
| Collab Client | `packages/collab-client/` | ✅ Production-ready | Real-time collaboration |
| Database Layer | `amprealize/storage/` | ✅ Production-ready | PostgresPool, 3 DBs (telemetry, behavior, workflow) |

### 5.2 What's Missing

| Gap | Severity | Required For |
|-----|----------|-------------|
| **Cloud hosting** — no deployment of web console or API | 🔴 Critical | Track B (Cloud SaaS) |
| **Onboarding flow** — login → Dashboard with no guidance | 🔴 Critical | Track C (all non-developer users) |
| **Desktop app** — no Electron/Tauri packaging | 🔴 Critical | Track E (non-technical users) |
| **Root README.md** — GitHub repo shows nothing | 🔴 Critical | Track A (repository) |
| **`amprealize init` command** — no guided setup | 🔴 Critical | Track D (developers) |
| **SQLite adapter** — Postgres required for any usage | 🟡 High | Track D (lightweight local mode) |
| **Config loader** — no `~/.amprealize/config.yaml` | 🟡 High | Track D (portable config) |
| **Marketplace publish** — extension not on VS Code Marketplace | 🟡 High | Track F (discoverability) |
| **Landing page** — no `breakeramp.ai` marketing site | 🟡 High | Track B (cloud conversion) |
| **Leaked credentials** — Google OAuth secret in repo | 🔴 Critical | Track A (security) |
| **Root LICENSE** — no license file at root | 🔴 Critical | Track A (legal) |
| **Governance files** — no CONTRIBUTING, SECURITY, CODE_OF_CONDUCT | 🟡 High | Track A (open source readiness) |
| **Root declutter** — ~119 items at repo root | 🟡 Medium | Track A (navigation) |
| **PyPI publication** — can't `pip install amprealize` | 🟡 Medium | Track D (distribution) |

### 5.3 Installation Friction Points (from v1 audit)

| Friction | Severity | Detail |
|----------|----------|--------|
| No root `README.md` | 🔴 Critical | GitHub repo page shows nothing to new visitors |
| No `amprealize init` command | 🔴 Critical | Users must piece together setup from 7+ docs |
| Hardcoded absolute paths | 🔴 Critical | `.vscode/mcp.json` uses `/Users/nick/amprealize/.venv/bin/python` |
| 15 per-service DSN env vars | 🟡 High | MCP config requires setting each DSN individually |
| Postgres required for any usage | 🟡 High | No lightweight fallback; must Docker Compose first |
| No PyPI publishing | 🟡 High | Can't `pip install amprealize` — must clone the repo |
| Scattered documentation | 🟡 High | Setup steps across 7+ files |
| No `amprealize doctor` | 🟢 Medium | No way to diagnose misconfiguration |
| MCP requires raw Python path | 🟢 Medium | `python -m amprealize.mcp_server` instead of `amprealize mcp-server` |

### 5.4 What's Already Good

- ✅ `.gitignore` is comprehensive (Python, Node, secrets, OS files)
- ✅ CI/CD pipeline exists (`.github/workflows/ci.yml` with security scanning)
- ✅ `.env.example` is thorough (40+ vars with comments)
- ✅ `amprealize/__main__.py` exists — `python -m amprealize` works
- ✅ Package structure is clean and modular
- ✅ DSN resolution has layered fallback (`resolve_postgres_dsn()`)
- ✅ Some services already have in-memory stubs (`ActionService`, `RunService`)
- ✅ BreakerAmp blueprints exist for local dev (`local-test-suite.yaml`)
- ✅ Copilot instructions at `.github/copilot-instructions.md`
- ✅ React web console is feature-complete for CRUD operations
- ✅ Multi-tenancy with RLS is production-ready
- ✅ Stripe billing integration exists

---

## 6. Track A — Security & Repository Optimization

### A1. Rotate Leaked Credentials

**🚨 IMMEDIATE ACTION — Do first, before any other repo changes.**

**File:** `client_secret_915481675158-j501h5r1rcte89g5reubo9j6oful0q36.apps.googleusercontent.com.json`

Contains a Google OAuth `client_secret` in plaintext.

**Steps:**
1. Delete the file from disk
2. Scrub from git history (`git filter-repo --path '<file>' --invert-paths`)
3. Rotate credentials in Google Cloud Console (`amprealize-481520` project)
4. Store new credentials in a secrets manager (not files)
5. Update `.env.example` with placeholder references
6. Verify `.gitignore` blocks `client_secret*.json`
7. Run `scripts/scan_secrets.sh` to confirm clean

### A2. Create Root `README.md`

**Structure:**
```
# Amprealize — Behavior-Driven AI Workflow Platform

One-sentence description + badges (CI, PyPI, License, Platforms)

## Get Started in 30 Seconds
  → breakeramp.ai (zero install — just sign up)
  → Desktop App (.dmg / .exe / .AppImage download)
  → CLI: pipx install amprealize && amprealize init

## What is Amprealize?
  2-3 paragraphs covering: behavior-driven workflows, MCP server,
  multi-surface (web/CLI/IDE/desktop), applicable to dev + PM + finance + legal...

## Features
  Bullet list with screenshots/links

## Documentation
  Links to docs/ folder key files

## Contributing
  Link to CONTRIBUTING.md

## License
  Link to LICENSE
```

### A3. Create Root `LICENSE` (Apache 2.0)

**Decision: Apache 2.0** — selected for maximum enterprise adoption compatibility, patent grant protection, and community contribution friendliness.

| Action | Detail |
|--------|--------|
| Create `LICENSE` | Apache License 2.0 full text at repo root |
| Update `pyproject.toml` | `license = { text = "Apache-2.0" }` |
| Add header template | `scripts/license-header.txt` for automated source file headers |
| Enterprise repo | `amprealize-enterprise/` uses a separate proprietary license |

> **Note:** Apache 2.0 applies to the OSS repo (`SandRiseStudio/amprealize`). Enterprise-only code in `SandRiseStudio/amprealize-enterprise` remains proprietary. See Section 2.2 for the boundary definition.

### A4. Create Governance Files

| File | Location | Content |
|------|----------|---------|
| `CONTRIBUTING.md` | `.github/CONTRIBUTING.md` | Dev setup, PR process, commit conventions, behavior handbook reference |
| `CODE_OF_CONDUCT.md` | Root | Contributor Covenant or similar |
| `SECURITY.md` | Root | Vulnerability reporting process (email, NOT GitHub Issues) |
| `CODEOWNERS` | `.github/CODEOWNERS` | Map directories to reviewers |

### A5. Issue & PR Templates

```
.github/
├── ISSUE_TEMPLATE/
│   ├── config.yml            # Template chooser
│   ├── bug_report.yml        # Structured bug form
│   └── feature_request.yml   # Structured feature form
└── pull_request_template.md  # PR checklist (tests, docs, behaviors cited, no secrets)
```

### A6. Repository Split & Directory Cleanup

**Current:** Single monorepo with ~119 items at root, mixing OSS and enterprise code.
**Target:** Two repositories with clean separation.

#### OSS Repo: `SandRiseStudio/amprealize` (Apache 2.0)

```
amprealize/
├── LICENSE                    # Apache 2.0
├── README.md                  # PyPI-focused, badges, quick start
├── AGENTS.md                  # Behavior handbook
├── CLAUDE.md                  # Agent instructions
├── pyproject.toml             # license = "Apache-2.0"
├── .pre-commit-config.yaml
├── .env.example
├── amprealize/                   # Core Python package
│   ├── behaviors/             # Behavior engine
│   ├── agents/                # Agent runner
│   ├── mcp/                   # MCP server
│   ├── cli/                   # CLI commands
│   ├── config/                # Config loader
│   └── storage/               # SQLite adapter
├── packages/
│   ├── raze/                  # Structured logging
│   └── breakeramp/            # Local infra mgmt
├── extension/                 # VS Code extension
├── web-console/               # Single-user web UI
├── tests/
├── docs/
│   ├── contracts/             # Service contract specs
│   └── agents/                # Agent role docs
└── scripts/
```

#### Enterprise Repo: `SandRiseStudio/amprealize-enterprise` (Proprietary)

```
amprealize-enterprise/
├── LICENSE                    # Proprietary
├── README.md
├── amprealize_enterprise/        # Enterprise Python package
│   ├── billing/               # Stripe integration
│   ├── sso/                   # OAuth/SAML providers
│   ├── compliance/            # Compliance service
│   ├── analytics/             # Behavior analytics
│   ├── collaboration/         # Multi-user, teams
│   └── cloud/                 # Cloud SaaS adapters
├── infra/
│   ├── docker-compose.*.yml
│   ├── Dockerfile.*
│   ├── cloudbuild.*.yaml
│   └── environments.yaml
└── tests/
```

#### Migration Plan

| Step | Action | Notes |
|------|--------|-------|
| 1 | Create `amprealize-enterprise` repo | Private, proprietary license |
| 2 | Move enterprise-only code | billing/, sso/, compliance/, analytics/ |
| 3 | Move infra files | docker-compose.*, Dockerfile.*, cloudbuild.* |
| 4 | Move docs to `docs/` subdirs | contracts/, agents/ (stays in OSS) |
| 5 | Clean OSS root | Target ~20 items |
| 6 | Add `amprealize-enterprise` as optional dependency | `pip install amprealize[enterprise]` loads from private index |
| 7 | Update CI/CD | Separate pipelines per repo |

### A7. Dependency Management & Metadata

**Create `.github/dependabot.yml`** for pip, npm (extension + web-console), and GitHub Actions.

**Update `pyproject.toml`:**
```toml
[project.urls]
Documentation = "https://breakeramp.ai/docs"
Source = "https://github.com/SandRiseStudio/amprealize"
"Bug Tracker" = "https://github.com/SandRiseStudio/amprealize/issues"
Changelog = "https://github.com/SandRiseStudio/amprealize/blob/main/BUILD_TIMELINE.md"
```

---

## 7. Track B — Cloud SaaS (`breakeramp.ai`)

### B1. DNS & Domain Setup

**Domain:** `breakeramp.ai`

| Subdomain | Purpose | Target |
|-----------|---------|--------|
| `breakeramp.ai` | Marketing landing page + web console SPA | CDN / edge (Cloudflare Pages or Vercel) |
| `api.breakeramp.ai` | REST API (FastAPI) | Cloud Run / Fly.io / managed container |
| `mcp.breakeramp.ai` | MCP WebSocket proxy for IDE ↔ cloud | Cloud Run / Fly.io with WebSocket support |
| `docs.breakeramp.ai` | Documentation site | Static hosting |

### B2. Web Console Deployment

**Build:**
- Add Dockerfile for `web-console/`:
  ```dockerfile
  FROM node:22-slim AS build
  WORKDIR /app
  COPY web-console/ .
  RUN npm ci && npm run build

  FROM nginx:alpine
  COPY --from=build /app/dist /usr/share/nginx/html
  COPY nginx.conf /etc/nginx/conf.d/default.conf
  ```
- Set `VITE_API_BASE_URL=https://api.breakeramp.ai` at build time
- SPA routing: nginx config catches all routes → `index.html`

**Deploy options (evaluate):**
- **Cloudflare Pages**: Free tier, global CDN, automatic SSL, GitHub integration
- **Vercel**: Free tier, edge functions, preview deployments
- **Cloud Run**: If bundling with API in single container

### B3. API Deployment

**FastAPI (`amprealize/api.py`) containerization:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install -e ".[postgres,telemetry,semantic]"
COPY amprealize/ amprealize/
CMD ["uvicorn", "amprealize.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

**Managed database options:**
- **Neon** (Postgres): Free tier, serverless, auto-scaling, pgvector support
- **Supabase**: Free tier, Postgres + auth + realtime
- **Cloud SQL**: GCP-native, already have `amprealize-481520` project
- **TimescaleDB Cloud**: For telemetry database specifically

**Recommended setup:**
- 1× Neon Postgres cluster (with pgvector extension for behavior embeddings)
- OR 2× Neon: one for workflow+behavior, one for telemetry (TimescaleDB extension)
- Redis: Upstash (serverless, free tier) or managed Redis

### B4. Landing Page at `breakeramp.ai`

**Purpose:** Marketing + signup funnel. Not the web console itself — the **first thing a visitor sees**.

**Structure:**
```
breakeramp.ai/
├── /              → Landing page (hero, features, pricing, CTA)
├── /login         → Auth page (Device Flow + OAuth)
├── /signup        → Redirect to /login with signup mode
├── /pricing       → Pricing tiers detail
├── /docs          → Documentation hub
├── /dashboard     → Web console (authenticated)
├── /projects/*    → Web console routes (authenticated)
└── ...            → All existing web console routes
```

**Landing page sections:**
1. **Hero**: "AI-Powered Workflow Platform" — sign up free CTA
2. **Personas**: Cards for Developer, PM, Business Analyst, Enterprise
3. **Features**: Behaviors, MCP tools, multi-surface, agent orchestration
4. **How it works**: 3-step visual (Sign up → Create project → Add behaviors)
5. **Pricing**: OSS (free), Starter (free), Pro ($29/mo), Team ($99/seat), Enterprise
6. **Social proof**: Usage stats, testimonials
7. **Footer**: Docs, GitHub, Status, Terms, Privacy

### B5. MCP Cloud Proxy

**Purpose:** Allow VS Code/Cursor/Claude Desktop users to connect to cloud-hosted MCP server instead of running locally.

**Architecture:**
- Client (IDE) connects to `wss://mcp.breakeramp.ai/v1/mcp` with auth token
- Proxy translates WebSocket ↔ internal MCP server (stdio)
- Each connection gets isolated MCP server instance scoped to user's org

**IDE config for cloud mode:**
```json
{
  "servers": {
    "amprealize-cloud": {
      "url": "wss://mcp.breakeramp.ai/v1/mcp",
      "headers": {
        "Authorization": "Bearer ${AMPREALIZE_TOKEN}"
      }
    }
  }
}
```

**`amprealize init --cloud`** writes this config automatically after login.

### B6. Billing Tiers (Capacity + Feature Gated)

Leverage existing Stripe integration in `amprealize/billing/`. Differentiation uses **both capacity limits AND feature gates** — OSS is a fully functional standalone product; commercial tiers add cloud infrastructure, higher limits, and platform features. Reference model: **Arize AI** (Phoenix OSS + AX commercial tiers).

**5-Layer Tier Summary:**

| Tier | Price | Deployment | Key Differentiator |
|------|-------|------------|-------------------|
| **OSS** | Free (MIT) | Self-hosted only | Fully functional single-user/small-team. No account. CLI + MCP + VS Code. SQLite/JSON storage. |
| **Starter** | $0 | Cloud or self-hosted | Free commercial. Managed Postgres, Web Console, cloud MCP. 1 org, basic RBAC. Account required. |
| **Pro** | $29/mo flat ($290/yr) | Cloud or self-hosted | Power user. Audit logs, behavior versioning, cost analytics, webhooks. Email support (48hr). |
| **Team** | $99/seat/mo ($990/yr) | Cloud, self-hosted, or hybrid | Collaboration. Real-time collab, SSO, BCI automation, compliance suite, custom branding. Priority support (24hr). |
| **Enterprise** | Custom | All topologies | Dedicated support, 99.9% SLA, SOC2/HIPAA, multi-region, data residency, HA, SIEM export. |

**Capacity Limits by Tier:**

| Resource | OSS | Starter | Pro | Team | Enterprise |
|----------|-----|---------|-----|------|------------|
| Projects | Unlimited (local) | 3 | 10 | Unlimited | Custom |
| Members | 1 (local) | 5 | 15 | 50 | Custom |
| Agents | Unlimited (local) | 1 | 5 | 10 | Custom |
| Tokens/mo | Unlimited (local) | 100K | 500K | 2M | Custom |
| API calls/mo | N/A | 10K | 50K | 200K | Custom |
| Storage | Local disk | 1 GB | 10 GB | 100 GB | Custom |
| Retention | Local disk | 7 days | 30 days | 90 days | Custom |
| Boards | Unlimited (local) | 1 | 5 | Unlimited | Custom |

**Feature Gates (not in OSS):**

| Feature | Starter | Pro | Team | Enterprise |
|---------|:-------:|:---:|:----:|:----------:|
| Managed PostgreSQL | ✅ | ✅ | ✅ | ✅ |
| Web Console (cloud) | ✅ | ✅ | ✅ | ✅ |
| Cloud MCP endpoint | ✅ | ✅ | ✅ | ✅ |
| Basic RBAC (owner+member) | ✅ | ✅ | ✅ | ✅ |
| Audit logs | — | ✅ | ✅ | ✅ |
| Behavior versioning + diffs | — | ✅ | ✅ | ✅ |
| Cost analytics dashboard | — | ✅ | ✅ | ✅ |
| Webhook integrations | — | ✅ | ✅ | ✅ |
| Real-time collab (WebSocket) | — | — | ✅ | ✅ |
| SSO / SAML | — | — | ✅ | ✅ |
| BCI automation pipeline | — | — | ✅ | ✅ |
| Full compliance suite | — | — | ✅ | ✅ |
| Custom branding | — | — | ✅ | ✅ |
| Role-based RBAC | — | — | ✅ | ✅ |
| Hybrid deployment | — | — | ✅ | ✅ |
| 99.9% SLA | — | — | — | ✅ |
| SOC2 / HIPAA | — | — | — | ✅ |
| Multi-region / HA | — | — | — | ✅ |
| Data residency | — | — | — | ✅ |
| SIEM export | — | — | — | ✅ |

**Pricing model:**
- **Starter/Pro**: Flat-rate (no per-seat). Low-friction for individual adoption.
- **Team**: Per-seat. Natural for team collaboration budgets.
- **Enterprise**: Custom. Negotiated based on org size and requirements.

**Self-hosted licensing:**
- OSS: No license required (MIT).
- Commercial self-hosted: License key via `amprealize license activate <key>`. Key encodes tier + capacity limits. Validated against `breakeramp.ai/v1/licenses` (online) or signed JWT (air-gapped, Enterprise only).

**Why capacity + feature gated (not collaboration-gated):**
- OSS is a real standalone product (like Arize Phoenix) — builds genuine community and trust
- Free Starter removes all friction for cloud evaluation — "sign up and go"
- Capacity limits create natural upgrade pressure as usage grows
- Feature gates (BCI, SSO, compliance) are compelling Team-tier justifications for organizations
- Self-hosting at all tiers differentiates from competitors who restrict self-hosted to Enterprise

**Implementation notes:**
- Free tier never phones home — fully offline-capable
- Pro upgrade flow: `amprealize auth login` → Stripe checkout → cloud config auto-written
- Enterprise: contact sales flow on `breakeramp.ai/enterprise`

---

## 8. Track C — Web Console Onboarding

### C1. Welcome Page (`/welcome`)

**Shown on first login** (no `hasCompletedOnboarding` flag in user profile).

```
┌─────────────────────────────────────────────────┐
│                                                   │
│          Welcome to Amprealize! 👋                  │
│                                                   │
│    What best describes your role?                │
│                                                   │
│    ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│    │ 🛠️      │  │ 📋      │  │ 📊      │     │
│    │Developer │  │ Project  │  │ Business │     │
│    │          │  │ Manager  │  │ Analyst  │     │
│    └──────────┘  └──────────┘  └──────────┘     │
│                                                   │
│    ┌──────────┐  ┌──────────┐                    │
│    │ 🏗️      │  │ 🎯      │                    │
│    │ DevOps   │  │ Other    │                    │
│    │          │  │          │                    │
│    └──────────┘  └──────────┘                    │
│                                                   │
│    (Don't worry — you can change this later)      │
│                                                   │
└─────────────────────────────────────────────────┘
```

### C2. Role-Based Quick Start

After role selection, show a **guided setup flow** tailored to the persona. Each gets 3-5 steps that produce an immediate "quick win."

**Developer path:**
1. Create your first project (pre-filled template: "My App")
2. Connect your IDE (show MCP config button — one click copies config)
3. Run your first behavior search (in-browser demo, no IDE needed)
4. "You're all set! Explore behaviors or head to Dashboard →"

**Project Manager path:**
1. Create your first project (template: "Team Project")
2. Create a board with columns (Backlog, In Progress, Done)
3. Add your first work item
4. "You're all set! Invite team members or explore behaviors →"

**Business Analyst path:**
1. Create your first project (template: "Analysis Workspace")
2. Browse the behavior library (curated for business use cases)
3. Start a guided agent run
4. "You're all set! Check your dashboard for results →"

### C3. Onboarding API Changes

**New endpoint:** `POST /v1/users/me/onboarding`
```json
{
  "role": "developer",
  "completed_steps": ["created_project", "connected_ide"],
  "completed_at": "2026-03-11T..."
}
```

**Auth store changes:** `authStore.ts` gets `hasCompletedOnboarding` flag.

**Route guard:** `App.tsx` checks onboarding status:
```
Login → hasCompletedOnboarding?
  → YES → Dashboard (as today)
  → NO → /welcome → quick start → mark complete → Dashboard
```

### C4. Contextual Tooltips & Help

**For non-technical users**, add inline help throughout the web console:

- **Tooltip on "Behavior"**: "A behavior is a reusable set of instructions — like a recipe — that tells AI agents how to approach a specific type of task."
- **Tooltip on "MCP"**: "Model Context Protocol — a way for your IDE (code editor) to communicate with Amprealize's AI tools."
- **Tooltip on "Run"**: "A run is one execution of a task — like pressing 'Go' on a workflow."
- **Tooltip on "Agent"**: "An AI agent is an automated assistant that follows behaviors to complete tasks."

**Implementation:** Reusable `<HelpTooltip term="behavior" />` component that pulls definitions from a glossary.

### C5. In-App Help Center

**Persistent help button** (bottom-right `?` icon) that opens a slide-out panel with:

1. **Glossary**: Searchable list of all Amprealize terms with plain-English definitions
2. **Getting Started Guides**: Role-specific (matches onboarding role selection)
3. **Video Walkthroughs**: Embedded short clips for key workflows
4. **Contact Support**: Email / chat link
5. **Keyboard Shortcuts**: Reference card

### C6. Interactive Tour (Post-Onboarding)

Optional walkthrough overlay (e.g., `react-joyride` or similar) that highlights key UI elements:

1. **Sidebar navigation** → "This is where you switch between projects, behaviors, agents, and settings"
2. **Project header** → "Your current project. Click to switch."
3. **Dashboard stats** → "Overview of your runs, behaviors, and agent activity"
4. **New button** → "Create projects, behaviors, or work items from here"

---

## 9. Track D — CLI & Local Installation

### D1. Config Loader (`~/.amprealize/config.yaml`)

Central config that all Amprealize tools read from.

```yaml
version: 1
storage:
  backend: postgres            # postgres | sqlite | memory
  postgres:
    dsn: postgresql://amprealize:amprealize_dev@localhost:5432/amprealize
    telemetry_dsn: postgresql://telemetry:telemetry_dev@localhost:5433/telemetry
  sqlite:
    path: ~/.amprealize/data/amprealize.db
auth:
  mode: local                  # local | cloud
  cloud:
    server_url: https://api.breakeramp.ai
    token_store: keyring
mcp:
  transport: stdio
infra:
  managed_by: breakeramp       # breakeramp | external | none
  blueprint: local-test-suite
  plan_id: null
```

**Files to create:** `amprealize/config/loader.py`, `amprealize/config/schema.py`

### D2. SQLite Storage Adapter

**New file:** `amprealize/storage/sqlite_pool.py`

Same interface as `PostgresPool`. Stores everything in `~/.amprealize/data/amprealize.db`.

**Service support:**

| Service | SQLite | Fallback |
|---------|--------|----------|
| BehaviorService | ✅ Full | — |
| ActionService | ✅ Full | In-memory stub |
| RunService | ✅ Full | In-memory stub |
| ComplianceService | ⚠️ Partial | Basic features |
| TelemetryService | ❌ | FileSink (JSONL) via Raze |

### D3. `amprealize mcp-server` CLI Command

Stable entry point replacing `python -m amprealize.mcp_server`.

```bash
amprealize mcp-server              # stdio mode (primary)
amprealize mcp-server --transport sse --port 3001
amprealize mcp-server --verbose
```

Reads `~/.amprealize/config.yaml`, resolves all env vars, runs MCP server. Portable IDE config:
```json
{"servers": {"amprealize": {"command": "amprealize", "args": ["mcp-server"]}}}
```

### D4. `amprealize init` — Interactive Setup Wizard

```
$ amprealize init

  ╔══════════════════════════════════════╗
  ║   Welcome to Amprealize 🚀             ║
  ║   Let's set up your environment.     ║
  ╚══════════════════════════════════════╝

  Detected:
    OS: macOS 15.2 (Apple Silicon)
    Python: 3.12.1
    Container runtime: Podman 5.2.1
    IDE: VS Code, Cursor

  [1/4] Storage backend
    ❯ postgres  (recommended — full persistence, provisions via BreakerAmp)
      sqlite    (lightweight — single file, no containers needed)
      memory    (ephemeral — data lost on restart, good for quick try)

  [2/4] Provision infrastructure?
    ❯ Yes, provision now   (starts PostgreSQL + Redis containers)
      No, I'll manage my own databases

  [3/4] Configure IDE integration?
    ❯ VS Code  (write .vscode/mcp.json)
      Cursor   (write .cursor/mcp.json)
      Claude Desktop
      Skip

  [4/4] Authentication
    ❯ Local only (no login, all features work locally)
      Cloud (breakeramp.ai login for team sync)

  ✓ Created ~/.amprealize/config.yaml
  ✓ Provisioned PostgreSQL (localhost:5432) + Redis (localhost:6379)
  ✓ Ran database migrations
  ✓ Wrote .vscode/mcp.json
  ✓ MCP server verified — 64 tools available

  You're ready! Try:
    amprealize behaviors list
    amprealize open              ← opens web dashboard in browser
    amprealize doctor
```

**Flags:** `--storage`, `--ide`, `--no-infra`, `--workspace`, `--non-interactive`, `--force`, `--cloud`

### D5. `amprealize open` — Launch Web Dashboard

```bash
amprealize open                    # Opens localhost web console in browser
amprealize open --cloud            # Opens breakeramp.ai in browser
```

Starts the local FastAPI server (if not running) + serves the pre-built web console, then opens the default browser.

### D6. `amprealize infra` — Infrastructure Management

```bash
amprealize infra up          # Provision Postgres + Redis via BreakerAmp
amprealize infra down        # Tear down containers
amprealize infra status      # Show services, ports, health
amprealize infra logs        # Tail container logs
amprealize infra reset       # Destroy + re-provision
```

Wraps BreakerAmp `plan/apply/destroy` with sensible defaults.

### D7. `amprealize doctor` — Diagnostic Command

```
$ amprealize doctor

  Amprealize Health Check
  ────────────────────
  ✓ Python 3.12.1 (>= 3.10 required)
  ✓ amprealize 0.1.0 installed
  ✓ Config: ~/.amprealize/config.yaml (storage: postgres)
  ✓ PostgreSQL reachable (localhost:5432, latency: 2ms)
  ✓ Database migrations up to date (head: a3f2b1c)
  ✗ VS Code MCP config missing
    → Fix: amprealize init --ide vscode
  ✓ MCP server responds (64 tools available)
  ✓ BreakerAmp containers running (3/3 healthy)

  Result: 7/8 checks passed. Run suggested fix above.
```

### D8. PyPI Publication — `pipx install amprealize`

**Changes to `pyproject.toml`:**
```toml
[project.optional-dependencies]
lite = []           # Minimal: CLI + MCP + SQLite (fast install ~50MB)
full = ["amprealize[postgres,semantic,telemetry,breakeramp]"]

[project.scripts]
amprealize = "amprealize.cli:main"
amprealize-mcp = "amprealize.mcp_server:main"
```

**Release workflow** (`.github/workflows/release.yml`): Tag → build → PyPI → GitHub Release.

**Slim `[lite]` install:** Move heavy deps (`boto3`, `anthropic`, `openai`, `redis`, `podman`) from core `dependencies` to `[full]`. Cuts install from ~500MB to ~50MB.

### D9. Homebrew Formula

```bash
brew tap amprealize/tap
brew install amprealize
amprealize init
```

**New repository:** `homebrew-amprealize` on GitHub.

### D10. npm Wrapper

```bash
npx amprealize init
```

**New package:** `packages/amprealize-npm/` — thin Node.js wrapper that checks for Python, installs via pipx, delegates to CLI.

---

## 10. Track E — Desktop Application

### E1. Technology Choice: Electron

**Why Electron over alternatives:**

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Electron** | Web console reuse (React), mature, cross-platform, large ecosystem | Bundle size (~200MB) | ✅ Best fit — maximizes code reuse |
| **Tauri** | Small bundles, Rust backend | Must port FastAPI to Rust or bundle Python separately | ❌ Too much rework |
| **PyInstaller** | Pure Python | No web UI embedding, poor UX | ❌ Wrong tool |
| **Flutter** | Beautiful native UI | Complete rewrite needed | ❌ No code reuse |

### E2. Architecture

```
┌──────────── Electron App ────────────────────┐
│                                               │
│  ┌───────────────────────────────────────┐   │
│  │ Renderer Process (web-console React)  │   │
│  │ Same code as breakeramp.ai SPA        │   │
│  │ VITE_API_BASE_URL = http://127.0.0.1  │   │
│  └───────────────┬───────────────────────┘   │
│                  │ HTTP                        │
│  ┌───────────────┴───────────────────────┐   │
│  │ Main Process (Electron + Node.js)     │   │
│  │ • Spawn FastAPI as child process      │   │
│  │ • Manage SQLite DB lifecycle          │   │
│  │ • System tray icon + notifications    │   │
│  │ • Auto-updater (electron-updater)     │   │
│  └───────────────┬───────────────────────┘   │
│                  │                             │
│  ┌───────────────┴───────────────────────┐   │
│  │ Bundled FastAPI (Python, pyinstaller) │   │
│  │ Storage: ~/.amprealize/data/amprealize.db   │   │
│  └───────────────────────────────────────┘   │
└───────────────────────────────────────────────┘
```

### E3. Electron Project Structure

```
packages/desktop/
├── package.json
├── electron-builder.yml         # Build config for .dmg, .exe, .AppImage
├── src/
│   ├── main/
│   │   ├── index.ts             # Electron main process
│   │   ├── fastapi-manager.ts   # Spawn/manage bundled FastAPI
│   │   ├── updater.ts           # Auto-update logic
│   │   └── tray.ts              # System tray icon
│   └── preload/
│       └── index.ts             # Preload bridge
├── resources/
│   ├── icon.icns                # macOS icon
│   ├── icon.ico                 # Windows icon
│   └── icon.png                 # Linux icon
└── scripts/
    ├── bundle-python.sh         # Package FastAPI with PyInstaller
    └── build.sh                 # Full build pipeline
```

### E4. FastAPI Bundling

```bash
# Bundle FastAPI server as standalone binary
pyinstaller --onefile \
  --name amprealize-server \
  --hidden-import amprealize.api \
  amprealize/api.py
```

The Electron main process spawns this binary, waits for FastAPI to start on a random available port, then loads the web console pointing at that port.

### E5. Desktop App User Experience

**First launch:**
1. Splash screen: "Setting up Amprealize..." (initializes SQLite DB, runs migrations)
2. Welcome wizard (same as web console `/welcome` but embedded)
3. Dashboard — identical to `breakeramp.ai` web console

**Subsequent launches:**
1. System tray icon appears
2. Main window opens to Dashboard
3. FastAPI starts in background (< 2 seconds)

**Menu bar / System tray:**
- "Open Amprealize" — show/focus main window
- "Open in Browser" — open `localhost:PORT` in default browser
- "Start MCP Server" — for IDE integration
- "Check for Updates"
- "Quit"

### E6. Platform Builds

| Platform | Format | Tool | Signing |
|----------|--------|------|---------|
| macOS | `.dmg` + `.zip` (auto-update) | electron-builder | Apple Developer ID |
| Windows | `.exe` (NSIS installer) + `.msi` | electron-builder | Code signing cert |
| Linux | `.AppImage` + `.deb` + `.rpm` | electron-builder | — |

### E7. Distribution

- **GitHub Releases**: All platforms, auto-update feed
- **breakeramp.ai/download**: Download page with platform detection
- **Homebrew Cask** (macOS): `brew install --cask amprealize`
- **Microsoft Store** (Windows): Future consideration
- **Snap Store** (Linux): Future consideration

---

## 11. Track F — IDE Integration

### F1. Getting Started WebView Panel

New panel in VS Code extension shown when Amprealize is not configured:

```
┌──────────────────────────────────────────┐
│  Amprealize: Getting Started                 │
│──────────────────────────────────────────│
│                                           │
│  Welcome! Let's connect Amprealize. 🚀      │
│                                           │
│  Choose your setup:                       │
│                                           │
│  [Use Cloud (breakeramp.ai)]              │
│     → Sign in and connect instantly       │
│                                           │
│  [Use Local Installation]                 │
│     → Requires amprealize CLI installed      │
│     → Run: pipx install amprealize           │
│                                           │
│  [Download Desktop App]                   │
│     → breakeramp.ai/download              │
│                                           │
│  Status: ❌ Not connected                 │
│  [Run Diagnostics]                        │
│                                           │
└──────────────────────────────────────────┘
```

### F2. MCP Auto-Configuration

When the extension detects `amprealize` CLI is installed:
1. Prompt: "Amprealize CLI detected. Configure MCP server for this workspace?"
2. If yes: run `amprealize init --ide vscode --workspace --non-interactive`
3. Write `.vscode/mcp.json` with portable config
4. Show notification: "Amprealize MCP server configured! 64 tools available."

### F3. VS Code Marketplace Publication

Publish the extension from `extension/` to the VS Code Marketplace:
- Publisher ID setup
- `vsce package` + `vsce publish`
- CI workflow for automatic releases
- Extension icon, README, changelog

---

## 12. Decisions & Trade-offs

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Product model** | **Open-core** (Apache 2.0 OSS + proprietary enterprise) | Maximizes developer adoption; monetize via collaboration/cloud features |
| **Primary value prop** | **Behavior engine for AI agents** (flywheel: define → execute → trace → refine) | Clear, differentiated positioning; avoids "everything for everyone" scope creep |
| **Adoption sequence** | **Developer-first funnel** (Individual → Team → Org → Cross-functional) | Bottoms-up adoption mirrors Docker, Terraform, VS Code patterns |
| **Free tier model** | **Capacity + feature gated** (OSS = unlimited local standalone; Starter = free commercial with capacity limits; upgrade via usage growth or feature needs) | OSS is a real product (Arize Phoenix model); Starter removes cloud friction; capacity limits create natural upgrade pressure |
| **License** | **Apache 2.0** (OSS core) | Patent grant, enterprise-friendly, community contributions, strong ecosystem signal |
| **Repository structure** | **Split** — `SandRiseStudio/amprealize` (OSS) + `SandRiseStudio/amprealize-enterprise` (proprietary) | Clean IP separation, independent release cadences, community contribution clarity |
| Cloud domain | `breakeramp.ai` | Aligns with BreakerAmp infrastructure brand |
| Cloud SaaS stack | Managed Postgres (Neon) + CDN (Cloudflare/Vercel) + Cloud Run | Low ops overhead, generous free tiers, auto-scaling |
| Desktop framework | Electron | Maximizes React web console code reuse; mature cross-platform |
| Default storage (local) | SQLite (OSS default), Postgres (enterprise/cloud) | SQLite = zero-dependency local; Postgres = scalable multi-tenant |
| MCP entry point | `amprealize mcp-server` | Portable, no absolute paths, reads config.yaml |
| Config location | `~/.amprealize/config.yaml` | User state separate from workspace config |
| Auth default (local) | Local-only; `amprealize auth login` for cloud | Removes friction for CLI users |
| Onboarding trigger | `hasCompletedOnboarding` flag on user profile | Clean separation, works across devices |
| Non-technical help | Glossary + tooltips + contextual help panel | Scales better than embedded docs; maintainable |
| Billing model | OSS (free) → Starter ($0) → Pro ($29/mo flat) → Team ($99/seat/mo) → Enterprise (custom) — capacity + feature gated | 5-layer architecture; flat-rate at Starter/Pro for low friction; per-seat at Team for collaboration budgets |
| Self-hosted model | All commercial tiers self-hostable via license key; air-gapped = OSS or Enterprise only | Differentiates from competitors who restrict self-hosted to Enterprise |
| Reference model | Arize AI (Phoenix OSS + AX commercial) — OSS as real product, commercial as superset | Proven pattern; genuine community trust; commercial never forks OSS |

---

## 13. Verification Scenarios

### Scenario 1: Non-Technical PM — Cloud Path

```
1. Visit breakeramp.ai → sees landing page
2. Click "Sign Up Free" → OAuth with Google
3. Welcome wizard → select "Project Manager" role
4. Guided: create project "Q2 Campaign"
5. Guided: create board with columns
6. Guided: add first work item
7. Dashboard shows project overview
```

**Pass criteria:** Zero terminal usage, zero downloads, under 5 minutes end-to-end.

### Scenario 2: Solo Developer — CLI Path

```
1. pipx install amprealize
2. amprealize init --storage sqlite --ide vscode
3. amprealize doctor → all green
4. Open VS Code → Copilot Chat → mcp_amprealize_behaviors_list works
5. amprealize open → web dashboard opens in browser
```

**Pass criteria:** Under 2 minutes, no Docker, no manual config editing.

### Scenario 3: Business Analyst — Desktop App Path

```
1. Download Amprealize.dmg from breakeramp.ai/download
2. Drag to Applications → launch
3. Welcome wizard → "Business Analyst" role
4. Create workspace, browse behavior library
5. Run first agent-guided analysis
```

**Pass criteria:** No terminal, no command line, native app experience.

### Scenario 4: DevOps — Self-Hosted Docker

```
1. git clone + docker compose up
2. Visit localhost:5173 → web console running
3. amprealize init --storage postgres → connects to Docker Postgres
4. amprealize doctor → all services healthy
```

**Pass criteria:** Full stack running locally with persistent Postgres.

### Scenario 5: Team Portability

```
1. Admin: amprealize init --workspace → .vscode/mcp.json committed
2. New member: pipx install amprealize && amprealize init
3. amprealize doctor → all green, MCP working
```

### Scenario 6: Cloud → Desktop Migration

```
1. User starts on breakeramp.ai (cloud)
2. Downloads desktop app
3. Logs in with same breakeramp.ai account
4. Projects/behaviors sync from cloud
```

### Scenario 7: Repository Optimization

- [ ] GitHub repo page shows rich README with badges & install instructions
- [ ] Root directory has ~20 items (down from ~119)
- [ ] `client_secret_*.json` removed from disk and history
- [ ] LICENSE, CONTRIBUTING, SECURITY all present
- [ ] Issue templates produce structured forms
- [ ] Dependabot creates weekly update PRs
- [ ] `pyproject.toml` URLs point to `breakeramp.ai`

---

## 14. Implementation Schedule

> **Sequencing rationale:** Ordered by the adoption funnel (Section 2.3). Foundation first, then developer on-ramp (the OSS entry point), then team/cloud features, then cross-functional expansion, then polish.

### Week 1–2 — Foundation + Developer On-Ramp

*Priority: Everything a solo developer needs to run `pipx install amprealize` and start using behaviors.*

| # | Task | Track | Priority |
|---|------|-------|----------|
| A1 | Rotate leaked OAuth credentials | A | 🔴 Critical |
| A2 | Create root README.md (OSS-focused, badges, quick start) | A | 🔴 Critical |
| A3 | Create root LICENSE (Apache 2.0) | A | 🔴 Critical |
| A6 | Repository split — create `amprealize-enterprise`, move enterprise code | A | 🔴 Critical |
| D1 | Config loader (`~/.amprealize/config.yaml`) | D | 🔴 High |
| D2 | SQLite storage adapter (default local storage) | D | 🔴 High |
| D3 | `amprealize mcp-server` CLI command | D | 🔴 High |
| D4 | `amprealize init` interactive wizard | D | 🔴 High |
| D8 | PyPI publish workflow + slim dependencies | D | 🔴 High |
| F1 | Getting Started WebView panel (VS Code) | F | 🟡 High |
| F2 | MCP auto-configuration in extension | F | 🟡 High |

### Week 2–3 — DX Polish

*Priority: Smooth the developer experience — diagnostics, dashboard, marketplace presence.*

| # | Task | Track | Priority |
|---|------|-------|----------|
| D5 | `amprealize open` (launch web dashboard in browser) | D | 🟡 Medium |
| D7 | `amprealize doctor` diagnostic command | D | 🟡 Medium |
| D6 | `amprealize infra` commands (wrapping BreakerAmp) | D | 🟡 Medium |
| F3 | VS Code Marketplace publish workflow | F | 🟡 Medium |
| A4 | Governance files (CONTRIBUTING, SECURITY, CODE_OF_CONDUCT) | A | 🟡 Medium |
| A5 | Issue/PR templates | A | 🟡 Medium |
| A7 | Dependabot + pyproject.toml metadata | A | 🟢 Low |

### Week 3–4 — Cloud + Teams (Pro Tier)

*Priority: Enable the Individual → Team upgrade path via cloud SaaS.*

| # | Task | Track | Priority |
|---|------|-------|----------|
| B1 | DNS setup for breakeramp.ai | B | 🔴 High |
| B2 | Web console Dockerfile + deploy pipeline | B | 🔴 High |
| B3 | API Dockerfile + managed Postgres setup | B | 🔴 High |
| B4 | Landing page at breakeramp.ai | B | 🔴 High |
| B5 | MCP WebSocket proxy (mcp.breakeramp.ai) | B | 🟡 Medium |
| B6 | Billing tier setup in Stripe (collaboration-gated) | B | 🟡 Medium |
| C1 | Welcome page (`/welcome` route + role selector) | C | 🟡 Medium |
| C2 | Role-based quick start flows | C | 🟡 Medium |
| C3 | Onboarding API endpoint + auth store changes | C | 🟡 Medium |

### Week 4–5 — Cross-Functional Expansion

*Priority: Enable PM/analyst personas. Build supplementary tools that extend the core flywheel.*

| # | Task | Track | Priority |
|---|------|-------|----------|
| C4 | Contextual tooltips + help component | C | 🟡 Medium |
| C5 | In-app help center (glossary, guides) | C | 🟡 Medium |
| E1 | Electron project scaffold (`packages/desktop/`) | E | 🟡 Medium |
| E2 | FastAPI PyInstaller bundling | E | 🟡 Medium |
| E3 | Electron main process (spawn FastAPI, load web console) | E | 🟡 Medium |

### Week 5+ — Platform Builds & Polish

*Priority: Desktop distribution, OS-specific builds, formula/npm convenience wrappers.*

| # | Task | Track | Priority |
|---|------|-------|----------|
| E4 | macOS build (.dmg, code signing) | E | 🟡 Medium |
| E5 | Windows build (.exe, code signing) | E | 🟡 Medium |
| E6 | Linux build (.AppImage, .deb) | E | 🟡 Medium |
| E7 | Auto-updater + breakeramp.ai/download page | E | 🟡 Medium |
| D9 | Homebrew formula | D | 🟢 Low |
| D10 | npm wrapper package | D | 🟢 Low |
| C6 | Interactive tour overlay (react-joyride) | C | 🟢 Low |
| A7 | Dependabot + pyproject.toml metadata | A | 🟢 Low |

---

## 15. Further Considerations

### Open-Core & Community

1. **Apache 2.0 community strategy** — Draft a `CONTRIBUTING.md` that clarifies: OSS contributions go to `SandRiseStudio/amprealize`, contributor license agreement (CLA) required, community governance model (benevolent dictator initially, steering committee later).

2. **Repo split migration plan** — Execute the monorepo → split-repo migration: create `amprealize-enterprise`, move enterprise code, update CI/CD pipelines, update all import paths, verify both repos build independently. Target: complete before first PyPI publish.

3. **Behavior marketplace** — Community-contributed behavior packs shared via `breakeramp.ai/marketplace` or a simple Git-based registry. OSS behaviors are Apache 2.0; premium packs are enterprise-only.

4. **Positioning discipline** — All public-facing copy leads with *"The behavior engine for AI agents"*. Supplementary tools (PM, compliance, analytics) are framed as extensions of the core flywheel, not independent products.

### Product & Distribution

5. **Offline mode** — CLI and desktop app should work fully offline with SQLite. Sync to cloud when connectivity returns.

6. **Data export/import** — Users who start on cloud may want to move to self-hosted (or vice versa). Provide `amprealize export` and `amprealize import` commands.

7. **Mobile app** — Future consideration. Web console is responsive and works on tablets. Native mobile app is lower priority.

8. **SSO/SAML** — Enterprise tier feature. On roadmap for hybrid deployment topology.

9. **White-label** — Enterprise customers may want to customize branding. Architecture should support theme overrides.

10. **Plugin ecosystem** — Allow users to create custom behaviors, agents, and MCP tools that can be shared via the behavior marketplace.

### Technical

11. **First-run telemetry** — Opt-in anonymous usage analytics during onboarding. Default off for privacy. OSS version never phones home.

12. **Version pinning** — `.amprealize-version` file (like `.node-version`) so teams stay on the same version.

13. **Docker-based install** — publish a container image (for example `ghcr.io/sandrisestudio/amprealize`) and run `amprealize init` inside it for CI and isolated testing.

14. **Internationalization** — Web console and desktop app should support i18n from the start. English primary, community translations later.

15. **Competitive moat** — The behavior handbook + trace data is the compounding asset. Every agent run makes the behavior library more valuable. Prioritize features that accelerate this flywheel over one-off tools.

---

*v3.1 — Supersedes v3.0. Adds 5-layer tier architecture (OSS → Starter → Pro → Team → Enterprise), self-hosting at all commercial tiers, Arize AI reference model, capacity + feature differentiation replacing collaboration-gated billing.*

*Document follows `behavior_update_docs_after_changes`. Cite as `docs/INSTALLATION_AND_REPO_OPTIMIZATION_PLAN.md` in PRs and BUILD_TIMELINE.md entries.*
