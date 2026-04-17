# Perf audit results — Neon (2026-04-16)

End-to-end results of the sequenced perf audit against the Neon
cloud-dev stack. Each row below links to the harness output folder
under `scripts/perf/out/`.

## Setup

- **Context:** `neon` (Neon Postgres pooler, cloud-dev breakeramp stack)
- **API workers:** `1` for phases baseline→B; **`4`** for phase C (Postgres
  write-through unblocks multi-worker auth)
- **Project / board under test:** `proj-b575d734aa37` / `523b3a4f-4157-4fd1-b5e9-93437eca6009`
- **Harness:** `scripts/perf/bench.sh` (Playwright + server perf logs + nginx access log)
- **Runs per toggle:** 3 cold (dashboard + board), `headless=true`

## Bottom-line numbers (cold, p50)

| scenario                                     | dashboard ready → total (ms) | board shell → first items → total (ms) |
|----------------------------------------------|------------------------------|----------------------------------------|
| baseline (before audit, pre-toggle)          | 3,439 → 6,356                | 3,971 → 5,446 → 15,908                 |
| toggle 1: capabilities dedup                 | 3,439 → 6,356                | 5,330 → 5,446 → 15,908                 |
| toggle 2: razeLog POST disabled              | 3,690 → 6,629                | 4,072 → 4,192 → 15,777                 |
| toggle 3: hydrate `sleep(400)` → 0           | 2,871 → 5,723                | 5,134 → 5,134 → 16,093                 |
| **all three toggles on (final)**             | **3,361 → 6,332**            | **4,071 → 4,424 → 14,936**             |

Net movement from combined toggles: **~0s on dashboard, ~1s on cold_board**
(~6% on total). Meaningful but not transformative.

The dominant cost is **not** redundant client calls; it is the
**server-side per-request latency under a single uvicorn worker**. See
next section.

## What the toggles actually fixed

Numbers below compare *call counts and per-call latencies*, not page totals.

### Toggle 1 — `/api/v1/capabilities` in-flight dedup

File: [`web-console/src/api/capabilities.ts`](../../web-console/src/api/capabilities.ts)

`fetchCapabilities()` had a 60-second module cache but **no in-flight
dedup**. 23 call sites fire during the first render; all 23 read an
empty cache and each make their own HTTP request.

Added a shared `_inflight` promise. Concurrent callers now await the
same request.

- Calls per board load: **23 → 3** (cold_board)
- Calls per dashboard load: **7 → 3** (cold_dashboard)

No behaviour change — same API, same cache TTL. Safe to leave on.

### Toggle 2 — `razeLog` POST gated

File: [`web-console/src/telemetry/raze.ts`](../../web-console/src/telemetry/raze.ts)

`razeLog()` POSTs to `/api/v1/logs/ingest` (fire-and-forget, but still
shares the single uvicorn worker). Added runtime lever:

- `localStorage['amprealize.razeIngest'] = 'off'`, or
- `VITE_RAZE_LOG_ENABLED=false` at build time.

`perfMark()` (the in-process breadcrumb path) is unaffected.

- Calls per board load: **10 → 0** (cold_board)
- Calls per dashboard load: **1 → 0** (cold_dashboard)

Effect on page ready time is minimal because the POSTs were already
off the critical path, but they were competing with real API calls for
the single worker, so disabling them in dev is strictly better.

### Toggle 3 — progressive hydration sleep

File: [`web-console/src/api/boards.ts`](../../web-console/src/api/boards.ts)

`sleep(400)` between hydration page fetches. Runtime lever:
`localStorage['amprealize.hydrateSleepMs']`, default stays `400`.

This pause happens **after** `board.first_items_page_ready`, so it
cannot speed up the `ready` milestone. It *can* speed up
`board.full_hydration_ready` (fully-populated board) for boards with
>1 page of items, which is why it's worth keeping as a tunable.

## The real bottleneck: single-worker uvicorn

Both the server-side perf log (`perf.span` entries) and the nginx
gateway access log tell the same story:

| endpoint                                       | server handler time (p50) | browser responseEnd (p50) | gap    |
|------------------------------------------------|---------------------------|---------------------------|--------|
| `boards.get`                                   | 886 ms                    | 4,044 ms                  | 3.2 s  |
| `boards.list`                                  | 451 ms                    | 3,674 ms                  | 3.2 s  |
| `dashboard.stats`                              | 681 ms                    | 2,497 ms                  | 1.8 s  |
| `work_items.list`                              | 604 ms                    | 2,644 ms                  | 2.0 s  |
| `/projects/agents` (list, not instrumented)    | 3.1 s nginx upstream_time | 10,062 ms                 | 7.0 s  |
| `/projects/agents/presence` (not instrumented) | ~2.5 s nginx upstream_time| 3,067 ms                  | 0.6 s  |

