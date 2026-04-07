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
