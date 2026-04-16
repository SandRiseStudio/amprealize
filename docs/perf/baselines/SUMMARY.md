# Perf baseline summary

Captured on `perf-audit-wip` @ tag `pre-perf-audit-20260416`.

## Neon, 5 cold runs

Source: [`neon/report.md`](neon/report.md) — project `proj-b575d734aa37`, board `523b3a4f-…-eca6009`.

### Client milestones (p50 ms)

| milestone | p50 | p95 |
|---|---|---|
| dashboard.chrome_ready | **3497** | 3571 |
| dashboard.agent_panel_ready | **6066** | 6162 |
| board.shell_ready | **6960** | 7598 |
| board.first_items_page_ready | **5943** | 6961 |
| cold_board total (incl. full hydration wait) | **17438** | 18089 |

### The dominant finding — "browser sees 4–6× the server time"

| endpoint | server `t_total_ms` p50 | browser `responseEnd` p50 | gap |
|---|---|---|---|
| `boards.list` | **451** | 2470 | ~2000 ms |
| `boards.get` | **896** | 6909 | ~6000 ms |
| `work_items.list` | **611** | 1845 | ~1200 ms |
| `dashboard.stats` | **696** | 2627 | ~2000 ms |

The handlers themselves are not the bottleneck. The gap is consistent per-request and grows with concurrency → it smells like single-worker uvicorn serializing an in-flight queue of parallel calls plus gateway/TLS overhead.

### Request-volume red flags (single cold board load)

| endpoint | calls in one cold load | p50 per call |
|---|---|---|
| `/api/v1/work-items` | 28 | 1845 ms |
| `/api/v1/capabilities` | 23 | **11039** ms |
| `/api/v1/logs/ingest` (razeLog) | 10 | **4076** ms |
| `/api/v1/projects/agents` | 5 | 11030 ms |
| `/api/v1/boards/:id` | 5 | 6909 ms |
| `/api/v1/work-items` server-side perf line | 33 |  |

`work_items` at 28 calls is the intended progressive-hydration path. But:

- **`/api/v1/capabilities` fetched 23 times in a single board cold open.** This is almost certainly a React effect refetching on every state change. Easy win.
- **`/api/v1/logs/ingest` @ 4s × 10 calls.** Every `razeLog` milestone POSTs to this endpoint. The POSTs are fire-and-forget from the component's point of view but they're stuck in the same serialized queue as real API calls and they're clogging it at board load.
- **`/api/v1/projects/agents` @ 11s.** Way out of line with server-side work. Deferred after 250 ms but still shows up on the critical path for `agent_panel_ready`.

## Local Postgres, 5 cold runs

Not yet captured — see "Next" below.

## Ranked Phase-5 hypotheses (from Neon baseline alone)

1. **Bump `AMPREALIZE_API_WORKERS` from 1 to 4.** If the 2–6s browser/server gap collapses, we have confirmed uvicorn worker serialization as the #1 bottleneck on Neon. Cheap to test (`breakeramp restart -s amprealize-api` with the env var).
2. **Disable `razeLog` ingest POST during milestone events** or batch them behind a 5 s debounce. Expected to shave seconds off the full-hydration window during board load.
3. **Investigate `/api/v1/capabilities` refetch storm.** 23 calls on one cold board load is almost certainly bug-shaped.
4. **Investigate `/api/v1/projects/agents` 11 s latency.** Either it's doing real work and needs a query tune, or it's also stuck behind the serialized worker.
5. **Try the Neon pooler DSN** (`*-pooler.*.neon.tech`) if not already in use. Only relevant if the worker bump doesn't fully explain the gap.
6. **Drop the 400 ms `sleep` between progressive pages** in `useWorkItems`. Should shorten full-hydration wall clock by `400 * (pages-1)` ms.