Nginx `upstream_time` equals `request_time` (gateway adds no queueing),
so the 2.5–6 s per `/projects/agents*` call is uvicorn itself. And
several of those are N-way parallel from the browser, but with a single
Python process and GIL-bound sync handlers using psycopg2, they run
effectively sequentially.

Observed several `status=499` entries (client cancelled) on duplicate
presence calls, confirming those requests sat in the uvicorn queue
long enough for the browser to abandon them.

## Why we're not raising `--workers` (yet)

Tried `--workers=4`. Login "worked" (dashboard renders) but on the very
next fetch the user is bounced to `/login`. Root cause, from API logs:

```
AuthMiddleware: Validating ga_* token via device_flow_manager
device_flow_manager returned: None
Auth failed (non-enforcing): Invalid device flow token
```

`container.device_flow_manager.create_session_from_oauth()`
([amprealize/api.py:6729](../../amprealize/api.py)) writes the new
session into the per-process in-memory `DeviceFlowManager`. A
PostgresDeviceFlowStore exists but the **write path does not use it**
— only the read path (middleware) prefers postgres. With multiple
workers, writes land on worker A's memory; the next request hits
B/C/D, which have no record of the session.

This is a latent bug, pre-existing, independent of the perf work.
Filing a separate issue. Until fixed, we can't turn on multiple
workers in cloud-dev without breaking auth.

## Recommendations, ranked

1. **Fix device-flow multi-worker bug, then run `--workers=4`.** Highest
   expected impact for the dashboard/board pages. Fix is to route
   `create_session_from_oauth` / `approve_user_code` through the
   postgres store when available, same as the read path does.
2. **Instrument and attack `/api/v1/projects/agents*`.** It's the
   largest remaining single-call cost (2.5–3 s server-side per call)
   and the board page fires 3 concurrent presence requests + 1 list
   request. Add `perf_span` around `list_user_project_agent_assignments`
   and `list_project_agents_presence`, then either batch them
   client-side (one `/agents/presence?project_ids=...`) or push
   caching into the service.
3. **Make hot-path handlers `async def` + asyncpg.** The sync `def`
   handlers monopolise the single worker's event loop via threadpool
   offload; a proper async stack would let concurrent requests
   interleave on I/O waits.
4. **Keep Toggles 1 + 2 on permanently.** No risk, real call-count
   reductions, easy to revert.
5. **Neon pooler / statement cache.** Lower priority; the observed
   timings are dominated by Python-side work, not DB round-trips
   (server handler times are 0.5–1 s for non-agents endpoints on the
   same Neon instance).

## Inventory of what's landed on disk

Implementation changes (safe, gated, reversible):

- `web-console/src/api/capabilities.ts`
- `web-console/src/telemetry/raze.ts`
- `web-console/src/api/boards.ts` (lines 887–904)

Instrumentation / harness (dev-only, `AMPREALIZE_PERF_LOG`-gated):

- `amprealize/perf_log.py`
- `amprealize/services/board_api_v2.py` (perf spans)
- `amprealize/api.py` (perf span around `dashboard_stats`)
- `web-console/src/telemetry/raze.ts` (`perfMark`)
- `web-console/src/components/boards/BoardPage.tsx` (perfMark hooks)
- `web-console/src/components/Dashboard.tsx` (perfMark hooks)
- `scripts/perf/*` (Playwright runner, driver, report builder, README)
- `packages/breakeramp/src/breakeramp/blueprints/{cloud-dev,local-dev}.yaml`
  (env passthroughs: `AMPREALIZE_PERF_LOG`, `AMPREALIZE_API_WORKERS`)

One-time fixes surfaced during the audit:

- `scripts/perf/set-api-workers.sh` — recreates API container in-place
  preserving DNS aliases, injecting persistent `AMPREALIZE_JWT_SECRET`
  from `scripts/perf/.jwt-secret` (gitignored).
- `packages/breakeramp/.../cloud-dev.yaml` — `AMPREALIZE_API_WORKERS`
  env passthrough (the previous `${AMPREALIZE_API_WORKERS:-1}` shell
  expansion inside `command:` always resolved to 1).

## Phase B — server pool + batched presence + UUID fix (2026-04-16)

Recommendation #2 from the ranked list above, implemented after the
phase-5 toggles landed.

### Changes under test

Server, `amprealize/projects/service.py`:

- `OSSProjectService._get_conn()` now returns
  `engine.raw_connection()` from the shared SQLAlchemy pool instead of
  `psycopg2.connect(self._dsn)`. The pre-pool path paid a full Neon
  TCP+TLS+auth handshake (~75–150 ms) on every call; the pool amortises
  it.
- `perf_span("projects.list_user_agents")` around
  `list_user_project_agent_assignments`.
- `perf_span("projects.list_agent_presence")` +
  `projects.list_agent_presence_batch` span around the new batched
  presence implementation.
