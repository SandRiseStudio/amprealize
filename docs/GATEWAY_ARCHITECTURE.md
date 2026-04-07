# Gateway Architecture

> **Last Updated:** 2026-03-30 (AMPREALIZE-409/410/411)
>
> **Purpose:** Documents the nginx gateway that serves as the single entry point for all Amprealize traffic.

---

## Overview

All client traffic — Web Console, CLI, VS Code Extension, and MCP — enters through **nginx on port 8080**. The gateway handles TLS termination, header management, rate limiting, and static asset serving before proxying to the FastAPI application server on port 8000.

```
Clients (browser, CLI, VS Code, MCP)
        │
        ▼
┌───────────────────────────────┐
│  Nginx Gateway (:8080)        │
│  ┌──────────────────────────┐ │
│  │ TLS Termination          │ │
│  │ Header Stripping         │ │
│  │ Rate Limiting            │ │
│  │ Static File Serving      │ │
│  └──────────────────────────┘ │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│  FastAPI App (:8000)          │
│  ┌──────────────────────────┐ │
│  │ AuthMiddleware           │ │
│  │ TenantMiddleware         │ │
│  │ CORS Middleware          │ │
│  └──────────────────────────┘ │
└───────────────────────────────┘
```

---

## Nginx Configuration

**Config file:** `config/nginx/nginx.conf`

### Proxy Locations

| Location | Backend | Purpose |
|----------|---------|---------|
| `/api/` | `http://amprealize-api:8000` | REST API |
| `/v1/` | `http://amprealize-api:8000` | Versioned API endpoints |
| `/mcp/` | `http://amprealize-api:8000` | MCP server endpoints |
| `/ws/` | `http://amprealize-api:8000` | WebSocket connections |
| `/` | Static files | Web Console (React build) |

### Header Stripping

At every proxy location, nginx strips client-supplied identity headers to prevent spoofing:

```nginx
proxy_set_header X-Tenant-Id "";
proxy_set_header X-User-Id "";
```

These headers are set exclusively by the `AuthMiddleware` and `TenantMiddleware` after authentication. Clients cannot inject tenant or user identity.

### TLS Termination

TLS is optional (plain HTTP in development) and controlled via environment variables:

| Variable | Description |
|----------|-------------|
| `NGINX_SSL_CERT` | Path to TLS certificate (e.g., `/etc/nginx/certs/fullchain.pem`) |
| `NGINX_SSL_KEY` | Path to TLS private key (e.g., `/etc/nginx/certs/privkey.pem`) |

When both are set, nginx listens on 443 with TLS and redirects 80 → 443.

### Rate Limiting

| Zone | Rate | Applies To |
|------|------|------------|
| `api_limit` | 100 req/s | `/api/`, `/v1/`, `/mcp/` |
| `ws_limit` | 10 req/s | `/ws/` |

Burst is allowed with `nodelay` to handle short spikes without queuing.

---

## FastAPI Middleware Stack

**Config file:** `amprealize/api.py`, `amprealize/auth/middleware.py`

Request processing order (outermost first):

1. **CORSMiddleware** — allows origins from `AMPREALIZE_CORS_ORIGINS` env var
2. **AuthMiddleware** — validates bearer tokens, enforces 401 on non-public paths; bypass controlled by `AMPREALIZE_AUTH_ENABLED`
3. **TenantMiddleware** — extracts tenant context from the authenticated token and sets request-scoped `X-Tenant-Id`

### Public Paths

Paths that bypass authentication (e.g., health checks, device flow endpoints) are configured in `middleware.py`. The `AMPREALIZE_AUTH_ENABLED=false` setting disables auth enforcement entirely (for local development).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AMPREALIZE_CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated allowed CORS origins |
| `AMPREALIZE_AUTH_ENABLED` | `false` | Enable/disable auth middleware enforcement |
| `NGINX_SSL_CERT` | _(unset)_ | TLS certificate path |
| `NGINX_SSL_KEY` | _(unset)_ | TLS private key path |
| `AMPREALIZE_API_HOST` | `0.0.0.0` | FastAPI bind host |
| `AMPREALIZE_API_PORT` | `8000` | FastAPI bind port |
| `AMPREALIZE_RATE_LIMIT_REQUESTS` | `100` | API rate limit (req/s) |
| `AMPREALIZE_RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window |

---

## Deployment Profiles

### Development

- Nginx on `:8080` (HTTP only, no TLS)
- `AMPREALIZE_AUTH_ENABLED=false`
- CORS allows `localhost:3000` and `localhost:5173`

### Staging

- Nginx on `:8080` with TLS
- `AMPREALIZE_AUTH_ENABLED=true`
- CORS restricted to staging domain
- Blueprint: `infra/environments.yaml` (L358)

### Production

- Nginx on `:8080` with TLS
- `AMPREALIZE_AUTH_ENABLED=true`
- CORS restricted to production domain
- Blueprint: `config/breakeramp/blueprints/production.yaml`
- Environment: `infra/environments.yaml` (L509)

---

## Related Documents

- [README.md](../README.md) — Gateway summary in Architecture section
- [SECRETS_MANAGEMENT_PLAN.md](SECRETS_MANAGEMENT_PLAN.md) — Header stripping policy
- [environments.yaml](../infra/environments.yaml) — Staging/production environment profiles
- [nginx.conf](../config/nginx/nginx.conf) — Nginx configuration source
- [BUILD_TIMELINE.md](../BUILD_TIMELINE.md) — Entry #182

---

## Behaviors

- `behavior_lock_down_security_surface` — CORS, auth, header stripping
- `behavior_externalize_configuration` — All gateway config via env vars
- `behavior_prevent_secret_leaks` — TLS keys never committed
