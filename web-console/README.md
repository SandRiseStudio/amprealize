# Amprealize Web Console

React + TypeScript + Vite front end for the Amprealize platform. Point it at a running Amprealize API (local OSS server, staging, or cloud).

## Network architecture

All client traffic flows through the **nginx gateway** on port **8080** (HTTP) or **8443** (HTTPS when TLS is configured). The gateway proxies `/api/`, `/v1/`, `/ws/`, `/sse/`, `/mcp/` to the API and serves the web console on `/`.

```
Browser ──▶ :8080 nginx gateway ──┬─▶ /api/*, /v1/*, /ws/*, /sse/*, /mcp/*  →  amprealize-api :8000
                                  └─▶ /*  →  web-console :5173
```

In development the direct service ports (:8000, :5173) remain reachable but are **non-canonical**. Always prefer the gateway URL so cookies, CORS, and auth headers behave identically to production.

## Prerequisites

- Node.js 20+ (matches CI)
- An Amprealize API instance (for example `uvicorn amprealize.api:app --reload` from the repository root)

## Configuration

| Variable | Purpose |
|----------|---------|
| `VITE_API_BASE_URL` | Base URL for the Amprealize REST API (no trailing slash). Defaults to `http://localhost:8080` (the gateway). |

If you are running the API directly without the gateway, create `.env.local` (gitignored):

```bash
echo 'VITE_API_BASE_URL=http://localhost:8000' > .env.local
```

### Cloud-dev (Neon) vs Cursor MCP — point both at the same backend

On **cloud-dev**, board data lives on **Neon**; the API reaches it via `AMPREALIZE_BOARD_PG_DSN`.

| Surface | How it reaches data |
|--------|---------------------|
| **Web (`npm run dev` on :5173)** | HTTP only. `VITE_API_BASE_URL` (default `http://localhost:8080`) → nginx gateway → FastAPI → Neon. Must match the gateway you actually run for cloud-dev. |
| **Amprealize MCP (stdio)** | **Does not read `VITE_*`.** It builds `BoardService` from **`AMPREALIZE_BOARD_PG_DSN`** after [`scripts/start_amprealize_mcp.py`](../scripts/start_amprealize_mcp.py) applies your Amprealize CLI context (`apply_context_to_environment`). Use the **`neon` / cloud-dev** context so DSN targets Neon, not localhost Postgres. |

**Checklist:** (1) Gateway URL in DevTools Network matches `VITE_API_BASE_URL`. (2) `amprealize context` (or your team’s command) shows the Neon-backed context active before Cursor launches MCP. (3) Restart Vite after editing `.env.local`.

**Queue execution (boards / work-item run):** cloud-dev defaults to `EXECUTION_MODE=queue`. Before `breakeramp apply --env cloud-dev` (or `--env neon`), run `amprealize context use neon` so BreakerAmp can fill `BREAKERAMP_CLOUD_DATABASE_URL` for the API and `execution-worker`. Keep **Redis**, **execution-worker**, **podman-socket-proxy** (host port **8888**), and **gateway :8080** healthy; the API uses `PODMAN_HOST=tcp://host.containers.internal:8888` to reach your Podman socket on the Mac VM. BreakerAmp sets **`AMPREALIZE_PODMAN_SOCK_HOST_PATH`** from `podman machine inspect` (or Linux user paths) before expanding blueprints so the socket bind mount matches your host; override that env if you use a non-standard socket. Optional LLM keys on the host (`OPENAI_API_KEY`, etc.) are forwarded into the worker for agent runs.

## Commands

```bash
npm install
npm run dev      # dev server with HMR
npm run build    # production bundle → dist/
npm run preview  # serve dist/ locally
npm run test     # Vitest
npm run lint     # ESLint
```

## Monorepo note

`@amprealize/collab-client` and the legacy alias `@amprealize/collab-client` resolve to [`../packages/collab-client`](../packages/collab-client). Clone the full repository and install from the repo root when working on both packages.