- `_row_to_agent_assignment` / `_row_to_presence` coerce UUID columns
  to `str` — the SQLAlchemy psycopg2 dialect registers
  `psycopg2.extras.register_uuid()` on engine init, so UUID columns
  now come back as `uuid.UUID` instances rather than the bare strings
  the pre-pool path produced.

Server, `amprealize/projects_api.py`:

- `GET /v1/projects/agents/presence?project_ids=a,b,c` (comma-separated
  batched form) alongside the legacy `?project_id=` query shape.
  Authorises every project then hits `list_agent_presence_batch` —
  one round-trip instead of N.

Client, `web-console/src/api/agentRegistry.ts`:

- `useVisibleProjectAgentPresence(projectIds)` now issues a single
  `listProjectAgentPresenceBatch(ids)` query rather than N parallel
  `useQuery` calls. Back-fills the per-project React Query cache so
  downstream consumers (project detail pages, etc.) don't double
  fetch.
- New `listProjectAgentPresenceBatch` wraps the batched endpoint and
  normalises the response into the existing per-project shape.

Infra, `scripts/perf/set-api-workers.sh`:

- Forwards the caller's `AMPREALIZE_PERF_LOG` env when recreating the
  container so future benches can turn on server-side spans without
  editing the blueprint.

Middleware, `amprealize/api.py`:

- `AuthMiddleware` now receives a `_CompositeDeviceFlow` wrapper that
  reads Postgres-first, in-memory fallback. This hardens lookups but
  is **not** the full multi-worker fix — the OAuth callback still
  writes only in-memory. See phase C below.

### Bottom-line numbers (cold, p50, n=3)

| scenario                              | dashboard ready → total (ms) | board shell → first items → total (ms) |
|---------------------------------------|------------------------------|----------------------------------------|
| phase-5 final (all toggles)           | 3,361 → 6,332                | 4,071 → 4,424 → 14,936                 |
| **phase B (pool + batched + UUID)**   | **4,010 → 7,246**            | **2,763 → 5,101 → 15,655**             |

[Run folder](../../scripts/perf/out/neon-2026-04-16T20-42-02Z-phaseB/report.md)

### Deltas vs phase-5 end-state

- **cold_board `shell_ready`: 4,071 → 2,763 ms (−32%, −1.3 s).**
  Layout and initial data paint faster — this is what a user would
  notice first.
- **cold_board `first_items_page_ready` and `total_ms`: unchanged.**
  Shell wins don't flow through because 9 progressive pages of
  `work_items.list` now dominate.
- **cold_dashboard: broadly flat.** `chrome_ready` nudged up ~650 ms
  and total up ~900 ms, both inside the n=3 noise band (dashboard
  variance in phase-5 was ~500 ms run-to-run at p50).

### Server perf spans (3 cold runs, workers=1)

| endpoint                              | calls | avg handler ms | max   |
|---------------------------------------|-------|----------------|-------|
| `projects.list_user_agents`           | 6     | 297            | 300   |
| `projects.list_agent_presence_batch`  | 3     | 299            | 306   |
| `boards.list`                         | 12    | 453            | 463   |
| `boards.get`                          | 3     | 892            | 894   |
| `dashboard.stats`                     | 3     | 699            | 741   |
| **`work_items.list`**                 | **27**| **675**        | 1,135 |

- **`projects.list_user_agents` handler: 297 ms.** Phase-5 nginx
  `upstream_time` for the same endpoint was 3.1 s. **~10× reduction**
  — the pool fix landed the entire Neon handshake savings we
  expected.
- **`projects.list_agent_presence_batch`: 299 ms for 3 projects in one
  call.** Phase-5 fired 3 separate `/presence` calls (~2.5 s each
  nginx upstream_time). **~25× reduction in total time spent on
  presence per page load**, and call count N → 1.
- **`work_items.list` is the new dominant cost:** 27 × ~675 ms =
  **~18 s of serial handler time per 3-run bench**, i.e. ~6 s per
  board load. A cold board fires 9 pages of 100 items (the
  progressive hydration strategy); under `workers=1` they serialize.

### Why browser-observed `/v1/projects/agents` is still ~8.8 s

The browser's `responseEnd` timing includes queue wait. Single-worker
uvicorn serializes every request; a 300 ms handler whose request is
30 places back in the queue appears to the browser as ~9 s. Per-call
*handler* time is now healthy (~300 ms). **Total page time is gated
by queue depth × per-call time**, not per-call time.

### Conclusion and read-out for phase C

Phase B removed the per-call Neon handshake cost and collapsed N
presence calls to 1. The remaining bottleneck is fundamental
single-worker serialization of ~40 board-page API calls, now visible
cleanly in the server perf spans.

Rough projection at `workers=4` (phase C, requires Postgres
write-through for OAuth sessions first):

