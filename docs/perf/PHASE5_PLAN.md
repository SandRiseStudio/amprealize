# Phase 5 A/B plan — ordered by cost and confidence

Baseline: `docs/perf/baselines/SUMMARY.md`. All runs are 5 cold × Neon unless otherwise noted.

## Run order

| # | Toggle | Needs API recreate? | Needs re-login? | Expected p50 shift |
|---|--------|---------------------|-----------------|--------------------|
| 0 | **Pinned workers=4 baseline** (current state after JWT fix) | already paid | already done | Collapse the 2–6 s browser/server gap on parallel fan-out endpoints. |
| 1 | **`/v1/capabilities` in-flight dedupe** in `web-console/src/api/capabilities.ts` | no | no | Cut 23 calls → 1 per cold board load; should shave ~2–5 s off full-hydration time. |
| 2 | **Disable `razeLog` POST during benches** via env flag read by `web-console/src/telemetry/raze.ts` | no | no | Remove 10× 4-s POSTs clogging the queue. |
| 3 | **Progressive-hydration sleep 400ms → 0** in `web-console/src/api/boards.ts:888` | no | no | `full_hydration_ready` − `first_items_page_ready` wall-clock shortens by `400 * (pages-1)` ms. |
| 4 | **`/v1/projects/agents` deep dive** (5 calls, 11 s p50) — check handler + call sites | maybe | no | — |
| 5 | **Neon pooler DSN** (`…-pooler.*.neon.tech`) if still gap left | no (env-only restart) | no | Lower connect-time RTT per new physical conn. |

After every run: copy `report.md` + `summary.json` + `api.perf.log` into `docs/perf/ab/<n>-<label>/` and update `CHANGE_INVENTORY.md` statuses.

## Revert plan

- Per-toggle branches in `perf-audit-wip/ab-<n>-<label>` so any bad change is `git restore`-able without impacting others.
- `scripts/perf/set-api-workers.sh 1` puts the API back to the original cmd.
- `git restore scripts/perf/` + `rm scripts/perf/.jwt-secret` reverts the harness entirely.

## Exact hunks staged for edit

### Toggle 1 — capabilities dedupe

`web-console/src/api/capabilities.ts` today:

```ts
let _moduleCache: { data: ApiCapabilitiesResponse; expiresAt: number } | null = null;
const MODULE_CACHE_TTL_MS = 60_000;

async function fetchCapabilities(): Promise<ApiCapabilitiesResponse> {
  const now = Date.now();
  if (_moduleCache && _moduleCache.expiresAt > now) {
    return _moduleCache.data;
  }
  try {
    const data = await apiClient.get<…>('/v1/capabilities', { skipRetry: true });
    …
  }
}
```

Add in-flight promise dedupe:

```ts
let _inflight: Promise<ApiCapabilitiesResponse> | null = null;
async function fetchCapabilities(): Promise<ApiCapabilitiesResponse> {
  const now = Date.now();
  if (_moduleCache && _moduleCache.expiresAt > now) return _moduleCache.data;
  if (_inflight) return _inflight;
  _inflight = (async () => { try { … } finally { _inflight = null; } })();
  return _inflight;
}
```

### Toggle 2 — razeLog disable flag

`web-console/src/telemetry/raze.ts`: gate the POST on `import.meta.env.VITE_RAZE_LOG_ENABLED !== 'false'`. The `perfMark` path (which writes to `window.__perfMarks`) already works without the POST.

### Toggle 3 — progressive sleep

`web-console/src/api/boards.ts:888` — change `await sleep(400)` to `await sleep(Number(import.meta.env.VITE_HYDRATE_SLEEP_MS ?? 400))`, then run with `VITE_HYDRATE_SLEEP_MS=0` for the toggle-on run. Default stays at 400 so no behavior change until opted-in.
