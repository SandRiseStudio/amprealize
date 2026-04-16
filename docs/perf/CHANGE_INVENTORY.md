# Perf change inventory

Snapshot: `pre-perf-audit-20260416` on branch `perf-audit-wip`.
Baseline for comparison: commit `0d88595` ("Initial commit: Amprealize OSS v0.1.0").

Each row has a `status:` that gets updated as Phase 5 attribution runs.
Values: `unverified` (default) / `helped` / `hurt` / `no-op` / `reverted`.

> **See [RESULTS.md](RESULTS.md) for the full phase-5 findings.** The
> single biggest takeaway: dashboard/board page latency is dominated
> by per-request time under a single uvicorn worker — many API calls
> cost 500 ms–3 s in the handler itself, and a dozen+ calls fire
> concurrently on page load. Client-side dedup and telemetry-POST
> toggles recover ~1 s on cold_board but leave ~15 s on the floor. The
> next win requires raising the worker count (blocked by a latent
> multi-worker device-flow bug, documented there) and/or making the
> hot-path handlers properly async.

## backend-pooling

| File | Change | Hypothesis | Status |
|------|--------|------------|--------|
| [amprealize/storage/postgres_pool.py](../../amprealize/storage/postgres_pool.py) | Detect cloud DSNs (`neon.tech`, etc.); for cloud shorten `pool_recycle` (270 vs 1800), raise `connect_timeout` (10 vs 5), smaller default `pool_size`/`max_overflow` (5/10 vs 10/20 when settings unavailable). Register SQLAlchemy `connect` event handler that runs `SET search_path = …` once per physical connection; `set_tenant_context` no longer runs `SET LOCAL search_path` per request. | Cloud-specific tuning; eliminate ~75ms Neon RTT per connection checkout. | unverified |
| [amprealize/api.py](../../amprealize/api.py) | Call `apply_context_to_environment(force=True)` early so active context DSN (e.g. Neon) overrides a stale `.env` localhost URL. | Ensure API actually connects to the context the user selected. | unverified |

## db-index

| File | Change | Hypothesis | Status |
|------|--------|------------|--------|
| [migrations/versions/20260415_board_item_perf_indexes.py](../../migrations/versions/20260415_board_item_perf_indexes.py) | `board.work_items` indexes: `(board_id, position, created_at)`, partial `(parent_id) WHERE parent_id IS NOT NULL`, GIN on `labels`. | Speed up the board list query and child aggregation lateral join. | unverified |

## backend-query

| File | Change | Hypothesis | Status |
|------|--------|------------|--------|
| [amprealize/services/board_service.py](../../amprealize/services/board_service.py) | `list_work_items` uses `LEFT JOIN LATERAL` for per-row child counts/completion; joins `auth.projects` so `display_id` is filled without a second pass; multi-value filters via `ANY(%s)`; `__unassigned__` assignee; fast-path skipping child-agg query when `parent_id` column absent; new `get_work_items_batch(WHERE id = ANY(%s))`; `count_work_items()` reused. | Fewer round-trips for board lists; bulk hydration path for ancestor items. | unverified |
| [amprealize/services/board_api_v2.py](../../amprealize/services/board_api_v2.py) | `GET /v1/work-items` adds `include_total` query param; when `false` uses `limit+1` to infer `has_more` without `COUNT(*)`; `POST /v1/work-items/batch` for bulk hydration. | Avoid `COUNT(*)` on every page; progressive paging. | unverified |
| [amprealize/api.py](../../amprealize/api.py) | Register `GZipMiddleware` (min 1000 bytes) before CORS. | Cut over-the-wire JSON size on dashboard/board responses. | unverified |

## frontend-data-fetch

| File | Change | Hypothesis | Status |
|------|--------|------------|--------|
| [web-console/src/api/boards.ts](../../web-console/src/api/boards.ts) | `useWorkItems` fetches page 1 with `include_total: true`, then background pages with `include_total: false`; `keepPreviousData`; `staleTime: 5m`, `gcTime: 15m`; polling disabled; `useBoardsMultiProject` parallel per-project via `Promise.allSettled` seeding `boardKeys.list`; ancestor hydration via `POST /v1/work-items/batch`; `fetchAllWorkItemsPaged` for full resync; mutation-aware cancel helpers; **400ms `sleep` between progressive pages** (now `localStorage['amprealize.hydrateSleepMs']`-tunable, default preserved). | Show first page fast, hydrate rest in background without hammering Neon. | no-op on `ready_ms` (post-ready pacing); kept as tunable |
| [web-console/src/api/capabilities.ts](../../web-console/src/api/capabilities.ts) | **Phase-5 Toggle 1.** Added `_inflight` shared promise in `fetchCapabilities` so concurrent call sites dedup a single HTTP request per TTL window. | 23 concurrent callers all missed an empty module cache, each firing its own `/v1/capabilities`. | helped (23 → 3 calls on cold_board) |
| [web-console/src/telemetry/raze.ts](../../web-console/src/telemetry/raze.ts) | **Phase-5 Toggle 2.** `razeLog()` POST now honours `VITE_RAZE_LOG_ENABLED=false` build flag or `localStorage['amprealize.razeIngest']='off'` runtime flag. `perfMark()` path unchanged. | 10 ingest POSTs per board load competed with real API calls on the single worker. | helped (10 → 0 calls on cold_board) |
| [web-console/src/api/dashboard.ts](../../web-console/src/api/dashboard.ts) | `useDashboardStats` failure returns zeroed `EMPTY_STATS` instead of fanning out to 4 fallback endpoints; `useOrganizations` prefers `/v1/orgs`, falls back to `/v1/organizations` only on 404. | Remove thundering herd of fallback probes on initial load. | unverified |

## frontend-render