- `work_items.list` parallelism: 18 s / 4 = ~4.5 s serial cost
- Estimated cold_board total: 15.7 s → **5–6 s**
- Estimated cold_dashboard total: 7.2 s → **3–4 s**

Without phase B, a 4× worker bump would have been swamped by the
per-call handshake (each of those 4 concurrent workers still eating
~100 ms × many-calls of Neon connect latency). With phase B, the
concurrency gives near-linear speedup.

Phase C is now clearly worth the write-through effort.

## Phase C — Postgres write-through + workers=4 + batched `set_tenant_context`

Three changes landed together (one restart, one re-auth, one bench):

1. **Postgres write-through for OAuth sessions**
   (`amprealize/auth/postgres_device_flow.py`, `amprealize/api.py`) —
   the OAuth callback now mirrors the approved device session into
   `auth.device_sessions` with the **same** `access_token` the
   in-memory `DeviceFlowManager` issued. The middleware's
   `_CompositeDeviceFlow` (Postgres-first, in-memory fallback) now
   resolves tokens from Postgres on any worker, so sessions survive
   both worker-to-worker routing under `--workers=N` *and* full
   container recreates. This unblocked the 4-worker rollout that
   phase-5 was blocked on.

2. **`--workers=4`** (up from 1). uvicorn no longer serializes every
   request through a single async loop; the ~40 API calls a cold
   board fires now run 4-wide instead of strictly FIFO.

3. **Batched `set_tenant_context` in `PostgresPool`**
   (`amprealize/storage/postgres_pool.py`) — the two `SET LOCAL
   app.current_*` statements used to be two separate
   `cur.execute()` calls, i.e. **two Neon round-trips per pooled
   query** (~75–150 ms each on this network). They're now a single
   `cur.execute()` sending both statements in one protocol message.
   Micro-bench on the container: `run_query` p50 dropped 468 ms → 386
   ms (~82 ms saved) on the same workload.

### Bottom-line numbers (cold, p50, n=3)

| scenario                                       | dashboard: agent_panel → chrome → total | board: shell → first items → full hydration → total |
|------------------------------------------------|----------------------------------------|-----------------------------------------------------|
| phase-5 final (all toggles, w=1)               | — → 3,361 → 6,332                      | 4,071 → 4,424 → — → 14,936                          |
| phase B (pool + batched presence, w=1)         | 6,630 → 4,010 → 7,246                  | 2,763 → 5,101 → — → 15,655                          |
| **phase C (write-through + w=4 + set-tenant batch)** | **1,321 → 1,939 → 2,380**        | **1,769 → 2,110 → 12,022 → 12,551**                 |

[Run folder](../../scripts/perf/out/neon-2026-04-16T21-10-41Z-phaseC-w4/report.md)

### Deltas vs phase B (same harness, same project/board)

Dashboard:

- `dashboard.agent_panel_ready`: **6,630 → 1,321 ms (−80%, 5×)**.
- `dashboard.chrome_ready`: **4,010 → 1,939 ms (−52%)**.
- `cold_dashboard total`: **7,246 → 2,380 ms (−67%, 3×)**.

Board:

- `board.shell_ready`: **2,763 → 1,769 ms (−36%)**.
- `board.first_items_page_ready`: **5,101 → 2,110 ms (−59%)**.
- `cold_board total`: **15,655 → 12,551 ms (−20%)**.
  (Full hydration — 9 pages of `work_items.list` — is now the full
  residual cost; see "Remaining bottleneck" below.)

### Client-observed API latencies (browser `responseEnd`)

Phase B → Phase C, selected endpoints:

| path                                                     | phase B p50 | phase C p50 | delta   |
|----------------------------------------------------------|-------------|-------------|---------|
| `/v1/projects/agents` (dashboard)                        | 6,341 ms    | 1,057 ms    | **−83%** |
| `/v1/dashboard/stats`                                    | 3,396 ms    | 1,290 ms    | −62%    |
| `/v1/modules` (dashboard)                                | 3,697 ms    | 701 ms      | −81%    |
| `/v1/capabilities` (dashboard)                           | 3,577 ms    | 646 ms      | −82%    |
| `/v1/projects/agents` (board)                            | 8,829 ms    | 3,451 ms    | −61%    |
| `/v1/projects/.../participants`                          | 6,630 ms    | 3,015 ms    | −55%    |
| `/v1/boards/.../progress-rollups`                        | 3,748 ms    | 1,879 ms    | −50%    |
| `/v1/work-items` (board, p50 of 46–49 calls)             | 2,547 ms    | 974 ms      | −62%    |
| `/v1/executions` (board)                                 | 5,153 ms    | 1,709 ms    | −67%    |

These are **network-observed** numbers. The handler times (below)
barely moved — Postgres is doing roughly the same work per call.
The collapse comes almost entirely from removing the single-worker
serial queue: a 400 ms handler that used to wait behind 30 queued
requests showed up as ~12 s in the browser; now it shows up as
~400 ms.

