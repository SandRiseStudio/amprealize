---
title: "Surfaces"
type: reference
last_updated: 2026-04-14
applies_to:
  - dev
  - test
  - staging
  - prod
tags:
  - surfaces
  - cli
  - api
  - mcp
  - vscode
  - web-console
---

# Surfaces

Amprealize exposes functionality through five surfaces. Every feature aims for
**cross-surface parity** — the same operation should produce identical results regardless
of which surface you use.

## Surface Overview

| Surface | Entry Point | Primary Users | Protocol |
|---------|-------------|---------------|----------|
| **CLI** | `amprealize <command>` | Developers, CI/CD | Click commands → service calls |
| **REST API** | `http://localhost:8080/v1/` | External integrations, web console | FastAPI, JSON, Bearer auth |
| **MCP Server** | VS Code Copilot Chat / IDE | AI agents, IDE extensions | JSON-RPC over stdio/SSE |
| **VS Code Extension** | Command palette, sidebar | Developers in VS Code | Extension API + MCP client |
| **Web Console** | `http://localhost:5173/` | Team leads, analysts | React SPA + REST API |

## CLI

The CLI is the primary developer interface. Built with Click, it mirrors every service
operation as a subcommand group:

```bash
amprealize behaviors list
amprealize runs create --workflow "my-workflow"
amprealize actions get <action-id>
amprealize compliance validate
amprealize context use neon
```

Key groups: `behaviors`, `runs`, `actions`, `compliance`, `context`, `pack`, `mcp`, `wiki`.

## REST API

FastAPI application serving JSON endpoints behind an Nginx gateway (:8080):

- **Gateway features**: TLS termination, header stripping, rate limiting, CORS
- **Auth**: Bearer token via device flow or API key
- **Versioning**: `/v1/` prefix on all routes
- **OpenAPI docs**: Auto-generated at `/docs`

## MCP Server

The MCP (Model Context Protocol) server exposes **64+ tools** across 16 service families,
callable from VS Code Copilot Chat or any MCP-compatible client:

| Family | Tool Count | Examples |
|--------|:----------:|---------|
| behaviors | 9 | create, get, list, search, approve, submit |
| runs | 6 | create, get, list, updateProgress, complete, cancel |
| bci | 11 | retrieve, composePrompt, detectPatterns, parseCitations |
| actions | 5 | create, get, list, replay, replayStatus |
| compliance | 5 | createChecklist, validateChecklist, recordStep |
| auth | 8 | deviceLogin, authStatus, listGrants, revoke |
| workitems | 6 | create, get, list, update, delete |
| analytics | 4 | behaviorUsage, tokenSavings, kpiSummary |
| See also | — | [MCP Tool Families](mcp-tools.md) for the full catalog |

## VS Code Extension

The extension provides:
- **Sidebar panels**: Behavior browser, run status, pack activation
- **Command palette**: Quick access to common operations
- **MCP integration**: Copilot Chat can invoke Amprealize tools directly
- **Raze logging**: Client-side telemetry via `RazeClient.ts`

Located at `extension/` in the repo.

## Web Console

React-based SPA at `web-console/`:
- **Dashboards**: Run history, behavior metrics, compliance status
- **Management**: Behavior CRUD, project settings, team management
- **Real-time**: SSE-powered progress updates for active runs

## Cross-Surface Parity

Parity is enforced through:
1. **Shared service layer**: CLI, API, MCP all call the same Python service classes
2. **Parity tests**: `tests/test_*_parity.py` verify identical results across surfaces
3. **Schema alignment**: Shared Pydantic models for request/response
4. **Capability matrix**: `docs/capability_matrix.md` tracks feature availability per surface