| File | Change | Hypothesis | Status |
|------|--------|------------|--------|
| [web-console/src/components/boards/BoardPage.tsx](../../web-console/src/components/boards/BoardPage.tsx) | `memo` on `WorkItemCard`, `ColumnLaneHeader`, `ColumnLane`, `OutlineView`; `@tanstack/react-virtual` when `visibleRows.length > 80`; `deferColumnVirtualization` during partial/background hydration; extensive `useMemo`/`useCallback`; `rAF` throttled drag-over. | Reduce reconciliation + DOM node count for large boards. | unverified |
| [web-console/src/components/Dashboard.tsx](../../web-console/src/components/Dashboard.tsx) | Defer agent list fetch 250ms (`agentPanelEnabled`); `useBoardsMultiProject(visibleProjectIds)`, pass boards down instead of per-card `useBoards`; `useAllProjectAgents({ enabled: agentPanelEnabled })`. | Lift N+1 board fetches; defer non-critical agents panel. | unverified |

## frontend-bundle

| File | Change | Hypothesis | Status |
|------|--------|------------|--------|
| [web-console/vite.config.ts](../../web-console/vite.config.ts) | `manualChunks` split: `whiteboard-vendor` (tldraw/yjs), `markdown-vendor`, `collab-vendor`; `chunkSizeWarningLimit: 2000`; tests use `happy-dom` instead of `jsdom`. | Shrink initial parse/eval for dashboard/board routes. | unverified |
| [web-console/src/App.tsx](../../web-console/src/App.tsx) | Lazy routes for Wiki and Whiteboard. | Avoid loading collaboration vendors on dashboard/board. | unverified |

## instrumentation-logging

| File | Change | Status |
|------|--------|--------|
| [amprealize/services/board_api_v2.py](../../amprealize/services/board_api_v2.py) (~679–690) | `logger.info("work_items.list timing …")` with `t_count_ms`, `t_list_ms`, `t_shape_ms`, `t_total_handler_ms`. Hot-path. | keep-gated |
| [amprealize/services/board_service.py](../../amprealize/services/board_service.py) (~1498–1506) | `logger.debug` `t_child_agg_ms`. | keep |
| [web-console/src/components/boards/BoardPage.tsx](../../web-console/src/components/boards/BoardPage.tsx) (~3667–3709) | `razeLog` `board.shell_ready`, `board.first_items_page_ready`, `board.full_hydration_ready` with `elapsed_ms`. | keep (extend to `window.__perfMarks`) |
| [web-console/src/components/Dashboard.tsx](../../web-console/src/components/Dashboard.tsx) (~912–938) | `razeLog` `dashboard.chrome_ready`, `dashboard.agent_panel_ready`. | keep (extend to `window.__perfMarks`) |

## Red flags to attribute in Phase 5

1. **Sidebar still N+1:** [SidebarNav.tsx](../../web-console/src/components/sidebar/SidebarNav.tsx) L259–261 calls `useBoards(project.id)` per `SidebarProjectNode`; only partially masked by dashboard's `useBoardsMultiProject` cache seeding.
2. **Hot-path `logger.info`** in [board_api_v2.py](../../amprealize/services/board_api_v2.py) — cost and log volume on every list.
3. **400ms inter-page `sleep`** in [boards.ts](../../web-console/src/api/boards.ts) L882–888 — extends "feels slow" window by design.
4. **Cloud pool defaults undersized** (5/10) vs local (10/20) when settings absent — may serialize concurrent Neon queries.
5. **`include_total=true` on page 1** triggers `COUNT(*)` + `SELECT` — two Neon round-trips for the first paint.
6. **`_enrich_child_aggregation` on `get_work_items_batch`** ([board_service.py](../../amprealize/services/board_service.py) L1344–1370) — extra queries per ancestor hydration.

## Harness / infra changes made during the audit itself

These are not perf fixes — they're prerequisites that surfaced while running the harness against the actual cloud-dev stack. Documented so they can be rolled back or promoted intentionally.

| File | Change | Reason | Status |
|------|--------|--------|--------|
| [scripts/perf/set-api-workers.sh](../../scripts/perf/set-api-workers.sh) | Recreates the `amprealize-api` container in-place with a new `--workers` count. Preserves image / env / mounts / ports / network DNS aliases. Injects a persistent `AMPREALIZE_JWT_SECRET` from `scripts/perf/.jwt-secret` (gitignored) when the container doesn't already have one. | Enables the workers A/B toggle without losing the saved Playwright auth session. | unverified |
| [scripts/perf/.jwt-secret](../../scripts/perf/.jwt-secret) (gitignored) | Random 32-byte URL-safe secret persisted to disk. | Bug flagged: `amprealize/api.py:1076` generates a random JWT secret per boot when `AMPREALIZE_JWT_SECRET` is unset. Every container recreate would otherwise log everyone out. | unverified |
| [packages/breakeramp/src/breakeramp/blueprints/cloud-dev.yaml](../../packages/breakeramp/src/breakeramp/blueprints/cloud-dev.yaml) | Added `AMPREALIZE_API_WORKERS: "${AMPREALIZE_API_WORKERS:-1}"` passthrough in the `amprealize-api` env block. | Without this, the `${AMPREALIZE_API_WORKERS:-1}` shell expansion inside the container `command:` always resolves to 1 because the variable never reached the container env. | unverified |

> **Follow-up bug to file after the sweep:** cloud-dev API regenerates JWT secret on every boot — should either default to a persistent file (`AMPREALIZE_JWT_SECRET_FILE`) or fail hard when unset in non-dev envs.

## Out of scope (this pass)

- Whiteboard/wiki/brainstorm/wizard new features (not on dashboard/board hot path).
- BFF rewrite.
- Porting wins to `amprealize-enterprise` (sync after).