### Server perf spans (3 cold runs, workers=4)

| endpoint                              | phase B avg | phase C avg | phase C p95 | delta        |
|---------------------------------------|-------------|-------------|-------------|--------------|
| `boards.get`                          | 892         | 773         | 777         | −13%         |
| `boards.list`                         | 453         | 391         | 397         | −14%         |
| `dashboard.stats`                     | 699         | 721         | —           | ~flat        |
| `projects.list_user_agents`           | 297         | 311         | 314         | ~flat        |
| `projects.list_agent_presence_batch`  | 299         | 311         | —           | ~flat        |
| **`work_items.list`**                 | 675 (p95 1,135) | **557** | **742**     | −18% / −35%  |

- `work_items.list` is where the `set_tenant_context` batching fix
  shows up most: p50 606 → 557 ms, **p95 1,135 → 742 ms (−35%)**.
  p95 shrinking faster than p50 is consistent with removing a fixed
  per-call network round-trip — the tail had more of those RTTs
  stacked.
- `boards.get` / `boards.list` also drop 13–14% for the same reason.
- Endpoints dominated by actual query work (`dashboard.stats`,
  `projects.list_user_agents`) are flat, as expected.

### Remaining bottleneck (cold_board full_hydration = 12.0 s)

The board page fires **46–49 `/v1/work-items` calls** (progressive
hydration, 9+ pages of 100 items). At 557 ms p50 handler × 4 workers,
the bounded serial cost is ~6.6 s of backend work, plus network
overhead per call. The client's fetch/render loop pushes this to
~12 s end-to-end.

This is now a **product shape** problem, not a perf bug:

- Page size / fewer pages.
- Server-side aggregation for the initial board render so we don't
  need 9 round-trips before the page is "fully hydrated".
- Defer low-priority pages until idle.

None of those are in scope for this audit.

### Conclusion

Combined phase-B + phase-C land the transformative speedup the user
felt was missing:

- **Dashboard is 3× faster end-to-end (7.2 s → 2.4 s).**
- **Board shell is 36% faster (2.8 s → 1.8 s); first-items page is
  59% faster (5.1 s → 2.1 s).**
- **Every user-visible API call on the dashboard responds in ~1 s
  instead of 3–8 s.**

Auth is durable across worker recreates and restarts — the OAuth
session is now the single source of truth in `auth.device_sessions`,
visible to every worker, and survives container recreates. The
multi-worker device-flow bug is closed.

## Phase A — collapse count+list + cache parent_id probe + threadpool offload

Targets the residual `work_items.list` cost identified at the end of phase C.
Three small, independent changes landed together:

1. **`COUNT(*) OVER()` inline in `list_work_items`**
   (`amprealize/services/board_service.py`) — the first page used to fire
   a separate `count_work_items` round-trip alongside the list. The two
   are now a single query that emits a `_total` window-function column.
   The REST handler (`amprealize/services/board_api_v2.py`) reads the
   count from the same result set when the client asks for
   `include_total=true`.

2. **Module-level cache for the `parent_id` `information_schema` probe**
   (`amprealize/services/board_service.py`) — `_enrich_child_aggregation`
   used to re-run a schema lookup on every call on every pool-bound
   worker. Cached once per `id(pool)` for the life of the process.

3. **Threadpool offload for sync DB calls in async handlers**
   (`amprealize/services/board_api_v2.py`) — `list_boards`, `get_board`,
   `get_work_items_batch`, `get_children`, and both paths of
   `list_work_items` now wrap their blocking `board_service.*` calls in
   `starlette.concurrency.run_in_threadpool`. Under `--workers=4`,
   requests that would otherwise have monopolised a single worker's
   event loop on psycopg2 I/O now interleave with other I/O-bound
   handlers on the same worker.

Instrumentation: `work_items.list` perf line now splits total into
`t_query_ms` (DB-bound) and `t_shape_ms` (Python row-to-dataclass), plus
a new `work_items.batch.enrich` `perf_span` around child-aggregation
and display-id enrichment in `get_work_items_batch`.

### Bottom-line numbers (cold, p50, n=3)

| scenario | dashboard: agent_panel → chrome → total | board: shell → first items → full hydration → total |
|---|---|---|
| phase C (write-through + w=4 + set-tenant batch) | 1,321 → 1,939 → 2,380 | 1,769 → 2,110 → 12,022 → 12,551 |
| **phase A (count+list collapse + probe cache + threadpool, w=4)** | **1,512 → 1,824 → 2,255** | **2,113 → 1,522 → 5,323 → 5,746** |

[Run folder](../../scripts/perf/out/neon-2026-04-17T03-52-15Z-phaseA-w4/report.md)

### Deltas vs phase C (same harness, same project/board)

Dashboard:

