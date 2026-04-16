# Web console perf harness

End-to-end timing harness for the Amprealize web console. Runs scripted
Chromium journeys, records client-side milestones (`window.__perfMarks`)
and the server-side `perf …` log lines, and produces one markdown report
per run that can be compared across contexts (local Postgres vs. Neon)
and across A/B toggles.

## One-time setup

```bash
cd /Users/nick/Main/amprealize/scripts/perf
npm install
npx playwright install chromium
```

## Capture your auth session

Google OAuth cannot be scripted reliably, so we capture `storageState.json`
once in a headed window and reuse it:

```bash
node auth-login.mjs --base=http://localhost:5173
# Sign in with Google in the opened window, then press Enter.
```

Re-run whenever the Amprealize session expires (the journeys will fail
with a redirect to `/login` when that happens).

## Run the benchmark

```bash
# Neon
amprealize context use neon
breakeramp up cloud-dev
./bench.sh --project=<project-uuid> --board=<board-uuid> --runs=5

# Local Postgres
amprealize context use local
breakeramp up development
./bench.sh --project=<project-uuid> --board=<board-uuid> --runs=5
```

Each invocation creates `./out/<context>-<timestamp>/` containing:

- `run-1.json` … `run-N.json` — Playwright per-run records (marks, HTTP, nav timing).
- `api.log` — full podman api container log for the bench window.
- `api.perf.log` — only the structured `perf …` lines.
- `summary.json` — inputs and per-run index.
- `report.md` — human-readable rollup with p50/p95 per milestone and per API path.

Omit `--project` / `--board` to run only the cold-dashboard journey.

## A/B toggles for Phase 5

```bash
# Disable server-side perf logging (measures logger cost itself)
AMPREALIZE_PERF_LOG=0 breakeramp restart -s amprealize-api
./bench.sh --project=... --board=...

# Enlarge Neon pool
AMPREALIZE_PG_POOL_SIZE=20 AMPREALIZE_PG_POOL_MAX_OVERFLOW=40 \
  breakeramp restart -s amprealize-api
./bench.sh --project=... --board=...
```

Client-side toggles (progressive-hydration sleep, `include_total`, sidebar
`useBoardsMultiProject`, etc.) are made as small code edits on
`perf-audit-wip` between runs — see `docs/perf/CHANGE_INVENTORY.md`.

## Anatomy of the harness

- `auth-login.mjs` — headed Chromium, writes `storageState.json`.
- `run-journeys.mjs` — headless Chromium, `storageState.json` reused; collects
  `performance.getEntriesByType('navigation')`, every `__perfMarks` entry, and
  every observed HTTP response with CDP timing.
- `bench.sh` — wraps all of the above, captures `podman logs --since <t0>`
  for the api container, and invokes `build-report.mjs`.
- `build-report.mjs` — aggregates `run-*.json` + `api.perf.log` into `report.md`.

## The two things the app adds for you

- **Server:** `amprealize/perf_log.py` exposes `perf_span(endpoint, **tags)` /
  `perf_log(...)`. Gated by `AMPREALIZE_PERF_LOG` (default 1). Endpoints
  already instrumented: `boards.list`, `boards.get`, `work_items.list`,
  `work_items.batch`, `dashboard.stats`.
- **Client:** `web-console/src/telemetry/raze.ts` exports `perfMark(name, ctx)`.
  `BoardPage.tsx` and `Dashboard.tsx` emit:
  `board.shell_ready`, `board.first_items_page_ready`, `board.full_hydration_ready`,
  `dashboard.chrome_ready`, `dashboard.agent_panel_ready`.
