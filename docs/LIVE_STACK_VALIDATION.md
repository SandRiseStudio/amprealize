# Live stack validation (separate layer)

Work-item trackers and CI unit/integration tests can be green while **deployed** behavior—nginx hop, TLS, real JWTs, warm caches, cross-region latency—still needs a targeted pass against a **running** API + gateway.

This document defines that **live-stack layer**: what it covers, what it does **not** replace, and which scripts to run.

**Behaviors referenced**: `behavior_design_test_strategy`, `behavior_orchestrate_cicd`, `behavior_update_docs_after_changes`

---

## What this layer is not

| Layer | Proves | Typical gate |
|--------|--------|----------------|
| **Unit / component tests** | Correctness of modules with mocks or fast fakes | PR / `npm test`, targeted `pytest` |
| **Integration / staging smoke** | Services wired together (often localhost staging via `./scripts/run_tests.sh`) | CI or pre-release |
| **Live stack** (this doc) | End-to-end latency, auth’d bootstrap paths, infra config vs **real** URL | Release checklist, perf regressions, incidents |

Closing a board item or merging a PR does **not** imply live-stack validation ran unless someone explicitly ran these checks (or an equivalent monitored probe in production).

---

## When to run live-stack checks

- Before tagging a release or promoting a console-heavy change.
- After nginx, gateway, pool, or bootstrap API changes (`dashboard-bootstrap`, `global-chat-bootstrap`, board bootstrap).
- When investigating “slow first paint” or 401/403 only in staging/prod.
- Optionally on a schedule (cron) against a stable staging URL—not as a blocking step on every PR.

---

## Scripts (repository root = `amprealize/`)

### 1. Gateway / nginx config validation — `scripts/validate_gateway_infra_performance.py`

- **Static:** Parses `config/nginx/nginx.conf` for keepalive, gzip, `/api/` HTTP/1.1, SSE buffering, WS timeouts (no network required).
- **Live (optional):** `--base-url https://your-staging.example` probes `GET /health`. With `AMPREALIZE_SERVER_TIMING=1` on the API, responses may include `Server-Timing` for debugging latency through the proxy.

```bash
# Config-only (good for CI that checks out the repo)
python scripts/validate_gateway_infra_performance.py

# Plus live health against a deployed stack
python scripts/validate_gateway_infra_performance.py --base-url https://staging.example.com
```

Exit codes: `0` pass, `1` failures, `2` warnings only.

### 2. Console hot-path load / latency — `scripts/load_test_console_hot_paths.py`

Measures p50/p75/p95 and error rate for real routes through the **gateway URL** (default `http://localhost:8080`), including authenticated bootstrap endpoints.

Typical env vars:

| Variable | Purpose |
|----------|---------|
| `AMPREALIZE_LOAD_TEST_BASE_URL` | Gateway base (e.g. `https://staging.example.com`) |
| `AMPREALIZE_LOAD_TEST_BEARER_TOKEN` | JWT for protected routes |
| `AMPREALIZE_LOAD_TEST_ORG_ID` | Org query param for dashboard-bootstrap |
| `AMPREALIZE_LOAD_TEST_BOARD_ID` | Optional; board bootstrap path |

```bash
export AMPREALIZE_LOAD_TEST_BASE_URL="https://staging.example.com"
export AMPREALIZE_LOAD_TEST_BEARER_TOKEN="$( … obtain token … )"

python scripts/load_test_console_hot_paths.py --iterations 40 --concurrency 4
python scripts/load_test_console_hot_paths.py --json --max-p95-ms 800
```

**Recommended wrapper (repo venv + OAuth token store):** `scripts/run_load_test_console_hot_paths.sh` resolves `AMPREALIZE_LOAD_TEST_BEARER_TOKEN` from the same keychain/file store as `amprealize auth login` (uses `.venv/bin/python`). If the access token is expired it tries `.venv/bin/amprealize auth refresh` once, then exits with instructions if you still need to log in.

```bash
cd amprealize
./scripts/run_load_test_console_hot_paths.sh --iterations 25 --concurrency 2
```

Prerequisites:

1. **Gateway reachable** at `AMPREALIZE_LOAD_TEST_BASE_URL` (default `http://localhost:8080`, e.g. cloud-dev nginx from BreakerAmp).
2. **OAuth:** For **dashboard** and **global-chat bootstrap** scenarios you need a valid JWT. Run `.venv/bin/amprealize auth login --provider=github` (or google). Without a token, `capabilities` still runs; auth’d scenarios are skipped with `missing bearer token`.
3. Optional: set `AMPREALIZE_LOAD_TEST_BEARER_TOKEN` yourself (CI or copied from a secure location) to bypass resolution.

Paths exercised include `GET /api/v1/capabilities`, `GET /api/v1/console/dashboard-bootstrap`, `GET /api/v1/conversations/global-chat-bootstrap`, and optionally board bootstrap. See the script docstring for CLI flags.

Server-side DB timing, queue depth, and Redis hit rates are **not** asserted here—correlate with `/metrics`, Raze, or your observability stack.

---

## Related: managed staging in tests

`./scripts/run_tests.sh` can start **local** staging (API + nginx) for pytest selections that need it (`tests/smoke/test_staging_core.py`, etc.). That is still **not** the same as validating your **remote** staging or production URL; use the scripts above for URL-specific behavior.

See also:

- `docs/TESTING_GUIDE.md` — runner, env vars, staging stack toggles.
- `docs/STAGING_INTEGRATION_TESTING_GUIDE.md` — OAuth/device flow and deeper staging procedures.
- `deployment/STAGING_DEPLOYMENT_GUIDE.md` — bringing up staging-like stacks.

---

## Suggested release checklist (minimal)

1. CI green on unit/integration suites you rely on.
2. `python scripts/validate_gateway_infra_performance.py` (static); optional `--base-url` against target deploy.
3. `./scripts/run_load_test_console_hot_paths.sh` (or explicit token + `python scripts/load_test_console_hot_paths.py`) against the same base URL; review p95 vs your SLO.
4. Spot-check the web console first load and authenticated home in a browser.

Document outcomes in your release notes or incident ticket—not assumed from tracker status alone.