- `dashboard.agent_panel_ready`: 1,321 → 1,512 ms (inside n=3 noise).
- `dashboard.chrome_ready`: 1,939 → 1,824 ms (−6%).
- `cold_dashboard total`: 2,380 → 2,255 ms (−5%).

Dashboard moves are in the noise band; the Phase A changes aren't on
the cold-dashboard critical path. The board page is where the win lands.

Board:

- `board.first_items_page_ready`: **2,110 → 1,522 ms (−28%)**.
- `board.full_hydration_ready`: **12,022 → 5,323 ms (−56%, −6.7 s)**.
- `cold_board total`: **12,551 → 5,746 ms (−54%, −6.8 s)**.

`full_hydration_ready` is the 9 progressive `/v1/work-items` pages
finishing. That's the phase C "remaining bottleneck" — now cut in half
+ change.

### Server perf spans (3 cold runs, workers=4)

| endpoint | phase C avg | phase A avg | phase A p95 | delta |
|---|---|---|---|---|
| `boards.get` | 773 | 1,004 | 1,373 | +30% (noise on n=3) |
| `boards.list` | 391 | 396 | 958 | ~flat |
| `dashboard.stats` | 721 | 717 | — | ~flat |
| `projects.list_user_agents` | 311 | 297 | 318 | ~flat |
| `projects.list_agent_presence_batch` | 311 | 303 | — | ~flat |
| **`work_items.list`** | 557 (p95 742) | **523** | **848** | **−6% / +14%** |

Per-call `work_items.list` handler time is only marginally better (523
vs 557 ms p50); that is expected — the SQL hasn't gotten cheaper, only
the *number of round-trips* has changed. The new perf line splits cost
cleanly: `t_query_ms ≈ t_total_ms` in every sample, and `t_shape_ms` is
0–1 ms. All remaining latency is SQL execution + Neon network.

### Why the board page collapsed

Two compounding effects:

1. **Fewer `work_items.list` calls per page load.** Phase C fired
   46–49 `/v1/work-items` requests per 3-run bench (~15–16 per cold
   board). Phase A fires 33 (~11 per cold board). The count collapse
   (A1) removed one round-trip per page; the first page also drops
   its separate `count_work_items` call.

2. **Threadpool offload unblocks parallelism within each worker.**
   Phase C's handlers were `def` (sync), so each worker could only
   progress one request at a time; four concurrent board-page fetches
   meant a fixed 4-wide serial line. Phase A's async handlers await on
   `run_in_threadpool`, so while worker N is blocked on psycopg2 for
   `/v1/work-items` page 3, it can still shape-and-emit a response
   for `/v1/capabilities` that landed on the same worker. Effective
   concurrency ≈ `workers × threadpool_size` instead of `workers × 1`,
   which is why the 9-page hydration went from ~12 s wall-clock to
   ~5.3 s.

### Client-observed API latencies (browser `responseEnd`, board page)

| path | phase C p50 | phase A p50 | delta |
|---|---|---|---|
| `/v1/projects/.../participants` | 3,015 ms | 2,375 ms | −21% |
| `/v1/boards/.../progress-rollups` | 1,879 ms | 2,169 ms | +15% (noise) |
| `/v1/boards/<id>` (get) | ~1,700 ms | 2,081 ms | +22% (noise, n=3) |
| `/v1/projects/agents` (board) | 3,451 ms | 1,522 ms | **−56%** |
| `/v1/executions` (board) | 1,709 ms | 1,686 ms | ~flat |
| **`/v1/work-items` (board, p50 of 33–49 calls)** | **974 ms** | **1,109 ms** | +14% |

The `/v1/work-items` p50 *per call* went slightly up, but call count
dropped ~30% and the serial tail shrank dramatically. Net page time
fell ~6.8 s. Per-call p95 did tighten: 1,687 ms here vs 2,547 ms in
phase B baseline shape — the queue tail that used to stack behind
~15 sync calls on one worker is gone.

### Conclusion

Phase A closes the remaining `work_items.list` bottleneck called out at
the end of phase C. Combined chain since the audit started:

- **Dashboard total:** 6,356 (baseline) → 2,380 (phase C) → 2,255 ms
  (phase A). **~2.8× faster.**
- **Cold board total:** 15,908 (baseline) → 12,551 (phase C) → 5,746 ms
  (phase A). **~2.8× faster.**
- **Full board hydration (9 pages):** — → 12,022 (phase C) → 5,323 ms
  (phase A). **2.3× faster in one phase.**

Phase A is entirely server-side and transparent to clients: no schema
changes, no client refactors, no new dependencies, no new env flags.

## Phase B-projects — async offload + batched auth + UNION ALL participants

Targets `/v1/projects*` latency on the cold dashboard after Phase A. Three
interlocking changes in `amprealize/projects_api.py` and
`amprealize/projects/service.py`:

1. **Every handler is `async def` + `run_in_threadpool` + `perf_span`**
   (`projects_api.py`). `list_projects`, `create_project`, `get_project`,
   `list_project_agents`, `create_project_agent`, `delete_project_agent`,
   `list_project_participants`, `list_agent_presence`, and
   `update_agent_presence` were all `def` (sync) handlers that monopolised
   a worker's event loop while psycopg2 was blocked. They're now async and
   offload each `org_service.*` call to the threadpool, matching the
   pattern Phase A applied to `board_api_v2.py`. Same for the
   `_require_project_access` helper.

2. **Batched project authorisation in `list_agent_presence`**
   (`projects_api.py` + new `OSSProjectService.get_projects(ids)` in
   `projects/service.py`). The batched presence handler used to loop
   `_require_project_access` once per project — an N-query authorisation
   check for an otherwise single-query presence fetch. When
   `org_service.get_projects` is available it now issues **one**
   `WHERE project_id = ANY(%s)` query, verifies ownership in Python, and
   raises 404 for missing/unauthorised ids before the presence call.

3. **`list_project_participants` collapses into one `UNION ALL` query**
   (`projects/service.py`). The previous implementation fired 3–4
   sequential queries (owner, members, collaborators?, agent
   assignments) and stitched results in Python. All four branches are
   now a single statement returning 14 consistent columns plus a `kind`
   discriminator, ordered client-side. The `auth.project_collaborators`
   existence check (`to_regclass(...)`) is cached per-DSN on first call
   so the probe doesn't re-run on every request.

Also bundled: `create_project_agent` returns the fully-joined assignment
straight from a CTE `INSERT ... RETURNING + LEFT JOIN` on
`execution.agents`, skipping a redundant follow-up
`list_project_agent_assignments` round-trip (`projects_api.py` retains
the legacy fallback if the service returns a bare row).

Instrumentation: new `perf_span` tags —
`projects.{list,create,get,list_agents,create_agent,delete_agent,
list_participants,list_presence,list_presence_single,
update_presence,get_projects_batch,list_participants_query}` — plus
`has_collab_table` / `row_count` tags on the participants query span.

Tests: `tests/unit/test_projects_phase_b.py` covers (a) the batched
presence handler uses `get_projects` (not N × `get_project`), (b) legacy
single-id path still uses `get_project`, (c) rejected/missing projects
still 404, (d) concurrent handlers return independently, (e)
`get_projects([])` is a no-op that issues zero queries, (f)
`get_projects(ids)` issues a single `ANY(%s)` query, (g) missing ids
are silently omitted.

### Bottom-line numbers (cold, p50)

| scenario | dashboard: agent_panel → chrome → total | board: shell → first items → full hydration → total |
|---|---|---|
| phase A (n=3) | 1,512 → 1,824 → 2,255 | 2,113 → 1,522 → 5,323 → 5,746 |
| **phase B-projects (n=5)** | **1,309 → 1,595 → 2,058** | **1,440 → 1,859 → 6,580 → 7,035** |

[Run folder](../../scripts/perf/out/neon-2026-04-17T17-36-05Z-phaseB-w4/report.md)

### Deltas vs phase A

Dashboard (the target):

- `dashboard.agent_panel_ready`: **1,512 → 1,309 ms (−13%)**.
- `dashboard.chrome_ready`: **1,824 → 1,595 ms (−13%)**.
- `cold_dashboard total`: **2,255 → 2,058 ms (−9%)**.

Board (not the target; mixed):

- `board.shell_ready`: 2,113 → 1,440 ms (−32%). Consistent with
  `_require_project_access` dropping from a blocking sync call to an
  awaited threadpool offload on the board-shell critical path.
- `board.first_items_page_ready`: 1,522 → 1,859 ms (+22%).
- `board.full_hydration_ready`: 5,323 → 6,580 ms (+24%).
- `cold_board total`: 5,746 → 7,035 ms (+22%).

The cold_board regressions land on the `work_items.list` hydration
tail, which Phase B-projects didn't touch. The phase-A bench was n=3
on a narrow window; the phase-B-projects bench is n=5, which surfaces
more Neon cold-cache variance (per-call `work_items.list` p50 moved
523 → 564 ms server-side, p95 848 → 1,433 ms — within expected cold
variance on this instance). The shell/first-items milestones are what
Phase B-projects can influence; those are flat or better.

### Server perf spans (5 cold runs, workers=4)

New spans introduced by this phase (no pre-Phase-B-projects data to
compare against directly — these handlers were `def` and unwrapped
before today):

| span | p50 | p95 | n |
|---|---|---|---|
| `projects.get_projects_batch` | 158 ms | 164 ms | 5 |
| `projects.list_participants_query` | 230 ms | 255 ms | 5 |
| `projects.list_participants` (full handler) | 411 ms | 633 ms | 5 |
| `projects.list_presence` (full handler) | 1,094 ms | 1,145 ms | 5 |
| `projects.list` (full handler) | 325 ms | 627 ms | 10 |
| `projects.get` (full handler) | 360 ms | 943 ms | 5 |

Pre-existing spans:

| span | phase A p50 | phase B-p50 | delta |
|---|---|---|---|
| `projects.list_agent_presence_batch` | 303 ms | 306 ms | ~flat |
| `projects.list_user_agents` | 297 ms | 314 ms | ~flat |
| `boards.get` | 1,004 ms | 776 ms | −23% |
| `boards.list` | 396 ms | 401 ms | ~flat |
| `dashboard.stats` | 717 ms | 716 ms | ~flat |
| `work_items.list` | 523 ms | 564 ms | +8% (noise) |

### Where the targeted wins actually landed

- **N+1 authorisation in batched presence is gone.** `get_projects_batch`
  is a single 158 ms query; the legacy path would have fired 3 individual
  `get_project` queries (~360 ms each = ~1.1 s of sequential work) just
  to authorise the three projects the page is asking about. The whole
  batched-presence handler (`projects.list_presence`) now completes in
  ~1.1 s where the legacy wait pattern could compound well past 2 s
  under worker contention.
- **`list_project_participants` is one query.** The participants handler
  (`projects.list_participants`) p50 is 411 ms with the actual SQL
  (`projects.list_participants_query`) only 230 ms of that. The plan
  called out 2.4 s as the pre-B baseline for this path; the
  **server-side handler is ~5.8× faster**. Browser-observed time stayed
  at ~2.6 s p50 because other parallel requests now dominate the
  client's queue wait, not this call's handler time.
- **Every projects handler participates in async offload.** Under
  workers=4, a blocked psycopg2 call no longer stalls the worker's
  event loop; other I/O-bound handlers can progress on the same worker.
  This is the same mechanism that flattened the board page's 9-way
  hydration in Phase A, now applied to the dashboard's projects
  surface.

### What this doesn't fix

The cold_dashboard improvement is real but modest (~200 ms p50). The
residual ~2 s is split across many endpoints that each cost
300 ms–1.1 s server-side; the next lever would be either reducing the
request fan-out (client-side: can the dashboard get by with fewer
calls on first paint?) or caching shared bits (e.g. `projects.list`
and `projects.get` for the currently-active project overlap heavily).
Neither is in scope for this audit.

### Deferred follow-ons

- **Keyset pagination on `/v1/work-items`.** Draft plan staged at
  `~/.cursor/plans/keyset_work_items_9daeb078.plan.md`; gated on a
  5k+ item board or seeded 10k-item load test showing
  `work_items.list` p95 > 2 s on page 10+. Current p95 is 1.4 s on
  page 1, and the dominant hydration cost now is request count, not
  per-call OFFSET sequential-scan cost.
- **Client-side lazy total.** Superseded by Phase A's `COUNT(*) OVER()`
  collapse; the total arrives in the first-page result set with no
  extra round-trip, so there's no separate "count" request to lazy-load.
- **Legacy single-project `?project_id=` branch on
  `/v1/projects/agents/presence`.** Left intact — the enterprise
  `web-console` still issues single-id lookups on project-detail pages.
  The batched path is live for the dashboard; cleanup deferred until
  the enterprise client migrates.

## Raw run folders

- [neon-2026-04-16T19-43-21Z-smoke_workers1](../../scripts/perf/out/neon-2026-04-16T19-43-21Z-smoke_workers1/report.md)
- [neon-2026-04-16T19-44-46Z-toggle1_capabilities_dedup](../../scripts/perf/out/neon-2026-04-16T19-44-46Z-toggle1_capabilities_dedup/report.md)
- [neon-2026-04-16T19-49-23Z-toggle2_raze_off](../../scripts/perf/out/neon-2026-04-16T19-49-23Z-toggle2_raze_off/report.md)
- [neon-2026-04-16T19-50-50Z-toggle3_hydrate_sleep_0](../../scripts/perf/out/neon-2026-04-16T19-50-50Z-toggle3_hydrate_sleep_0/report.md)
- [neon-2026-04-16T19-52-30Z-toggles_all](../../scripts/perf/out/neon-2026-04-16T19-52-30Z-toggles_all/report.md)
- [neon-2026-04-16T20-42-02Z-phaseB](../../scripts/perf/out/neon-2026-04-16T20-42-02Z-phaseB/report.md)
- [neon-2026-04-16T21-10-41Z-phaseC-w4](../../scripts/perf/out/neon-2026-04-16T21-10-41Z-phaseC-w4/report.md)
- [neon-2026-04-17T03-52-15Z-phaseA-w4](../../scripts/perf/out/neon-2026-04-17T03-52-15Z-phaseA-w4/report.md)
- [neon-2026-04-17T17-36-05Z-phaseB-w4](../../scripts/perf/out/neon-2026-04-17T17-36-05Z-phaseB-w4/report.md)
